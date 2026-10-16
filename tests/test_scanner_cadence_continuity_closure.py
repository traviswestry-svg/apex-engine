from engine.scanner_cadence_closure import next_scan_sleep


def test_default_interval_cannot_wait_past_freshness_budget():
    assert next_scan_sleep(300, 180, 60) == 100


def test_postscan_work_reduces_sleep():
    assert next_scan_sleep(300, 180, 145) == 15


def test_exhausted_budget_restarts_without_sleep():
    assert next_scan_sleep(300, 180, 200) == 0


def test_short_configured_interval_is_respected():
    assert next_scan_sleep(30, 180, 10) == 30


def test_nonfinite_inputs_do_not_crash_scheduler():
    assert next_scan_sleep(float('nan'), 180, float('inf')) == 160
