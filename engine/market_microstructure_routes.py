"""Read/diagnostic routes for APEX 68.7.0 Market Microstructure Intelligence."""
from __future__ import annotations

from flask import jsonify, request

from .market_microstructure import analyze, capability_audit


def register_market_microstructure_routes(app) -> None:
    @app.get("/api/microstructure/capability")
    def market_microstructure_capability():
        return jsonify(capability_audit())

    @app.get("/api/microstructure/health")
    def market_microstructure_health():
        audit = capability_audit()
        has_depth = bool(audit["current_repository_capabilities"]["resting_l2_depth"])
        return jsonify({
            "ok": True,
            "status": "READY" if has_depth else "FEED_REQUIRED",
            "version": audit["version"],
            "target_instrument": "ES",
            "aggregate_futures_context_available": audit["current_repository_capabilities"]["massive_polygon_futures_aggregate_bars"],
            "l2_depth_available": has_depth,
            "execution_authority": False,
            "production_effect": "NONE",
        })

    @app.post("/api/microstructure/analyze")
    def market_microstructure_analyze():
        body = request.get_json(silent=True) or {}
        return jsonify(analyze(body))
