"""Async SQLAlchemy engine, session factory, and FastAPI session dependency.

The Repository layer is the only consumer of Session, so swapping the database
backend (SQLite -> Postgres) requires changing only DATABASE_URL.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# check_same_thread only applies to SQLite; harmless key otherwise since we gate it.
_connect_args = (
    {"check_same_thread": False, "timeout": 30}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    connect_args=_connect_args,
)

# SQLite is a single-writer store: concurrent writes (request thread + background
# evaluation tasks) otherwise raise "database is locked" and fail the operation.
# WAL lets readers and a writer proceed concurrently and survives a writer mid-flight,
# which is what the in-process task queue + live polling need. Applied per raw
# connection so every session gets it.
if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _conn_record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            # 15s: long enough that legitimate short write transactions (a run's
            # batch persist, or several runs' persists queued behind the single
            # WAL writer) wait their turn instead of being spuriously failed as
            # "database is locked"; short enough that the frontend's 30s fetch
            # timeout still surfaces a real deadlock to the user.
            cur.execute("PRAGMA busy_timeout=15000")
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
