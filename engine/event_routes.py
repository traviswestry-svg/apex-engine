"""engine/event_routes.py — APEX 7.5.4 Event Intelligence API.

register_event_routes(app) attaches:

    GET /api/events   — upcoming market-event landscape (FOMC/CPI/NFP/OPEX/…)
                        with proximity-aware, descriptive (non-signal) guidance.

Self-contained: the engine computes dates from rules + a curated table and needs
no Data Bus input. Never 500s the dashboard.
"""
from __future__ import annotations

from flask import jsonify

from .event_calendar import build_event_intelligence


def register_event_routes(app) -> None:

    @app.route("/api/events")
    def _events():
        try:
            return jsonify({"ok": True, "events": build_event_intelligence()})
        except Exception as e:
            return jsonify({"ok": True, "events": {
                "available": False, "note": f"events route recovered: {e}",
                "event_regime": "CLEAR", "headline_event": None,
                "today_events": [], "upcoming": [],
            }})
