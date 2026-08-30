from __future__ import annotations

from flask import jsonify, request

from .trigger_observatory import capability, history

REQUIRED_ROUTES = ("/api/triggers/capability", "/api/triggers/history")


def register_trigger_observatory_routes(app) -> None:
    @app.get("/api/triggers/capability")
    def trigger_observatory_capability():
        return jsonify(capability())

    @app.get("/api/triggers/history")
    def trigger_observatory_history():
        return jsonify(history(symbol=request.args.get("symbol", "SPX"),
                               status=request.args.get("status"),
                               limit=request.args.get("limit", 100)))


def verify_registered(app) -> bool:
    paths = {rule.rule for rule in app.url_map.iter_rules()}
    return all(path in paths for path in REQUIRED_ROUTES)
