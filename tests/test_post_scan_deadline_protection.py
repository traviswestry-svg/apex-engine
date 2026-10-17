from engine.post_scan_deadline import deadline_seconds, should_defer, safe_positive_seconds


def test_deadline_reserves_scan_time():
    assert deadline_seconds(180, 45) == 135
    assert not should_defer(134.9, 180, 45)
    assert should_defer(135, 180, 45)


def test_no_budget_defers_immediately():
    assert should_defer(0, 30, 45)


def test_invalid_inputs_fail_safe():
    assert safe_positive_seconds("NaN", 180) == 180
    assert safe_positive_seconds(-2, 180) == 180
    assert should_defer(float("inf"), 180) is False  # invalid elapsed sanitized


def test_policy_has_no_concurrent_execution_or_io():
    import inspect
    from engine import post_scan_deadline
    source = inspect.getsource(post_scan_deadline)
    assert "Thread(" not in source
    assert "sqlite3" not in source
