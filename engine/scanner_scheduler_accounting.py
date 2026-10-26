"""Bound scheduler retry cadence and expose truthful budget diagnostics.

Observational scheduler accounting only; does not alter scan eligibility, locking,
market decisions, or execution permissions.
"""
from __future__ import annotations

VERSION = '69.10.46'


def bounded_scheduler_sleep(planned_seconds: float, *, freshness_exhausted: bool,
                            min_exhausted_sleep_seconds: float = 5.0) -> float:
    """Avoid a tight busy loop after freshness budget is already exhausted.

    The minimum sleep applies ONLY to exhausted cycles. Healthy cadence is
    preserved. Five seconds is deliberately shorter than full scan runtimes.
    """
    planned = max(0.0, float(planned_seconds))
    if not freshness_exhausted:
        return planned
    return max(planned, max(1.0, min(30.0, float(min_exhausted_sleep_seconds))))


def update_freshness_episode(state: dict, *, exhausted: bool, now_iso: str) -> None:
    """Count scheduler cycles and separate continuous exhaustion episodes."""
    state['scheduler_cycles_accounted'] = int(state.get('scheduler_cycles_accounted') or 0) + 1
    previous = bool(state.get('freshness_budget_exhausted_active', False))
    if exhausted:
        state['freshness_budget_exhausted_cycles'] = int(state.get('freshness_budget_exhausted_cycles') or 0) + 1
        if not previous:
            state['freshness_budget_exhausted_episodes'] = int(state.get('freshness_budget_exhausted_episodes') or 0) + 1
            state['last_freshness_exhausted_episode_at'] = now_iso
    state['freshness_budget_exhausted_active'] = bool(exhausted)
