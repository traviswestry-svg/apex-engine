"""engine/probability_distribution_routes.py — APEX 11.0C Module 3 routes."""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from flask import jsonify

from engine.probability_distribution import (PROBABILITY_DISTRIBUTION_VERSION,
                                            build_probability_distribution)


def register_probability_distribution_routes(
    app,
    *,
    last_result_provider: Optional[Callable[[], Dict[str, Any]]] = None,
) -> None:

    @app.route("/api/probability_distribution", methods=["GET"])
    def _probability_distribution():
        try:
            bus = last_result_provider() if last_result_provider else None
            payload = build_probability_distribution(bus)
            return jsonify(payload), (200 if payload.get("available") else 503)
        except Exception as e:  # pragma: no cover
            return jsonify({"available": False, "ok": True, "degraded": True,
                            "version": PROBABILITY_DISTRIBUTION_VERSION,
                            "error": str(e)}), 503

    @app.route("/api/probability_distribution/health", methods=["GET"])
    def _probability_distribution_health():
        return jsonify({"ok": True, "version": PROBABILITY_DISTRIBUTION_VERSION}), 200
