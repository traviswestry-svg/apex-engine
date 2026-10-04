"""Read-only routes for APEX 69.10.33 Open Discovery discrimination."""
from flask import jsonify, request
from .open_discovery_shadow_eligibility import summary, detail

def register_open_discovery_shadow_eligibility_routes(app):
    @app.get('/api/effectiveness/open-discovery-discrimination')
    def apex_69_10_33_open_discovery_discrimination():
        return jsonify(summary())

    @app.get('/api/effectiveness/open-discovery-clusters')
    def apex_69_10_33_open_discovery_clusters():
        try: limit=int(request.args.get('limit','500'))
        except Exception: limit=500
        return jsonify(detail(limit=limit,classification=request.args.get('classification')))
