"""APEX 11.0C Module 3 — Probability Distribution Engine."""
from engine.probability_distribution import (SCENARIOS, build_probability_distribution)

_POS_GAMMA_BALANCED = {"gamma_regime": {"regime": "POSITIVE_GAMMA"},
                       "auction": {"state": "BALANCED"},
                       "volatility": {"regime": "COMPRESSION"}}
_STRONG_BULL = {"gamma_regime": {"regime": "NEGATIVE_GAMMA"}, "auction": {"state": "TREND_UP"},
                "trend": {"direction": "BULLISH", "strength": 40},
                "flow": {"bias": "BULLISH", "conviction": 85},
                "volatility": {"regime": "EXPANSION", "vix": 24}}
_STRONG_BEAR = {"gamma_regime": {"regime": "NEGATIVE_GAMMA"}, "auction": {"state": "TREND_DOWN"},
                "trend": {"direction": "BEARISH", "strength": 35},
                "flow": {"bias": "BEARISH", "conviction": 70},
                "volatility": {"regime": "EXPANSION", "vix": 26}}


def test_distribution_sums_to_100():
    r = build_probability_distribution(_STRONG_BULL)
    assert abs(sum(s["probability_pct"] for s in r["scenarios"]) - 100.0) < 0.5


def test_all_five_scenarios_present():
    r = build_probability_distribution(_POS_GAMMA_BALANCED)
    assert {s["scenario"] for s in r["scenarios"]} == set(SCENARIOS)


def test_no_scenario_is_ever_a_near_certainty():
    """A 0DTE session is never 100% one outcome — the engine must stay a distribution."""
    for bus in (_STRONG_BULL, _STRONG_BEAR, _POS_GAMMA_BALANCED):
        r = build_probability_distribution(bus)
        assert all(s["probability_pct"] < 90 for s in r["scenarios"])


def test_strong_bull_leans_bullish():
    r = build_probability_distribution(_STRONG_BULL)
    assert r["directional_lean"]["label"] == "BULLISH"
    assert r["directional_lean"]["bullish_pct"] > r["directional_lean"]["bearish_pct"]


def test_strong_bear_leans_bearish():
    r = build_probability_distribution(_STRONG_BEAR)
    assert r["directional_lean"]["label"] == "BEARISH"


def test_positive_gamma_favours_balance():
    r = build_probability_distribution(_POS_GAMMA_BALANCED)
    assert r["primary_scenario"] == "BALANCED_AUCTION"
    assert r["directional_lean"]["label"] == "BALANCED"


def test_no_evidence_is_near_uniform_and_not_informative():
    r = build_probability_distribution({"market_state": {}})
    assert all(abs(s["probability_pct"] - 20.0) < 1.0 for s in r["scenarios"])
    assert r["distribution_is_informative"] is False


def test_basis_is_structural_not_historical():
    """The engine must never claim historical frequency."""
    r = build_probability_distribution(_STRONG_BULL)
    assert r["basis"] == "structural_current_state"
    assert "not historical" in r["basis_note"].lower()


def test_empty_bus_is_unavailable_not_crash():
    r = build_probability_distribution({})
    assert r["available"] is False
    r2 = build_probability_distribution(None)
    assert r2["available"] is False


def test_evidence_trail_explains_the_distribution():
    r = build_probability_distribution(_STRONG_BULL)
    assert r["evidence"]
    assert all("source" in e and "detail" in e for e in r["evidence"])
