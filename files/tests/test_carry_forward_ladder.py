"""Tests for the Carry-Forward Levels Ladder (engine.carry_forward_ladder)."""
from engine.carry_forward_ladder import build_carry_forward_ladder


def _structured():
    # Mirrors DailyKeyLevels.to_dict(): spot + levels[] + expected_move + gamma_regime.
    return {
        "spot": 7748.5,
        "gamma_regime": "long_gamma",
        "expected_move": {"upper": 7805.87, "lower": 7763.03},
        "levels": [
            {"kind": "gamma_flip", "price": 7807.5, "label": "Gamma Flip", "distance": 59.0, "prior_reactions": 13},
            {"kind": "call_wall", "price": 8000.0, "label": "Call Wall", "distance": 251.5},
            {"kind": "overnight_high", "price": 7784.7, "label": "Overnight High", "prior_reactions": 29},
            {"kind": "vah", "price": 7767.0, "label": "VAH"},
            {"kind": "developing_poc", "price": 7749.0, "label": "Developing POC"},
            {"kind": "val", "price": 7748.0, "label": "VAL"},
            {"kind": "prev_close", "price": 7748.5, "label": "Prev Close"},
            {"kind": "prev_day_low", "price": 7737.95, "label": "Prev Day Low"},
            {"kind": "put_wall", "price": 7700.0, "label": "Put Wall"},
            {"kind": "composite_poc", "price": 7679.4, "label": "Composite POC"},
            {"kind": "low_gamma_strike", "price": 7500.0, "label": "Low Gamma Strike"},
        ],
    }


def test_empty_input_is_unavailable():
    d = build_carry_forward_ladder(None)
    assert d["available"] is False
    assert d["overhead"] == [] and d["value"] == [] and d["below"] == []


def test_classifies_relative_to_spot():
    d = build_carry_forward_ladder(_structured())
    assert d["available"] is True
    over = {r["kind"] for r in d["overhead"]}
    below = {r["kind"] for r in d["below"]}
    value = {r["kind"] for r in d["value"]}
    # Well above spot -> overhead
    assert {"gamma_flip", "call_wall", "overnight_high", "vah"} <= over
    # Well below spot -> below
    assert {"put_wall", "composite_poc", "low_gamma_strike", "prev_day_low"} <= below
    # Hugging spot (7748.5 +/- ~11.6pt band) -> value shelf
    assert {"prev_close", "val", "developing_poc"} <= value


def test_overhead_sorted_high_to_low_and_nearest():
    d = build_carry_forward_ladder(_structured())
    prices = [r["price"] for r in d["overhead"]]
    assert prices == sorted(prices, reverse=True)
    # nearest_above is the lowest overhead; nearest_below the highest below
    assert d["nearest_above"]["price"] == min(prices)
    below_prices = [r["price"] for r in d["below"]]
    assert d["nearest_below"]["price"] == max(below_prices)


def test_key_pivots_and_expected_move_folded_in():
    d = build_carry_forward_ladder(_structured())
    assert d["key_pivots"]["gamma_flip"] == 7807.5
    assert d["key_pivots"]["put_wall"] == 7700.0
    assert d["key_pivots"]["call_wall"] == 8000.0
    # expected move upper/lower folded in as levels
    kinds = {r["kind"] for r in d["overhead"] + d["value"] + d["below"]}
    assert "em_upper" in kinds and "em_lower" in kinds


def test_plan_line_is_neutral_and_present():
    d = build_carry_forward_ladder(_structured())
    plan = d["plan"]
    assert plan and "gamma flip" in plan
    # never a trade call
    assert not any(w in plan.lower() for w in ("buy", "sell", "long", "short", "enter"))


def test_feed_required_and_bad_prices_dropped():
    s = {"spot": 7748.5, "levels": [
        {"kind": "vah", "price": "[FEED REQUIRED]", "label": "VAH"},
        {"kind": "val", "price": None, "label": "VAL"},
        {"kind": "put_wall", "price": 7700.0, "label": "Put Wall"},
    ]}
    d = build_carry_forward_ladder(s)
    kinds = {r["kind"] for r in d["overhead"] + d["value"] + d["below"]}
    assert kinds == {"put_wall"}


def test_no_spot_still_returns_ordered_ladder():
    s = dict(_structured())
    s.pop("spot")
    d = build_carry_forward_ladder(s, spot=None)
    assert d["available"] is True
    # With no spot, everything lands in the single ordered ladder (overhead slot)
    assert len(d["overhead"]) >= 11
    prices = [r["price"] for r in d["overhead"]]
    assert prices == sorted(prices, reverse=True)


def test_never_raises_on_garbage():
    for bad in [{"levels": "nope"}, {"levels": [1, 2, 3]}, {"levels": [{"no_price": 1}]}, 42, "x"]:
        d = build_carry_forward_ladder(bad)
        assert "available" in d
