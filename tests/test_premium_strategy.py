"""Tests for APEX 7.6.0 Institutional Premium Strategy Engine.

Read-only structure selection over the composed Data Bus. The engine consumes
`confluence` for direction, so tests build it the same way the route does.
"""
from engine.premium_strategy import (
    build_premium_strategy,
    DEBIT_CALL, DEBIT_PUT, BULL_PUT, BEAR_CALL, IRON_CONDOR, NO_TRADE,
)
from engine.confluence import build_confluence


def _bus(ii=None, ms=None, vol=None, rng=None):
    return {
        "institutional_intelligence": ii or {},
        "market_state": ms or {},
        "volatility": vol or {},
        "range_intelligence": {"range_intelligence": rng or {}},
    }


def _ii(**over):
    base = {
        "institutional_bias": "NEUTRAL", "gamma_regime": "POSITIVE_GAMMA",
        "dealer_bias": "NEUTRAL", "flow_bias": "NEUTRAL", "flow_conviction": 20,
        "auction_state": "BALANCED", "auction_bias": "NEUTRAL", "acceptance": "ROTATING",
        "market_driver_bias": "NEUTRAL", "momentum_probability": 40, "direction": "NEUTRAL",
        "ici_score": 30, "pin_probability": 30, "vol_regime": "MID",
        "flow_contradictions": [], "pine_confirmed": None,
    }
    base.update(over)
    return base


_MS = {"price": 6300, "vwap": 6288, "poc": 6280, "call_wall": 6350, "put_wall": 6240,
       "zero_gamma": 6275, "minutes_open": 60, "price_vs_poc": "ABOVE_POC",
       "session_state": "RTH", "flow_bias": "NEUTRAL"}
_RNG = {"expected_move": 28, "invalidation": ["Loss of VWAP 6288"],
        "session_high": 6305, "session_low": 6270, "mid": 6300}


def _run(ii, ms=None, vol=None, rng=None):
    b = _bus(ii, ms or dict(_MS), vol or {"vix": 18, "iv_rank_estimate": 40}, rng or dict(_RNG))
    return build_premium_strategy(b, confluence=build_confluence(b))


# ── envelope / safety ────────────────────────────────────────────────────────
def test_empty_bus_is_unavailable_not_crash():
    r = build_premium_strategy({})
    assert r["available"] is False
    assert r["strategy"] == NO_TRADE
    assert r["headline"]


def test_no_institutional_layer_is_unavailable():
    r = build_premium_strategy({"market_state": {"price": 6300}})
    assert r["available"] is False


def test_never_raises_on_garbage():
    r = build_premium_strategy({"institutional_intelligence": {"institutional_bias": object()}})
    assert isinstance(r, dict)
    assert "strategy" in r


# ── CASE 1 — strong direction + low VIX → debit spread ───────────────────────
def test_case1_strong_bull_low_vix_is_debit_call():
    ii = _ii(institutional_bias="BULLISH", gamma_regime="NEGATIVE_GAMMA", dealer_bias="BULLISH",
             flow_bias="BULLISH", flow_conviction=80, auction_state="TREND_DAY_UP",
             auction_bias="BULLISH", acceptance="ACCEPTING", market_driver_bias="BULLISH",
             momentum_probability=82, direction="BULLISH", ici_score=78, pine_confirmed="CALL")
    r = _run(ii, vol={"vix": 13.5, "iv_rank_estimate": 20})
    assert r["strategy"] == DEBIT_CALL
    assert r["premium_kind"] == "DEBIT"
    assert r["legs"]["buy_leg"] < r["legs"]["sell_leg"]      # call debit: long below short
    assert r["legs"]["entry_debit"] > 0
    assert r["legs"]["max_loss"] > 0


def test_case1_strong_bear_low_vix_is_debit_put():
    ii = _ii(institutional_bias="BEARISH", gamma_regime="NEGATIVE_GAMMA", dealer_bias="BEARISH",
             flow_bias="BEARISH", flow_conviction=80, auction_state="TREND_DAY_DOWN",
             auction_bias="BEARISH", acceptance="ACCEPTING", market_driver_bias="BEARISH",
             momentum_probability=82, direction="BEARISH", ici_score=78, pine_confirmed="PUT")
    ms = dict(_MS, vwap=6312, price_vs_poc="BELOW_POC", flow_bias="BEARISH")
    r = _run(ii, ms=ms, vol={"vix": 13.5, "iv_rank_estimate": 20})
    assert r["strategy"] == DEBIT_PUT
    assert r["legs"]["buy_leg"] > r["legs"]["sell_leg"]      # put debit: long above short


# ── CASE 2 — directional + high VIX → credit spread in the direction ─────────
def test_case2_bear_high_vix_is_bear_call_credit():
    ii = _ii(institutional_bias="BEARISH", gamma_regime="NEGATIVE_GAMMA", dealer_bias="BEARISH",
             flow_bias="BEARISH", flow_conviction=75, auction_state="TREND_DAY_DOWN",
             auction_bias="BEARISH", acceptance="ACCEPTING", market_driver_bias="BEARISH",
             momentum_probability=60, direction="BEARISH", ici_score=72, pine_confirmed="PUT")
    ms = dict(_MS, vwap=6312, price_vs_poc="BELOW_POC", flow_bias="BEARISH")
    r = _run(ii, ms=ms, vol={"vix": 24, "iv_rank_estimate": 70})
    assert r["strategy"] == BEAR_CALL
    assert r["premium_kind"] == "CREDIT"
    assert r["legs"]["sell_leg"] < r["legs"]["buy_leg"]      # bear call: short below long
    assert r["legs"]["sell_leg"] > r["price"]               # short above spot
    assert r["legs"]["pop"] >= 0.65


def test_case2_bull_high_vix_is_bull_put_credit():
    ii = _ii(institutional_bias="BULLISH", gamma_regime="NEGATIVE_GAMMA", dealer_bias="BULLISH",
             flow_bias="BULLISH", flow_conviction=75, auction_state="TREND_DAY_UP",
             auction_bias="BULLISH", acceptance="ACCEPTING", market_driver_bias="BULLISH",
             momentum_probability=60, direction="BULLISH", ici_score=72, pine_confirmed="CALL")
    r = _run(ii, ms=dict(_MS, flow_bias="BULLISH"), vol={"vix": 24, "iv_rank_estimate": 70})
    assert r["strategy"] == BULL_PUT
    assert r["legs"]["sell_leg"] < r["price"]               # short below spot


# ── VIX filter — elite trend overrides the high-VIX credit preference ────────
def test_elite_trend_overrides_high_vix_to_debit():
    ii = _ii(institutional_bias="BULLISH", gamma_regime="NEGATIVE_GAMMA", dealer_bias="BULLISH",
             flow_bias="BULLISH", flow_conviction=90, auction_state="TREND_DAY_UP",
             auction_bias="BULLISH", acceptance="ACCEPTING", market_driver_bias="BULLISH",
             momentum_probability=88, direction="BULLISH", ici_score=82, pine_confirmed="CALL")
    r = _run(ii, ms=dict(_MS, flow_bias="BULLISH"), vol={"vix": 26, "iv_rank_estimate": 80})
    assert r["strategy"] == DEBIT_CALL
    assert "ELITE" in r["case"]


# ── CASE 3 — balanced + positive gamma / high pin → iron condor ──────────────
def test_case3_balanced_pinning_high_vix_is_condor():
    ii = _ii(institutional_bias="NEUTRAL", gamma_regime="POSITIVE_GAMMA", flow_bias="NEUTRAL",
             auction_state="BALANCED", acceptance="ROTATING", pin_probability=72)
    r = _run(ii, ms=dict(_MS, gamma_regime="POSITIVE_GAMMA", price_vs_poc="AT_POC"),
             vol={"vix": 22, "iv_rank_estimate": 55})
    assert r["strategy"] == IRON_CONDOR
    legs = r["legs"]
    assert legs["put_short"] < r["price"] < legs["call_short"]
    assert legs["put_long"] < legs["put_short"]
    assert legs["call_long"] > legs["call_short"]
    assert legs["entry_credit"] > 0


def test_case3_balanced_pinning_low_vix_no_premium_is_no_trade():
    ii = _ii(institutional_bias="NEUTRAL", gamma_regime="POSITIVE_GAMMA", flow_bias="NEUTRAL",
             auction_state="BALANCED", acceptance="ROTATING", pin_probability=62)
    r = _run(ii, ms=dict(_MS, gamma_regime="POSITIVE_GAMMA"),
             vol={"vix": 12, "iv_rank_estimate": 10})
    assert r["strategy"] == NO_TRADE


# ── CASE 4 — contradiction / weak → no trade ─────────────────────────────────
def test_case4_flow_contradiction_is_no_trade():
    ii = _ii(institutional_bias="BEARISH", flow_bias="BEARISH", flow_conviction=60,
             auction_state="TREND_DAY_DOWN", auction_bias="BEARISH", direction="BEARISH",
             momentum_probability=55, ici_score=55,
             flow_contradictions=["Bullish sweeps against a bearish tape"])
    r = _run(ii, ms=dict(_MS, flow_bias="BEARISH"))
    assert r["strategy"] == NO_TRADE
    assert "CONTRADICTION" in r["case"]


def test_event_day_is_no_trade():
    ii = _ii(institutional_bias="BULLISH", flow_bias="BULLISH", flow_conviction=80,
             auction_state="TREND_DAY_UP", auction_bias="BULLISH", direction="BULLISH",
             momentum_probability=80, ici_score=80)
    b = _bus(ii, dict(_MS, flow_bias="BULLISH"), {"vix": 14}, dict(_RNG))
    r = build_premium_strategy(b, confluence=build_confluence(b),
                               events={"event_regime": "EVENT_DAY",
                                       "headline_event": {"label": "CPI"}})
    assert r["strategy"] == NO_TRADE
    assert r["case"] == "EVENT_GATE"


# ── credit-quality filter ────────────────────────────────────────────────────
def test_debit_spread_not_rejected_for_low_pop():
    # A directional debit spread has ~50% POP by nature — it must NOT be culled
    # by the credit POP floor.
    ii = _ii(institutional_bias="BULLISH", gamma_regime="NEGATIVE_GAMMA", dealer_bias="BULLISH",
             flow_bias="BULLISH", flow_conviction=80, auction_state="TREND_DAY_UP",
             auction_bias="BULLISH", acceptance="ACCEPTING", market_driver_bias="BULLISH",
             momentum_probability=82, direction="BULLISH", ici_score=78, pine_confirmed="CALL")
    r = _run(ii, ms=dict(_MS, flow_bias="BULLISH"), vol={"vix": 13, "iv_rank_estimate": 20})
    assert r["strategy"] == DEBIT_CALL
    assert r["legs"]["pop"] < 0.65   # low POP, still accepted


def test_credit_spread_respects_pop_floor():
    r = _run(_ii(institutional_bias="BULLISH", flow_bias="BULLISH", flow_conviction=75,
                 auction_state="TREND_DAY_UP", auction_bias="BULLISH", acceptance="ACCEPTING",
                 market_driver_bias="BULLISH", momentum_probability=60, direction="BULLISH",
                 ici_score=72, gamma_regime="NEGATIVE_GAMMA", dealer_bias="BULLISH"),
             ms=dict(_MS, flow_bias="BULLISH"), vol={"vix": 24, "iv_rank_estimate": 70})
    if r["strategy"] in (BULL_PUT, BEAR_CALL):
        assert r["legs"]["pop"] >= 0.65


# ── exit plan + structure of the payload ─────────────────────────────────────
def test_recommendation_carries_exit_plan_and_story():
    ii = _ii(institutional_bias="BEARISH", flow_bias="BEARISH", flow_conviction=75,
             auction_state="TREND_DAY_DOWN", auction_bias="BEARISH", direction="BEARISH",
             momentum_probability=60, ici_score=72, gamma_regime="NEGATIVE_GAMMA",
             dealer_bias="BEARISH", market_driver_bias="BEARISH", acceptance="ACCEPTING")
    r = _run(ii, ms=dict(_MS, vwap=6312, flow_bias="BEARISH"),
             vol={"vix": 23, "iv_rank_estimate": 60})
    assert r["strategy"] != NO_TRADE
    assert r["exit_plan"]["target"]
    assert r["exit_plan"]["stop"]
    assert r["exit_plan"]["time_stop"]
    assert isinstance(r["story"], list) and r["story"]
    assert r["headline"]


# ── opening-range proxy model ────────────────────────────────────────────────
def test_opening_range_model_inactive_before_15_min():
    ii = _ii()
    r = _run(ii, ms=dict(_MS, minutes_open=8))
    assert r["opening_range_model"]["active"] is False
    assert r["opening_range_model"]["basis"] == "session_range_proxy"


def test_opening_range_bear_call_confirmation():
    ii = _ii(institutional_bias="BEARISH", flow_bias="BEARISH", flow_conviction=75,
             auction_state="TREND_DAY_DOWN", auction_bias="BEARISH", direction="BEARISH",
             momentum_probability=60, ici_score=72, gamma_regime="NEGATIVE_GAMMA",
             dealer_bias="BEARISH", market_driver_bias="BEARISH", acceptance="ACCEPTING")
    # price below the developing range low, below VWAP, below POC
    ms = dict(_MS, price=6265, vwap=6300, price_vs_poc="BELOW_POC",
              flow_bias="BEARISH", minutes_open=30)
    rng = dict(_RNG, session_low=6270, session_high=6310)
    r = _run(ii, ms=ms, vol={"vix": 23}, rng=rng)
    orm = r["opening_range_model"]
    assert orm["active"] is True
    assert orm["side"] == BEAR_CALL
