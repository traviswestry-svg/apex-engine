"""Flask routes for APEX 11.0E Recommendation Ledger."""
from __future__ import annotations

from flask import jsonify, request

from . import recommendation_ledger as ledger

VERSION = ledger.VERSION


def register_recommendation_ledger_routes(app, **_kwargs) -> None:
    ledger.init_db()

    @app.get("/api/recommendation-ledger")
    @app.get("/api/recommendation-ledger/recommendations")
    def _ledger_list():
        rows = ledger.list_recommendations(
            limit=request.args.get("limit", 100, type=int),
            session_date=request.args.get("session_date"), strategy=request.args.get("strategy"),
            state=request.args.get("state"), unresolved_only=request.args.get("unresolved", "false").lower() == "true")
        return jsonify({"ok": True, "version": VERSION, "count": len(rows), "recommendations": rows})

    @app.get("/api/recommendation-ledger/latest")
    def _ledger_latest():
        rows = ledger.list_recommendations(limit=1)
        return jsonify({"ok": True, "version": VERSION, "recommendation": rows[0] if rows else None})

    @app.get("/api/recommendation-ledger/recommendations/<recommendation_id>")
    def _ledger_get(recommendation_id: str):
        row = ledger.get_recommendation(recommendation_id)
        if row is None:
            return jsonify({"ok": False, "error": "not_found"}), 404
        return jsonify({"ok": True, "version": VERSION, "recommendation": row})

    @app.get("/api/recommendation-ledger/counts")
    def _ledger_counts():
        return jsonify({"ok": True, "version": VERSION, **ledger.counts()})

    @app.get("/api/recommendation-ledger/coverage")
    def _ledger_coverage():
        return jsonify({"ok": True, "version": VERSION, **ledger.coverage()})

    @app.get("/api/recommendation-ledger/health")
    def _ledger_health():
        payload = ledger.health()
        return jsonify({"ok": payload.get("status") != "FAIL", "version": VERSION, **payload}), (503 if payload.get("status") == "FAIL" else 200)

    @app.get("/api/recommendation-ledger/unresolved")
    @app.get("/api/recommendation-ledger/pending-grades")
    def _ledger_unresolved():
        rows = ledger.list_recommendations(limit=request.args.get("limit", 200, type=int), unresolved_only=True)
        return jsonify({"ok": True, "version": VERSION, "count": len(rows), "recommendations": rows})

    @app.post("/api/recommendation-ledger/record")
    def _ledger_record():
        body = request.get_json(silent=True) or {}
        if "panel" not in body:
            return jsonify({"ok": False, "error": "panel_required"}), 400
        capture = ledger.build_capture(ticker=(body.get("ticker") or "SPX"), panel=body["panel"],
                                       last_result=body.get("last_result") or {}, session_date=body.get("session_date"),
                                       spot=body.get("spot"), application_version=body.get("application_version"))
        result = ledger.record_recommendation(capture)
        return jsonify({"ok": True, "version": VERSION, **result}), (201 if result["created"] else 200)

    def _event(recommendation_id: str, event_type: str):
        try:
            result = ledger.append_event(recommendation_id, event_type, request.get_json(silent=True) or {})
            return jsonify({"ok": True, "version": VERSION, **result})
        except KeyError:
            return jsonify({"ok": False, "error": "not_found"}), 404
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.post("/api/recommendation-ledger/<recommendation_id>/activate")
    def _activate(recommendation_id: str): return _event(recommendation_id, "ACTIVATED")

    @app.post("/api/recommendation-ledger/<recommendation_id>/quote-snapshot")
    def _quote(recommendation_id: str): return _event(recommendation_id, "QUOTE_SNAPSHOT")

    @app.post("/api/recommendation-ledger/<recommendation_id>/fill")
    def _fill(recommendation_id: str): return _event(recommendation_id, "FILL")

    @app.post("/api/recommendation-ledger/<recommendation_id>/close")
    def _close(recommendation_id: str): return _event(recommendation_id, "CLOSED")

    @app.post("/api/recommendation-ledger/<recommendation_id>/settle")
    def _settle(recommendation_id: str): return _event(recommendation_id, "SETTLED")

    @app.post("/api/recommendation-ledger/<recommendation_id>/invalidate")
    def _invalidate(recommendation_id: str): return _event(recommendation_id, "INVALIDATED")

    @app.get("/api/recommendation-ledger/<recommendation_id>/timeline")
    def _timeline(recommendation_id: str):
        row = ledger.get_recommendation(recommendation_id)
        if row is None:
            return jsonify({"ok": False, "error": "not_found"}), 404
        return jsonify({"ok": True, "version": VERSION, "recommendation_id": recommendation_id, "events": row["events"]})

    @app.post("/api/recommendation-ledger/grade-due")
    def _grade_due():
        # Honest gate: automatic executable-P/L grading is enabled only after quote/fill
        # lifecycle data exists. This endpoint reports work pending; it never infers P/L
        # from underlying direction.
        pending = ledger.list_recommendations(limit=500, unresolved_only=True)
        return jsonify({"ok": True, "version": VERSION, "graded": 0, "pending": len(pending),
                        "status": "AWAITING_EXECUTABLE_OUTCOMES",
                        "note": "No directional proxy grading. Record close/settlement economics first."})

    @app.get("/api/calibration/readiness")
    def _calibration_readiness():
        minimum = request.args.get("minimum", 50, type=int)
        return jsonify({"ok": True, "version": VERSION, **ledger.calibration_readiness(max(1, minimum))})
