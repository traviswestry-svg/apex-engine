"""Read-only provenance and replay-integrity API routes."""
from __future__ import annotations

from flask import jsonify
from . import decision_provenance


def register_provenance_routes(app) -> None:
    @app.route('/api/provenance/<sample_id>')
    def _provenance(sample_id):
        if not decision_provenance.is_ready():
            decision_provenance.init_db()
        row = decision_provenance.get_snapshot(sample_id)
        if not row:
            return jsonify({"ok": False, "error": "snapshot not found"}), 404
        return jsonify({"ok": True, "snapshot": row})
