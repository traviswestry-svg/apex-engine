"""HTTP routes for APEX 25.0 Institutional Decision Integrity."""
from flask import jsonify, request
from . import institutional_decision_integrity_v250 as integrity

REQUIRED_ROUTES = (
    ("GET", "/api/decision-integrity/status"),
    ("GET", "/api/decision-integrity/current"),
    ("GET", "/api/decision-integrity/evidence-health"),
    ("POST", "/api/decision-integrity/evaluate"),
)


def verify_registered(app):
    present = {(method, str(rule)) for rule in app.url_map.iter_rules() for method in (rule.methods or set())}
    return [f"{method} {path}" for method, path in REQUIRED_ROUTES if (method, path) not in present]


def register_institutional_decision_integrity_v250_routes(app, *, last_result_provider=None):
    def current_payload():
        value = last_result_provider() if callable(last_result_provider) else {}
        return value if isinstance(value, dict) else {}

    @app.get("/api/decision-integrity/status")
    def decision_integrity_v250_status():
        return jsonify(integrity.status())

    @app.get("/api/decision-integrity/current")
    def decision_integrity_v250_current():
        return jsonify(integrity.evaluate_decision(current_payload()))

    @app.get("/api/decision-integrity/evidence-health")
    def decision_integrity_v250_evidence_health():
        return jsonify(integrity.evaluate_evidence_health(current_payload()))

    @app.post("/api/decision-integrity/evaluate")
    def decision_integrity_v250_evaluate():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "status": "INVALID_REQUEST", "message": "JSON object required."}), 400
        return jsonify(integrity.evaluate_decision(payload))
