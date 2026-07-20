"""HTTP routes for APEX 25.4 Institutional Decision Review & Learning.

Read routes are open like the rest of the 25.x line. The two mutation routes
(approve / reject) are authorized with the repository's shared-secret idiom
(``hmac.compare_digest`` against ``APEX_OPERATOR_TOKEN``), mirroring the existing
webhook-secret gate. No recommendation alters production behavior; approval only
advances the governance workflow and writes the governance audit trail.
"""
import hmac
import os

from flask import jsonify, request

from . import institutional_decision_review_v254 as review

REQUIRED_ROUTES = (
    ("GET", "/api/decision-review/status"),
    ("GET", "/api/decision-review/recent"),
    ("GET", "/api/decision-review/worst"),
    ("GET", "/api/decision-review/best"),
    ("GET", "/api/decision-review/<decision_id>"),
    ("GET", "/api/decision-review/recommendations"),
    ("GET", "/api/decision-review/promotion-queue"),
    ("POST", "/api/decision-review/evaluate"),
    ("POST", "/api/decision-review/recommendations/<recommendation_id>/approve"),
    ("POST", "/api/decision-review/recommendations/<recommendation_id>/reject"),
)


def verify_registered(app):
    present = {(method, str(rule)) for rule in app.url_map.iter_rules() for method in (rule.methods or set())}
    return [f"{method} {path}" for method, path in REQUIRED_ROUTES if (method, path) not in present]


def _authorize():
    """Return (ok, error_response). Shared-secret operator authorization."""
    token = os.getenv("APEX_OPERATOR_TOKEN", "")
    if not token:
        return False, (jsonify({"ok": False, "status": "AUTHZ_NOT_CONFIGURED",
                                "message": "Operator authorization is not configured; "
                                           "set APEX_OPERATOR_TOKEN to enable approvals."}), 503)
    supplied = request.headers.get("X-APEX-Operator-Token", "")
    if not supplied or not hmac.compare_digest(supplied.encode("utf-8"), token.encode("utf-8")):
        return False, (jsonify({"ok": False, "status": "UNAUTHORIZED",
                                "message": "Valid X-APEX-Operator-Token required."}), 403)
    return True, None


def register_institutional_decision_review_v254_routes(app, *, last_result_provider=None):
    def current_payload():
        value = last_result_provider() if callable(last_result_provider) else {}
        return value if isinstance(value, dict) else {}

    @app.get("/api/decision-review/status")
    def decision_review_v254_status():
        return jsonify(review.status())

    @app.get("/api/decision-review/recent")
    def decision_review_v254_recent():
        try:
            limit = min(200, max(1, int(request.args.get("limit", 25))))
        except (TypeError, ValueError):
            limit = 25
        return jsonify(review.recent(limit))

    @app.get("/api/decision-review/best")
    def decision_review_v254_best():
        return jsonify(review.best())

    @app.get("/api/decision-review/worst")
    def decision_review_v254_worst():
        return jsonify(review.worst())

    @app.get("/api/decision-review/recommendations")
    def decision_review_v254_recommendations():
        status = (request.args.get("status") or "").strip() or None
        return jsonify(review.list_recommendations(status=status))

    @app.get("/api/decision-review/promotion-queue")
    def decision_review_v254_promotion_queue():
        return jsonify(review.promotion_queue())

    # Report route (institutional reports) — read-only.
    @app.get("/api/decision-review/report/<kind>")
    def decision_review_v254_report(kind):
        result = review.build_report(kind)
        return jsonify(result), (200 if result.get("ok") else 404)

    # Dynamic single-decision route registered last so it doesn't shadow the
    # static paths above.
    @app.get("/api/decision-review/<decision_id>")
    def decision_review_v254_detail(decision_id):
        result = review.replay(decision_id)
        return jsonify(result), (200 if result.get("ok") else 404)

    @app.post("/api/decision-review/evaluate")
    def decision_review_v254_evaluate():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "status": "INVALID_REQUEST",
                            "message": "JSON object required."}), 400
        realized = payload.get("realized") if isinstance(payload.get("realized"), dict) else None
        snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else payload
        result = review.build_review(snapshot, realized=realized)
        if payload.get("persist"):
            try:
                review.record_decision(lifecycle=result["lifecycle"])
                if realized is not None and result["review"].get("gradeable"):
                    review.persist_review(result["lifecycle"]["decision_id"], result["review"], realized)
                if result["recommendations"]:
                    review.store_recommendations(result["recommendations"])
            except Exception as exc:
                result["persistence_warning"] = str(exc)
        return jsonify(result)

    @app.post("/api/decision-review/recommendations/<recommendation_id>/approve")
    def decision_review_v254_approve(recommendation_id):
        ok, error = _authorize()
        if not ok:
            return error
        body = request.get_json(silent=True) or {}
        actor = str(body.get("actor") or request.headers.get("X-APEX-Operator", "operator"))
        result = review.approve_recommendation(recommendation_id, actor=actor, note=str(body.get("note", "")))
        return jsonify(result), (200 if result.get("ok") else 404)

    @app.post("/api/decision-review/recommendations/<recommendation_id>/reject")
    def decision_review_v254_reject(recommendation_id):
        ok, error = _authorize()
        if not ok:
            return error
        body = request.get_json(silent=True) or {}
        actor = str(body.get("actor") or request.headers.get("X-APEX-Operator", "operator"))
        result = review.reject_recommendation(recommendation_id, actor=actor, note=str(body.get("note", "")))
        return jsonify(result), (200 if result.get("ok") else 404)
