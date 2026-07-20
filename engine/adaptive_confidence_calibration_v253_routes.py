"""HTTP routes for APEX 25.3 Adaptive Confidence Calibration (shadow-mode)."""
from flask import jsonify, request

from . import adaptive_confidence_calibration_v253 as calibration

REQUIRED_ROUTES = (
    ("GET", "/api/confidence-calibration/status"),
    ("GET", "/api/confidence-calibration/current"),
    ("GET", "/api/confidence-calibration/curve"),
    ("GET", "/api/confidence-calibration/buckets"),
    ("GET", "/api/confidence-calibration/drift"),
    ("POST", "/api/confidence-calibration/evaluate"),
)


def verify_registered(app):
    present = {(method, str(rule)) for rule in app.url_map.iter_rules() for method in (rule.methods or set())}
    return [f"{method} {path}" for method, path in REQUIRED_ROUTES if (method, path) not in present]


def register_adaptive_confidence_calibration_v253_routes(app, *, last_result_provider=None):
    def current_payload():
        value = last_result_provider() if callable(last_result_provider) else {}
        return value if isinstance(value, dict) else {}

    @app.get("/api/confidence-calibration/status")
    def confidence_calibration_v253_status():
        return jsonify(calibration.status())

    @app.get("/api/confidence-calibration/current")
    def confidence_calibration_v253_current():
        return jsonify(calibration.build_calibration(current_payload()))

    @app.get("/api/confidence-calibration/curve")
    def confidence_calibration_v253_curve():
        result = calibration.build_calibration(current_payload())
        reliability = result.get("calibration", {}).get("reliability", {})
        return jsonify({
            "ok": True, "version": calibration.VERSION,
            "generated_at": result.get("generated_at"),
            "reliability_curve": reliability.get("buckets", []),
            "brier_score": reliability.get("brier_score"),
            "expected_calibration_error": reliability.get("expected_calibration_error"),
            "max_calibration_error": reliability.get("max_calibration_error"),
            "production_effect": "NONE",
        })

    @app.get("/api/confidence-calibration/buckets")
    def confidence_calibration_v253_buckets():
        result = calibration.build_calibration(current_payload())
        reliability = result.get("calibration", {}).get("reliability", {})
        return jsonify({
            "ok": True, "version": calibration.VERSION,
            "generated_at": result.get("generated_at"),
            "buckets": reliability.get("buckets", []),
            "false_confidence_rate_pct": reliability.get("false_confidence_rate_pct"),
            "underconfidence_rate_pct": reliability.get("underconfidence_rate_pct"),
            "production_effect": "NONE",
        })

    @app.get("/api/confidence-calibration/drift")
    def confidence_calibration_v253_drift():
        result = calibration.build_calibration(current_payload())
        return jsonify({
            "ok": True, "version": calibration.VERSION,
            "generated_at": result.get("generated_at"),
            "drift": result.get("calibration", {}).get("drift", {}),
            "production_effect": "NONE",
        })

    @app.post("/api/confidence-calibration/evaluate")
    def confidence_calibration_v253_evaluate():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "status": "INVALID_REQUEST",
                            "message": "JSON object required."}), 400
        before = payload.get("before") if isinstance(payload.get("before"), str) else None
        return jsonify(calibration.build_calibration(payload, before=before))
