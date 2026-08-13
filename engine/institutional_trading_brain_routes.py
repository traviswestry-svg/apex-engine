"""Read-only routes for APEX 23.0 Institutional Trading Brain."""
from flask import jsonify, request
from .institutional_trading_brain_v230 import build_institutional_trading_brain


def register_institutional_trading_brain_routes(app, last_result_provider):
    def current():
        value = last_result_provider() if callable(last_result_provider) else {}
        return value if isinstance(value, dict) else {}

    def brain():
        return build_institutional_trading_brain(current(), before=request.args.get("before"))

    @app.get("/api/trading-brain/status")
    def trading_brain_status():
        x = brain()
        keys = ("ok", "version", "semantic_version", "schema_version", "evaluated_at", "ticker", "session",
                "decision", "bias", "regime", "base_confidence", "calibrated_confidence", "headline",
                "primary_thesis", "alternate_scenario", "execution_readiness", "evidence_summary",
                "confidence_calibration", "guardrails")
        return jsonify({k: x[k] for k in keys})

    @app.get("/api/trading-brain/diagnostics")
    def trading_brain_diagnostics():
        return jsonify(brain())

    @app.get("/api/trading-brain/thesis")
    def trading_brain_thesis():
        x = brain()
        return jsonify({"ok": True, "version": x["version"], "headline": x["headline"],
                        "primary_thesis": x["primary_thesis"], "alternate_scenario": x["alternate_scenario"],
                        "thesis_timeline": x["thesis_timeline"], "execution_readiness": x["execution_readiness"],
                        "guardrails": x["guardrails"]})

    @app.get("/api/trading-brain/evidence")
    def trading_brain_evidence():
        x = brain()
        return jsonify({"ok": True, "version": x["version"], "evidence": x["evidence"],
                        "supporting_evidence": x["supporting_evidence"], "conflicting_evidence": x["conflicting_evidence"],
                        "evidence_summary": x["evidence_summary"], "explainability": x["explainability"]})

    @app.get("/api/trading-brain/calibration")
    def trading_brain_calibration():
        x = brain()
        return jsonify({"ok": True, "version": x["version"], "confidence_calibration": x["confidence_calibration"],
                        "memory_context": x["memory_context"], "guardrails": x["guardrails"]})
