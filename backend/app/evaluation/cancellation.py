"""In-process cancellation registry for evaluation runs.

The runner checks this registry between rows so a cancel request from the API
process stops a run at the next row boundary without a per-row database query.
Cross-process cancellation (ARQ workers) still relies on the DB status / Redis
abort set; the runner additionally polls the DB on its normal progress cadence
as a fallback.
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_cancelled: set[str] = set()


def request_cancel(experiment_id: str) -> None:
    """Ask the in-process runner to stop after its current row."""
    with _lock:
        _cancelled.add(experiment_id)


def is_cancelled(experiment_id: str) -> bool:
    """Return True when a graceful cancellation was requested for the run."""
    with _lock:
        return experiment_id in _cancelled


def clear_cancelled(experiment_id: str) -> None:
    """Drop a stale cancellation marker (e.g. when a new run starts)."""
    with _lock:
        _cancelled.discard(experiment_id)
