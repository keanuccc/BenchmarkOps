"""Unit tests for app.core.database.with_retry_on_lock (optimization A).

The helper retries on sqlalchemy.exc.OperationalError containing
"database is locked" with exponential backoff, re-raises other exceptions
untouched, and re-raises the last lock error after max_attempts.
"""
from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from app.core.database import with_retry_on_lock


def _make_lock_error(attempt: int) -> OperationalError:
    # A real OperationalError carries a DBAPI-level args tuple; build one whose
    # str() renders the "database is locked" text the helper checks for.
    return OperationalError(
        statement="COMMIT",
        params=None,
        orig=Exception(f"(attempt {attempt}) database is locked"),
    )


def _make_other_operational_error() -> OperationalError:
    return OperationalError(
        statement="COMMIT",
        params=None,
        orig=Exception("no such table: experiments"),
    )


async def test_retries_then_succeeds_on_locked():
    """N 'database is locked' failures then success -> returns the result."""
    calls: list[int] = []

    async def op() -> str:
        calls.append(len(calls))
        if len(calls) <= 3:  # fail the first 3 attempts
            raise _make_lock_error(len(calls))
        return "ok"

    result = await with_retry_on_lock(op, max_attempts=5, base_delay=0.0)
    assert result == "ok"
    # 3 failures + 1 success = 4 invocations.
    assert len(calls) == 4


async def test_non_lock_operational_error_not_retried():
    """A non-lock OperationalError is raised immediately, never retried."""
    calls: list[int] = []

    async def op() -> str:
        calls.append(len(calls))
        raise _make_other_operational_error()

    with pytest.raises(OperationalError, match="no such table"):
        await with_retry_on_lock(op, max_attempts=5, base_delay=0.0)
    # Exactly one invocation — it was never retried.
    assert len(calls) == 1


async def test_exhausted_lock_retries_reraises_last():
    """All max_attempts 'database is locked' -> re-raises the OperationalError."""
    calls: list[int] = []

    async def op() -> str:
        calls.append(len(calls))
        raise _make_lock_error(len(calls))

    with pytest.raises(OperationalError, match="database is locked"):
        await with_retry_on_lock(op, max_attempts=5, base_delay=0.0)
    # max_attempts invocations; the last raised error is what propagates.
    assert len(calls) == 5


async def test_other_exception_type_propagates_untouched():
    """Non-OperationalError exceptions propagate without retry/transform."""
    calls: list[int] = []

    async def op() -> str:
        calls.append(len(calls))
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await with_retry_on_lock(op, max_attempts=5, base_delay=0.0)
    assert len(calls) == 1
