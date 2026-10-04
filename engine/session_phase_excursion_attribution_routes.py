"""Read-only routes for APEX 69.10.32 canonical excursion/session-phase attribution."""
from flask import jsonify, request
from .session_phase_excursion_attribution import summary, excursion_detail

def register_session_phase_excursion_attribution_routes(app):
    @app.get('/api/effectiveness/canonical-excursion-session-phase')
    def apex_69_10_32_canonical_excursion_session_phase():
        return jsonify(summary())

    @app.get('/api/effectiveness/canonical-excursions')
    def apex_69_10_32_canonical_excursions():
        try: limit=int(request.args.get('limit','500'))
        except Exception: limit=500
        return jsonify(excursion_detail(limit=limit))
