"""APEX 68.8.0 — read/diagnostic + normalized depth-ingestion routes."""
from __future__ import annotations

import os
from flask import jsonify, request

from .market_microstructure import analyze, capability_audit
from .market_microstructure_ingest import ingest, MicrostructureValidationError
from .market_microstructure_store import MicrostructureStore

VERSION = "68.8.0"


def _enabled() -> bool:
    return str(os.getenv("MICROSTRUCTURE_INGEST_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "on"}


def register_market_microstructure_routes(app) -> None:
    def _store() -> MicrostructureStore:
        return MicrostructureStore()

    @app.get("/api/microstructure/capability")
    def market_microstructure_capability():
        return jsonify(capability_audit())

    @app.get("/api/microstructure/health")
    def market_microstructure_health():
        audit = capability_audit()
        store_health = _store().health("ES")
        has_runtime_depth = bool(store_health.get("observations_present"))
        return jsonify({
            "ok": True,
            "status": "READY" if has_runtime_depth else ("WAITING_FOR_DEPTH" if _enabled() else "CONFIG_REQUIRED"),
            "version": VERSION,
            "target_instrument": "ES",
            "configured_depth_provider": audit["current_repository_capabilities"].get("configured_depth_provider"),
            "ingest_enabled": _enabled(),
            "runtime_depth_observed": has_runtime_depth,
            "aggregate_futures_context_available": audit["current_repository_capabilities"]["massive_polygon_futures_aggregate_bars"],
            "store": store_health,
            "execution_authority": False,
            "production_effect": "NONE",
        })

    @app.post("/api/microstructure/analyze")
    def market_microstructure_analyze():
        body = request.get_json(silent=True) or {}
        return jsonify(analyze(body))

    @app.post("/api/microstructure/ingest")
    def market_microstructure_ingest():
        if not _enabled():
            return jsonify({"ok": False, "status": "INGEST_DISABLED", "version": VERSION,
                            "detail": "Set MICROSTRUCTURE_INGEST_ENABLED=true only when a licensed depth bridge is configured."}), 503
        body = request.get_json(silent=True)
        try:
            result = ingest(body, _store())
            return jsonify(result), 201
        except MicrostructureValidationError as exc:
            return jsonify({"ok": False, "status": "REJECTED", "version": VERSION, "error": str(exc)}), 400

    @app.get("/api/microstructure/state")
    def market_microstructure_state():
        instrument = str(request.args.get("instrument") or "ES").upper()
        store = _store()
        latest = store.latest_analysis(instrument)
        cvd = store.rolling_cvd(instrument, limit=min(int(request.args.get("cvd_limit", 600)), 2000))
        return jsonify({
            "ok": True,
            "status": "READY" if latest else "NO_DEPTH_OBSERVED",
            "version": VERSION,
            "instrument": instrument,
            "latest": latest,
            "rolling_cvd": cvd,
            "governance": {"production_effect": "NONE", "influences_decision": False, "execution_authority": False},
        })

    @app.get("/api/microstructure/history")
    def market_microstructure_history():
        instrument = str(request.args.get("instrument") or "ES").upper()
        limit = min(max(int(request.args.get("limit", 120)), 1), 2000)
        rows = _store().history(instrument, limit=limit)
        return jsonify({"ok": True, "version": VERSION, "instrument": instrument, "count": len(rows), "observations": rows})

    @app.get("/api/microstructure/heatmap")
    def market_microstructure_heatmap():
        instrument = str(request.args.get("instrument") or "ES").upper()
        limit = min(max(int(request.args.get("limit", 240)), 1), 2000)
        try:
            persistence = float(request.args.get("min_persistence", 0.05))
        except (TypeError, ValueError):
            persistence = 0.05
        persistence = min(max(persistence, 0.0), 1.0)
        out = _store().heatmap(instrument, limit=limit, min_persistence=persistence)
        out.update({"ok": True, "version": VERSION})
        return jsonify(out)
