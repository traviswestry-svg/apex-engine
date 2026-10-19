"""Pure scanner completion-deadline planner; no threads, writes or execution authority."""
from __future__ import annotations
from dataclasses import dataclass
import math


def safe_positive(value, default):
    try:
        v = float(value)
        return v if math.isfinite(v) and v > 0 else float(default)
    except (TypeError, ValueError, OverflowError):
        return float(default)


@dataclass(frozen=True)
class DeadlinePlan:
    sleep_seconds: float
    allow_optional_work: bool
    deadline_at_risk: bool
    reason: str
    completion_budget_seconds: float


def deadline_plan(stale_after_seconds, age_since_completion_seconds,
                  expected_next_scan_seconds, margin_seconds=20,
                  optional_work_estimate_seconds=0):
    stale = safe_positive(stale_after_seconds, 180)
    age = max(0.0, float(age_since_completion_seconds or 0))
    if not math.isfinite(age):
        age = stale
    next_scan = safe_positive(expected_next_scan_seconds, 90)
    margin = max(0.0, float(margin_seconds or 0))
    if not math.isfinite(margin):
        margin = 20.0
    work = max(0.0, float(optional_work_estimate_seconds or 0))
    if not math.isfinite(work):
        work = stale
    budget = stale - age - next_scan - margin
    allow = budget >= work
    return DeadlinePlan(sleep_seconds=max(0.0, budget),
                        allow_optional_work=allow,
                        deadline_at_risk=budget <= 0,
                        reason='WITHIN_DEADLINE' if allow else 'RESERVE_NEXT_FULL_SCAN',
                        completion_budget_seconds=budget)
