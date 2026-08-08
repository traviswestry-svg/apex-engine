"""Routes for APEX 65.8 Evidence Accumulation Observatory."""
from __future__ import annotations
from .evidence_accumulation_observatory import build_observatory, VERSION


def register_evidence_accumulation_routes(app):
    @app.route("/api/learning/evidence-readiness", methods=["GET"])
    def apex_65_8_evidence_readiness():
        from flask import jsonify, request
        try:
            result = build_observatory(
                symbol=request.args.get("symbol", "SPX"),
                session_date=request.args.get("session_date"),
            )
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify(result), (200 if result.get("ok") else 503)

    @app.route("/api/learning/evidence-readiness/health", methods=["GET"])
    def apex_65_8_evidence_readiness_health():
        from flask import jsonify
        result = build_observatory()
        summary = result.get("summary") or {}
        return jsonify({
            "ok": result.get("ok", False),
            "version": VERSION,
            "state": result.get("state"),
            "accumulating": summary.get("accumulating", []),
            "cold": summary.get("cold", []),
            "errors": summary.get("errors", []),
            "generated_at": result.get("generated_at"),
        }), (200 if result.get("ok") else 503)
