"""engine/confluence_routes.py — APEX 7.5.3 Confluence API.

register_confluence_routes(app, last_result_provider=...) attaches:

    GET /api/confluence   — long/short setup scorecard synthesized from the
                            already-composed Institutional Intelligence Layer.

Isolated here (mirrors engine/range_routes.py) so app.py stays thin. The engine
consumes the composed Data Bus object and never re-fetches or recomputes. Never
500s the dashboard.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from flask import jsonify

from .confluence import build_confluence


def register_confluence_routes(
    app,
    *,
    last_result_provider: Optional[Callable[[], Dict[str, Any]]] = None,
) -> None:

    @app.route("/api/confluence")
    def _confluence():
        try:
            lr = last_result_provider() if last_result_provider else {}
            return jsonify({"ok": True, "confluence": build_confluence(lr or {})})
        except Exception as e:
            return jsonify({
                "ok": True,
                "confluence": {
                    "available": False,
                    "note": f"confluence route recovered: {e}",
                    "dominant_side": "NEITHER", "conviction": "NONE",
                    "long_setup_score": 0.0, "short_setup_score": 0.0,
                },
            })
