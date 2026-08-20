"""Routes for APEX 67.9.0 Post-Persistence Architecture Audit."""
from __future__ import annotations
from flask import jsonify, render_template
from .post_persistence_architecture_audit import VERSION, snapshot


def register_post_persistence_architecture_audit_routes(app):
    @app.route("/api/post-persistence-architecture-audit")
    def api_post_persistence_architecture_audit():
        return jsonify(snapshot())

    @app.route("/apex_os/post-persistence-architecture-audit")
    def post_persistence_architecture_audit_dashboard():
        return render_template("post_persistence_architecture_audit.html", version=VERSION)
