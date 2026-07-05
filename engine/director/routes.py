"""engine/director/routes.py — Active Trade Director API (Part 20).

register_director_routes(app, **providers) attaches:

    GET  /api/active_trade_director            — the live directive
    GET  /api/active_trade_director/timeline   — active-trade storytelling (Part 17)
    GET  /api/active_trade_director/log        — recent logged directives (Part 18)
    POST /api/active_trade_director/reset       — clear flow/persistence/narrative memory

Isolated here (mirrors engine/execution/trade_routes.py) so app.py stays thin.
Every input is injected as a provider callable so this module never imports app.py
and never fetches data itself. Missing providers degrade gracefully.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from flask import jsonify, request

from .contracts import DirectorContext, PositionView
from .director import get_director
from .position import detect_position
from .snapshots import get_flow_tracker
from .persistence import get_persistence
from .narrative import get_narrator
from .store import recent_directives, init_store


def _call(fn: Optional[Callable], *args, default=None):
    if not fn:
        return default
    try:
        return fn(*args)
    except Exception:
        return default


def register_director_routes(
    app,
    *,
    last_result_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    flow_snapshot_provider: Optional[Callable[[str], Dict[str, Any]]] = None,
    session_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    signal_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    broker_positions_provider: Optional[Callable[[], List[Dict[str, Any]]]] = None,
    open_brackets_provider: Optional[Callable[[], List[Dict[str, Any]]]] = None,
    manual_position_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    default_ticker: str = "SPX",
) -> None:
    """Wire the Director endpoints. All providers optional; the Director degrades
    to OBSERVE/NO_TRADE when data is missing rather than erroring."""

    init_store()

    def _build_context(ticker: str) -> DirectorContext:
        ticker = (ticker or default_ticker).upper()
        last = _call(last_result_provider, default={}) or {}
        ms = last.get("market_state") or {}
        ii = last.get("institutional_intelligence") or {}
        auction = last.get("auction_intelligence") or last.get("auction") or {}
        dealer = last.get("dealer_positioning") or {}
        magnets = last.get("strike_magnets") or {}
        execution = last.get("execution_intelligence") or {}
        risk = last.get("risk") or {}

        session = _call(session_provider, default={}) or {}
        market_open = bool(session.get("is_tradeable_session", session.get("is_tradeable", False)))
        session_state = str(session.get("session") or ms.get("session_state") or "UNKNOWN")

        flow_snap = _call(flow_snapshot_provider, ticker, default={}) or {}
        signal = _call(signal_provider, default={}) or {}

        price = None
        for src in (ms.get("price"), flow_snap.get("stock_price"), magnets.get("price")):
            try:
                if src:
                    price = float(src); break
            except (TypeError, ValueError):
                continue

        pos = detect_position(
            symbol=ticker,
            broker_positions_provider=broker_positions_provider,
            open_brackets_provider=open_brackets_provider,
            manual_position_provider=manual_position_provider,
            current_price=price,
        )

        # staleness: no market_state price OR institutional not computed
        data_stale = (not ms) or (not ii) or (price is None)
        stale_reason = ""
        if not ms:
            stale_reason = "No market_state — run a scan first."
        elif not ii:
            stale_reason = "Institutional intelligence not yet computed."
        elif price is None:
            stale_reason = "No price available."

        return DirectorContext(
            symbol=ticker, market_open=market_open, session_state=session_state, price=price,
            market_state=ms, institutional=ii, auction=auction, dealer=dealer,
            strike_magnets=magnets, execution=execution, flow_snapshot=flow_snap,
            risk=risk, signal=signal, position=pos,
            data_stale=data_stale, stale_reason=stale_reason,
        )

    @app.route("/api/active_trade_director")
    def _active_trade_director():
        ticker = (request.args.get("ticker", default_ticker) or default_ticker).upper()
        try:
            ctx = _build_context(ticker)
            directive = get_director().build(ctx)
            body = directive.to_dict()
            body["ok"] = True
            body["stale_reason"] = ctx.stale_reason
            return jsonify(body)
        except Exception as e:  # never 500 the operator dashboard
            return jsonify({"ok": False, "symbol": ticker, "directive": "OBSERVE",
                            "position_state": "FLAT", "error": str(e),
                            "reason": "Director error — see logs.",
                            "quality_flags": ["DIRECTOR_EXCEPTION"]}), 200

    @app.route("/api/active_trade_director/timeline")
    def _director_timeline():
        ticker = (request.args.get("ticker", default_ticker) or default_ticker).upper()
        return jsonify({"ok": True, "symbol": ticker,
                        "timeline": get_narrator().timeline(ticker)})

    @app.route("/api/active_trade_director/log")
    def _director_log():
        ticker = (request.args.get("ticker", default_ticker) or default_ticker).upper()
        limit = min(200, max(1, int(request.args.get("limit", "50") or 50)))
        return jsonify({"ok": True, "symbol": ticker,
                        "directives": recent_directives(ticker, limit)})

    @app.route("/api/active_trade_director/reset", methods=["POST"])
    def _director_reset():
        ticker = (request.args.get("ticker", default_ticker) or default_ticker).upper()
        get_flow_tracker().reset(ticker)
        get_persistence().reset(ticker)
        get_narrator().reset(ticker)
        return jsonify({"ok": True, "message": f"Director memory reset for {ticker}."})
