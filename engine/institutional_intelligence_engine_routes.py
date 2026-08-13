"""Read-only routes for APEX 19.0 Institutional Intelligence Engine."""
from flask import jsonify
from .institutional_intelligence_engine import build_institutional_intelligence_v19, VERSION

def register_institutional_intelligence_engine_routes(app, *, last_result_provider):
    def current():
        value = last_result_provider() or {}
        return value if isinstance(value, dict) else {}
    @app.get('/api/institutional-intelligence-engine/status')
    def status():
        payload = build_institutional_intelligence_v19(current())
        return jsonify({k: payload[k] for k in ('ok','version','evaluated_at','ticker','bias','conviction','coverage_pct','scenario','execution_eligible','quality_flags','guardrails')})
    @app.get('/api/institutional-intelligence-engine/diagnostics')
    def diagnostics(): return jsonify(build_institutional_intelligence_v19(current()))
    @app.get('/api/institutional-intelligence-engine/volume-transition')
    def volume_transition(): return jsonify({'ok': True, 'version': VERSION, **build_institutional_intelligence_v19(current())['volume_transition']})
    @app.get('/api/institutional-intelligence-engine/expected-move')
    def expected_move(): return jsonify({'ok': True, 'version': VERSION, **build_institutional_intelligence_v19(current())['expected_move']})
