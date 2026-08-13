"""HTTP routes for APEX 23.2 Institutional Forecast Engine."""
from __future__ import annotations
from flask import jsonify, request
from .institutional_forecast_engine_v232 import build_institutional_forecast


def register_institutional_forecast_routes(app, *, last_result_provider, history_provider=None):
    def result():
        last = last_result_provider() if callable(last_result_provider) else {}
        history = history_provider() if callable(history_provider) else None
        return build_institutional_forecast(last or {}, history, before=request.args.get("before"))

    @app.get("/api/institutional-forecast/status")
    def institutional_forecast_status():
        x=result(); keys=("ok","version","semantic_version","schema_version","evaluated_at","ticker","status","primary_scenario","forecast_confidence","scenario_probabilities","forecast_quality","guardrails")
        return jsonify({k:x[k] for k in keys})

    @app.get("/api/institutional-forecast/diagnostics")
    def institutional_forecast_diagnostics(): return jsonify(result())

    @app.get("/api/institutional-forecast/paths")
    def institutional_forecast_paths():
        x=result(); return jsonify({"ok":True,"version":x["version"],"primary_scenario":x["primary_scenario"],"scenario_probabilities":x["scenario_probabilities"],"projected_paths":x["projected_paths"]})

    @app.get("/api/institutional-forecast/bands")
    def institutional_forecast_bands():
        x=result(); return jsonify({"ok":True,"version":x["version"],"price_context":x["price_context"],"uncertainty_bands":x["uncertainty_bands"]})

    @app.get("/api/institutional-forecast/timing")
    def institutional_forecast_timing():
        x=result(); return jsonify({"ok":True,"version":x["version"],"timing_guidance":x["timing_guidance"],"context":x["context"],"guardrails":x["guardrails"]})
