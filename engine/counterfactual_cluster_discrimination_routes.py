"""Read-only routes for APEX 69.10.31 counterfactual cluster discrimination."""
from flask import jsonify, request
from .counterfactual_cluster_discrimination import summary, cluster_detail

def register_counterfactual_cluster_discrimination_routes(app):
    @app.get('/api/effectiveness/counterfactual-cluster-discrimination')
    def apex_69_10_31_counterfactual_cluster_discrimination():
        return jsonify(summary())

    @app.get('/api/effectiveness/counterfactual-clusters')
    def apex_69_10_31_counterfactual_clusters():
        try: limit=int(request.args.get('limit','500'))
        except Exception: limit=500
        return jsonify(cluster_detail(limit=limit,classification=request.args.get('classification')))
