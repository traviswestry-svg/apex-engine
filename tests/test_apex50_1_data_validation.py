from types import SimpleNamespace

from engine.data_registry import DataRegistry
from engine.data_quality import build_morning_registry
from engine.daily_key_levels_adapters import compute_atm_straddle_iv_details


def contract(strike, *, mid=None, last=None, iv=None, bid=None, ask=None):
    return SimpleNamespace(strike=strike, mid=mid, last=last, iv=iv, bid=bid, ask=ask)


def test_expected_move_uses_last_trade_fallback_preopen():
    calls = [contract(7300, last=42.0, iv=0.20)]
    puts = [contract(7300, last=38.0, iv=0.22)]
    straddle, iv, details = compute_atm_straddle_iv_details(calls, puts, 7302.0)
    assert straddle == 80.0
    assert round(iv, 4) == 0.21
    assert details["price_method"] == "last_trade_fallback"
    assert details["confidence"] == "MEDIUM"


def test_expected_move_prefers_two_sided_mid():
    calls = [contract(7300, mid=40.0, last=39.0, iv=0.20, bid=39.5, ask=40.5)]
    puts = [contract(7300, mid=36.0, last=35.0, iv=0.22, bid=35.5, ask=36.5)]
    straddle, _, details = compute_atm_straddle_iv_details(calls, puts, 7302.0)
    assert straddle == 76.0
    assert details["price_method"] == "two_sided_mid"
    assert details["confidence"] == "HIGH"


def test_not_applicable_gamma_crossing_does_not_reduce_completeness():
    structured = {
        "gamma_regime": "short_gamma",
        "expected_move": {"one_sigma": 50, "upper": 7350, "lower": 7250, "confidence": 0.9},
        "levels": [
            {"kind": "call_wall", "price": 7400},
            {"kind": "put_wall", "price": 7200},
            {"kind": "high_gamma_strike", "price": 7400},
            {"kind": "low_gamma_strike", "price": 7200},
        ],
    }
    report = build_morning_registry(
        structured=structured,
        options_feed={"call_contracts": 10, "put_contracts": 10},
        flow={"zero_gamma_confidence": "LOW", "active_gamma_flip": None},
        overnight_meta={}, provider_flags={},
    ).report()
    assert report["points"]["gamma_flip"]["status"] == "NOT_APPLICABLE"
    assert report["providers"]["quantdata"]["not_applicable"] == 3


def test_registry_excludes_not_applicable_from_denominator():
    registry = DataRegistry()
    registry.put("available", 1, source="x")
    registry.put("no_crossing", None, source="x", applicable=False, reason="not expected")
    report = registry.report()
    assert report["score"] == 100.0
    assert report["total"] == 1
