"""Routes for APEX 22.0 Market Memory Engine."""
from flask import jsonify, request
from .market_memory_engine_v220 import capture_snapshot, diagnostics, find_similar, list_sessions, status


def register_market_memory_routes(app, last_result_provider):
    def current():
        value = last_result_provider() if callable(last_result_provider) else {}
        return value if isinstance(value, dict) else {}

    @app.get('/api/market-memory/status')
    def market_memory_status():
        return jsonify(status())

    @app.get('/api/market-memory/diagnostics')
    def market_memory_diagnostics():
        return jsonify(diagnostics())

    @app.get('/api/market-memory/sessions')
    def market_memory_sessions():
        return jsonify(list_sessions(limit=request.args.get('limit', 50, type=int)))

    @app.get('/api/market-memory/similar')
    def market_memory_similar():
        return jsonify(find_similar(current(), limit=request.args.get('limit', 10, type=int),
                                    min_score=request.args.get('min_score', 55.0, type=float),
                                    before=request.args.get('before')))

    @app.post('/api/market-memory/capture')
    def market_memory_capture():
        return jsonify(capture_snapshot(current()))
