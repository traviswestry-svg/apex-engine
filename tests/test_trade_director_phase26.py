from engine.trade_director_command_center import build_command_center, build_drift_detection, build_performance_scorecards


def _records(n=30):
    return [{"r_multiple": 1.0 if i % 3 else -0.5, "realized_pnl": 100 if i % 3 else -50,
             "decision_confidence": 70, "decision_quality": 82} for i in range(n)]


def test_scorecard_computes_core_metrics():
    s = build_performance_scorecards(_records())
    assert s["sample_size"] == 30
    assert s["expectancy_r"] is not None
    assert s["profit_factor"] is not None


def test_drift_detection_is_bounded_and_structured():
    d = build_drift_detection(_records(80))
    assert d["state"] in {"STABLE", "WATCH", "DRIFT_DETECTED"}
    assert isinstance(d["alerts"], list)


def test_command_center_is_observational_only():
    c = build_command_center({"session_intelligence": {"as_of": "2099-01-01T00:00:00+00:00", "confidence": 90}}, _records())
    assert c["version"] == "PHASE_26"
    assert 0 <= c["system_confidence_index"]["score"] <= 100
    assert c["controls"]["observational_only"] is True
    assert c["controls"]["broker_access"] is False
