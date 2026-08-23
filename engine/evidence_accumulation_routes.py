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

    @app.route("/api/learning/evidence-lifecycle", methods=["GET"])
    def apex_69_historical_evidence_lifecycle():
        """Unified proof of capture -> persistence -> grading -> learning readiness."""
        from flask import jsonify
        from .historical_evidence_lifecycle import runtime_status
        from . import feature_store_db, flow_pl_store
        from .market_memory_engine_v220 import status as market_memory_status
        payload = runtime_status()
        # APEX 69.0.1 — scanner is the authoritative runtime owner. Gunicorn
        # reads the durable DB correctly, but its in-memory counters are local
        # to the web process and can misleadingly remain zero. Prefer the fresh
        # scanner heartbeat while preserving web-local counters for diagnosis.
        from .operational_runtime import read_scanner_heartbeat
        hb = read_scanner_heartbeat()
        hb_fresh = bool(hb.get("available")) and float(hb.get("age_seconds") or 1e9) <= 60.0
        scanner_lifecycle = hb.get("historical_evidence_lifecycle") if hb_fresh else None
        web_local_runtime = dict(payload.get("runtime") or {})
        if isinstance(scanner_lifecycle, dict) and isinstance(scanner_lifecycle.get("runtime"), dict):
            payload["runtime"] = dict(scanner_lifecycle["runtime"])
            payload["runtime_source"] = "SCANNER_HEARTBEAT"
        else:
            payload["runtime_source"] = "WEB_PROCESS_LOCAL_FALLBACK"
        payload["web_local_runtime"] = web_local_runtime
        payload["scanner_heartbeat"] = {
            "available": bool(hb.get("available")),
            "fresh": hb_fresh,
            "age_seconds": hb.get("age_seconds"),
            "updated_at": hb.get("updated_at"),
            "pid": hb.get("pid"),
        }
        try:
            fs = feature_store_db.health()
        except Exception as exc:
            fs = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        try:
            mm = market_memory_status()
        except Exception as exc:
            mm = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        r = payload.get("readiness") or {}
        try:
            flow_linkage = flow_pl_store.sample_excursion_health()
        except Exception as exc:
            flow_linkage = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        payload["families"] = {
            "decisions": {
                "captured": r.get("decisions_recorded", 0),
                "persisted": r.get("decisions_recorded", 0),
                "pending": r.get("pending_decisions", 0),
                "graded": r.get("graded_outcomes", 0),
                "excluded": r.get("excluded_outcomes", 0),
                "price_samples": r.get("price_samples", 0),
                "state": r.get("status"),
            },
            "flow_features": {
                "captured": fs.get("feature_rows", 0),
                "persisted": fs.get("feature_rows", 0),
                "graded": fs.get("label_rows", 0),
                "unlabelled": fs.get("unlabelled", 0),
                "sessions": fs.get("feature_sessions", fs.get("sessions_covered", 0)),
                "state": "ACCUMULATING" if fs.get("feature_rows", 0) else "COLD",
                "settlement": (hb.get("feature_label_settlement") if hb_fresh else None) or {
                    "state": "SCANNER_SETTLEMENT_DIAGNOSTICS_UNAVAILABLE",
                    "reason": "SCANNER_HEARTBEAT_STALE_OR_NO_SETTLEMENT_ATTEMPT",
                },
                "excursion_linkage": flow_linkage,
            },
            "market_memory": {
                "captured": mm.get("sessions", 0),
                "graded": mm.get("graded_sessions", 0),
                "learning_ready": mm.get("learning_ready", False),
                "state": mm.get("state"),
            },
        }
        payload["guardrails"].update({
            "read_only_endpoint": True,
            "automatic_recalibration": False,
            "human_promotion_required": True,
            "runtime_telemetry_authority": "SCANNER_HEARTBEAT_WHEN_FRESH",
        })
        return jsonify(payload), (200 if payload.get("ok") else 503)

