"""Routes for APEX 50.5.0 Historical Level Calibration Engine (HLCE).

Thin HTTP surface over ``historical_level_calibration``. Route registration has
no process-lifecycle side effects; the dedicated scanner process owns the collector.
"""
from __future__ import annotations

from flask import jsonify, render_template, request

from .historical_level_calibration import get_service, VERSION
from .operational_runtime import read_scanner_heartbeat
from .scanner_process_supervisor import supervisor_status


def register_calibration_routes(app, last_result_provider=None):
    service = get_service()

    def _provider():
        if callable(last_result_provider):
            value = last_result_provider()
            return value if isinstance(value, dict) else {}
        return {}

    # ---- Spec section 9 endpoints ---------------------------------------- #
    @app.get("/api/level-calibration/status")
    def level_calibration_status():
        payload = service.status()
        hb = read_scanner_heartbeat()
        fresh = bool(hb.get("available")) and float(hb.get("age_seconds") or 1e9) <= 60.0
        payload["collector_owner"] = "scanner_process"
        payload["local_web_collector_running"] = bool(payload.get("collector_running"))
        payload["scanner_heartbeat"] = hb
        # Public status reports the canonical owner, not the intentionally idle
        # Gunicorn-local singleton. Preserve the local value explicitly above.
        payload["collector_running"] = bool(fresh and hb.get("hlce_collector_running"))
        payload["collector_status_source"] = "scanner_heartbeat" if fresh else "scanner_heartbeat_stale_or_missing"
        payload["web_scanner_supervisor"] = supervisor_status()
        return jsonify(payload)

    @app.get("/api/level-calibration/statistics")
    def level_calibration_statistics():
        from .historical_level_calibration import get_statistics
        return jsonify({
            "ok": True,
            "version": VERSION,
            "segment": {
                "key": request.args.get("segment_key", "ALL"),
                "value": request.args.get("segment_value", "ALL"),
            },
            "rows": get_statistics(
                symbol=request.args.get("symbol"),
                level_type=request.args.get("level_type"),
                segment_key=request.args.get("segment_key", "ALL"),
                segment_value=request.args.get("segment_value", "ALL"),
            ),
        })

    @app.get("/api/level-calibration/levels")
    def level_calibration_levels():
        return jsonify(service.levels(
            session_date=request.args.get("session_date"),
            symbol=request.args.get("symbol")))

    @app.get("/api/level-calibration/history")
    def level_calibration_history():
        return jsonify(service.history(
            symbol=request.args.get("symbol"),
            level_type=request.args.get("level_type"),
            limit=request.args.get("limit", 200, type=int)))

    @app.get("/api/level-calibration/replay/<level_id>")
    def level_calibration_replay(level_id):
        from .historical_level_calibration import replay_level
        return jsonify(replay_level(level_id))

    # ---- Operational / integration surface ------------------------------- #
    @app.get("/api/level-calibration/health")
    def level_calibration_health():
        payload = service.health()
        hb = read_scanner_heartbeat()
        fresh = bool(hb.get("available")) and float(hb.get("age_seconds") or 1e9) <= 60.0
        payload["collector_owner"] = "scanner_process"
        payload["local_web_collector_running"] = bool(payload.get("collector_running"))
        payload["collector_running"] = bool(fresh and hb.get("hlce_collector_running"))
        payload["scanner_heartbeat_age_seconds"] = hb.get("age_seconds")
        payload["provider_ok"] = hb.get("hlce_provider_ok") if fresh else None
        payload["provider_error"] = hb.get("hlce_provider_error") if fresh else "SCANNER_HEARTBEAT_STALE_OR_MISSING"
        payload["web_scanner_supervisor"] = supervisor_status()
        return jsonify(payload)


    @app.get("/api/level-calibration/interactions/diagnostics")
    def level_calibration_interaction_diagnostics():
        """Read-only proof of whether zero interactions are legitimate or missed."""
        hb = read_scanner_heartbeat()
        fresh = bool(hb.get("available")) and float(hb.get("age_seconds") or 1e9) <= 60.0
        database = service.status().get("database") or {}
        counts = database.get("counts") or {}
        diagnostics = hb.get("hlce_interaction_diagnostics") if fresh else None
        collector_stats = hb.get("hlce_collector_stats") if fresh else None
        if not isinstance(diagnostics, dict):
            diagnostics = {
                "state": "SCANNER_DIAGNOSTICS_UNAVAILABLE",
                "reason": "SCANNER_HEARTBEAT_STALE_OR_MISSING" if not fresh else "NO_DIAGNOSTICS_YET",
            }
        return jsonify({
            "ok": True,
            "version": "65.9.0_INTERACTION_DETECTION_LIFECYCLE",
            "read_only": True,
            "decision_influence": "NONE",
            "execution_influence": "NONE",
            "scanner_heartbeat_fresh": fresh,
            "collector_running": bool(fresh and hb.get("hlce_collector_running")),
            "collector_stats": collector_stats or {},
            "diagnostics": diagnostics,
            "database_counts": counts,
            "interpretation": (
                "ZERO_INTERACTIONS_EXPLAINED_BY_DISTANCE"
                if counts.get("interactions", 0) == 0
                and diagnostics.get("state") == "NO_QUALIFYING_INTERACTION"
                else "INTERACTIONS_PRESENT_OR_DIAGNOSTICS_PENDING"
            ),
            "probability_policy": "EVIDENCE_ONLY_NO_FABRICATION",
        })


    @app.get("/api/level-calibration/active-levels/diagnostics")
    def level_calibration_active_levels_diagnostics():
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from .canonical_session_context import active_levels as registry_active_levels, latest as latest_context
        target = request.args.get("session_date") or datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        symbol = request.args.get("symbol", "SPX").upper()
        registry = registry_active_levels(symbol, target_session_date=target)
        hlce = service.levels(session_date=target, symbol=symbol)
        ctx = latest_context(symbol, target_session_date=target)
        registry_keys={(str(r.get("kind")), round(float(r.get("price")),4)) for r in registry}
        hlce_keys={(str(r.get("level_type")), round(float(r.get("price")),4)) for r in hlce.get("levels",[]) if r.get("price") is not None}
        hb = read_scanner_heartbeat()
        fresh = bool(hb.get("available")) and float(hb.get("age_seconds") or 1e9) <= 60.0
        publisher = hb.get("live_active_level_publisher") if fresh and isinstance(hb.get("live_active_level_publisher"), dict) else {}
        return jsonify({
            "ok": True,
            "version": "66.1.2_DYNAMIC_LEVEL_IDENTITY",
            "session_date": target,
            "symbol": symbol,
            "canonical_context_present": bool(ctx),
            "canonical_context_generated_at": (ctx or {}).get("generated_at"),
            "canonical_context_source": (ctx or {}).get("source"),
            "registry_active_count": len(registry),
            "hlce_active_count": len(hlce_keys),
            "registry_only": [{"kind":k,"price":p} for k,p in sorted(registry_keys-hlce_keys)],
            "hlce_only": [{"kind":k,"price":p} for k,p in sorted(hlce_keys-registry_keys)],
            "in_sync": registry_keys == hlce_keys,
            "live_publisher": publisher,
            "live_publisher_heartbeat_fresh": fresh,
            "levels": registry,
            "read_only": True,
            "decision_influence": "NONE",
            "execution_influence": "NONE",
        })

    @app.get("/api/level-calibration/dashboard")
    def level_calibration_dashboard_data():
        return jsonify(service.dashboard())

    @app.get("/api/level-calibration/probabilities")
    def level_calibration_probabilities():
        from .historical_level_calibration import calibrated_probabilities
        ctx = {
            "gamma_regime": request.args.get("gamma_regime"),
            "trend_regime": request.args.get("trend_regime"),
            "session_bucket": request.args.get("session_bucket"),
            "expected_move_regime": request.args.get("expected_move_regime"),
        }
        return jsonify(calibrated_probabilities(
            request.args.get("symbol", "SPX"),
            request.args.get("level_type", "put_wall"),
            context=ctx))

    @app.post("/api/level-calibration/tick")
    def level_calibration_tick():
        # Manual observe/grade cycle against the live snapshot (testing / cron).
        return jsonify(service.tick(_provider()))

    @app.post("/api/level-calibration/replay/record")
    def level_calibration_record_replay():
        from .historical_level_calibration import record_trade_replay
        body = request.get_json(silent=True) or {}
        return jsonify(record_trade_replay(
            _provider(),
            trade_result=body.get("trade_result"),
            trade_id=body.get("trade_id")))


    # ---- APEX 50.6.0 Level Transition Probability Engine ---------------- #
    @app.get("/api/level-calibration/transitions/status")
    def level_transition_status():
        from .level_transition_probability import status
        return jsonify(status(path=service.path))

    @app.get("/api/level-calibration/transitions/learning-status")
    def level_transition_learning_status():
        # APEX 50.7.0.1: this operational endpoint must never leak Flask's
        # generic HTML 500 page.  The engine is already schema-aware/fail-safe;
        # this route boundary is the final containment layer.
        try:
            from .level_transition_probability import learning_status
            return jsonify(learning_status(path=service.path))
        except Exception as exc:
            return jsonify({
                "ok": False,
                "status": "DEGRADED",
                "version": "50.7.0.1_LTPE_LEARNING_STATUS_FAILSAFE",
                "state": "COLLECTING",
                "failure_stage": "ROUTE_BOUNDARY",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "probability_policy": "EVIDENCE_ONLY_NO_FABRICATION",
            }), 200

    @app.post("/api/level-calibration/transitions/learn")
    def level_transition_learn():
        # Manual evidence-only catch-up. No provider/network or broker calls.
        try:
            from .level_transition_probability import run_learning_cycle
            return jsonify(run_learning_cycle(path=service.path))
        except Exception as exc:
            return jsonify({
                "ok": False,
                "status": "DEGRADED",
                "version": "50.7.0.1_LTPE_LEARNING_STATUS_FAILSAFE",
                "failure_stage": "LEARNING_CYCLE_ROUTE_BOUNDARY",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "probability_policy": "EVIDENCE_ONLY_NO_FABRICATION",
            }), 200

    @app.get("/api/level-calibration/transitions/statistics")
    def level_transition_statistics_route():
        from .level_transition_probability import transition_statistics
        return jsonify({
            "ok": True,
            "rows": transition_statistics(
                symbol=request.args.get("symbol"),
                source_level_type=request.args.get("source_level_type"),
                source_event=request.args.get("source_event"),
                direction=request.args.get("direction"),
                target_level_type=request.args.get("target_level_type"),
                segment_key=request.args.get("segment_key", "ALL"),
                segment_value=request.args.get("segment_value", "ALL"),
                path=service.path,
            ),
        })

    @app.get("/api/level-calibration/transitions/next")
    def level_transition_next():
        from .level_transition_probability import next_level_probability
        ctx = {
            "gamma_regime": request.args.get("gamma_regime"),
            "auction_regime": request.args.get("auction_regime"),
            "trend_regime": request.args.get("trend_regime"),
            "volatility_regime": request.args.get("volatility_regime"),
            "session_bucket": request.args.get("session_bucket"),
            "expected_move_regime": request.args.get("expected_move_regime"),
        }
        return jsonify(next_level_probability(
            request.args.get("symbol", "SPX"),
            request.args.get("source_level_type", "prev_day_high"),
            request.args.get("source_event", "ACCEPTED"),
            request.args.get("direction", "UP"),
            target_level_type=request.args.get("target_level_type"),
            context=ctx, path=service.path,
        ))

    @app.get("/api/level-calibration/transitions/path")
    def level_transition_path():
        from .level_transition_probability import current_transition_path
        explicit_spot = request.args.get("spot", type=float)
        direction = request.args.get("direction", "UP")
        max_steps = request.args.get("max_steps", 6, type=int)
        try:
            payload = current_transition_path(
                _provider(), path=service.path, direction=direction,
                max_steps=max_steps, spot=explicit_spot,
            )
        except Exception as exc:
            # Last-resort HTTP boundary: read-only LTPE diagnostics must never
            # fall through to Flask's HTML 500 response.
            payload = {
                "ok": False,
                "version": "50.6.2.1_LEVEL_TRANSITION_PROBABILITY",
                "error": "LTPE_PATH_UNHANDLED_FAILURE",
                "failure_stage": "HTTP_BOUNDARY",
                "exception_type": type(exc).__name__,
                "direction": str(direction or "UP").upper(),
                "spot_mode": "UNAVAILABLE",
                "level_universe_mode": "UNAVAILABLE",
                "steps": [],
                "probability_policy": "EVIDENCE_ONLY_NO_FABRICATION",
            }
        return jsonify(payload)

    @app.get("/api/level-calibration/evidence-audit")
    def level_calibration_evidence_audit():
        """Read-only proof of persistent HLCE/LTPE and forecast archive evidence."""
        try:
            from .evidence_audit import evidence_audit
            return jsonify(evidence_audit(calibration_path=service.path))
        except Exception as exc:
            return jsonify({
                "ok": False,
                "status": "DEGRADED",
                "version": "50.7.2_EVIDENCE_AUDIT",
                "read_only": True,
                "failure_stage": "EVIDENCE_AUDIT_ROUTE_BOUNDARY",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "evidence_policy": "EVIDENCE_ONLY_NO_FABRICATION",
            }), 200

    @app.get("/api/level-calibration/transitions/history")
    def level_transition_history():
        from .level_transition_probability import transition_history
        return jsonify(transition_history(
            symbol=request.args.get("symbol"),
            source_level_type=request.args.get("source_level_type"),
            limit=request.args.get("limit", 200, type=int),
            path=service.path,
        ))

    @app.post("/api/level-calibration/transitions/rebuild")
    def level_transition_rebuild():
        from .level_transition_probability import (
            process_transition_outcomes, rebuild_transition_statistics,
        )
        processed = process_transition_outcomes(path=service.path)
        statistics = rebuild_transition_statistics(path=service.path)
        return jsonify({"ok": True, "processed": processed, "statistics": statistics})

    # ---- Dashboard page (spec section 8) --------------------------------- #
    @app.get("/level-calibration")
    def level_calibration_page():
        from engine.version import APPLICATION_VERSION
        try:
            return render_template("historical_calibration.html",
                                   version=APPLICATION_VERSION)
        except Exception:
            # Template optional; JSON dashboard is always available.
            return jsonify(service.dashboard())

    return service
