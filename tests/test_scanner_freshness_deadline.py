from engine.scanner_freshness_deadline import deadline_plan, safe_positive


def test_sleep_reserves_next_full_scan():
    p = deadline_plan(180, 75, 75, 20)
    assert p.sleep_seconds == 10
    assert not p.deadline_at_risk


def test_long_flow_work_is_deferred():
    p = deadline_plan(180, 0, 90, 20, 75)
    assert not p.allow_optional_work
    assert p.reason == 'RESERVE_NEXT_FULL_SCAN'


def test_small_work_allowed():
    assert deadline_plan(180, 0, 75, 20, 60).allow_optional_work


def test_overrun_starts_immediately():
    p = deadline_plan(180, 120, 90, 20)
    assert p.sleep_seconds == 0
    assert p.deadline_at_risk


def test_bad_config_safe():
    assert safe_positive('bad', 180) == 180
    assert safe_positive(float('nan'), 180) == 180
    assert deadline_plan(180, float('inf'), 90).sleep_seconds == 0


def test_zero_optional_work_not_authorized_after_deadline():
    assert not deadline_plan(180, 180, 90, 20).allow_optional_work
