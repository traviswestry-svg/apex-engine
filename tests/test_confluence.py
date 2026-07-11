"""Tests for APEX 7.5.3 Confluence Synthesizer — read-only, conviction-gated."""
from engine.confluence import build_confluence


def _ii(**over):
    base = {
        "institutional_bias": "NEUTRAL", "gamma_regime": "POSITIVE_GAMMA",
        "dealer_bias": "NEUTRAL", "flow_bias": "NEUTRAL", "flow_conviction": 20,
        "auction_state": "BALANCED", "auction_bias": "NEUTRAL", "acceptance": "ROTATING",
        "market_driver_bias": "NEUTRAL", "momentum_probability": 40, "direction": "NEUTRAL",
        "ici_score": 30, "pine_confirmed": None,
    }
    base.update(over)
    return {"institutional_intelligence": base, "market_state": {"price": 7531}}


def test_empty_bus_is_unavailable_not_crash():
    c = build_confluence({})
    assert c["available"] is False
    assert c["dominant_side"] == "NEITHER"


def test_mixed_signals_favour_neither():
    c = build_confluence(_ii())
    assert c["dominant_side"] == "NEITHER"
    assert c["conviction"] == "NONE"


def test_incomplete_bull_is_capped_not_aplus():
    # bullish evidence but ICI below floor + positive gamma → must not grade A+/STRONG
    c = build_confluence(_ii(
        institutional_bias="BULLISH", flow_bias="BULLISH", flow_conviction=86,
        auction_state="TREND_DAY_UP", auction_bias="BULLISH", acceptance="ACCEPTING",
        market_driver_bias="BULLISH", momentum_probability=90, direction="BULLISH",
        ici_score=55, pine_confirmed="CALL"))
    assert c["dominant_side"] == "LONG"
    assert c["conviction"] not in ("A+", "STRONG")
    assert any("ici" in m.lower() for m in c["long_missing"])


def test_complete_bull_earns_aplus():
    c = build_confluence(_ii(
        institutional_bias="BULLISH", gamma_regime="NEGATIVE_GAMMA", dealer_bias="BULLISH",
        flow_bias="BULLISH", flow_conviction=86, auction_state="TREND_DAY_UP",
        auction_bias="BULLISH", acceptance="ACCEPTING", market_driver_bias="BULLISH",
        momentum_probability=90, direction="BULLISH", ici_score=72, pine_confirmed="CALL"))
    assert c["dominant_side"] == "LONG"
    assert c["conviction"] == "A+"


def test_scores_are_bounded():
    c = build_confluence(_ii(institutional_bias="BEARISH", flow_bias="BEARISH", flow_conviction=90))
    assert 0 <= c["long_setup_score"] <= 100
    assert 0 <= c["short_setup_score"] <= 100


def test_missing_confirmations_listed():
    c = build_confluence(_ii(institutional_bias="BULLISH", flow_bias="BULLISH", flow_conviction=80))
    # something bullish leads but many confirmations absent → missing list populated
    assert len(c["long_missing"]) > 0
