"""Tests for SQLite single-writer lock mechanism."""
from __future__ import annotations

import os
import pathlib

import pytest


@pytest.fixture
def lock_file(tmp_path: pathlib.Path) -> pathlib.Path:
    """Fixture providing a temp lock file path and restoring on exit."""
    import app.core.database as db_module
    original_lock = db_module._WRITER_LOCK_FILE
    lf = tmp_path / "benchmarkops_writer.lock"
    db_module._WRITER_LOCK_FILE = lf
    yield lf
    db_module._WRITER_LOCK_FILE = original_lock


def test_acquire_lock_creates_file(tmp_path: pathlib.Path) -> None:
    """When no lock exists, acquire_writer_lock creates it with current PID."""
    import app.core.database as db_module

    original_lock = db_module._WRITER_LOCK_FILE
    lock_file = tmp_path / "benchmarkops_writer.lock"
    db_module._WRITER_LOCK_FILE = lock_file

    try:
        assert not lock_file.exists()
        db_module.acquire_writer_lock()
        assert lock_file.exists()
        assert int(lock_file.read_text().strip()) == os.getpid()
    finally:
        db_module._WRITER_LOCK_FILE = original_lock


def test_acquire_lock_same_pid_succeeds(tmp_path: pathlib.Path) -> None:
    """When lock exists with current PID, it succeeds (no-op)."""
    import app.core.database as db_module

    original_lock = db_module._WRITER_LOCK_FILE
    lock_file = tmp_path / "benchmarkops_writer.lock"
    db_module._WRITER_LOCK_FILE = lock_file

    try:
        lock_file.write_text(str(os.getpid()))
        db_module.acquire_writer_lock()  # Should NOT raise
    finally:
        db_module._WRITER_LOCK_FILE = original_lock


def test_acquire_lock_different_alive_pid_raises(lock_file: pathlib.Path) -> None:
    """When lock exists with different ALIVE PID, raises RuntimeError."""
    import app.core.database as db_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            db_module, "_process_is_alive",
            lambda pid: pid != os.getpid()  # Simulate: all other PIDs are alive
        )
        lock_file.write_text(str(os.getpid() + 1))
        with pytest.raises(RuntimeError, match="Another BenchmarkOps"):
            db_module.acquire_writer_lock()


def test_acquire_lock_dead_pid_removes_stale(lock_file: pathlib.Path) -> None:
    """When lock exists with DEAD PID, removes stale lock and allows."""
    import app.core.database as db_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            db_module, "_process_is_alive",
            lambda pid: False  # Simulate: all other PIDs are dead
        )
        lock_file.write_text("999999")
        db_module.acquire_writer_lock()  # Should succeed after removing stale lock
        assert lock_file.exists()  # New lock file created
        assert int(lock_file.read_text().strip()) == os.getpid()


def test_acquire_lock_corrupted_pid_file(lock_file: pathlib.Path) -> None:
    """When lock file contains non-numeric data, removes and allows."""
    lock_file.write_text("not-a-pid")
    import app.core.database as db_module
    db_module.acquire_writer_lock()  # Should succeed
    assert lock_file.exists()
    assert int(lock_file.read_text().strip()) == os.getpid()
