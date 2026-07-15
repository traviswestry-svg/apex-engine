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


# ── 7.6.0 spine hooks: settlement grading + dispatch ────────────────────────
import datetime as _dt
from zoneinfo import ZoneInfo as _ZI

import engine.premium_strategy_routes as _psr

_EASTERN = _ZI("America/New_York")


def _settle(strategy, legs, close_px):
    return _psr._settle_structure(strategy, legs, close_px)


def test_settle_bull_put_win_and_loss():
    legs = {"sell_leg": 6270, "buy_leg": 6260, "width": 10, "entry_credit": 1.94}
    pnl, _ = _settle("BULL_PUT_CREDIT_SPREAD", legs, 6300)   # OTM → keep credit
    assert round(pnl, 2) == 1.94
    pnl, _ = _settle("BULL_PUT_CREDIT_SPREAD", legs, 6255)   # through long → max loss
    assert round(pnl, 2) == -8.06


def test_settle_bear_call_win_and_loss():
    legs = {"sell_leg": 6330, "buy_leg": 6340, "width": 10, "entry_credit": 1.49}
    assert round(_settle("BEAR_CALL_CREDIT_SPREAD", legs, 6300)[0], 2) == 1.49
    assert round(_settle("BEAR_CALL_CREDIT_SPREAD", legs, 6345)[0], 2) == -8.51


def test_settle_debit_call_win_and_loss():
    legs = {"buy_leg": 6295, "sell_leg": 6305, "width": 10, "entry_debit": 5.71}
    assert round(_settle("DEBIT_CALL_SPREAD", legs, 6320)[0], 2) == 4.29   # full width
    assert round(_settle("DEBIT_CALL_SPREAD", legs, 6296)[0], 2) == -4.71  # barely ITM


def test_settle_debit_put_win_and_loss():
    legs = {"buy_leg": 6300, "sell_leg": 6290, "width": 10, "entry_debit": 4.0}
    assert round(_settle("DEBIT_PUT_SPREAD", legs, 6280)[0], 2) == 6.0
    assert round(_settle("DEBIT_PUT_SPREAD", legs, 6299)[0], 2) == -3.0


def test_settle_condor_win_and_loss():
    legs = {"put_short": 6270, "put_long": 6260, "call_short": 6330, "call_long": 6340,
            "width": 10, "entry_credit": 2.72}
    assert round(_settle("IRON_CONDOR", legs, 6300)[0], 2) == 2.72   # inside both
    assert round(_settle("IRON_CONDOR", legs, 6345)[0], 2) == -7.28  # call side breached


def test_settle_missing_legs_returns_none():
    pnl, reason = _settle("BULL_PUT_CREDIT_SPREAD", {}, 6300)
    assert pnl is None and "missing" in reason


def _fresh_db(tmp_path):
    """Point the routes module at a throwaway DB and initialise it."""
    _psr._DB_PATH = str(tmp_path / "premium_test.db")
    _psr._DB_READY = False
    _psr._LAST_DISPATCH.clear()
    _psr._init_db()
    assert _psr._DB_READY


def test_grade_settles_logged_recommendation(tmp_path):
    _fresh_db(tmp_path)
    # A bull put logged earlier today, session not yet marked graded.
    now_et = _dt.datetime(2026, 7, 14, 16, 30, tzinfo=_EASTERN)   # past cash close
    sess = now_et.date().isoformat()
    rec_utc = _dt.datetime(2026, 7, 14, 17, 0, tzinfo=_dt.timezone.utc)  # 13:00 ET
    panel = {"strategy": "BULL_PUT_CREDIT_SPREAD", "premium_kind": "CREDIT",
             "confidence": 88, "vix": 24, "vix_regime": "HIGH", "case": "CASE_2",
             "legs": {"sell_leg": 6270, "buy_leg": 6260, "width": 10,
                      "entry_credit": 1.94, "pop": 0.84}}
    # Insert with a controlled ts by patching the log to our rec time.
    import engine.premium_strategy_routes as m
    orig_now = m._dt.datetime
    with m._conn() as c:
        c.execute("INSERT INTO premium_recommendations "
                  "(ts, session_date, ticker, strategy, premium_kind, confidence, vix, "
                  "vix_regime, case_label, pop, spot, legs_json, outcome) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
                  (rec_utc.isoformat(), sess, "SPX", "BULL_PUT_CREDIT_SPREAD", "CREDIT",
                   88, 24, "HIGH", "CASE_2", 0.84, 6300,
                   '{"sell_leg":6270,"buy_leg":6260,"width":10,"entry_credit":1.94}'))
        c.commit()

    # Bars that close at 6300 (short put OTM → win).
    def fake_bars(ticker, mult=5, days=5):
        out = []
        t = _dt.datetime(2026, 7, 14, 17, 0, tzinfo=_dt.timezone.utc)
        px = 6300
        for _ in range(30):
            ms = int(t.timestamp() * 1000)
            out.append({"t": ms, "o": px, "h": px + 2, "l": px - 2, "c": px})
            t += _dt.timedelta(minutes=5)
        return out

    n = _psr.grade_due_recommendations(fake_bars, lambda: now_et)
    assert n == 1
    with _psr._conn() as c:
        row = c.execute("SELECT outcome, outcome_pnl FROM premium_recommendations").fetchone()
    assert row["outcome"] == "WIN"
    assert round(row["outcome_pnl"], 0) == 194   # 1.94 * 100


def test_grade_before_close_leaves_open(tmp_path):
    _fresh_db(tmp_path)
    # 11:00 ET on the session date → before cash close, nothing is ready.
    early_et = _dt.datetime(2026, 7, 14, 11, 0, tzinfo=_EASTERN)
    with _psr._conn() as c:
        c.execute("INSERT INTO premium_recommendations "
                  "(ts, session_date, ticker, strategy, premium_kind, confidence, "
                  "vix_regime, pop, legs_json, outcome) VALUES (?,?,?,?,?,?,?,?,?,NULL)",
                  (_dt.datetime(2026,7,14,15,0,tzinfo=_dt.timezone.utc).isoformat(),
                   "2026-07-14", "SPX", "BULL_PUT_CREDIT_SPREAD", "CREDIT", 80, "HIGH", 0.8,
                   '{"sell_leg":6270,"buy_leg":6260,"width":10,"entry_credit":1.9}'))
        c.commit()
    graded = _psr.grade_due_recommendations(lambda *a, **k: [], lambda: early_et)
    assert graded == 0
    with _psr._conn() as c:
        assert c.execute("SELECT outcome FROM premium_recommendations").fetchone()["outcome"] is None


def test_grade_scratches_no_trade_and_holds_missing_bars(tmp_path):
    _fresh_db(tmp_path)
    post_close = _dt.datetime(2026, 7, 14, 16, 30, tzinfo=_EASTERN)  # ready
    with _psr._conn() as c:
        # NO_TRADE — no position → SCRATCH even without bars.
        c.execute("INSERT INTO premium_recommendations "
                  "(ts, session_date, ticker, strategy, premium_kind, confidence, "
                  "vix_regime, outcome) VALUES (?,?,?,?,?,?,?,NULL)",
                  (_dt.datetime(2026,7,14,14,0,tzinfo=_dt.timezone.utc).isoformat(),
                   "2026-07-14", "SPX", "NO_TRADE", "NONE", 40, "MID"))
        # A real structure but no bars available yet, fresh → left open to retry.
        c.execute("INSERT INTO premium_recommendations "
                  "(ts, session_date, ticker, strategy, premium_kind, confidence, "
                  "vix_regime, pop, legs_json, outcome) VALUES (?,?,?,?,?,?,?,?,?,NULL)",
                  (_dt.datetime(2026,7,14,15,0,tzinfo=_dt.timezone.utc).isoformat(),
                   "2026-07-14", "SPX", "BULL_PUT_CREDIT_SPREAD", "CREDIT", 80, "HIGH", 0.8,
                   '{"sell_leg":6270,"buy_leg":6260,"width":10,"entry_credit":1.9}'))
        c.commit()
    graded = _psr.grade_due_recommendations(lambda *a, **k: [], lambda: post_close)
    with _psr._conn() as c:
        rows = {r["strategy"]: r["outcome"] for r in
                c.execute("SELECT strategy, outcome FROM premium_recommendations")}
    assert rows["NO_TRADE"] == "SCRATCH"           # no position, closed out
    assert rows["BULL_PUT_CREDIT_SPREAD"] is None  # no bars → retry later
    assert graded == 1


def test_dispatch_fires_once_per_change(tmp_path):
    _fresh_db(tmp_path)
    sent = []
    now_et = _dt.datetime(2026, 7, 14, 12, 0, tzinfo=_EASTERN)

    # Strong bearish, high-VIX bus → an actionable credit structure.
    ii = _ii(institutional_bias="BEARISH", flow_bias="BEARISH", flow_conviction=75,
             auction_state="TREND_DAY_DOWN", auction_bias="BEARISH", direction="BEARISH",
             momentum_probability=60, ici_score=72, gamma_regime="NEGATIVE_GAMMA",
             dealer_bias="BEARISH", market_driver_bias="BEARISH", acceptance="ACCEPTING")
    bus = _bus(ii=ii, ms=dict(_MS, vwap=6312, flow_bias="BEARISH"),
               vol={"vix": 24, "iv_rank_estimate": 65}, rng=dict(_RNG))

    r1 = _psr.dispatch_and_log(bus, "SPX", sent.append, events={}, now_et_provider=lambda: now_et)
    r2 = _psr.dispatch_and_log(bus, "SPX", sent.append, events={}, now_et_provider=lambda: now_et)
    assert r1["changed"] is True and r1["dispatched"] is True
    assert r2["changed"] is False          # same structure → no duplicate alert
    assert len(sent) == 1
    # It logged exactly one row for grading.
    with _psr._conn() as c:
        n = c.execute("SELECT COUNT(*) n FROM premium_recommendations").fetchone()["n"]
    assert n == 1


def test_dispatch_no_trade_is_silent_but_logged(tmp_path):
    _fresh_db(tmp_path)
    sent = []
    now_et = _dt.datetime(2026, 7, 14, 12, 0, tzinfo=_EASTERN)
    # Flow contradiction with weak conviction → CASE_4 NO_TRADE.
    ii = _ii(flow_contradictions=["flow disagrees with auction"], flow_conviction=30,
             direction="NEUTRAL")
    bus = _bus(ii=ii, ms=dict(_MS), vol={"vix": 18}, rng=dict(_RNG))
    r = _psr.dispatch_and_log(bus, "SPX", sent.append, events={}, now_et_provider=lambda: now_et)
    assert r["strategy"] == NO_TRADE
    assert r["dispatched"] is False        # stand-aside is silent
    assert sent == []


# ── Alert ticket formatting (B/S + strike + P/C) ────────────────────────────
# Safety-critical: a flipped buy/sell would enter the inverse structure.
_XP = {"target": "Buy back at 30% of credit.", "stop": "Close if short strike breaks."}


def _alert(strategy, label, legs, **panel_over):
    panel = {"strategy": strategy, "strategy_label": label, "confidence": 80.0,
             "price": 6300.0, "expected_move": 30.0, "vix": 20.0, "vix_regime": "MID",
             "exit_plan": _XP}
    panel.update(panel_over)
    return _psr._alert_text("SPX", panel, legs)


def test_alert_bull_put_sells_higher_put_buys_lower():
    t = _alert("BULL_PUT_CREDIT_SPREAD", "Bull Put Credit Spread",
               {"sell_leg": 6270.0, "buy_leg": 6260.0, "width": 10.0,
                "entry_credit": 1.94, "pop": 0.84, "max_profit": 194.0,
                "max_loss": 806.0, "risk_reward": 0.24})
    assert "S 6270P / B 6260P" in t
    assert "Net credit 1.94" in t and "POP 84%" in t
    assert "Max profit $194" in t and "Max loss $806" in t


def test_alert_bear_call_sells_lower_call_buys_higher():
    t = _alert("BEAR_CALL_CREDIT_SPREAD", "Bear Call Credit Spread",
               {"sell_leg": 6330.0, "buy_leg": 6340.0, "width": 10.0,
                "entry_credit": 1.49, "pop": 0.86})
    assert "S 6330C / B 6340C" in t


def test_alert_debit_call_buys_lower_sells_higher():
    t = _alert("DEBIT_CALL_SPREAD", "Debit Call Spread",
               {"buy_leg": 6295.0, "sell_leg": 6305.0, "width": 10.0,
                "entry_debit": 5.71, "breakeven": 6300.7})
    assert "B 6295C / S 6305C" in t
    assert "Net debit 5.71" in t
    assert "Breakeven 6300.7" in t


def test_alert_debit_put_buys_higher_sells_lower():
    t = _alert("DEBIT_PUT_SPREAD", "Debit Put Spread",
               {"buy_leg": 6300.0, "sell_leg": 6290.0, "width": 10.0,
                "entry_debit": 4.0})
    assert "B 6300P / S 6290P" in t


def test_alert_condor_labels_both_wings():
    t = _alert("IRON_CONDOR", "Iron Condor",
               {"put_short": 7490.0, "put_long": 7480.0, "call_short": 7640.0,
                "call_long": 7650.0, "width": 10.0, "entry_credit": 3.2, "pop": 0.72,
                "max_profit": 320.0, "max_loss": 680.0, "risk_reward": 0.47},
               price=7565.0, expected_move=45.0, vix=18.2)
    assert "PUTS   S 7490P / B 7480P" in t
    assert "CALLS  S 7640C / B 7650C" in t
    assert "10 wide each side" in t
    # short strikes must straddle spot — a condor that doesn't is malformed
    assert "Spot 7565" in t


def test_alert_strips_trailing_zero_and_keeps_half_strikes():
    assert _psr._fmt_strike(6270.0) == "6270"
    assert _psr._fmt_strike(6272.5) == "6272.5"
    assert _psr._fmt_strike(None) == "--"


def test_alert_includes_modeled_pricing_caveat():
    t = _alert("BULL_PUT_CREDIT_SPREAD", "Bull Put Credit Spread",
               {"sell_leg": 6270.0, "buy_leg": 6260.0, "width": 10.0,
                "entry_credit": 1.9, "pricing_basis": "modeled_from_expected_move"})
    assert "verify on the live chain" in t


def test_alert_survives_missing_fields():
    # A sparse legs dict must not raise — alerts are dispatched from the bus cycle.
    t = _alert("BULL_PUT_CREDIT_SPREAD", "Bull Put Credit Spread", {})
    assert "APEX ALERT" in t and "--" in t
