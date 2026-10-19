"""Fail-closed, single-owner learning admission and starvation observability.

No background writer, broker authority, or synthetic evidence is introduced.
"""
from __future__ import annotations
from dataclasses import dataclass
from engine.scanner_freshness_deadline import deadline_plan, safe_positive

@dataclass(frozen=True)
class LearningAdmission:
    admitted: bool
    state: str
    remaining_budget_seconds: float
    estimate_seconds: float
    consecutive_deferrals: int
    starvation_warning: bool


def assess_learning(*, enabled, available, wired, session_allowed,
                    stale_seconds, elapsed_seconds, next_scan_seconds,
                    reserve_seconds, estimated_work_seconds,
                    consecutive_deferrals=0, warning_threshold=5):
    """Check eligibility before applying a conservative completion deadline."""
    if not enabled:
        reason = 'DISABLED'
    elif not available:
        reason = 'UNAVAILABLE'
    elif not wired:
        reason = 'UNWIRED'
    elif not session_allowed:
        reason = 'SESSION_GATED'
    else:
        reason = None
    estimate = safe_positive(estimated_work_seconds, 120)
    plan = deadline_plan(stale_seconds, elapsed_seconds, next_scan_seconds,
                         margin_seconds=reserve_seconds,
                         optional_work_estimate_seconds=estimate)
    if reason:
        return LearningAdmission(False, reason, plan.completion_budget_seconds,
                                 estimate, 0, False)
    if plan.allow_optional_work:
        return LearningAdmission(True, 'ADMITTED', plan.completion_budget_seconds,
                                 estimate, 0, False)
    n = max(0, int(consecutive_deferrals)) + 1
    return LearningAdmission(False, 'DEFERRED_SCANNER_DEADLINE',
                             plan.completion_budget_seconds, estimate, n,
                             n >= max(1, int(warning_threshold)))
