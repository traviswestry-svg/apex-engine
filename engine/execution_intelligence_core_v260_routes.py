"""HTTP routes for APEX 26.0 Execution Intelligence Core (advisory only).

Every route is read-only advice. None of these place, preview-and-confirm, or
submit an order — real order flow stays on the existing confirmation-gated
`engine/execution/trade_routes` path.
"""
from flask import jsonify, request

from . import execution_intelligence_core_v260 as execution

REQUIRED_ROUTES = (
    ("GET", "/api/execution/status"),
    ("GET", "/api/execution/readiness"),
    ("GET", "/api/execution/plan"),
    ("POST", "/api/execution/evaluate"),
    ("POST", "/api/execution/size"),
    ("POST", "/api/execution/grade"),
)


def verify_registered(app):
    present = {(method, str(rule)) for rule in app.url_map.iter_rules() for method in (rule.methods or set())}
    return [f"{method} {path}" for method, path in REQUIRED_ROUTES if (method, path) not in present]


def register_execution_intelligence_core_v260_routes(app, *, last_result_provider=None):
    def current_payload():
        value = last_result_provider() if callable(last_result_provider) else {}
        return value if isinstance(value, dict) else {}

    @app.get("/api/execution/status")
    def execution_v260_status():
        return jsonify(execution.status())

    @app.get("/api/execution/readiness")
    def execution_v260_readiness():
        payload = current_payload()
        from . import institutional_decision_integrity_v250 as integrity
        decision = integrity.evaluate_decision(payload)
        readiness = execution.assess_readiness(payload, decision)
        return jsonify({"ok": True, "version": execution.VERSION,
                        "generated_at": execution._iso_now(), "readiness": readiness,
                        "places_orders": False, "production_effect": "NONE"})

    @app.get("/api/execution/plan")
    def execution_v260_plan():
        return jsonify(execution.build_execution_plan(current_payload()))

    @app.post("/api/execution/evaluate")
    def execution_v260_evaluate():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "status": "INVALID_REQUEST",
                            "message": "JSON object required."}), 400
        return jsonify(execution.build_execution_plan(payload))

    @app.post("/api/execution/size")
    def execution_v260_size():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "status": "INVALID_REQUEST",
                            "message": "JSON object required."}), 400
        result = execution.size_position(
            payload,
            entry_premium=payload.get("entry_premium"),
            stop_premium=payload.get("stop_premium"),
            confidence=payload.get("confidence"),
        )
        return jsonify({"ok": True, "version": execution.VERSION,
                        "generated_at": execution._iso_now(), "position_sizing": result,
                        "places_orders": False, "production_effect": "NONE"})

    @app.post("/api/execution/grade")
    def execution_v260_grade():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "status": "INVALID_REQUEST",
                            "message": "JSON object required."}), 400
        plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else {}
        fill = payload.get("fill") if isinstance(payload.get("fill"), dict) else {}
        return jsonify(execution.grade_execution(plan, fill))
