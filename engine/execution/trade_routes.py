"""engine/execution/trade_routes.py — Trade Command Center routes.

register_trade_routes(app, **hooks) attaches every /api/trade, /api/broker and the
/apex_os/trade_command route to the existing Flask app. Isolated here so app.py's
delta is one non-fatal call. All broker-specific logic stays behind the adapter; all
order-changing endpoints run the risk guard and audit the event.

Every JSON response uses the shared envelope:
  { ok, mode, data, warnings, errors, timestamp }
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Any, Callable, Dict, Optional

from flask import request, render_template, jsonify

from engine.brokers.etrade_adapter import ETradeAdapter
from engine.options.options_data_bus import OptionsDataBus
from engine.execution.broker_interface import OrderIntent, ChangeIntent, envelope
from engine.execution.bracket_manager import get_bracket_manager
from engine.execution import trade_risk_guard as guard
from engine.execution.trade_audit import audit, read_audit

# Module state (single trader, single active plan in V1).
_ADAPTER: Optional[ETradeAdapter] = None
_BUS: Optional[OptionsDataBus] = None
_LAST_ORDER_EPOCH: Dict[str, float] = {}


def _adapter() -> ETradeAdapter:
    global _ADAPTER
    if _ADAPTER is None:
        _ADAPTER = ETradeAdapter()
    return _ADAPTER


def _bus() -> OptionsDataBus:
    global _BUS
    if _BUS is None:
        _BUS = OptionsDataBus()
    return _BUS


def register_trade_routes(
    app,
    *,
    quantdata_chain_fetcher: Optional[Callable] = None,
    polygon_chain_fetcher: Optional[Callable] = None,
    spot_provider: Optional[Callable[[], float]] = None,
    expected_path_provider: Optional[Callable[[], Optional[float]]] = None,
    spx_candles_provider: Optional[Callable[[int, int], Any]] = None,
) -> None:
    """Attach all trade routes. Optional hooks let app.py inject its existing
    QuantData / Polygon chain fetchers and SPX spot; failover order is
    QuantData → Polygon/Massive → E*TRADE."""
    bus = _bus()
    if quantdata_chain_fetcher:
        bus.register("quantdata", quantdata_chain_fetcher)
    if polygon_chain_fetcher:
        bus.register("polygon", polygon_chain_fetcher)
    # E*TRADE market API is always the final fallback.
    bus.register("etrade", lambda sym, exp, side: (
        (_adapter().get_option_chain(sym, exp, side).data or {}).get("contracts")))

    def _spot() -> Optional[float]:
        try:
            return float(spot_provider()) if spot_provider else None
        except Exception:
            return None

    def _expected_path() -> Optional[float]:
        try:
            return expected_path_provider() if expected_path_provider else None
        except Exception:
            return None

    # ── broker status / accounts ─────────────────────────────────────────
    @app.route("/api/broker/etrade/status")
    def _etrade_status():
        r = _adapter().status()
        return jsonify(envelope(r.ok, r.data, mode=r.mode, warnings=r.warnings, errors=r.errors))

    @app.route("/api/broker/etrade/accounts")
    def _etrade_accounts():
        r = _adapter().list_accounts()
        audit("ACCOUNTS_LISTED", {"ok": r.ok})
        return jsonify(envelope(r.ok, r.data, mode=r.mode, warnings=r.warnings, errors=r.errors))

    # ── chain / contract selection ───────────────────────────────────────
    @app.route("/api/trade/spx/expirations")
    def _spx_expirations():
        r = _adapter().get_option_expirations("SPX")
        return jsonify(envelope(r.ok, r.data, mode=r.mode, warnings=r.warnings, errors=r.errors))

    @app.route("/api/trade/spx/chain")
    def _spx_chain():
        exp = request.args.get("expiration", "")
        side = request.args.get("side", "CALL").upper()
        if not exp:
            return jsonify(envelope(False, errors=["expiration is required (YYYY-MM-DD)"]))
        res = _bus().get_chain("SPX", exp, side)
        audit("QUOTE_SNAPSHOT", {"expiration": exp, "side": side,
                                 "source": res.get("source"), "n": len(res.get("contracts", []))})
        return jsonify(envelope(bool(res.get("contracts")), res,
                                warnings=res.get("warnings", [])))

    @app.route("/api/trade/spx/recommended-contracts")
    def _spx_recommended():
        exp = request.args.get("expiration", "")
        side = request.args.get("side", "CALL").upper()
        if not exp:
            return jsonify(envelope(False, errors=["expiration is required"]))
        res = _bus().get_chain("SPX", exp, side)
        spot = _spot()
        recs = _bus().recommend_contracts(res.get("contracts", []), spot=spot or 0,
                                          expected_path=_expected_path(), side=side)
        return jsonify(envelope(True, {"recommended": recs, "spot": spot,
                                       "source": res.get("source")}))

    @app.route("/api/trade/spx/select-contract", methods=["POST"])
    def _spx_select():
        body = request.get_json(silent=True) or {}
        audit("CONTRACT_SELECTED", {"osi_key": body.get("osi_key"), "strike": body.get("strike"),
                                    "side": body.get("side")})
        return jsonify(envelope(True, {"selected": body}))

    @app.route("/api/trade/spx/candles")
    def _spx_candles():
        """SPX cash candles for the command-center chart, in Lightweight Charts shape.
        Reuses APEX's existing SPX fetch (I:SPX). Returns UTC-second timestamps."""
        try:
            days = max(1, min(5, int(request.args.get("days", 1))))
        except Exception:
            days = 1
        try:
            tf = int(request.args.get("tf", 5))
        except Exception:
            tf = 5
        tf = tf if tf in (1, 5, 15) else 5
        if not spx_candles_provider:
            return jsonify(envelope(False, errors=["SPX candle feed not wired on this deployment."]))
        try:
            raw = spx_candles_provider(days, tf) or []
        except Exception as e:
            return jsonify(envelope(False, errors=[f"candle fetch failed: {e}"]))
        candles = []
        for b in raw:
            t = b.get("t")
            if t is None:
                continue
            candles.append({
                "time": int(float(t) / 1000.0),
                "open": b.get("o"), "high": b.get("h"),
                "low": b.get("l"), "close": b.get("c"),
            })
        candles.sort(key=lambda c: c["time"])
        # de-dup identical timestamps (Lightweight Charts requires strictly ascending)
        deduped = []
        seen = set()
        for c in candles:
            if c["time"] in seen:
                continue
            seen.add(c["time"])
            deduped.append(c)
        last = deduped[-1]["close"] if deduped else None
        return jsonify(envelope(bool(deduped), {"candles": deduped, "count": len(deduped),
                                                "last": last, "tf": tf, "days": days}))

    @app.route("/api/trade/spx/project-levels", methods=["POST"])
    def _spx_project_levels():
        """Server-side source of truth for the dual chart. Projects trade lines between
        the SPX index axis and the option premium axis. Body:
          { spot, base_premium, delta, gamma?, source_axis: 'spx'|'premium',
            levels: {ENTRY,STOP,BREAKEVEN,TP1,TP2,TP3}, suggest?: bool }"""
        from engine.execution import price_mapper as pm
        body = request.get_json(silent=True) or {}
        try:
            spot = float(body.get("spot"))
            base_premium = float(body.get("base_premium"))
            delta = float(body.get("delta"))
        except (TypeError, ValueError):
            return jsonify(envelope(False, errors=["spot, base_premium and delta are required numbers"]))
        gamma = float(body.get("gamma") or 0.0)
        source_axis = str(body.get("source_axis", "premium")).lower()
        data: Dict[str, Any] = {}
        if body.get("suggest"):
            data["suggested"] = pm.suggest_bracket(base_premium, spot=spot, delta=delta, gamma=gamma)
        levels = body.get("levels") or {}
        if levels:
            try:
                data["projected"] = pm.project_levels(levels, source_axis, spot=spot,
                                                      base_premium=base_premium, delta=delta, gamma=gamma)
            except ValueError as e:
                return jsonify(envelope(False, errors=[str(e)]))
        return jsonify(envelope(True, data))

    # ── entry preview / place ────────────────────────────────────────────
    @app.route("/api/trade/spx/preview-entry", methods=["POST"])
    def _preview_entry():
        body = request.get_json(silent=True) or {}
        contract = body.get("contract") or {}
        qty = int(body.get("quantity") or 0)
        entry = body.get("entry_premium")
        stop = body.get("stop_premium")
        decision = guard.validate_entry(
            contract=contract, quantity=qty, entry_premium=entry, stop_premium=stop,
            session_state=body.get("session_state", "MARKET_OPEN"),
            last_order_epoch=_LAST_ORDER_EPOCH.get("SPX"), now_epoch=time.time(),
        )
        audit("PREVIEW_REQUEST", {"contract": contract.get("osi_key"), "qty": qty,
                                  "entry": entry, "stop": stop, "risk": decision.to_dict()})
        if not decision.allow:
            audit("RISK_REJECTION", {"stage": "preview_entry", "reasons": decision.reasons})
            return jsonify(envelope(False, {"risk": decision.to_dict()},
                                    errors=decision.reasons))
        intent = OrderIntent(symbol="SPX", osi_key=contract.get("osi_key", ""),
                             side=contract.get("side", "CALL"), action="BUY_OPEN",
                             quantity=qty, order_type="LIMIT", limit_price=entry, tag="ENTRY")
        r = _adapter().preview_order(intent)
        audit("PREVIEW_RESPONSE", {"ok": r.ok, "preview_id": (r.data or {}).get("preview_id")})
        data = {"risk": decision.to_dict(), "broker": r.data,
                "preview_id": (r.data or {}).get("preview_id"), "intent": intent.to_dict()}
        return jsonify(envelope(r.ok, data, mode=r.mode, warnings=decision.warnings, errors=r.errors))

    @app.route("/api/trade/spx/place-entry", methods=["POST"])
    def _place_entry():
        body = request.get_json(silent=True) or {}
        if not body.get("confirmed") and guard.RiskLimits.from_env().require_confirmation:
            return jsonify(envelope(False, errors=["Confirmation required (confirmed=true)."]))
        contract = body.get("contract") or {}
        qty = int(body.get("quantity") or 0)
        entry = body.get("entry_premium")
        preview_id = body.get("preview_id")
        intent = OrderIntent(symbol="SPX", osi_key=contract.get("osi_key", ""),
                             side=contract.get("side", "CALL"), action="BUY_OPEN",
                             quantity=qty, order_type="LIMIT", limit_price=entry, tag="ENTRY")
        r = _adapter().place_order(preview_id, intent)
        _LAST_ORDER_EPOCH["SPX"] = time.time()
        bracket = None
        if r.ok:
            bm = get_bracket_manager()
            b = bm.create(symbol="SPX", osi_key=intent.osi_key, side=intent.side, quantity=qty,
                          entry_price=entry, stop_price=body.get("stop_premium") or 0,
                          tp_prices=body.get("tp_prices") or [])
            bm.transition(b.bracket_id, "PREVIEWED"); bm.transition(b.bracket_id, "SENT")
            bracket = b.bracket_id
        audit("ORDER_PLACED", {"ok": r.ok, "preview_id": preview_id, "bracket": bracket})
        audit("BROKER_RESPONSE", {"ok": r.ok, "data": r.data})
        return jsonify(envelope(r.ok, {"broker": r.data, "bracket_id": bracket},
                                mode=r.mode, errors=r.errors))

    @app.route("/api/trade/spx/active-position")
    def _active_position():
        bm = get_bracket_manager()
        brackets = [b.to_dict() for b in bm.open_brackets()]
        pos = _adapter().get_positions(_adapter().account_id_key) if _adapter().configured else None
        return jsonify(envelope(True, {"brackets": brackets,
                                       "positions": (pos.data if pos and pos.ok else {})}))

    # ── change (drag stop / TP) ──────────────────────────────────────────
    @app.route("/api/trade/spx/preview-change", methods=["POST"])
    def _preview_change():
        body = request.get_json(silent=True) or {}
        line = str(body.get("line", "")).upper()
        new_price = body.get("new_price")
        decision = guard.validate_line_drag(
            line=line, new_price=new_price,
            entry_premium=body.get("entry_premium"), current_premium=body.get("current_premium"),
            levels=body.get("levels") or {}, side=body.get("side", "CALL"),
            position_qty=int(body.get("position_qty") or 0),
            exit_qty=body.get("exit_qty"),
            breakeven_armed=bool(body.get("breakeven_armed")),
        )
        audit("DRAG_EVENT", {"line": line, "new_price": new_price, "risk": decision.to_dict()})
        if not decision.allow:
            audit("DRAG_REJECTED", {"line": line, "reasons": decision.reasons})
            return jsonify(envelope(False, {"risk": decision.to_dict()}, errors=decision.reasons))
        order_id = body.get("order_id")
        ci = ChangeIntent(order_id=order_id or "",
                          new_limit_price=new_price if line != "STOP" else None,
                          new_stop_price=new_price if line == "STOP" else None, tag=line)
        r = _adapter().preview_change_order(order_id, ci) if order_id else None
        data = {"risk": decision.to_dict(),
                "broker": (r.data if r else {}), "preview_id": ((r.data or {}).get("preview_id") if r else None),
                "change": ci.to_dict()}
        ok = decision.allow and (r.ok if r else True)
        return jsonify(envelope(ok, data, warnings=decision.warnings,
                                errors=(r.errors if r else [])))

    @app.route("/api/trade/spx/place-change", methods=["POST"])
    def _place_change():
        body = request.get_json(silent=True) or {}
        if not body.get("confirmed") and guard.RiskLimits.from_env().require_confirmation:
            return jsonify(envelope(False, errors=["Confirmation required (confirmed=true)."]))
        line = str(body.get("line", "")).upper()
        new_price = body.get("new_price")
        order_id = body.get("order_id")
        preview_id = body.get("preview_id")
        ci = ChangeIntent(order_id=order_id or "",
                          new_limit_price=new_price if line != "STOP" else None,
                          new_stop_price=new_price if line == "STOP" else None, tag=line)
        r = _adapter().place_change_order(order_id, preview_id, ci)
        audit("CHANGE_ORDER", {"ok": r.ok, "line": line, "new_price": new_price, "order_id": order_id})
        return jsonify(envelope(r.ok, {"broker": r.data}, mode=r.mode, errors=r.errors))

    @app.route("/api/trade/spx/cancel-order", methods=["POST"])
    def _cancel_order():
        body = request.get_json(silent=True) or {}
        order_id = body.get("order_id")
        if not order_id:
            return jsonify(envelope(False, errors=["order_id required"]))
        r = _adapter().cancel_order(order_id)
        audit("CANCEL_ORDER", {"ok": r.ok, "order_id": order_id})
        return jsonify(envelope(r.ok, {"broker": r.data}, mode=r.mode, errors=r.errors))

    @app.route("/api/trade/spx/flatten", methods=["POST"])
    def _flatten():
        body = request.get_json(silent=True) or {}
        if not body.get("confirmed") and guard.RiskLimits.from_env().require_confirmation:
            return jsonify(envelope(False, errors=["Confirmation required to flatten (confirmed=true)."]))
        bracket_id = body.get("bracket_id")
        bm = get_bracket_manager()
        result: Dict[str, Any] = {"flattened": None}
        if bracket_id and bm.get(bracket_id):
            b = bm.flatten(bracket_id)
            result["flattened"] = b.to_dict()
        audit("FLATTEN_REQUEST", {"bracket_id": bracket_id})
        return jsonify(envelope(True, result))

    @app.route("/api/trade/spx/audit-log")
    def _audit_log():
        day = request.args.get("day")
        try:
            limit = min(1000, int(request.args.get("limit", 200)))
        except Exception:
            limit = 200
        return jsonify(envelope(True, {"records": read_audit(day, limit)}))

    # ── page ─────────────────────────────────────────────────────────────
    @app.route("/apex_os/trade_command")
    def _trade_command_page():
        try:
            return render_template("trade_command.html")
        except Exception as e:
            # Never 500 the route just because a template is missing.
            return (f"<h2>APEX Trade Command Center</h2><p>Backend online. "
                    f"UI template pending (Phase 2). {e}</p>", 200)
