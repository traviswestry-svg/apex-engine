from engine.flow_learning_deadline_audit import audit_admission
from engine.scanner_learning_continuity import assess_learning

BASE = dict(stale_seconds=180, elapsed_seconds=30, next_scan_seconds=33,
            reserve_seconds=45, estimated_work_seconds=120)

def check(**overrides):
    args = dict(BASE, **overrides)
    admission = assess_learning(enabled=True, available=True, wired=True,
                                session_allowed=True, **args)
    return admission, audit_admission(**args, actual_state=admission.state,
                                      consecutive_deferrals=admission.consecutive_deferrals)

def test_structurally_impossible_with_33_second_scan():
    admission, report = check()
    assert not admission.admitted
    assert report['classification'] == 'STRUCTURALLY_INFEASIBLE_AT_CURRENT_ESTIMATE'
    assert report['theoretical_max_budget_seconds'] == 102
    assert report['remaining_budget_seconds'] == 72
    assert report['work_budget_shortfall_seconds'] == 48

def test_transient_deferral_with_feasible_work():
    _, report = check(estimated_work_seconds=60, elapsed_seconds=60)
    assert report['classification'] == 'TRANSIENT_DEADLINE_DEFERRAL'
    assert not report['structurally_infeasible']

def test_admission_does_not_change():
    admission, report = check(estimated_work_seconds=60, elapsed_seconds=0)
    assert admission.admitted and report['classification'] == 'ADMITTED'
    assert not report['changes_learning_admission']

def test_gate_exclusion_takes_priority():
    report = audit_admission(**BASE, actual_state='SESSION_GATED',
                             consecutive_deferrals=0, session_allowed=False)
    assert report['classification'] == 'UPSTREAM_GATE_BLOCKED'
    assert report['gate_blocked'] == 'session_allowed'
    assert report['structurally_infeasible'] is None

def test_non_finite_inputs_safe():
    report = audit_admission(**{**BASE, 'elapsed_seconds': float('inf')},
                             actual_state='DEFERRED_SCANNER_DEADLINE',
                             consecutive_deferrals=75)
    assert report['elapsed_seconds'] == 180
    assert report['consecutive_deferrals'] == 75
