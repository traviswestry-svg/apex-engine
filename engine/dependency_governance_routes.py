"""Read-only Flask routes for APEX 18.0.5 dependency governance."""
from flask import jsonify
from .dependency_governance import diagnostics, inventory, status

def register_dependency_governance_routes(app):
    @app.get('/api/dependencies/status')
    def dependency_status(): return jsonify(status())
    @app.get('/api/dependencies/diagnostics')
    def dependency_diagnostics(): return jsonify(diagnostics())
    @app.get('/api/dependencies/inventory')
    def dependency_inventory(): return jsonify(inventory())
