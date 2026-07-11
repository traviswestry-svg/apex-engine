"""engine/decision_routes.py — APEX 7.5.7 Decision Intelligence API.

register_decision_routes(app, last_result_provider=...) attaches:

    GET /api/decision   — the six-question decision panel, assembled read-only
                          from the composed Data Bus + confluence + events.

Never 500s the dashboard.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from flask import jsonify

from .decision_intelligence import build_decision_intelligence
from .confluence import build_confluence
from .event_calendar import build_event_intelligence


def register_decision_routes(
    app,
    *,
    last_result_provider: Optional[Callable[[], Dict[str, Any]]] = None,
) -> None:

    @app.route("/api/decision")
    def _decision():
        try:
            lr = (last_result_provider() if last_result_provider else {}) or {}
            conf = build_confluence(lr)
            ev = build_event_intelligence()
            panel = build_decision_intelligence(lr, confluence=conf, events=ev)
            return jsonify({"ok": True, "decision": panel})
        except Exception as e:
            return jsonify({"ok": True, "decision": {
                "available": False, "note": f"decision route recovered: {e}",
                "verdict": "AVOID", "headline": "STAND ASIDE",
                "questions": [], "confidence_pyramid": [], "invalidation": [],
            }})
