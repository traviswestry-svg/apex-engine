"""HTTP routes for APEX 25.5 Institutional Validation & Promotion Gate.

Read routes are open. Promotion transitions (propose/review/approve/promote/
rollback) are authorized with the repository's shared-secret idiom
(``hmac.compare_digest`` against ``APEX_OPERATOR_TOKEN``, header
``X-APEX-Operator-Token``) — the same gate used by 25.4. Recording a promotion
state never flips an engine's behavior; the shadow engines keep their own
production flags.
"""
import hmac
import os

from flask import jsonify, request

from . import institutional_validation_promotion_v255 as validation

REQUIRED_ROUTES = (
    ("GET", "/api/validation/status"),
    ("GET", "/api/validation/current"),
    ("GET", "/api/validation/supervisor"),
    ("GET", "/api/validation/dashboard"),
    ("GET", "/api/validation/promotion"),
    ("GET", "/api/validation/lifecycle/<decision_id>"),
    ("GET", "/api/validation/replay-verify/<decision_id>"),
    ("GET", "/api/validation/report/<kind>"),
    ("POST", "/api/validation/evaluate"),
    ("POST", "/api/validation/promotion/<engine>/propose"),
    ("POST", "/api/validation/promotion/<engine>/approve"),
    ("POST", "/api/validation/promotion/<engine>/rollback"),
)


def verify_registered(app):
    present = {(method, str(rule)) for rule in app.url_map.iter_rules() for method in (rule.methods or set())}
    return [f"{method} {path}" for method, path in REQUIRED_ROUTES if (method, path) not in present]


def _authorize():
    token = os.getenv("APEX_OPERATOR_TOKEN", "")
    if not token:
        return False, (jsonify({"ok": False, "status": "AUTHZ_NOT_CONFIGURED",
                                "message": "Set APEX_OPERATOR_TOKEN to enable promotion transitions."}), 503)
    supplied = request.headers.get("X-APEX-Operator-Token", "")
    if not supplied or not hmac.compare_digest(supplied.encode("utf-8"), token.encode("utf-8")):
        return False, (jsonify({"ok": False, "status": "UNAUTHORIZED",
                                "message": "Valid X-APEX-Operator-Token required."}), 403)
    return True, None


def register_institutional_validation_promotion_v255_routes(app, *, last_result_provider=None):
    def current_payload():
        value = last_result_provider() if callable(last_result_provider) else {}
        return value if isinstance(value, dict) else {}

    @app.get("/api/validation/status")
    def validation_v255_status():
        return jsonify(validation.status())

    @app.get("/api/validation/current")
    def validation_v255_current():
        return jsonify(validation.build_validation(current_payload()))

    @app.get("/api/validation/supervisor")
    def validation_v255_supervisor():
        return jsonify(validation.supervise(current_payload()))

    @app.get("/api/validation/dashboard")
    def validation_v255_dashboard():
        return jsonify(validation.dashboard(current_payload()))

    @app.get("/api/validation/promotion")
    def validation_v255_promotion():
        return jsonify(validation.promotion_overview(current_payload()))

    @app.get("/api/validation/lifecycle/<decision_id>")
    def validation_v255_lifecycle(decision_id):
        return jsonify(validation.validate_lifecycle(current_payload(), decision_id=decision_id))

    @app.get("/api/validation/replay-verify/<decision_id>")
    def validation_v255_replay_verify(decision_id):
        result = validation.verify_replay(decision_id)
        return jsonify(result), (200 if result.get("ok") else 404)

    @app.get("/api/validation/report/<kind>")
    def validation_v255_report(kind):
        result = validation.build_report(kind, current_payload())
        return jsonify(result), (200 if result.get("ok") else 404)

    @app.post("/api/validation/evaluate")
    def validation_v255_evaluate():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "status": "INVALID_REQUEST",
                            "message": "JSON object required."}), 400
        realized = payload.get("realized") if isinstance(payload.get("realized"), dict) else None
        snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else payload
        return jsonify({
            "ok": True, "version": validation.VERSION, "generated_at": validation._iso_now(),
            "lifecycle_validation": validation.validate_lifecycle(snapshot, realized=realized),
            "supervisor": validation.supervise(snapshot),
            "dashboard": validation.dashboard(snapshot),
            "production_effect": "NONE",
        })

    def _promotion_action(engine, action):
        ok, error = _authorize()
        if not ok:
            return error
        body = request.get_json(silent=True) or {}
        actor = str(body.get("actor") or request.headers.get("X-APEX-Operator", "operator"))
        note = str(body.get("note", ""))
        payload = current_payload()
        if action == "propose":
            result = validation.propose_promotion(engine, actor=actor, payload=payload, note=note)
        elif action == "review":
            result = validation.review_promotion(engine, actor=actor, note=note)
        elif action == "approve":
            result = validation.approve_promotion(engine, actor=actor, payload=payload, note=note)
        elif action == "promote":
            result = validation.promote_to_production(engine, actor=actor, payload=payload, note=note)
        elif action == "rollback":
            result = validation.rollback_promotion(engine, actor=actor, note=note)
        else:
            return jsonify({"ok": False, "status": "UNKNOWN_ACTION"}), 400
        return jsonify(result), (200 if result.get("ok") else 409)

    @app.post("/api/validation/promotion/<engine>/propose")
    def validation_v255_promo_propose(engine):
        return _promotion_action(engine, "propose")

    @app.post("/api/validation/promotion/<engine>/review")
    def validation_v255_promo_review(engine):
        return _promotion_action(engine, "review")

    @app.post("/api/validation/promotion/<engine>/approve")
    def validation_v255_promo_approve(engine):
        return _promotion_action(engine, "approve")

    @app.post("/api/validation/promotion/<engine>/promote")
    def validation_v255_promo_promote(engine):
        return _promotion_action(engine, "promote")

    @app.post("/api/validation/promotion/<engine>/rollback")
    def validation_v255_promo_rollback(engine):
        return _promotion_action(engine, "rollback")
