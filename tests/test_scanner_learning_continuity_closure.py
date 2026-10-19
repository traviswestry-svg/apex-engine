from engine.scanner_learning_continuity import assess_learning

BASE = dict(enabled=True, available=True, wired=True, session_allowed=True,
            stale_seconds=180, elapsed_seconds=44, next_scan_seconds=44,
            reserve_seconds=45, estimated_work_seconds=120)

def test_starvation_reported_without_forced_unsafe_admission():
    result = assess_learning(**BASE, consecutive_deferrals=4)
    assert not result.admitted
    assert result.consecutive_deferrals == 5
    assert result.starvation_warning
    assert result.state == 'DEFERRED_SCANNER_DEADLINE'

def test_short_work_admitted_when_budget_exists():
    result = assess_learning(**{**BASE, 'estimated_work_seconds': 20})
    assert result.admitted
    assert result.consecutive_deferrals == 0

def test_session_gated_does_not_count_as_starvation():
    result = assess_learning(**{**BASE, 'session_allowed': False}, consecutive_deferrals=10)
    assert result.state == 'SESSION_GATED'
    assert result.consecutive_deferrals == 0
    assert not result.starvation_warning

def test_unwired_pipeline_not_misreported_as_deadline_starvation():
    result = assess_learning(**{**BASE, 'wired': False})
    assert result.state == 'UNWIRED'
    assert not result.starvation_warning

def test_disabled_pipeline_not_misreported_as_starvation():
    result = assess_learning(**{**BASE, 'enabled': False})
    assert result.state == 'DISABLED'
