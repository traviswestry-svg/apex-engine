"""Pure cooperative post-scan deadline policy; no broker or database authority.

Optional expensive work is deferred at stage boundaries. In-flight calls cannot be
preempted; no concurrent scanner/SQLite writer threads are created.
"""
from __future__ import annotations
import math


def safe_positive_seconds(value, default):
    try:
        number = float(value)
        if math.isfinite(number) and number > 0:
            return number
    except (ValueError, TypeError):
        pass
    return float(default)


def deadline_seconds(stale_after_seconds, reserve_seconds=45):
    stale = safe_positive_seconds(stale_after_seconds, 180)
    reserve = safe_positive_seconds(reserve_seconds, 45)
    return max(0.0, stale - reserve)


def should_defer(elapsed_seconds, stale_after_seconds, reserve_seconds=45):
    try:
        elapsed = float(elapsed_seconds)
    except (TypeError, ValueError):
        elapsed = 0.0
    if not math.isfinite(elapsed):
        elapsed = 0.0
    return max(0.0, elapsed) >= deadline_seconds(stale_after_seconds, reserve_seconds)
