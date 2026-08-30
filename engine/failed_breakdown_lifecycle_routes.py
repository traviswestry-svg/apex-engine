"""Read-only and explicit observational routes for APEX 69.7.0."""
from __future__ import annotations

from flask import jsonify, request

from .failed_breakdown_lifecycle import capability, current_state, history, observe

REQUIRED_ROUTES = (
    "/api/failed-breakdown/capability", "/api/failed-breakdown/state",
    "/api/failed-breakdown/history", "/api/failed-breakdown/observe",
)


def register_failed_breakdown_lifecycle_routes(app) -> None:
    @app.get("/api/failed-breakdown/capability")
    def failed_breakdown_capability():
        return jsonify(capability())

    @app.get("/api/failed-breakdown/state")
    def failed_breakdown_state():
        return jsonify(current_state(symbol=request.args.get("symbol", "SPX")))

    @app.get("/api/failed-breakdown/history")
    def failed_breakdown_history():
        return jsonify(history(symbol=request.args.get("symbol", "SPX"),
                               lifecycle_id=request.args.get("lifecycle_id"),
                               limit=request.args.get("limit", 100)))

    @app.post("/api/failed-breakdown/observe")
    def failed_breakdown_observe():
        body = request.get_json(silent=True) or {}
        if not bool(app.config.get("TESTING")):
            return jsonify({"ok": False, "status": "SCANNER_OWNED",
                            "reason": "Production observations are scanner-owned.",
                            "execution_authority": False, "production_effect": "NONE"}), 403
        return jsonify(observe(symbol=body.get("symbol", "SPX"), price=body.get("price"),
                               levels=body.get("levels") or [], observed_at=body.get("observed_at"),
                               relative_volume=body.get("relative_volume"),
                               tick_alignment=body.get("tick_alignment"),
                               absorption=body.get("absorption")))


def verify_registered(app) -> bool:
    paths = {rule.rule for rule in app.url_map.iter_rules()}
    return all(path in paths for path in REQUIRED_ROUTES)
