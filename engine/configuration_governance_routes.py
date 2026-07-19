"""Read-only Flask routes for APEX configuration governance."""
from __future__ import annotations
from flask import jsonify
from .configuration_governance import categories, diagnostics, execution_safety, status

def register_configuration_governance_routes(app):
    @app.get('/api/configuration/status')
    def configuration_status(): return jsonify(status())
    @app.get('/api/configuration/diagnostics')
    def configuration_diagnostics(): return jsonify(diagnostics())
    @app.get('/api/configuration/categories')
    def configuration_categories(): return jsonify(categories())
    @app.get('/api/configuration/execution-safety')
    def configuration_execution_safety(): return jsonify(execution_safety())
