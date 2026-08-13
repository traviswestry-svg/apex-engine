"""engine/flow_pl_routes.py — APEX 9 Step 4 API surface.

A thin wrapper over `flow_pl_pipeline.run_flow_pl`. The pipeline itself is shared
with the background scanner sampler so the two can never drift apart — see
flow_pl_pipeline's module docstring for why that matters.

Routes
------
GET /api/flow_pl          — cluster + single-event theoretical P/L.
GET /api/flow_pl/health   — versions, thresholds, store state, honest limits.

Public API preservation: /api/flow_tape, /api/flow_classifier and
/api/flow_clusters are untouched. This is an additive surface.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from flask import jsonify, request

from .flow_pl import (
    DEFAULT_MARK_METHOD,
    FLOW_PL_ENABLED,
    FLOW_PL_VERSION,
    MARK_METHODS,
    THEORETICAL_PL_LABEL,
    health as pl_health,
)
from .flow_pl_pipeline import run_flow_pl
from . import flow_pl_store


def _empty(note: str) -> Dict[str, Any]:
    return {"available": False, "note": note, "clusters": [], "single_events": [],
            "count": 0, "label": THEORETICAL_PL_LABEL,
            "flow_pl_version": FLOW_PL_VERSION}


def register_flow_pl_routes(
    app,
    *,
    flow_tape_provider: Optional[Callable[[List[str], float], Dict[str, Any]]] = None,
    chain_fetcher: Optional[Callable[[str, str, str], Any]] = None,
    last_result_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    default_ticker: str = "SPX",
    track: bool = True,
) -> None:
    """Attach P/L routes. All data access is injected — read-only by construction."""
    if track:
        flow_pl_store.init_db()

    @app.route("/api/flow_pl")
    def _flow_pl():
        try:
            if not FLOW_PL_ENABLED:
                return jsonify({"ok": True, "flow_pl": _empty(
                    "Flow P/L disabled (FLOW_PL_ENABLED=false).")})
            tickers = [t.strip().upper() for t in
                       (request.args.get("tickers") or default_ticker).split(",") if t.strip()]
            method = (request.args.get("method") or DEFAULT_MARK_METHOD).strip()
            if method not in MARK_METHODS:
                return jsonify({"ok": True, "flow_pl": _empty(
                    f"Unknown mark method {method!r}. Valid: {', '.join(MARK_METHODS)}.")})
            try:
                min_premium = float(request.args.get("min_premium") or 0)
            except (TypeError, ValueError):
                min_premium = 0.0

            payload = run_flow_pl(
                tickers=tickers,
                flow_tape_provider=flow_tape_provider,
                chain_fetcher=chain_fetcher,
                last_result_provider=last_result_provider,
                method=method,
                min_premium=min_premium,
                default_ticker=default_ticker,
                track=track,
                attach_excursions=True,
            )
            return jsonify({"ok": True, "tickers": tickers, "flow_pl": payload})
        except Exception as e:
            return jsonify({"ok": True, "flow_pl": _empty(f"flow P/L route recovered: {e}")})

    @app.route("/api/flow_pl/health")
    def _flow_pl_health():
        try:
            h = pl_health()
            h["store"] = flow_pl_store.health()
            h["ok"] = True
            return jsonify({"ok": True, "health": h})
        except Exception as e:
            return jsonify({"ok": True, "health": {
                "ok": False, "note": f"health recovered: {e}",
                "flow_pl_version": FLOW_PL_VERSION}})
