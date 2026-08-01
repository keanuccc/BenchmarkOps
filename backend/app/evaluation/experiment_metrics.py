"""Keep the experiment metrics JSON blob and materialized columns in sync."""
from __future__ import annotations


def metric_columns(metrics: dict) -> dict:
    """Return the materialized columns present in a metrics blob.

    Only keys actually present are returned, so incremental progress updates
    cannot clobber values the JSON blob does not (yet) contain.
    """
    out: dict = {}
    if "accuracy" in metrics:
        out["accuracy"] = float(metrics["accuracy"] or 0.0)
    if "avg_latency_ms" in metrics:
        out["avg_latency_ms"] = float(metrics["avg_latency_ms"] or 0.0)
    return out
