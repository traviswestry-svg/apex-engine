"""Read-only routes for APEX 69.10.34 forward shadow validation."""
from flask import jsonify, request
from .open_discovery_forward_validation import summary, detail

def register_open_discovery_forward_validation_routes(app):
    @app.get('/api/effectiveness/open-discovery-forward-validation')
    def apex_69_10_34_forward_validation(): return jsonify(summary())
    @app.get('/api/effectiveness/open-discovery-forward-observations')
    def apex_69_10_34_forward_observations():
        try: limit=int(request.args.get('limit','500'))
        except Exception: limit=500
        return jsonify(detail(limit=limit))
