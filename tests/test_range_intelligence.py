"""tests/test_range_intelligence.py — APEX 7.2 Range Intelligence tests.

Covers: ES/SPX basis conversion, confluence clustering into zones, all scenarios
(pre-RTH, base, bull/bear expansion, balanced rotation, exhaustion, insufficient),
range-used (session vs pre-RTH estimate), exhaustion risk, quality flags for every
missing input, the endpoint envelope, and the self-evaluation history/scorecard.

Run: python -m pytest tests/test_range_intelligence.py -q
(no pytest? the __main__ block runs the same assertions.)
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP_DB = os.path.join(tempfile.gettempdir(), "atd_range_test.db")
for _p in (_TMP_DB, _TMP_DB + "-wal", _TMP_DB + "-shm"):
    if os.path.exists(_p):
        os.remove(_p)
os.environ["RANGE_DB_PATH"] = _TMP_DB

from engine.range_intelligence import (  # noqa: E402
    build_range_intelligence, capture_projection, record_actuals, history, scorecard,
    init_history, VERSION,
)


# ── Data Bus fixtures ─────────────────────────────────────────────────────────

def _bus(**over):
    """A composed last_result with sensible SPX defaults; override per test."""
    ms = {"price": 7484.0, "vwap": 7480.0, "poc": 7482.0, "vah": 7488.0, "val": 7476.0,
          "call_wall": 7520.0, "put_wall": 7440.0, "zero_gamma": 7470.0,
          "gamma_regime": "POSITIVE_GAMMA", "poc_migration": "STABLE", "flow_bias": "NEUTRAL",
          "sweep_count": 0, "auction_state": "BALANCED", "session_state": "RTH"}
    st = {"prev_day_high": 7508.0, "prev_day_low": 7452.0, "prev_close": 7486.0,
          "session_high": 7495.0, "session_low": 7470.0, "current_price": 7484.0}
    vol = {"vix": 14.0, "regime": "NORMAL"}
    mags = {"magnets": [{"strike": 7520.0, "side": "ABOVE", "type": "CALL_WALL", "score": 88},
                        {"strike": 7440.0, "side": "BELOW", "type": "PUT_WALL", "score": 84}]}
    bus = {"market_state": ms, "structure": st, "volatility": vol, "strike_magnets": mags,
           "dealer_positioning": {"gamma_regime": "POSITIVE_GAMMA"},
           "market_drivers": {"bias": "NEUTRAL"},
           "institutional_intelligence": {"institutional_bias": "NEUTRAL"}}
    for k, v in over.items():
        if k in bus and isinstance(bus[k], dict) and isinstance(v, dict):
            bus[k] = {**bus[k], **v}
        else:
            bus[k] = v
    return bus


def _ri(env):
    return env["range_intelligence"]


# ── core envelope + zones ─────────────────────────────────────────────────────

def test_envelope_shape():
    env = build_range_intelligence(_bus(), market_open=True)
    assert env["ok"] and env["version"] == VERSION and env["ticker"] == "SPX"
    ri = _ri(env)
    assert ri["available"] is True
    for k in ("low", "high", "mid", "confidence", "reasons"):
        assert k in ri["projected_high_zone"] and k in ri["projected_low_zone"]
    assert ri["projected_high_zone"]["mid"] > 7484.0 > ri["projected_low_zone"]["mid"]


def test_zone_confidence_bounded():
    ri = _ri(build_range_intelligence(_bus(), market_open=True))
    for z in ("projected_high_zone", "projected_low_zone"):
        assert 30 <= ri[z]["confidence"] <= 90


def test_confluence_raises_confidence():
    # cluster three high-side levels tightly => higher confidence than a lone level
    tight = _bus(market_state={"call_wall": 7507.0}, strike_magnets={"magnets": [
        {"strike": 7508.0, "side": "ABOVE", "type": "CALL_WALL", "score": 88},
        {"strike": 7506.0, "side": "ABOVE", "type": "GAMMA", "score": 70}]})
    ri = _ri(build_range_intelligence(tight, market_open=True))
    # prev_day_high 7508 + call_wall 7507 + magnets 7508/7506 cluster
    assert ri["projected_high_zone"]["confidence"] >= 63


# ── ES/SPX basis conversion ───────────────────────────────────────────────────

def test_basis_conversion_present_pre_rth():
    bus = _bus(overnight_game_plan={"es_price": 7506.5, "overnight_high": 7530.0,
                                    "overnight_low": 7474.0})
    ri = _ri(build_range_intelligence(bus, market_open=False))
    b = ri["basis_diagnostics"]
    assert b["es_available"] is True
    assert b["basis"] == round(7506.5 - 7484.0, 2)  # 22.5
    # spx-equivalent = es_level - basis
    assert b["spx_equivalent_overnight_high"] == round(7530.0 - 22.5, 2)  # 7507.5
    assert b["spx_equivalent_overnight_low"] == round(7474.0 - 22.5, 2)   # 7451.5


def test_basis_never_compares_raw_es():
    # raw ES overnight high (7530) must NOT appear as a high-zone level; only its
    # SPX-equivalent (7507.5) may cluster in.
    bus = _bus(overnight_game_plan={"es_price": 7506.5, "overnight_high": 7530.0,
                                    "overnight_low": 7474.0})
    ri = _ri(build_range_intelligence(bus, market_open=False))
    assert ri["projected_high_zone"]["high"] < 7525.0  # nowhere near raw ES 7530


def test_es_unavailable_flag():
    ri = _ri(build_range_intelligence(_bus(), market_open=True))  # no overnight block
    assert "ES_FEED_UNAVAILABLE_USING_SPX_ONLY" in ri["quality_flags"]
    assert ri["basis_diagnostics"]["es_available"] is False


# ── expected move (VIX-derived) ──────────────────────────────────────────────

def test_expected_move_from_vix():
    ri = _ri(build_range_intelligence(_bus(), market_open=True))
    assert ri["expected_move"] is not None
    assert "EXPECTED_MOVE_DERIVED_FROM_VIX" in ri["quality_flags"]
    assert ri["expected_move"]["high"] > 7484.0 > ri["expected_move"]["low"]


def test_expected_move_unavailable_flag():
    ri = _ri(build_range_intelligence(_bus(volatility={"vix": None}), market_open=True))
    assert ri["expected_move"] is None
    assert "EXPECTED_MOVE_UNAVAILABLE" in ri["quality_flags"]


# ── scenarios ─────────────────────────────────────────────────────────────────

def test_base_case_inside_range():
    ri = _ri(build_range_intelligence(_bus(), market_open=True))
    assert ri["active_scenario"] in ("BASE_CASE", "BALANCED_ROTATION")


def test_bull_expansion():
    bus = _bus(market_state={"price": 7515.0, "vwap": 7500.0, "vah": 7505.0,
                             "poc_migration": "RISING", "gamma_regime": "NEGATIVE_GAMMA",
                             "flow_bias": "BULLISH", "sweep_count": 12},
               structure={"current_price": 7515.0, "session_high": 7516.0, "session_low": 7488.0},
               market_drivers={"bias": "BULLISH"})
    ri = _ri(build_range_intelligence(bus, market_open=True))
    assert ri["active_scenario"] == "BULL_EXPANSION"
    assert ri["bias"] == "BULLISH"


def test_bear_expansion():
    bus = _bus(market_state={"price": 7448.0, "vwap": 7465.0, "val": 7460.0,
                             "poc_migration": "FALLING", "gamma_regime": "NEGATIVE_GAMMA",
                             "flow_bias": "BEARISH", "sweep_count": 10},
               structure={"current_price": 7448.0, "session_high": 7486.0, "session_low": 7447.0},
               market_drivers={"bias": "BEARISH"})
    ri = _ri(build_range_intelligence(bus, market_open=True))
    assert ri["active_scenario"] == "BEAR_EXPANSION"
    assert ri["bias"] == "BEARISH"


def test_range_exhaustion():
    # narrow projected band + ~94% of it used, price at the upper edge,
    # positive gamma + flat POC -> exhaustion
    bus = _bus(market_state={"price": 7507.0, "poc_migration": "STABLE", "vah": 7505.0,
                             "val": 7476.0, "call_wall": 7509.0, "put_wall": 7474.0,
                             "gamma_regime": "POSITIVE_GAMMA", "auction_state": "BALANCED"},
               structure={"current_price": 7507.0, "session_high": 7508.0, "session_low": 7478.0,
                          "prev_day_high": 7508.0, "prev_day_low": 7476.0},
               strike_magnets={"magnets": [
                   {"strike": 7509.0, "side": "ABOVE", "type": "CALL_WALL", "score": 88},
                   {"strike": 7474.0, "side": "BELOW", "type": "PUT_WALL", "score": 84}]})
    ri = _ri(build_range_intelligence(bus, market_open=True))
    assert ri["range_used_percent"] >= 85
    assert ri["active_scenario"] == "RANGE_EXHAUSTION"
    assert ri["range_exhaustion_risk"] == "HIGH"


def test_waiting_for_open_pre_rth():
    bus = _bus(market_state={"session_state": "PREMARKET"},
               structure={"session_high": None, "session_low": None},
               overnight_game_plan={"es_price": 7506.5, "overnight_high": 7530.0,
                                    "overnight_low": 7474.0})
    ri = _ri(build_range_intelligence(bus, market_open=False))
    assert ri["active_scenario"] == "WAITING_FOR_OPEN"
    assert "PRE_RTH_ESTIMATE" in ri["quality_flags"]
    assert ri["range_used_method"] == "ESTIMATED_PRE_RTH"


def test_insufficient_data_no_price():
    ri = _ri(build_range_intelligence({"market_state": {}, "structure": {}}, market_open=True))
    assert ri["available"] is False
    assert ri["active_scenario"] == "INSUFFICIENT_DATA"


# ── range used + remaining + closed market ───────────────────────────────────

def test_range_used_session_method():
    ri = _ri(build_range_intelligence(_bus(), market_open=True))
    assert ri["range_used_method"] == "SESSION_RANGE"
    assert 0 <= ri["range_used_percent"] <= 140


def test_remaining_points_signs():
    ri = _ri(build_range_intelligence(_bus(), market_open=True))
    assert ri["upside_remaining_points"] == round(ri["projected_high_zone"]["mid"] - 7484.0, 2)
    assert ri["downside_remaining_points"] == round(7484.0 - ri["projected_low_zone"]["mid"], 2)


def test_closed_market_flag():
    ri = _ri(build_range_intelligence(_bus(), market_open=False))
    assert "MARKET_CLOSED_PROJECTION_ONLY" in ri["quality_flags"]


def test_prev_day_levels_missing_flag():
    ri = _ri(build_range_intelligence(
        _bus(structure={"prev_day_high": None, "prev_day_low": None}), market_open=True))
    assert "SPX_PREVIOUS_DAY_LEVELS_UNAVAILABLE" in ri["quality_flags"]


# ── self-evaluation ───────────────────────────────────────────────────────────

def test_capture_and_scorecard_roundtrip():
    for _p in (_TMP_DB, _TMP_DB + "-wal", _TMP_DB + "-shm"):
        if os.path.exists(_p):
            os.remove(_p)
    import engine.range_intelligence as RI
    RI._INIT = False
    init_history()
    env = build_range_intelligence(_bus(), market_open=False)
    assert capture_projection(env, "SPX") is True
    # empty scorecard until actuals recorded
    sc0 = scorecard("SPX")
    assert sc0["ok"] and sc0["graded_days"] == 0
    # record actuals: actual high 7510 vs projected high zone; low 7450 vs low zone
    assert record_actuals("SPX", actual_high=7510.0, actual_low=7450.0,
                          scenario_final="BASE_CASE") is True
    sc = scorecard("SPX")
    assert sc["graded_days"] == 1
    assert sc["hit_rate_within_10pts_pct"] is not None
    h = history("SPX", 10)
    assert len(h) == 1 and h[0]["actual_high"] == 7510.0


def test_edge_error_zero_inside_zone():
    for _p in (_TMP_DB, _TMP_DB + "-wal", _TMP_DB + "-shm"):
        if os.path.exists(_p):
            os.remove(_p)
    import engine.range_intelligence as RI
    RI._INIT = False
    init_history()
    env = build_range_intelligence(_bus(), market_open=False)
    ri = env["range_intelligence"]
    capture_projection(env, "SPX")
    # set actual high exactly at the projected high zone mid => zero error
    mid_hi = ri["projected_high_zone"]["mid"]
    mid_lo = ri["projected_low_zone"]["mid"]
    record_actuals("SPX", actual_high=mid_hi, actual_low=mid_lo)
    sc = scorecard("SPX")
    assert sc["avg_high_error_points"] == 0.0
    assert sc["avg_low_error_points"] == 0.0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn(); passed += 1; print(f"  PASS {fn.__name__}")
        except AssertionError as e:
            print(f"  FAIL {fn.__name__}: {e}")
        except Exception as e:
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
