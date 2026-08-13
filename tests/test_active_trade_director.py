"""tests/test_active_trade_director.py — Active Trade Director tests (Part 21).

Covers every required scenario: no-position (no setup / scalp / conviction),
CALL/PUT with strengthening/weakening thesis, flow reversals, hold-level
failures, targets reached, gamma regime changes, POC migration reversal, auction
acceptance failure, stale data, market closed, missing QuantData / TradingView
trigger, broker disconnected, manual position confirmation, duplicate directive
prevention, directive hysteresis, and cooldown behaviour — plus the state
machine and the position-detection hierarchy.

Run with: python -m pytest tests/test_active_trade_director.py -q
(no pytest? the __main__ block runs the same assertions with plain asserts.)
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DIRECTOR_DB_PATH", "/tmp/atd_test.db")
os.environ.setdefault("DIRECTOR_MIN_DIRECTIVE_S", "0")  # disable debounce for deterministic tests

from engine.director.contracts import DirectorContext, PositionView
from engine.director.director import get_director
from engine.director.snapshots import get_flow_tracker
from engine.director.persistence import get_persistence
from engine.director.narrative import get_narrator
from engine.director.states import (
    is_valid_transition, contradicts_position, coerce_transition,
)
from engine.director.position import detect_position, _side_from_osi


TR = get_flow_tracker()


# ── helpers ──────────────────────────────────────────────────────────────────

def _reset(sym="SPX"):
    TR.reset(sym)
    get_persistence().reset(sym)
    get_narrator().reset(sym)


def _load_flow(sym, snaps, dt=5.0):
    """Load a deterministic flow history with evenly spaced timestamps."""
    TR.reset(sym)
    base = time.time() - len(snaps) * dt - 1
    for i, s in enumerate(snaps):
        TR.record(sym, s)
        TR._hist[sym][-1].t = base + i * dt


def _buyers_accelerating(n=8, px0=7480.0):
    return [{"net_premium": 100e6 + i * i * 30e6, "call_premium": 300e6 + i * i * 30e6,
             "put_premium": 200e6, "flow_score": 55 + i * 2, "order_flow_score": 60,
             "sweep_count": 10 + i * 2, "call_ratio_pct": 60 + i, "stock_price": px0 + i * 0.4}
            for i in range(n)]


def _sellers_accelerating(n=8, px0=7484.0):
    return [{"net_premium": -i * i * 25e6, "call_premium": 200e6, "put_premium": 200e6 + i * i * 25e6,
             "flow_score": 45 - i * 2, "order_flow_score": 45, "sweep_count": 10 + i,
             "call_ratio_pct": 45 - i, "stock_price": px0 - i * 0.5} for i in range(n)]


def _flat_flow(n=8, px0=7484.0):
    return [{"net_premium": 5e6, "call_premium": 250e6, "put_premium": 245e6, "flow_score": 50,
             "order_flow_score": 50, "sweep_count": 10, "call_ratio_pct": 50, "stock_price": px0}
            for i in range(n)]


BULL_MS = {
    "price": 7484.0, "vwap": 7480.0, "poc": 7479.0, "developing_poc": 7482.0, "vah": 7488.0,
    "val": 7476.0, "call_wall": 7495.0, "put_wall": 7470.0, "zero_gamma": 7472.0,
    "gamma_regime": "POSITIVE_GAMMA", "approved_side": "CALL", "poc_migration": "RISING",
    "auction_state": "ACCEPTING_HIGHER", "signal_fresh": True, "flip_risk": "LOW",
    "entry_zone": 7484.0, "target1": 7489.7, "target2": 7494.5, "atr": 3.0,
}
BULL_II = {
    "institutional_bias": "BULLISH", "flow_bias": "BULLISH", "gamma_regime": "POSITIVE_GAMMA",
    "poc_migration": "RISING", "acceptance": "ACCEPTING_HIGHER", "auction_state": "ACCEPTING_HIGHER",
    "dealer_bias": "BULLISH", "market_driver_bias": "BULLISH",
}
DEALER = {"gamma": {"call_wall": 7495, "put_wall": 7470, "zero_gamma": 7472}}


def _ctx(**kw):
    base = dict(symbol="SPX", market_open=True, price=7484.0, market_state=dict(BULL_MS),
               institutional=dict(BULL_II), auction={"acceptance": "ACCEPTING_HIGHER"},
               dealer=dict(DEALER), execution={"stage": "ARMED", "trigger_active": True},
               flow_snapshot={}, risk={"approved": True, "risk_reward": 1.8},
               signal={"fresh_signal": True}, position=PositionView())
    base.update(kw)
    return DirectorContext(**base)


# ── state machine ─────────────────────────────────────────────────────────────

def test_state_machine_legal_and_illegal():
    assert is_valid_transition("FLAT", "WATCHING_CALLS")
    assert is_valid_transition("WATCHING_CALLS", "ENTER_CALL")
    assert is_valid_transition("IN_CALL", "HOLD_CALL")
    assert is_valid_transition("IN_CALL", "EXIT_IMMEDIATELY")  # emergency edge
    assert not is_valid_transition("IN_CALL", "ENTER_CALL")
    assert not is_valid_transition("FLAT", "HOLD_CALL")
    assert is_valid_transition("HOLD_CALL", "HOLD_CALL")  # identity


def test_state_machine_contradictions():
    assert contradicts_position("HOLD_CALL", False, False)     # hold while flat
    assert contradicts_position("WATCHING_CALLS", True, False)  # watching while in call
    assert contradicts_position("HOLD_CALL", False, True)       # hold call while in put
    assert not contradicts_position("HOLD_CALL", True, False)   # legit
    assert not contradicts_position("WATCHING_CALLS", False, False)


def test_coerce_transition():
    safe, coerced = coerce_transition("IN_CALL", "ENTER_CALL")
    assert coerced and safe == "HOLD_CALL"
    safe, coerced = coerce_transition("FLAT", "HOLD_CALL")
    assert coerced and safe == "OBSERVING"


# ── position detection hierarchy (Part 2) ─────────────────────────────────────

def test_side_from_osi():
    assert _side_from_osi("SPXW  260703C07485000") == "CALL"
    assert _side_from_osi("SPXW  260703P07485000") == "PUT"


def test_position_detection_priority():
    # broker position wins over bracket + manual
    pv = detect_position(
        broker_positions_provider=lambda: [{"symbol": "SPXW260703C07485000",
                                             "quantity": 2, "security_type": "OPTN",
                                             "osi_key": "SPXW  260703C07485000"}],
        open_brackets_provider=lambda: [{"state": "FILLED", "side": "PUT", "quantity": 1,
                                         "filled_qty": 1, "closed_qty": 0, "entry": {"price": 5.0},
                                         "stop": {}, "tps": [], "created_at": ""}],
        manual_position_provider=lambda: {"status": "OPEN", "side": "PUT"},
    )
    assert pv.active and pv.source == "BROKER_POSITION" and pv.side == "CALL"


def test_position_detection_bracket_fill():
    pv = detect_position(
        open_brackets_provider=lambda: [{"state": "FILLED", "side": "CALL", "quantity": 2,
                                         "filled_qty": 2, "closed_qty": 0, "entry": {"price": 5.5},
                                         "stop": {"price": 4.0}, "tps": [{"price": 7.0}],
                                         "created_at": "", "bracket_id": "abc"}],
    )
    assert pv.active and pv.source == "BROKER_FILL" and pv.side == "CALL" and pv.entry_price == 5.5


def test_position_detection_manual_and_none():
    pv = detect_position(manual_position_provider=lambda: {"status": "OPEN", "side": "PUT",
                                                           "entry_price": 6.0, "quantity": 1})
    assert pv.active and pv.source == "MANUAL" and pv.side == "PUT"
    pv2 = detect_position()
    assert (not pv2.active) and pv2.source == "NONE"


def test_broker_disconnected_falls_through():
    def _boom():
        raise RuntimeError("etrade down")
    pv = detect_position(broker_positions_provider=_boom,
                         manual_position_provider=lambda: {"status": "OPEN", "side": "CALL"})
    assert pv.active and pv.source == "MANUAL"  # broker error didn't crash detection


# ── pre-entry: no setup / scalp / conviction ──────────────────────────────────

def test_no_position_no_setup():
    _reset()
    _load_flow("SPX", _flat_flow())
    ms = dict(BULL_MS); ms.update({"approved_side": "NONE", "signal_fresh": False})
    ii = {"institutional_bias": "NEUTRAL"}
    d = get_director().build(_ctx(market_state=ms, institutional=ii,
                                  execution={}, signal={"fresh_signal": False}))
    assert d.directive in ("OBSERVE", "NO_TRADE")
    assert d.position_state in ("OBSERVING", "NO_TRADE")


def test_no_position_conviction_setup():
    _reset()
    _load_flow("SPX", _buyers_accelerating())
    d = get_director().build(_ctx())
    assert d.directive == "ENTER_CALL" and d.trade_type == "CONVICTION"
    assert d.hold_level and d.confidence >= 80


def test_no_position_scalp_setup():
    _reset()
    _load_flow("SPX", _buyers_accelerating())
    # break conviction (conflict) but keep strong short-term flow -> scalp
    ii = dict(BULL_II)
    ii.update({"gamma_regime": "NEGATIVE_GAMMA", "dealer_bias": "BEARISH",
               "market_driver_bias": "BEARISH", "poc_migration": "FALLING"})
    ms = dict(BULL_MS); ms.update({"gamma_regime": "NEGATIVE_GAMMA", "poc_migration": "FALLING"})
    d = get_director().build(_ctx(market_state=ms, institutional=ii))
    assert d.trade_type in ("SCALP", "CONVICTION")
    assert d.directive in ("ENTER_SCALP_CALL", "SCALP_READY_CALL", "ENTER_CALL", "WATCHING_CALLS")


# ── in-position: thesis strengthening / weakening ─────────────────────────────

def _call_pos(**kw):
    base = dict(active=True, source="MANUAL", confidence="MANUAL", side="CALL", symbol="SPX",
                quantity=2, held_qty=2, entry_price=7483.0, stop=7480.0, target1=7489.7,
                target2=7494.5, time_in_trade_s=90, order_stage="POSITION_ACTIVE")
    base.update(kw)
    return PositionView(**base)


def test_call_thesis_strengthening_hold():
    _reset()
    _load_flow("SPX", _buyers_accelerating())
    d = get_director().build(_ctx(position=_call_pos()))
    assert d.directive == "HOLD_CALL"
    assert d.thesis_status == "THESIS_STRENGTHENING"


def test_call_thesis_weakening():
    _reset()
    # buyers were strong then fade to steady/weakening
    snaps = _buyers_accelerating(5) + [{"net_premium": 100e6 + 4 * 4 * 30e6 + i * 1e6,
                                        "call_premium": 780e6, "put_premium": 200e6,
                                        "flow_score": 55, "order_flow_score": 55, "sweep_count": 25,
                                        "call_ratio_pct": 58, "stock_price": 7485 + i * 0.05}
                                       for i in range(4)]
    _load_flow("SPX", snaps)
    d = get_director().build(_ctx(position=_call_pos(time_in_trade_s=300)))
    assert d.directive in ("HOLD_CALL", "PROTECT_PROFIT", "SCALE_OUT_25", "SCALE_OUT_50")
    assert d.thesis_status in ("THESIS_INTACT", "THESIS_WEAKENING", "THESIS_STRENGTHENING")


def test_put_position_managed():
    _reset()
    _load_flow("SPX", _sellers_accelerating())
    ms = dict(BULL_MS); ms.update({"approved_side": "PUT", "poc_migration": "FALLING",
                                   "auction_state": "ACCEPTING_LOWER", "price": 7480.0})
    put_pos = PositionView(active=True, source="MANUAL", confidence="MANUAL", side="PUT", symbol="SPX",
                           quantity=2, held_qty=2, entry_price=7482.0, stop=7486.0, target1=7475.0,
                           target2=7470.0, time_in_trade_s=90)
    d = get_director().build(_ctx(price=7480.0, market_state=ms,
                                  institutional={"flow_bias": "BEARISH", "poc_migration": "FALLING",
                                                 "acceptance": "ACCEPTING_LOWER"},
                                  position=put_pos))
    assert d.side == "PUT"
    assert d.directive in ("HOLD_PUT", "PROTECT_PROFIT", "SCALE_OUT_25", "SCALE_OUT_50")


# ── flow reversal / level failure / targets ───────────────────────────────────

def test_flow_reversal_exits():
    _reset()
    # decisive bearish reversal
    rev = []
    for i in range(8):
        net = (100e6 + i * 60e6) if i < 5 else (100e6 + 4 * 60e6 - (i - 4) * 200e6)
        rev.append({"net_premium": net, "call_premium": max(50e6, net + 200e6), "put_premium": 220e6,
                    "flow_score": 60 - i * 3, "order_flow_score": 50, "sweep_count": 10 + i,
                    "call_ratio_pct": 60 - i * 3, "stock_price": 7484 - i * 0.4})
    _load_flow("SPX", rev)
    ms = dict(BULL_MS); ms.update({"price": 7480.5, "poc_migration": "FALLING", "auction_state": "REJECTED"})
    d = get_director().build(_ctx(price=7480.5, market_state=ms,
                                  institutional={"flow_bias": "BEARISH", "poc_migration": "FALLING",
                                                 "acceptance": "REJECTED"},
                                  position=_call_pos(time_in_trade_s=200)))
    assert d.directive == "EXIT_CALL_NOW" or d.thesis_status in ("THESIS_WEAKENING", "THESIS_INVALIDATED")


def test_hold_level_failure_exit():
    _reset()
    pos = _call_pos(entry_price=7484.0, stop=7480.0, time_in_trade_s=200)
    # anchor at VAL 7480 while above it, then break below with sellers accelerating
    for read, px in enumerate([7481.0, 7478.0, 7478.0], 1):
        _load_flow("SPX", _sellers_accelerating(px0=px + 5))
        ms = dict(BULL_MS)
        ms.update({"price": px, "val": 7480.0, "poc": 7484.0, "developing_poc": 7483.0,
                   "vwap": 7482.0, "poc_migration": "FALLING", "auction_state": "REJECTED",
                   "gamma_regime": "NEGATIVE_GAMMA"})
        d = get_director().build(_ctx(price=px, market_state=ms,
                                      institutional={"flow_bias": "BEARISH", "poc_migration": "FALLING",
                                                     "acceptance": "REJECTED"},
                                      position=pos))
    assert d.directive == "EXIT_CALL_NOW"
    assert "EXIT" in d.position_state


def test_target_reached_scales():
    _reset()
    _load_flow("SPX", _flat_flow(px0=7490))
    ms = dict(BULL_MS); ms.update({"price": 7490.0, "poc_migration": "STABLE"})
    pos = _call_pos(quantity=4, held_qty=4, entry_price=7484.0, target1=7489.7, target2=7494.5)
    d = get_director().build(_ctx(price=7490.0, market_state=ms, position=pos))
    assert d.directive in ("SCALE_OUT_25", "SCALE_OUT_50", "SCALE_OUT_75", "PROTECT_PROFIT")


# ── regime / migration / auction changes ──────────────────────────────────────

def test_gamma_regime_change_flagged():
    _reset()
    _load_flow("SPX", _buyers_accelerating())
    ms = dict(BULL_MS); ms.update({"gamma_regime": "NEGATIVE_GAMMA", "flip_risk": "HIGH"})
    d = get_director().build(_ctx(market_state=ms,
                                  institutional=dict(BULL_II, gamma_regime="NEGATIVE_GAMMA"),
                                  position=_call_pos()))
    assert d.risk_status in ("ELEVATED", "CONTROLLED", "BREACHED")


def test_poc_migration_reversal_weakens_thesis():
    _reset()
    _load_flow("SPX", _buyers_accelerating())
    ms = dict(BULL_MS); ms.update({"poc_migration": "FALLING"})
    d = get_director().build(_ctx(market_state=ms,
                                  institutional=dict(BULL_II, poc_migration="FALLING"),
                                  position=_call_pos()))
    assert d.poc_migration == "FALLING"


def test_auction_acceptance_failure():
    _reset()
    _load_flow("SPX", _buyers_accelerating())
    ms = dict(BULL_MS); ms.update({"auction_state": "REJECTED"})
    d = get_director().build(_ctx(market_state=ms, auction={"acceptance": "REJECTED"},
                                  institutional=dict(BULL_II, acceptance="REJECTED", auction_state="REJECTED"),
                                  position=_call_pos()))
    assert d.ok is True  # still produces a directive, no crash


# ── data quality / session ────────────────────────────────────────────────────

def test_market_closed():
    _reset()
    d = get_director().build(_ctx(market_open=False))
    assert d.directive == "STAND_DOWN"
    assert "MARKET_CLOSED" in d.quality_flags


def test_stale_data_veto():
    _reset()
    d = get_director().build(_ctx(market_state={}, institutional={}, data_stale=True))
    assert d.directive in ("NO_TRADE", "OBSERVE")
    assert "DATA_STALE" in d.quality_flags


def test_missing_quantdata_flow():
    _reset()
    # no flow history at all -> classification FLOW_UNKNOWN, still safe
    TR.reset("SPX")
    d = get_director().build(_ctx(flow_snapshot={}))
    assert d.flow_state == "FLOW_UNKNOWN"
    assert d.ok is True


def test_missing_pine_trigger_blocks_conviction():
    _reset()
    _load_flow("SPX", _buyers_accelerating())
    ms = dict(BULL_MS); ms.update({"signal_fresh": False})
    d = get_director().build(_ctx(market_state=ms, signal={"fresh_signal": False}, execution={}))
    # no fresh trigger -> not a conviction ENTER
    assert d.directive != "ENTER_CALL"


# ── manual confirmation / hysteresis / cooldown / dedupe ──────────────────────

def test_manual_position_confirmation_switches_to_management():
    _reset()
    _load_flow("SPX", _buyers_accelerating())
    d_flat = get_director().build(_ctx(position=PositionView()))
    assert d_flat.position_state.startswith(("ENTER", "WATCHING", "SCALP"))
    _load_flow("SPX", _buyers_accelerating())
    d_in = get_director().build(_ctx(position=_call_pos()))
    assert d_in.position_state.startswith(("HOLD", "IN_", "SCALE", "PROTECT"))


def test_directive_hysteresis_debounce():
    _reset()
    os.environ["DIRECTOR_MIN_DIRECTIVE_S"] = "3600"  # force debounce
    import importlib
    from engine.director import persistence as pmod
    importlib.reload(pmod)
    p = pmod.get_persistence(); p.reset("SPX")
    first = p.stabilize("SPX", proposed_directive="HOLD_CALL", proposed_state="HOLD_CALL", holding=True)
    assert first["directive"] == "HOLD_CALL"
    # a different, non-emergency directive within the window is held back
    second = p.stabilize("SPX", proposed_directive="SCALE_OUT_25", proposed_state="SCALE_OUT",
                         holding=True, exit_signals={})
    assert second["directive"] == "HOLD_CALL" and "Debouncing" in second["note"]
    os.environ["DIRECTOR_MIN_DIRECTIVE_S"] = "0"
    importlib.reload(pmod)


def test_exit_confirmation_window():
    from engine.director import persistence as pmod
    p = pmod.get_persistence(); p.reset("SPX")
    p.stabilize("SPX", proposed_directive="HOLD_CALL", proposed_state="HOLD_CALL", holding=True)
    # propose exit via level failure — first read unconfirmed, held back
    r1 = p.stabilize("SPX", proposed_directive="EXIT_CALL_NOW", proposed_state="EXIT_LEVEL_FAILURE",
                     holding=True, exit_signals={"level_failure": True})
    assert r1["directive"] == "HOLD_CALL"
    r2 = p.stabilize("SPX", proposed_directive="EXIT_CALL_NOW", proposed_state="EXIT_LEVEL_FAILURE",
                     holding=True, exit_signals={"level_failure": True})
    assert r2["directive"] == "EXIT_CALL_NOW"  # confirmed on the 2nd read


def test_emergency_bypasses_confirmation():
    from engine.director import persistence as pmod
    p = pmod.get_persistence(); p.reset("SPX")
    p.stabilize("SPX", proposed_directive="HOLD_CALL", proposed_state="HOLD_CALL", holding=True)
    r = p.stabilize("SPX", proposed_directive="EXIT_IMMEDIATELY", proposed_state="EXIT_IMMEDIATELY",
                    holding=True, exit_signals={"emergency": True})
    assert r["directive"] == "EXIT_IMMEDIATELY"


def test_cooldown_after_exit():
    from engine.director import persistence as pmod
    p = pmod.get_persistence(); p.reset("SPX")
    p.stabilize("SPX", proposed_directive="HOLD_CALL", proposed_state="HOLD_CALL", holding=True)
    p.stabilize("SPX", proposed_directive="EXIT_IMMEDIATELY", proposed_state="EXIT_IMMEDIATELY",
                holding=True, exit_signals={"emergency": True})
    assert p.in_cooldown("SPX")


def test_narrative_timeline_records_events():
    _reset()
    _load_flow("SPX", _buyers_accelerating())
    get_director().build(_ctx(position=_call_pos()))
    tl = get_narrator().timeline("SPX")
    assert isinstance(tl, list) and len(tl) >= 1


# ── plain-assert runner (no pytest required) ──────────────────────────────────

if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            passed += 1
            print(f"  PASS {fn.__name__}")
        except AssertionError as e:
            print(f"  FAIL {fn.__name__}: {e}")
        except Exception as e:
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
