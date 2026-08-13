"""HTTP routes for APEX 23.1 Institutional Regime Intelligence."""
from __future__ import annotations
from flask import jsonify, request
from .institutional_regime_intelligence_v231 import build_regime_intelligence


def register_institutional_regime_intelligence_routes(app, *, last_result_provider, history_provider=None):
    def result():
        last = last_result_provider() if callable(last_result_provider) else {}
        history = history_provider() if callable(history_provider) else None
        return build_regime_intelligence(last or {}, history, before=request.args.get("before"))

    @app.get("/api/regime-intelligence/status")
    def regime_intelligence_status():
        x = result(); keys = ("ok", "version", "semantic_version", "schema_version", "evaluated_at", "ticker", "primary_regime", "secondary_regime", "confidence", "transition", "risk_posture", "guardrails")
        return jsonify({k: x[k] for k in keys})

    @app.get("/api/regime-intelligence/diagnostics")
    def regime_intelligence_diagnostics(): return jsonify(result())

    @app.get("/api/regime-intelligence/scores")
    def regime_intelligence_scores():
        x=result(); return jsonify({"ok":True,"version":x["version"],"scores":x["scores"],"features":x["features"],"explainability":x["explainability"]})

    @app.get("/api/regime-intelligence/transition")
    def regime_intelligence_transition():
        x=result(); return jsonify({"ok":True,"version":x["version"],"primary_regime":x["primary_regime"],"confidence":x["confidence"],"transition":x["transition"],"risk_posture":x["risk_posture"]})

    @app.get("/api/regime-intelligence/guidance")
    def regime_intelligence_guidance():
        x=result(); return jsonify({"ok":True,"version":x["version"],"engine_weight_guidance":x["engine_weight_guidance"],"playbook_guidance":x["playbook_guidance"],"guardrails":x["guardrails"]})
