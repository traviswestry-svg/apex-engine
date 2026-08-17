from __future__ import annotations
from flask import jsonify, render_template
from .architecture_integrity import VERSION, snapshot

def register_architecture_integrity_routes(app):
    @app.route("/api/architecture-integrity")
    def api_architecture_integrity():
        return jsonify(snapshot())

    @app.route("/apex_os/architecture-integrity")
    def architecture_integrity_dashboard():
        return render_template("architecture_integrity.html", version=VERSION)
