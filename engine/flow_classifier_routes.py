"""engine/flow_classifier_routes.py — APEX 9 Step 2 API surface.

Mirrors engine/premium_strategy_routes.py: isolated so app.py stays thin,
read-only over data the app already fetched, and never 500s the dashboard.

Routes
------
GET /api/flow_classifier            — classified flow events for a ticker set.
GET /api/flow_classifier/health     — diagnostics, thresholds, freshness, and an
                                      explicit list of fields the provider does
                                      not supply (so the UI can state limits
                                      rather than imply completeness).

Public API preservation: /api/flow_tape is untouched. This is an additive
surface; nothing existing changes shape.
"""
from __future__ import annotations

import datetime as _dt
import os
from typing import Any, Callable, Dict, List, Optional

from flask import jsonify, request

from .flow_classifier import (
    CLASSIFIER_VERSION,
    FLOW_CLASSIFIER_ENABLED,
    classify_flow_events,
    health as classifier_health,
)


def _now_et_secs() -> Optional[int]:
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo("America/New_York")
        n = _dt.datetime.now(tz)
        return n.hour * 3600 + n.minute * 60 + n.second
    except Exception:  # pragma: no cover
        return None


def _disabled_payload(note: str) -> Dict[str, Any]:
    return {
        "available": False, "note": note, "count": 0, "events": [],
        "summary": {}, "classifier_version": CLASSIFIER_VERSION,
    }


def register_flow_classifier_routes(
    app,
    *,
    flow_tape_provider: Optional[Callable[[List[str], float], Dict[str, Any]]] = None,
    last_result_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    default_ticker: str = "SPX",
) -> None:
    """Attach the classifier routes.

    Args:
        flow_tape_provider: callable(tickers, min_premium) -> flow tape payload
            (the app's existing /api/flow_tape data path). Injected so this
            module never talks to a provider itself — read-only by construction.
        last_result_provider: callable() -> the canonical bus, for spot only.
    """

    @app.route("/api/flow_classifier")
    def _flow_classifier():
        try:
            if not FLOW_CLASSIFIER_ENABLED:
                return jsonify({"ok": True, "flow_classifier": _disabled_payload(
                    "Flow classifier disabled (FLOW_CLASSIFIER_ENABLED=false).")})
            tickers = [t.strip().upper() for t in
                       (request.args.get("tickers") or default_ticker).split(",") if t.strip()]
            try:
                min_premium = float(request.args.get("min_premium") or 0)
            except (TypeError, ValueError):
                min_premium = 0.0

            if flow_tape_provider is None:
                return jsonify({"ok": True, "flow_classifier": _disabled_payload(
                    "No flow source wired — classifier has nothing to read.")})

            tape = flow_tape_provider(tickers, min_premium) or {}
            rows = tape.get("rows") or []
            if not rows:
                payload = _disabled_payload(
                    tape.get("message") or "No flow rows available to classify.")
                payload["available"] = True
                payload["upstream_status"] = tape.get("status")
                return jsonify({"ok": True, "tickers": tickers, "flow_classifier": payload})

            # Spot is read from the bus for moneyness only — never recomputed.
            spot = None
            if last_result_provider:
                lr = last_result_provider() or {}
                ms = lr.get("market_state") or {}
                try:
                    spot = float(ms.get("price")) if ms.get("price") else None
                except (TypeError, ValueError):
                    spot = None

            result = classify_flow_events(rows, spot=spot, as_of_secs=_now_et_secs())
            result["upstream_status"] = tape.get("status")
            return jsonify({"ok": True, "tickers": tickers, "flow_classifier": result})
        except Exception as e:
            return jsonify({"ok": True, "flow_classifier": _disabled_payload(
                f"flow classifier route recovered: {e}")})

    @app.route("/api/flow_classifier/health")
    def _flow_classifier_health():
        try:
            h = classifier_health()
            h["ok"] = True
            return jsonify({"ok": True, "health": h})
        except Exception as e:
            return jsonify({"ok": True, "health": {
                "ok": False, "enabled": False, "note": f"health recovered: {e}",
                "classifier_version": CLASSIFIER_VERSION}})
