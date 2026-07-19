from engine.institutional_trading_brain_v230 import build_institutional_trading_brain, VERSION


def sample(direction="bullish"):
    bullish = direction == "bullish"
    return {
        "ticker": "SPX", "session": "OPEN", "data_fresh": True,
        "dealer_positioning": {"bias": "BULLISH" if bullish else "BEARISH", "pressure_score": 80, "available": True},
        "options_flow": {"bias": "BULLISH" if bullish else "BEARISH", "net_flow_score": 75, "available": True},
        "market_structure": {"direction": "BULLISH" if bullish else "BEARISH", "state": "READY", "opening_type": "OPEN_DRIVE"},
        "probability": {"directional": {"bullish": 75 if bullish else 25, "bearish": 25 if bullish else 75}, "state": "READY"},
    }


def test_brain_is_read_only_and_versioned(monkeypatch, tmp_path):
    monkeypatch.setenv("APEX_MARKET_MEMORY_DB", str(tmp_path / "memory.db"))
    out = build_institutional_trading_brain(sample())
    assert out["ok"] is True
    assert out["version"] == VERSION
    assert out["guardrails"]["read_only"] is True
    assert out["guardrails"]["broker_mutation"] is False
    assert out["guardrails"]["automatic_execution"] is False


def test_brain_exposes_reasoning_surfaces(monkeypatch, tmp_path):
    monkeypatch.setenv("APEX_MARKET_MEMORY_DB", str(tmp_path / "memory.db"))
    out = build_institutional_trading_brain(sample())
    assert out["primary_thesis"]["invalidations"]
    assert len(out["thesis_timeline"]) == 5
    assert "bull_score" in out["evidence_summary"]
    assert out["confidence_calibration"]["automatic_weight_mutation"] is False
    assert out["explainability"]["limitations"]


def test_brain_supports_point_in_time_memory_filter(monkeypatch, tmp_path):
    monkeypatch.setenv("APEX_MARKET_MEMORY_DB", str(tmp_path / "memory.db"))
    out = build_institutional_trading_brain(sample(), before="2026-07-19T12:00:00+00:00")
    assert out["memory_context"]["look_ahead_protected"] is True


def test_dynamic_weights_are_auditable(monkeypatch, tmp_path):
    monkeypatch.setenv("APEX_MARKET_MEMORY_DB", str(tmp_path / "memory.db"))
    out = build_institutional_trading_brain(sample())
    assert out["evidence"]
    for item in out["evidence"]:
        assert "base_weight" in item
        assert "dynamic_weight" in item
        assert "weight_adjustment" in item
        assert "reason" in item
