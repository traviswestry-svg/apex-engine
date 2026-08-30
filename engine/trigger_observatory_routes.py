from __future__ import annotations

from flask import jsonify, request

from .trigger_observatory import capability, effectiveness, history, learning_readiness, sync_canonical_outcomes, trade_visualization

REQUIRED_ROUTES = ("/api/triggers/capability", "/api/triggers/history", "/api/triggers/effectiveness", "/api/triggers/trade-view", "/api/triggers/learning-readiness")


def register_trigger_observatory_routes(app) -> None:
    @app.get("/api/triggers/capability")
    def trigger_observatory_capability():
        return jsonify(capability())

    @app.get("/api/triggers/history")
    def trigger_observatory_history():
        return jsonify(history(symbol=request.args.get("symbol", "SPX"),
                               status=request.args.get("status"),
                               limit=request.args.get("limit", 100)))

    @app.get("/api/triggers/effectiveness")
    def trigger_observatory_effectiveness():
        return jsonify(effectiveness(symbol=request.args.get("symbol", "SPX")))

    @app.get("/api/triggers/trade-view")
    def trigger_observatory_trade_view():
        return jsonify(trade_visualization(trigger_id=request.args.get("trigger_id"),
                                           symbol=request.args.get("symbol", "SPX")))

    @app.get("/api/triggers/learning-readiness")
    def trigger_observatory_learning_readiness():
        return jsonify(learning_readiness())


def verify_registered(app) -> bool:
    paths = {rule.rule for rule in app.url_map.iter_rules()}
    return all(path in paths for path in REQUIRED_ROUTES)
