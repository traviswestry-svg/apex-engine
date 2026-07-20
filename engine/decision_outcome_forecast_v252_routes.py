"""HTTP routes for APEX 25.2 Decision Outcome Forecasting (shadow-mode)."""
from flask import jsonify, request

from . import decision_outcome_forecast_v252 as forecast

REQUIRED_ROUTES = (
    ("GET", "/api/decision-forecast/status"),
    ("GET", "/api/decision-forecast/current"),
    ("GET", "/api/decision-forecast/scenarios"),
    ("GET", "/api/decision-forecast/analogs"),
    ("GET", "/api/decision-forecast/history"),
    ("POST", "/api/decision-forecast/evaluate"),
)


def verify_registered(app):
    present = {(method, str(rule)) for rule in app.url_map.iter_rules() for method in (rule.methods or set())}
    return [f"{method} {path}" for method, path in REQUIRED_ROUTES if (method, path) not in present]


def register_decision_outcome_forecast_v252_routes(app, *, last_result_provider=None):
    def current_payload():
        value = last_result_provider() if callable(last_result_provider) else {}
        return value if isinstance(value, dict) else {}

    def _horizon_arg():
        horizon = (request.args.get("horizon") or "").strip()
        return horizon if horizon in forecast.HORIZON_SECONDS else forecast.DEFAULT_HORIZON

    @app.get("/api/decision-forecast/status")
    def decision_forecast_v252_status():
        return jsonify(forecast.status())

    @app.get("/api/decision-forecast/current")
    def decision_forecast_v252_current():
        payload = current_payload()
        if request.args.get("all_horizons", "").lower() in {"1", "true", "yes"}:
            return jsonify(forecast.build_all_horizons(payload))
        return jsonify(forecast.build_forecast(payload, horizon=_horizon_arg()))

    @app.get("/api/decision-forecast/scenarios")
    def decision_forecast_v252_scenarios():
        result = forecast.build_forecast(current_payload(), horizon=_horizon_arg())
        forecast_block = result.get("forecast", {})
        return jsonify({
            "ok": True,
            "version": forecast.VERSION,
            "generated_at": result.get("generated_at"),
            "horizon": forecast_block.get("forecast_horizon"),
            "scenarios": forecast_block.get("scenarios", []),
            "production_effect": "NONE",
        })

    @app.get("/api/decision-forecast/analogs")
    def decision_forecast_v252_analogs():
        result = forecast.build_forecast(current_payload(), horizon=_horizon_arg())
        forecast_block = result.get("forecast", {})
        return jsonify({
            "ok": True,
            "version": forecast.VERSION,
            "generated_at": result.get("generated_at"),
            "forecast_basis": forecast_block.get("forecast_basis"),
            "comparable_sample_size": forecast_block.get("comparable_sample_size"),
            "comparable_sessions": forecast_block.get("comparable_sessions", []),
            "production_effect": "NONE",
        })

    @app.get("/api/decision-forecast/history")
    def decision_forecast_v252_history():
        try:
            limit = min(200, max(1, int(request.args.get("limit", 50))))
        except (TypeError, ValueError):
            limit = 50
        decision_id = (request.args.get("decision_id") or "").strip() or None
        try:
            return jsonify(forecast.history(limit=limit, decision_id=decision_id))
        except Exception as exc:  # persistence must fail explicitly, not silently
            return jsonify({"ok": False, "status": "PERSISTENCE_ERROR",
                            "message": str(exc), "version": forecast.VERSION}), 500

    @app.post("/api/decision-forecast/evaluate")
    def decision_forecast_v252_evaluate():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "status": "INVALID_REQUEST",
                            "message": "JSON object required."}), 400

        # Maturity scoring path: evaluate a matured forecast against realized truth.
        if isinstance(payload.get("forecast"), dict) and isinstance(payload.get("realized"), dict):
            evaluation = forecast.evaluate_forecast(payload["forecast"], payload["realized"])
            if payload.get("persist") and evaluation.get("status") == "MATURED":
                forecast.persist_evaluation(
                    payload["forecast"].get("forecast_id", ""), evaluation, payload["realized"])
            status_code = 200 if evaluation.get("ok") else 409  # NOT_MATURED -> conflict
            return jsonify(evaluation), status_code

        # Forecast-generation path: build (and optionally persist) a forecast.
        horizon = (payload.get("horizon") or forecast.DEFAULT_HORIZON)
        result = forecast.build_forecast(payload, horizon=horizon)
        if payload.get("persist"):
            try:
                forecast.persist_forecast(result, input_snapshot=payload)
            except Exception as exc:
                result["persistence_warning"] = str(exc)
        return jsonify(result)
