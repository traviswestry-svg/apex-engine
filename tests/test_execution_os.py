from engine.institutional_execution_os import build_execution_snapshot, build_morning_readiness


def sample_result():
    return {
        "market_open": True,
        "broker_ready": True,
        "premium_strategy": {
            "bid": 3.0, "ask": 3.2, "mid": 3.1,
            "max_profit": 310, "max_loss": 690,
            "execution_confidence": .9,
            "legs": [{"strike": 6000}, {"strike": 5990}],
            "chain_quality": {"quality_score": 92, "action": "ALLOW", "valid_contract_count": 2, "max_quote_age_seconds": 3},
        },
    }


def test_execution_snapshot_is_bounded_and_explainable():
    out = build_execution_snapshot(sample_result())
    assert 0 <= out["execution_score"] <= 100
    assert 0 <= out["fill_probability"] <= 1
    assert out["execution_decision"] in {"EXECUTABLE", "CAUTION", "DO_NOT_EXECUTE"}
    assert out["history_free"] is True
    assert out["pricing"]["spread"] == .2


def test_missing_recommendation_fails_closed():
    out = build_execution_snapshot({"market_open": True})
    assert out["execution_score"] <= 25
    assert out["execution_decision"] == "DO_NOT_EXECUTE"
    assert "recommendation_present" in out["blocking_items"]


def test_readiness_analysis_only_when_closed():
    checks = {k: {"status": "PASS", "summary": "ok"} for k in [
        "application", "database", "data_freshness", "providers", "recommendation_ledger",
        "execution", "clock", "version_consistency", "alerts", "scheduler"]}
    out = build_morning_readiness(system_checks=checks, execution={"execution_score": 95, "execution_decision": "EXECUTABLE"}, market_open=False)
    assert out["trading_mode"] == "ANALYSIS_ONLY"
    assert out["score"] >= 90


def test_readiness_blocks_on_critical_failure():
    checks = {k: {"status": "PASS", "summary": "ok"} for k in [
        "application", "database", "data_freshness", "providers", "recommendation_ledger",
        "execution", "clock", "version_consistency", "alerts", "scheduler"]}
    checks["database"] = {"status": "FAIL", "summary": "down"}
    out = build_morning_readiness(system_checks=checks, execution={"execution_score": 95}, market_open=True)
    assert out["trading_mode"] == "DO_NOT_TRADE"
    assert "database" in out["blocking_items"]
