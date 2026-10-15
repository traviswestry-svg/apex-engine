from engine.signal_integrity_guard import evaluate_signal_thresholds, finite_number


def test_missing_required_thresholds_abstain():
    for direction in ('CALL', 'PUT'):
        assert evaluate_signal_thresholds(500.0, direction, None, 510, None)[0] is None
        assert evaluate_signal_thresholds(500.0, direction, 490, None, None)[0] is None
        assert evaluate_signal_thresholds(None, direction, 490, 510, None)[0] is None


def test_stop_precedence_and_optional_t2():
    assert evaluate_signal_thresholds(480, 'CALL', 490, 510, None)[:2] == ('STOP', 490)
    assert evaluate_signal_thresholds(520, 'CALL', 490, 510, None)[:2] == ('T1', 510)
    assert evaluate_signal_thresholds(500, 'PUT', 490, 470, None)[:2] == ('STOP', 490)
    assert evaluate_signal_thresholds(460, 'PUT', 490, 470, None)[:2] == ('T1', 470)
    assert evaluate_signal_thresholds(530, 'CALL', 490, 510, 525)[:2] == ('T2', 525)


def test_nonfinite_rejected():
    assert finite_number(float('nan')) is None
    assert finite_number(float('inf')) is None
    assert finite_number(True) is None
    assert evaluate_signal_thresholds(500, 'CALL', float('nan'), 510, None)[0] is None


def test_invalid_direction_abstains():
    assert evaluate_signal_thresholds(500, 'UNKNOWN', 490, 510, None)[2] == ('direction',)
