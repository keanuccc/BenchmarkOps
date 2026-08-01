"""Async SQLAlchemy engine, session factory, and FastAPI session dependency.

The Repository layer is the only consumer of Session, so swapping the database
backend (SQLite -> Postgres) requires changing only DATABASE_URL.

Production notes:
- SQLite (v1): WAL mode + busy_timeout + connection pool tuned for single-writer.
  Suitable for low-to-moderate concurrency (<50 concurrent requests).
- Postgres: set DATABASE_URL to ``postgresql+asyncpg://...`` and the same
  code path works with a proper connection pool (see pool_size/max_overflow below).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import pathlib
import tempfile
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import TypeVar

from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

logger = logging.getLogger("benchmarkops")

_WRITER_LOCK_FILE = pathlib.Path("/tmp/benchmarkops_writer.lock")


def _process_is_alive(pid: int) -> bool:
    """Check whether *pid* refers to a running process (cross-platform).

    On Unix we use ``os.kill(pid, 0)``.  On Windows we open the process with
    ``PROCESS_QUERY_INFORMATION`` and call ``GetExitCodeProcess`` — a handle
    can stay valid for a short window after termination, but ``GetExitCodeProcess``
    returns ``STILL_ACTIVE`` only while the process is actually running.
    """
    import sys

    if sys.platform == "win32":
        import ctypes

        # PROCESS_QUERY_INFORMATION (0x0400) is required for GetExitCodeProcess.
        # PROCESS_QUERY_LIMITED_INFORMATION (0x0800) is NOT sufficient.
        PROCESS_QUERY_INFORMATION = 0x0400
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_INFORMATION, False, pid
        )
        if handle == 0:
            return False
        try:
            exit_code = ctypes.c_ulong()
            success = kernel32.GetExitCodeProcess(
                handle, ctypes.byref(exit_code)
            )
            if not success:
                return False
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    else:
        # Unix
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True


def acquire_writer_lock() -> None:
    """Ensure only one backend process writes to the SQLite database.

    Raises RuntimeError if another BenchmarkOps instance is already running
    and holding the lock. Removes stale locks from dead processes.
    """
    if not _is_sqlite:
        return

    _WRITER_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    pid_bytes = str(os.getpid()).encode("ascii")
    while True:
        try:
            fd = os.open(_WRITER_LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, pid_bytes)
            finally:
                os.close(fd)
            logger.info("acquired SQLite writer lock (PID %d)", os.getpid())
            return
        except FileExistsError:
            try:
                old_pid = int(_WRITER_LOCK_FILE.read_text().strip())
            except (ValueError, OSError):
                _WRITER_LOCK_FILE.unlink(missing_ok=True)
                continue

            if old_pid == os.getpid():
                return
            if _process_is_alive(old_pid):
                raise RuntimeError(
                    f"Another BenchmarkOps instance is already writing to the database (PID {old_pid}). "
                    "SQLite supports only one writer. Stop the other instance or switch to PostgreSQL."
                )
            _WRITER_LOCK_FILE.unlink(missing_ok=True)


# --- Connection pool configuration -------------------------------------------
# SQLite: use NullPool (no pooling — each request opens/closes a connection).
# This avoids "database is locked" from stale pooled connections that were
# created by a different process/thread.
# Postgres: use QueuePool with sensible defaults.
_is_sqlite = settings.database_url.startswith("sqlite")


def _lock_path_for_database(database_url: str) -> pathlib.Path:
    """Return a stable per-database lock path outside the project directory."""
    database_path = database_url.split("///", 1)[-1]
    resolved = pathlib.Path(database_path).expanduser().resolve()
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:16]
    return pathlib.Path(tempfile.gettempdir()) / f"benchmarkops_writer_{digest}.lock"


if _is_sqlite:
    _WRITER_LOCK_FILE = _lock_path_for_database(settings.database_url)

_connect_args = (
    {"check_same_thread": False, "timeout": 30}
    if _is_sqlite
    else {}
)

# Engine pool size differs by backend:
# - SQLite: pool_size=0 → NullPool (safe for file-based)
# - Postgres: pool_size=5, max_overflow=10 (tune via env vars later)
_pool_size = 5 if not _is_sqlite else 0
_max_overflow = 10 if not _is_sqlite else 0
_pool_recycle = 3600 if not _is_sqlite else -1  # -1 = no recycle (NullPool ignores, safe for SQLite)

engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    connect_args=_connect_args,
    pool_size=_pool_size,
    max_overflow=_max_overflow,
    pool_pre_ping=True,  # verify connections before use (PG connection health)
    pool_recycle=_pool_recycle,  # recycle PG connections after 1h; -1 = no recycle for SQLite
)

# SQLite-specific pragmas — applied per raw connection so every session gets them.
if _is_sqlite:

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _conn_record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        try:
            # WAL: allows readers and a writer to proceed concurrently.
            cur.execute("PRAGMA journal_mode=WAL")
            # 15s busy timeout — long enough for short write transactions to wait,
            # short enough that the frontend's 30s fetch timeout still surfaces real
            # deadlocks to the user.
            cur.execute("PRAGMA busy_timeout=15000")
            # synchronous=NORMAL (default) is fine for WAL; FULL would be safer but
            # adds disk sync overhead. For evaluation workloads NORMAL is sufficient.
            # cache_size=-2000 → -2 MB shared cache (negative = KiB in SQLite)
            cur.execute("PRAGMA cache_size=-2000")
            # temp_store=MEMORY → temporary tables/indexes in memory
            cur.execute("PRAGMA temp_store=MEMORY")
        finally:
            cur.close()


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a session with commit/rollback handling."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db_baseline() -> None:
    """Create tables from ORM metadata (version 0 baseline).

    This remains the original create_all path. It builds the initial schema
    on first boot; subsequent schema changes go through the migration
    registry in `app.migrations` instead of here.
    """
    # Import models so they register on Base.metadata before create_all.
    from app.models.base import Base  # noqa: F401
    import app.models  # noqa: F401  (registers all ORM models)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def init_db() -> None:
    """Initialize the database: baseline tables, then apply pending migrations."""
    await init_db_baseline()
    from app.migrations import run_migrations

    await run_migrations(engine)


_T = TypeVar("_T")


async def with_retry_on_lock(
    operation: Callable[[], Awaitable[_T]],
    *,
    max_attempts: int = 4,
    base_delay: float = 0.2,
) -> _T:
    """Run an async DB write with exponential-backoff retry on 'database is locked'.

    Two backend processes (e.g. ports 8000/8001) sharing one SQLite file can collide
    with ``database is locked`` under the single-writer WAL model. The engine already
    sets ``busy_timeout=15000`` so SQLite itself waits; this helper adds an
    application-level retry so a transient lock contention during a short write
    recovers instead of silently losing a status update (the bug where experiments
    stick at running/progress=0).

    Behaviour:
      * Executes ``await operation()``; if it raises ``sqlalchemy.exc.OperationalError``
        whose message contains "database is locked", retries with exponential backoff
        ``base_delay * 2**i`` between attempts, sleeping via ``asyncio.sleep`` so other
        coroutines stay responsive.
      * Other exceptions (including non-lock OperationalError) propagate untouched.
      * After ``max_attempts`` exhausted, the last OperationalError is re-raised as-is.

    Note: this is NOT deadlock detection. Each attempt also waits up to the engine's
    ``busy_timeout`` (15s), so a single call's worst-case wall time is roughly
    ``(sum of backoff sleeps up to ~1.4s) + 15s``, not just the backoff sum. The
    backoff is deliberately tiny vs busy_timeout so we never blow past the 30s client
    fetch timeout; a genuine unresolvable contention still surfaces to the caller.
    """
    last_exc: OperationalError | None = None
    for attempt in range(max_attempts):
        try:
            return await operation()
        except OperationalError as exc:
            if "database is locked" not in str(exc):
                raise
            last_exc = exc
            if attempt < max_attempts - 1:
                await asyncio.sleep(base_delay * (2**attempt))
            continue
    assert last_exc is not None  # loop always ends via a lock error here
    raise last_exc
