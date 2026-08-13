"""Tests for APEX 24.4 Multi-Timeframe Intelligence."""
from flask import Flask

from engine import institutional_multi_timeframe_v244 as mtf
from engine.institutional_multi_timeframe_v244_routes import (
    register_institutional_multi_timeframe_v244_routes, verify_registered, REQUIRED_ROUTES)


BULLISH_ALL = {"multi_timeframe": {tf: {"trend": "BULLISH", "strength": 80} for tf in mtf.TIMEFRAMES}}
HTF_LTF_CONFLICT = {"multi_timeframe": {
    "W": {"trend": "BULLISH", "strength": 90}, "D": {"trend": "BULLISH", "strength": 80},
    "4H": {"trend": "BULLISH", "strength": 70},
    "5M": {"trend": "BEARISH", "strength": 80}, "3M": {"trend": "BEARISH", "strength": 70},
    "1M": {"trend": "BEARISH", "strength": 60}}}


def test_status_read_only():
    s = mtf.status()
    assert s["status"] == "READY"
    assert s["read_only"] is True
    assert list(s["timeframes"]) == list(mtf.TIMEFRAMES)
    assert s["broker_order_submission_enabled"] is False


def test_full_bullish_alignment():
    a = mtf.alignment(BULLISH_ALL)
    assert a["dominant_bias"] == "BULLISH"
    assert a["alignment_score"] == 100.0
    assert a["trend_agreement_pct"] == 100.0
    assert a["higher_timeframe_bias"]["bias"] == "BULLISH"
    assert a["lower_timeframe_confirmation"] is True
    assert a["institutional_directional_confidence"] > 80


def test_htf_ltf_conflict_detected():
    c = mtf.conflicts(HTF_LTF_CONFLICT)
    codes = {x["code"] for x in c["conflicts"]}
    assert "HTF_LTF_CONFLICT" in codes
    assert c["has_conflict"] is True
    a = mtf.alignment(HTF_LTF_CONFLICT)
    # higher timeframe should dominate the net bias (weights favor W/D/4H)
    assert a["higher_timeframe_bias"]["bias"] == "BULLISH"
    assert a["lower_timeframe_bias"]["bias"] == "BEARISH"
    assert a["lower_timeframe_confirmation"] is False


def test_neutral_when_no_data():
    a = mtf.alignment({})
    assert a["dominant_bias"] == "NEUTRAL"
    assert a["alignment_score"] == 0.0
    assert a["available_timeframes"] == []


def test_alias_parsing():
    a = mtf.alignment({"timeframe_trends": {"weekly": "bullish", "daily": "bullish", "1h": "bullish"}})
    assert a["timeframes"]["W"]["available"] is True
    assert a["timeframes"]["D"]["trend"] == "BULLISH"
    assert a["timeframes"]["1H"]["available"] is True


def test_integration_signal_lists_consumers():
    sig = mtf.integration_signals(BULLISH_ALL)
    assert sig["bias"] == "BULLISH"
    assert "PORTFOLIO_INTELLIGENCE" in sig["consumers"]
    assert "TRADING_BRAIN" in sig["consumers"]


def test_build_payload_has_conflicts_and_integration():
    v = mtf.build_multi_timeframe(HTF_LTF_CONFLICT)
    assert "conflicts" in v and "integration" in v
    assert v["integration"]["higher_timeframe_bias"] == "BULLISH"


def _client():
    app = Flask(__name__)
    register_institutional_multi_timeframe_v244_routes(
        app, last_result_provider=lambda: BULLISH_ALL)
    return app, app.test_client()


def test_routes_and_verifier():
    app, c = _client()
    assert c.get("/api/multi-timeframe/status").get_json()["read_only"] is True
    assert c.get("/api/multi-timeframe/alignment").get_json()["dominant_bias"] == "BULLISH"
    assert c.get("/api/multi-timeframe/conflicts").get_json()["ok"] is True
    assert verify_registered(app) == []
    bare = Flask("bare")
    assert len(verify_registered(bare)) == len(REQUIRED_ROUTES)


def test_adhoc_post_alignment():
    app, c = _client()
    r = c.post("/api/multi-timeframe/alignment", json=HTF_LTF_CONFLICT).get_json()
    assert r["higher_timeframe_bias"]["bias"] == "BULLISH"


def test_mission_control_includes_mtf_panel():
    from engine.institutional_mission_control_v213 import build_mission_control
    mc = build_mission_control({"ticker": "SPX", **BULLISH_ALL})
    assert "MULTI_TIMEFRAME" in mc["groups"]
    assert mc["drilldowns"]["multi_timeframe"] == "/api/multi-timeframe/alignment"
