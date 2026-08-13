"""HTTP routes for APEX 25.1 Institutional Reasoning."""
from flask import jsonify, request
from . import institutional_reasoning_v251 as reasoning

REQUIRED_ROUTES = (
    ("GET", "/api/institutional-reasoning/status"),
    ("GET", "/api/institutional-reasoning/current"),
    ("GET", "/api/institutional-reasoning/evidence-ranking"),
    ("POST", "/api/institutional-reasoning/evaluate"),
)


def verify_registered(app):
    present = {(method, str(rule)) for rule in app.url_map.iter_rules() for method in (rule.methods or set())}
    return [f"{method} {path}" for method, path in REQUIRED_ROUTES if (method, path) not in present]


def register_institutional_reasoning_v251_routes(app, *, last_result_provider=None):
    def current_payload():
        value = last_result_provider() if callable(last_result_provider) else {}
        return value if isinstance(value, dict) else {}

    @app.get("/api/institutional-reasoning/status")
    def institutional_reasoning_v251_status():
        return jsonify(reasoning.status())

    @app.get("/api/institutional-reasoning/current")
    def institutional_reasoning_v251_current():
        return jsonify(reasoning.build_reasoning(current_payload()))

    @app.get("/api/institutional-reasoning/evidence-ranking")
    def institutional_reasoning_v251_evidence_ranking():
        payload = current_payload()
        return jsonify({"ok": True, "version": reasoning.VERSION, "evidence_rankings": reasoning.rank_evidence(payload)})

    @app.post("/api/institutional-reasoning/evaluate")
    def institutional_reasoning_v251_evaluate():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "status": "INVALID_REQUEST", "message": "JSON object required."}), 400
        return jsonify(reasoning.build_reasoning(payload))
