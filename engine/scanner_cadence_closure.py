"""Read-only cadence planning for scanner freshness (no lock or execution authority)."""
from __future__ import annotations

import math


def next_scan_sleep(configured_interval_seconds, stale_after_seconds,
                    elapsed_since_completion_seconds, safety_margin_seconds=20):
    """Bound the post-cycle sleep so a fresh scan can start before health expires.

    A full scan and post-scan tasks run serially. This planner cannot guarantee
    completion freshness when a scan or a post-scan task itself exceeds the budget.
    """
    def finite(value, default):
        try:
            number = float(value)
            return number if math.isfinite(number) else default
        except (ValueError, TypeError):
            return default

    interval = max(1.0, finite(configured_interval_seconds, 300.0))
    stale = max(1.0, finite(stale_after_seconds, 180.0))
    elapsed = max(0.0, finite(elapsed_since_completion_seconds, 0.0))
    margin = max(0.0, finite(safety_margin_seconds, 20.0))
    remaining = stale - elapsed - margin
    return max(0.0, min(interval, remaining))
