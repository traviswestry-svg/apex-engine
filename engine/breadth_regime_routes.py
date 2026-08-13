"""HTTP surface for the APEX Breadth Exhaustion & Recovery Engine."""
from __future__ import annotations

from flask import jsonify

from .breadth_regime import build_breadth_regime


def register_breadth_regime_routes(app, *, last_result_provider):
    def result():
        context = last_result_provider() if callable(last_result_provider) else {}
        cached = context.get("breadth_regime") if isinstance(context, dict) else None
        return cached if isinstance(cached, dict) else build_breadth_regime(context or {})

    @app.get("/api/breadth-regime/status")
    def breadth_regime_status():
        return jsonify(result())

    @app.get("/api/breadth-regime/diagnostics")
    def breadth_regime_diagnostics():
        return jsonify(result())

