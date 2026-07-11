"""Tests for APEX 7.5.7 Decision Intelligence."""
from engine.confluence import build_confluence
from engine.event_calendar import build_event_intelligence
from engine.decision_intelligence import build_decision_intelligence


def _panel(ii, inval=None):
    bus = {"institutional_intelligence": ii, "market_state": {"price": 7531},
           "range_intelligence": {"range_intelligence": {"invalidation": inval or []}}}
    return build_decision_intelligence(bus, confluence=build_confluence(bus),
                                       events=build_event_intelligence())


_BASE = dict(gamma_regime="POSITIVE_GAMMA", dealer_bias="NEUTRAL", pin_probability=50,
             market_driver_story="x", market_driver_bias="NEUTRAL", nearest_magnet="7540",
             primary_risk="r", evidence=["e"], available=True)


def test_empty_bus_avoids():
    d = build_decision_intelligence({})
    assert d["verdict"] == "AVOID"
    assert d["available"] is False


def test_forming_setup_is_watch():
    d = _panel({**_BASE, "institutional_bias": "BULLISH", "flow_bias": "BULLISH",
                "flow_conviction": 86, "auction_state": "TREND_DAY_UP", "auction_bias": "BULLISH",
                "acceptance": "ACCEPTING", "market_driver_bias": "BULLISH", "momentum_probability": 90,
                "direction": "BULLISH", "ici_score": 55, "pine_confirmed": "CALL"})
    assert d["verdict"] == "WATCH"
    assert len(d["questions"]) == 6


def test_complete_setup_trades():
    d = _panel({**_BASE, "institutional_bias": "BULLISH", "gamma_regime": "NEGATIVE_GAMMA",
                "dealer_bias": "BULLISH", "flow_bias": "BULLISH", "flow_conviction": 86,
                "auction_state": "TREND_DAY_UP", "auction_bias": "BULLISH", "acceptance": "ACCEPTING",
                "market_driver_bias": "BULLISH", "momentum_probability": 90, "direction": "BULLISH",
                "ici_score": 72, "pine_confirmed": "CALL"})
    assert d["verdict"] == "TRADE"


def test_chop_avoids():
    d = _panel({**_BASE, "institutional_bias": "NEUTRAL", "flow_bias": "NEUTRAL",
                "flow_conviction": 15, "auction_state": "BALANCED", "momentum_probability": 40,
                "direction": "NEUTRAL", "ici_score": 28})
    assert d["verdict"] == "AVOID"


def test_pyramid_has_four_tiers():
    d = _panel({**_BASE, "institutional_bias": "BULLISH", "ici_score": 55})
    assert len(d["confidence_pyramid"]) == 4
