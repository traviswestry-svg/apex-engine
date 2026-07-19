"""HTTP routes for APEX 24.0 Institutional Execution Intelligence."""
from flask import jsonify, request
from .institutional_execution_intelligence_v240 import build_execution_intelligence, create_lifecycle, journal, replay_lifecycle, transition_lifecycle


def register_institutional_execution_intelligence_routes(app, *, last_result_provider):
    def last():
        value = last_result_provider() if callable(last_result_provider) else {}
        return value if isinstance(value, dict) else {}

    @app.get('/api/execution-intelligence/status')
    def execution_intelligence_status(): return jsonify(build_execution_intelligence(last()))

    @app.get('/api/execution-intelligence/diagnostics')
    def execution_intelligence_diagnostics(): return jsonify(build_execution_intelligence(last(), request.args))

    @app.post('/api/execution-intelligence/score')
    def execution_intelligence_score(): return jsonify(build_execution_intelligence(last(), request.get_json(silent=True) or {}))

    @app.post('/api/execution-intelligence/lifecycles')
    def execution_intelligence_create(): return jsonify(create_lifecycle(last(), request.get_json(silent=True) or {}))

    @app.post('/api/execution-intelligence/lifecycles/<lifecycle_id>/transition')
    def execution_intelligence_transition(lifecycle_id): return jsonify(transition_lifecycle(lifecycle_id, request.get_json(silent=True) or {}))

    @app.get('/api/execution-intelligence/lifecycles/<lifecycle_id>/replay')
    def execution_intelligence_replay(lifecycle_id): return jsonify(replay_lifecycle(lifecycle_id))

    @app.get('/api/execution-intelligence/journal')
    def execution_intelligence_journal(): return jsonify(journal(request.args.get('ticker','SPX'), request.args.get('limit',50)))
