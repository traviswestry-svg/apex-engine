"""Read-only routes for APEX 69.10.30 abstention causality intelligence."""
from __future__ import annotations
from flask import jsonify, request
from .abstention_causality import summary, detail, cluster_detail


def register_abstention_causality_routes(app):
    @app.get('/api/effectiveness/abstention-causality')
    def apex_69_10_30_abstention_causality():
        return jsonify(summary())

    @app.get('/api/effectiveness/abstention-causality/decisions')
    def apex_69_10_30_abstention_causality_decisions():
        try:
            limit = int(request.args.get('limit', '500'))
        except Exception:
            limit = 500
        return jsonify(detail(limit=limit, classification=request.args.get('classification')))

    @app.get('/api/effectiveness/opportunity-clusters')
    def apex_69_10_30_opportunity_clusters():
        try:
            limit = int(request.args.get('limit', '200'))
        except Exception:
            limit = 200
        return jsonify(cluster_detail(limit=limit))
