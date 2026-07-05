"""engine/range_routes.py — APEX 7.2 Range Intelligence API.

register_range_routes(app, **providers) attaches:

    GET /api/range_intelligence?ticker=SPX            — live/pre-RTH range projection
    GET /api/range_intelligence/history?ticker=SPX    — stored daily projections
    GET /api/range_intelligence/scorecard?ticker=SPX  — projection accuracy scorecard

Isolated here (mirrors engine/director/routes.py) so app.py stays thin. Inputs are
injected via provider callables; the engine consumes the already-composed Data Bus
object and never re-fetches. Never 500s the dashboard.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from flask import jsonify, request

from .range_intelligence import (
    build_range_intelligence, capture_projection, history, scorecard,
    init_history, record_actuals,
)


def _call(fn: Optional[Callable], *args, default=None):
    if not fn:
        return default
    try:
        return fn(*args)
    except Exception:
        return default


def register_range_routes(
    app,
    *,
    last_result_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    session_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    default_ticker: str = "SPX",
) -> None:
    init_history()

    def _market_open() -> bool:
        s = _call(session_provider, default={}) or {}
        return bool(s.get("is_tradeable_session", s.get("is_tradeable", False)))

    @app.route("/api/range_intelligence")
    def _range_intelligence():
        ticker = (request.args.get("ticker", default_ticker) or default_ticker).upper()
        try:
            lr = _call(last_result_provider, default={}) or {}
            env = build_range_intelligence(lr, market_open=_market_open(), ticker=ticker)
            # opportunistically capture the projection for later self-evaluation
            try:
                capture_projection(env, ticker)
            except Exception:
                pass
            return jsonify(env)
        except Exception as e:  # never break the dashboard
            return jsonify({"ok": False, "ticker": ticker,
                            "version": "7.2_RANGE_INTELLIGENCE_ENGINE",
                            "range_intelligence": {"available": False,
                                                   "active_scenario": "INSUFFICIENT_DATA",
                                                   "quality_flags": ["RANGE_ENGINE_EXCEPTION"],
                                                   "interpretation": "Range engine error — see logs."},
                            "error": str(e)}), 200

    @app.route("/api/range_intelligence/history")
    def _range_history():
        ticker = (request.args.get("ticker", default_ticker) or default_ticker).upper()
        limit = min(200, max(1, int(request.args.get("limit", "50") or 50)))
        return jsonify({"ok": True, "ticker": ticker, "history": history(ticker, limit)})

    @app.route("/api/range_intelligence/scorecard")
    def _range_scorecard():
        ticker = (request.args.get("ticker", default_ticker) or default_ticker).upper()
        return jsonify(scorecard(ticker))

    @app.route("/api/range_intelligence/record_actuals", methods=["POST"])
    def _range_record_actuals():
        ticker = (request.args.get("ticker", default_ticker) or default_ticker).upper()
        hi = request.args.get("high") or (request.json or {}).get("high") if request.is_json else request.args.get("high")
        lo = request.args.get("low") or (request.json or {}).get("low") if request.is_json else request.args.get("low")
        scn = request.args.get("scenario_final", "") or ""
        try:
            ok = record_actuals(ticker, actual_high=float(hi), actual_low=float(lo),
                                scenario_final=scn)
            return jsonify({"ok": ok, "ticker": ticker})
        except Exception as e:
            return jsonify({"ok": False, "ticker": ticker, "error": str(e)}), 200
