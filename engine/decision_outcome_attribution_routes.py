"""Read-only API surface for APEX 68.6 decision effectiveness."""
from __future__ import annotations
from flask import jsonify, request
from .decision_outcome_attribution import summary, abstention_detail, exit_effectiveness, VERSION


def register_decision_outcome_attribution_routes(app):
    @app.get('/api/effectiveness/attribution')
    def apex_68_6_attribution_summary():
        return jsonify(summary())

    @app.get('/api/effectiveness/abstentions')
    def apex_68_6_abstentions():
        try:
            limit = int(request.args.get('limit', '100'))
        except Exception:
            limit = 100
        return jsonify(abstention_detail(limit=limit))

    @app.get('/api/effectiveness/exits')
    def apex_68_6_exits():
        try:
            limit = int(request.args.get('limit', '500'))
        except Exception:
            limit = 500
        return jsonify(exit_effectiveness(limit=limit))

    @app.get('/api/effectiveness')
    def apex_68_6_effectiveness():
        payload = summary()
        payload['exit_effectiveness'] = exit_effectiveness()
        payload['version'] = VERSION
        return jsonify(payload)
