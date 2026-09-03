from __future__ import annotations

from flask import jsonify, request

from .trigger_observatory import actionability_capture_readiness_validation, abstention_regret_validation, capability, counterfactual_regret_validation, effectiveness, history, learning_readiness, observation_integrity_validation, predictive_validation, sync_canonical_outcomes, trade_visualization

REQUIRED_ROUTES = ("/api/triggers/capability", "/api/triggers/history", "/api/triggers/effectiveness", "/api/triggers/trade-view", "/api/triggers/learning-readiness", "/api/triggers/predictive-validation", "/api/triggers/abstention-regret", "/api/triggers/counterfactual-regret", "/api/triggers/actionability-capture-readiness", "/api/triggers/observation-integrity", "/api/triggers/context-backfill")


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

    @app.get("/api/triggers/predictive-validation")
    def trigger_observatory_predictive_validation():
        return jsonify(predictive_validation(symbol=request.args.get("symbol", "SPX")))

    @app.get("/api/triggers/abstention-regret")
    def trigger_observatory_abstention_regret():
        return jsonify(abstention_regret_validation(symbol=request.args.get("symbol", "SPX")))

    @app.get("/api/triggers/counterfactual-regret")
    def trigger_observatory_counterfactual_regret():
        return jsonify(counterfactual_regret_validation(symbol=request.args.get("symbol", "SPX")))

    @app.get("/api/triggers/actionability-capture-readiness")
    def trigger_observatory_actionability_capture_readiness():
        return jsonify(actionability_capture_readiness_validation(limit=request.args.get("limit", 100)))

    @app.get("/api/triggers/observation-integrity")
    def trigger_observatory_observation_integrity():
        return jsonify(observation_integrity_validation(symbol=request.args.get("symbol", "SPX")))

    @app.post("/api/triggers/context-backfill")
    def trigger_observatory_context_backfill():
        body = request.get_json(silent=True) or {}
        apply = bool(body.get("apply") is True)
        from .dynamic_state_outcome_calibration import context_backfill
        from .evidence_pipeline import DEFAULT_DB
        out = context_backfill(DEFAULT_DB, apply=apply)
        out["broker_mutation"] = False
        out["behavioral_authority"] = False
        return jsonify(out)


def verify_registered(app) -> bool:
    paths = {rule.rule for rule in app.url_map.iter_rules()}
    return all(path in paths for path in REQUIRED_ROUTES)
