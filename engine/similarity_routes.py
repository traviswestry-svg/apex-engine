"""Read-only historical similarity routes."""
from flask import jsonify, request
from . import feature_store_db
from .historical_similarity import find_similar_to_sample, SIMILARITY_VERSION


def register_similarity_routes(app) -> None:
    if not feature_store_db.is_ready():
        feature_store_db.init_db()

    @app.route('/api/similarity/<sample_id>')
    def _similarity(sample_id):
        try:
            top_k = int(request.args.get('top_k') or 10)
            min_score = float(request.args.get('min_score') or 55)
            return jsonify({"ok": True, "similarity": find_similar_to_sample(
                sample_id, top_k=top_k, min_score=min_score)})
        except Exception as e:
            return jsonify({"ok": True, "similarity": {"available": False,
                "sample_id": sample_id, "version": SIMILARITY_VERSION,
                "reason": f"similarity recovered: {e}", "matches": []}})
