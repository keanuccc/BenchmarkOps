"""Evaluation-engine exception markers."""
from __future__ import annotations


class RetryableTaskError(Exception):
    """Transient failure that happens before any billable provider work.

    Only these failures are retried by the ARQ worker; provider-side failures
    (rate limits, quota exhaustion, row errors) are terminal by design so a
    billing-sensitive evaluation is never silently re-run.
    """
