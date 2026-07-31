"""Routes for APEX 50.5.0 Historical Level Calibration Engine (HLCE).

Thin HTTP surface over ``historical_level_calibration``. The collector is
started here (dormant-safe) using the shared live-result provider so the engine
observes exactly the same snapshot every other engine consumes.
"""
from __future__ import annotations

from flask import jsonify, render_template, request

from .historical_level_calibration import get_service, VERSION


def register_calibration_routes(app, last_result_provider=None):
    service = get_service()

    def _provider():
        if callable(last_result_provider):
            value = last_result_provider()
            return value if isinstance(value, dict) else {}
        return {}

    # Start the background collector once, bound to the live snapshot provider.
    if callable(last_result_provider):
        try:
            service.start(_provider)
        except Exception as exc:  # never block app startup
            print(f"[HLCE] collector start failed (non-fatal): {exc}", flush=True)

    # ---- Spec section 9 endpoints ---------------------------------------- #
    @app.get("/api/level-calibration/status")
    def level_calibration_status():
        return jsonify(service.status())

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
        return jsonify(service.health())

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
