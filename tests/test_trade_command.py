"""tests/test_trade_command.py — Phase 1 backend unit tests.

Run from the repo root:  python -m pytest tests/test_trade_command.py -q
(or plain:               python tests/test_trade_command.py)

No live E*TRADE calls. OAuth signing is validated against the canonical published
OAuth 1.0a test vector, which is how we verify the handshake without credentials.
"""
import os
import sys
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.brokers.etrade_adapter import oauth1_sign, oauth1_signature_base_string, ETradeAdapter
from engine.options.options_data_bus import normalize_contract, normalize_chain, compute_quote_metrics, OptionsDataBus
from engine.execution import trade_risk_guard as guard
from engine.execution.bracket_manager import BracketManager
from engine.execution.broker_interface import OrderIntent, ChangeIntent
from engine.execution import trade_audit
from engine.execution import price_mapper as pm


# ── 9. SPX ⇄ premium mapper (dual-chart keystone) ─────────────────────────────
def test_premium_from_spx_call_moves_up():
    # CALL delta > 0: SPX up 10 pts, delta 0.5 → premium up ~5.00
    p = pm.premium_from_spx(spot=6300, spx_level=6310, base_premium=4.00, delta=0.50)
    assert abs(p - 9.00) < 0.06


def test_premium_from_spx_put_moves_down():
    # PUT delta < 0: SPX up 10 pts, delta -0.5 → premium DOWN ~5.00
    p = pm.premium_from_spx(spot=6300, spx_level=6310, base_premium=8.00, delta=-0.50)
    assert abs(p - 3.00) < 0.06


def test_spx_premium_roundtrip_is_stable():
    # premium → SPX → premium returns the original within one tick (delta-only invertible)
    spot, base, delta = 6300.0, 4.20, 0.42
    target_prem = 5.20
    spx = pm.spx_from_premium(spot, target_prem, base, delta)
    back = pm.premium_from_spx(spot, spx, base, delta)
    assert abs(back - target_prem) <= 0.06, (spx, back)


def test_premium_never_negative():
    p = pm.premium_from_spx(spot=6300, spx_level=6200, base_premium=2.00, delta=0.5)
    assert p >= 0.0


def test_spx_from_premium_guards_zero_delta():
    assert pm.spx_from_premium(6300, 5.0, 4.0, 0.00005) is None


def test_project_levels_returns_both_axes():
    levels = {"ENTRY": 4.20, "STOP": 3.10, "TP1": 5.30}
    out = pm.project_levels(levels, "premium", spot=6300, base_premium=4.20, delta=0.42)
    assert set(out) == {"ENTRY", "STOP", "TP1"}
    assert out["ENTRY"]["premium"] == 4.2 and out["ENTRY"]["spx"] is not None
    # stop premium below entry → stop SPX below entry SPX (long call)
    assert out["STOP"]["spx"] < out["ENTRY"]["spx"]


def test_suggest_bracket_orders_targets():
    b = pm.suggest_bracket(4.00, spot=6300, delta=0.42)
    assert b["STOP"]["premium"] < b["ENTRY"]["premium"] < b["TP1"]["premium"] < b["TP2"]["premium"] < b["TP3"]["premium"]
    assert b["BREAKEVEN"]["premium"] == b["ENTRY"]["premium"]


# ── 1. OAuth 1.0a signing (canonical vector) ──────────────────────────────────
def test_oauth1_signature_matches_canonical_vector():
    # Fully self-consistent OAuth Core 1.0 HMAC-SHA1 example (key + params + signature
    # all from the same authoritative source), so it proves the signing end-to-end.
    params = {
        "file": "vacation.jpg", "size": "original",
        "oauth_consumer_key": "dpf43f3p2l4k3l03",
        "oauth_token": "nnch734d00sl2jdk",
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": "1191242096",
        "oauth_nonce": "kllo9940pd9333jh",
        "oauth_version": "1.0",
    }
    url = "http://photos.example.net/photos"
    base = oauth1_signature_base_string("GET", url, params)
    assert base.startswith("GET&http%3A%2F%2Fphotos.example.net%2Fphotos&")
    sig = oauth1_sign("GET", url, params, "kd94hf93k423kf44", "pfkkdhi9sl3r4s00")
    assert sig == "tR3+Ty81lMeYAr/Fid0kMTYa/WM=", f"got {sig}"


# ── 2. Option chain normalization ─────────────────────────────────────────────
def test_normalize_contract_maps_fields_and_metrics():
    raw = {"strikePrice": 7485, "optionType": "CALL", "bid": 4.0, "ask": 4.4,
           "volume": 1200, "openInterest": 5000, "expiration": "2026-07-06",
           "osiKey": "SPXW  260706C07485000",
           "greeks": {"delta": 0.42, "gamma": 0.01, "theta": -1.2, "vega": 0.3, "iv": 0.16}}
    c = normalize_contract(raw, symbol="SPX", source="etrade")
    assert c is not None and c.side == "CALL" and c.strike == 7485
    assert c.mid == 4.2 and round(c.spread_pct, 1) == round(0.4 / 4.2 * 100, 1)
    assert c.delta == 0.42 and c.liquidity_score > 60
    assert c.source == "etrade"


def test_normalize_chain_filters_bad_rows():
    rows = [{"strikePrice": 7480, "optionType": "CALL", "bid": 5, "ask": 5.2},
            {"junk": True}, {"strikePrice": 7490, "type": "P", "bid": 3, "ask": 3.1}]
    out = normalize_chain(rows, symbol="SPX")
    assert len(out) == 2  # the junk row is dropped


def test_compute_quote_metrics_wide_spread_low_score():
    m = compute_quote_metrics(1.0, 1.5, 5, 10, 30)  # 40% spread, thin, stale
    assert m["spread_pct"] > 30 and m["liquidity_score"] < 30


# ── 3. Risk guard: SPX-only, staleness, spread, sizing, time ──────────────────
def _call(**over):
    base = {"symbol": "SPX", "side": "CALL", "expiration": (dt.date.today()).isoformat(),
            "bid": 4.0, "ask": 4.3, "spread_pct": 5.0, "quote_age_seconds": 3.0}
    base.update(over)
    return base


def test_entry_rejects_non_spx():
    d = guard.validate_entry(contract=_call(symbol="AAPL"), quantity=1,
                             entry_premium=4.2, stop_premium=3.0)
    assert not d.allow and any("SPX" in r for r in d.reasons)


def test_entry_rejects_stale_quote():
    d = guard.validate_entry(contract=_call(quote_age_seconds=45), quantity=1,
                             entry_premium=4.2, stop_premium=3.0)
    assert not d.allow and any("stale" in r.lower() for r in d.reasons)


def test_entry_rejects_wide_spread():
    d = guard.validate_entry(contract=_call(spread_pct=20), quantity=1,
                             entry_premium=4.2, stop_premium=3.0)
    assert not d.allow and any("spread" in r.lower() for r in d.reasons)


def test_entry_rejects_missing_bid_ask():
    d = guard.validate_entry(contract=_call(bid=None), quantity=1,
                             entry_premium=4.2, stop_premium=3.0)
    assert not d.allow and any("bid/ask" in r.lower() for r in d.reasons)


def test_entry_rejects_risk_over_max():
    limits = guard.RiskLimits(max_risk_per_trade=100.0)
    # (4.2-3.0)*100*1 = 120 > 100
    d = guard.validate_entry(contract=_call(), quantity=1, entry_premium=4.2, stop_premium=3.0,
                             limits=limits, now=dt.datetime(2026, 7, 6, 10, 0))
    assert not d.allow and any("risk" in r.lower() for r in d.reasons)


def test_entry_ok_when_clean():
    d = guard.validate_entry(contract=_call(expiration="2026-07-06"), quantity=1,
                             entry_premium=4.2, stop_premium=3.5,
                             now=dt.datetime(2026, 7, 6, 10, 0))
    assert d.allow, d.reasons


def test_entry_rejects_after_cutoff():
    d = guard.validate_entry(contract=_call(), quantity=1, entry_premium=4.2, stop_premium=3.8,
                             now=dt.datetime(2026, 7, 6, 12, 0))  # past 11:30
    assert not d.allow and any("cutoff" in r.lower() for r in d.reasons)


# ── 4. Risk guard: line-drag rules ────────────────────────────────────────────
def test_stop_cannot_drag_above_tp1():
    d = guard.validate_line_drag(line="STOP", new_price=6.0, entry_premium=4.0,
                                 current_premium=4.2, levels={"TP1": 5.0, "STOP": 3.0})
    assert not d.allow and any("TP1" in r for r in d.reasons)


def test_tp_cannot_drag_below_entry():
    d = guard.validate_line_drag(line="TP1", new_price=3.5, entry_premium=4.0,
                                 current_premium=4.2, levels={"TP1": 5.0, "TP2": 6.0})
    assert not d.allow and any("entry" in r.lower() for r in d.reasons)


def test_stop_cannot_increase_risk_beyond_max():
    limits = guard.RiskLimits(max_risk_per_trade=100.0)
    d = guard.validate_line_drag(line="STOP", new_price=2.0, entry_premium=4.0,
                                 current_premium=4.2, levels={"TP1": 6.0, "STOP": 3.2},
                                 position_qty=1, limits=limits)
    assert not d.allow and any("risk" in r.lower() for r in d.reasons)


def test_stop_lower_blocked_after_breakeven_armed():
    d = guard.validate_line_drag(line="STOP", new_price=3.0, entry_premium=4.0,
                                 current_premium=4.5, levels={"TP1": 6.0, "STOP": 4.0},
                                 breakeven_armed=True)
    assert not d.allow and any("breakeven" in r.lower() for r in d.reasons)


def test_sell_to_close_cannot_exceed_position():
    d = guard.validate_exit_quantity(exit_qty=3, position_qty=2)
    assert not d.allow
    assert guard.validate_exit_quantity(exit_qty=2, position_qty=2).allow


# ── 5. Order payload generation ───────────────────────────────────────────────
def test_entry_preview_and_place_payloads():
    a = ETradeAdapter()
    intent = OrderIntent(symbol="SPX", osi_key="SPXW  260706C07485000", side="CALL",
                         action="BUY_OPEN", quantity=2, order_type="LIMIT", limit_price=4.2)
    prev = a._order_payload(intent, preview=True)
    assert "PreviewOrderRequest" in prev
    order = prev["PreviewOrderRequest"]["Order"][0]
    assert order["limitPrice"] == 4.2 and order["priceType"] == "LIMIT"
    inst = order["Instrument"][0]
    assert inst["orderAction"] == "BUY_OPEN" and inst["quantity"] == 2
    assert inst["Product"]["securityType"] == "OPTN"
    place = a._order_payload(intent, preview=False, preview_id="PID123")
    assert place["PlaceOrderRequest"]["PreviewIds"][0]["previewId"] == "PID123"


def test_place_order_blocked_without_trading_enabled(monkeypatch=None):
    os.environ["ETRADE_ENABLE_TRADING"] = "false"
    a = ETradeAdapter()
    r = a.place_order("PID", OrderIntent(symbol="SPX", osi_key="x", side="CALL",
                                         action="BUY_OPEN", quantity=1))
    assert not r.ok and any("ENABLE_TRADING" in e for e in r.errors)


# ── 6. Bracket manager state machine ──────────────────────────────────────────
def test_bracket_state_transitions_and_flatten(tmpdir_path="/tmp/apex_bracket_test.json"):
    if os.path.exists(tmpdir_path):
        os.remove(tmpdir_path)
    bm = BracketManager(snapshot_path=tmpdir_path)
    b = bm.create(symbol="SPX", osi_key="SPXW  260706C07485000", side="CALL", quantity=2,
                  entry_price=4.2, stop_price=3.4, tp_prices=[5.0, 5.6, 6.5])
    assert b.state == "PLANNED"
    bm.transition(b.bracket_id, "PREVIEWED"); bm.transition(b.bracket_id, "SENT")
    # illegal jump rejected
    try:
        bm.transition(b.bracket_id, "TP3_HIT"); assert False, "should reject"
    except ValueError:
        pass
    bm.record_fill(b.bracket_id, 2)
    assert bm.get(b.bracket_id).state == "FILLED"
    bm.transition(b.bracket_id, "PROTECTED")
    bm.record_exit(b.bracket_id, "TP1", 1)
    assert bm.get(b.bracket_id).state == "TP1_HIT"
    # flatten closes remainder and cancels working exits
    b2 = bm.flatten(b.bracket_id)
    assert b2.held_qty == 0 and b2.state in ("CLOSED", "MANUAL_REVIEW_REQUIRED")


def test_bracket_cannot_close_more_than_held():
    p = "/tmp/apex_bracket_test2.json"
    if os.path.exists(p):
        os.remove(p)
    bm = BracketManager(snapshot_path=p)
    b = bm.create(symbol="SPX", osi_key="x", side="CALL", quantity=1,
                  entry_price=4.0, stop_price=3.0, tp_prices=[5.0])
    bm.transition(b.bracket_id, "PREVIEWED"); bm.transition(b.bracket_id, "SENT")
    bm.record_fill(b.bracket_id, 1); bm.transition(b.bracket_id, "PROTECTED")
    bm.record_exit(b.bracket_id, "TP1", 1)      # closes the 1 held
    b2 = bm.record_exit(b.bracket_id, "STOP", 1)  # nothing left → clamped/review
    assert b2.closed_qty <= b2.filled_qty


# ── 7. Audit log creation ─────────────────────────────────────────────────────
def test_audit_writes_and_redacts(tmp_path=None):
    os.environ["TRADE_AUDIT_DIR"] = "/tmp/apex_audit_test"
    import importlib
    importlib.reload(trade_audit)
    ok = trade_audit.audit("PREVIEW_REQUEST",
                           {"consumer_secret": "TOPSECRET", "osi_key": "SPXW..C..", "qty": 1})
    assert ok
    recs = trade_audit.read_audit()
    assert recs and recs[-1]["event"] == "PREVIEW_REQUEST"
    assert recs[-1]["payload"]["consumer_secret"] == "***REDACTED***"
    assert recs[-1]["payload"]["qty"] == 1


# ── 8. Data bus failover ──────────────────────────────────────────────────────
def test_databus_failover_prefers_first_nonempty():
    bus = OptionsDataBus()
    bus.register("quantdata", lambda s, e, side: None)         # unavailable
    bus.register("polygon", lambda s, e, side: [               # first with data
        {"strikePrice": 7485, "optionType": "CALL", "bid": 4, "ask": 4.2, "volume": 100, "openInterest": 500}])
    res = bus.get_chain("SPX", "2026-07-06", "CALL")
    assert res["source"] == "polygon" and len(res["contracts"]) == 1
    assert "quantdata" in res["tried"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:
            print(f"ERROR {fn.__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
