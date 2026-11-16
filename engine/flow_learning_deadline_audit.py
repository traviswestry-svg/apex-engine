"""Read-only arithmetic audit of the existing scanner-owned learning admission.

This module does not schedule work, change admission, or retain historical records.
"""
from __future__ import annotations

from engine.scanner_freshness_deadline import safe_positive

SCHEMA = 'apex.flow_learning_deadline_audit.v1'


def audit_admission(*, stale_seconds, elapsed_seconds, next_scan_seconds,
                    reserve_seconds, estimated_work_seconds, actual_state,
                    consecutive_deferrals, enabled=True, available=True,
                    wired=True, session_allowed=True):
    """Explain the existing decision using bounded scalars only.

    The exact decision remains owned by ``assess_learning``.  No recommendation
    here is authorization to reduce scan margins or run work asynchronously.
    """
    stale = safe_positive(stale_seconds, 180.0)
    scan = safe_positive(next_scan_seconds, 90.0)
    estimate = safe_positive(estimated_work_seconds, 120.0)
    try:
        elapsed = max(0.0, float(elapsed_seconds))
        reserve = max(0.0, float(reserve_seconds))
    except (TypeError, ValueError, OverflowError):
        elapsed, reserve = stale, 45.0
    from math import isfinite
    if not isfinite(elapsed):
        elapsed = stale
    if not isfinite(reserve):
        reserve = 45.0
    theoretical = stale - scan - reserve
    remaining = theoretical - elapsed
    deficit = max(0.0, estimate - remaining)
    structural = estimate > theoretical
    gates = {'enabled': bool(enabled), 'available': bool(available),
             'wired': bool(wired), 'session_allowed': bool(session_allowed)}
    blocked_gate = next((k for k, v in gates.items() if not v), None)
    if blocked_gate:
        classification = 'UPSTREAM_GATE_BLOCKED'
    elif actual_state == 'ADMITTED':
        classification = 'ADMITTED'
    elif actual_state != 'DEFERRED_SCANNER_DEADLINE':
        classification = 'OTHER_ADMISSION_STATE'
    elif structural:
        classification = 'STRUCTURALLY_INFEASIBLE_AT_CURRENT_ESTIMATE'
    else:
        classification = 'TRANSIENT_DEADLINE_DEFERRAL'
    return {
        'schema': SCHEMA, 'read_only': True, 'execution_authority': False,
        'decision_authority': False, 'changes_scan_scheduling': False,
        'changes_learning_admission': False, 'runs_learning': False,
        'classification': classification, 'admission_state': str(actual_state),
        'gate_blocked': blocked_gate,
        'stale_seconds': round(stale, 3),
        'elapsed_seconds': round(elapsed, 3),
        'next_scan_estimate_seconds': round(scan, 3),
        'reserve_seconds': round(reserve, 3),
        'estimated_work_seconds': round(estimate, 3),
        'theoretical_max_budget_seconds': round(theoretical, 3),
        'remaining_budget_seconds': round(remaining, 3),
        'work_budget_shortfall_seconds': round(deficit, 3),
        'structurally_infeasible': structural if not blocked_gate else None,
        'consecutive_deferrals': max(0, int(consecutive_deferrals)),
        'limitations': [
            'Estimated work time is configuration, not measured flow-pipeline runtime',
            'This audit does not prove a safe shorter estimate or authorize an override',
            'Admission depends on the scanner-owned deadline calculation',
        ],
    }
