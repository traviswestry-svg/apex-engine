from __future__ import annotations
from pathlib import Path

from flask import jsonify, render_template, request

from .silent_degradation_observability import VERSION, snapshot


def register_silent_degradation_observability_routes(app):
    @app.route("/api/diagnostics/degradations")
    def api_silent_degradations():
        try:
            limit = int(request.args.get("limit", "100"))
        except Exception:
            limit = 100
        return jsonify(snapshot(limit=limit))

    @app.route("/apex_os/degradations")
    def silent_degradation_dashboard():
        return render_template("silent_degradation_observability.html", version=VERSION)
