"""Read-only API routes for APEX 20.0 Institutional Decision Engine."""
from flask import jsonify
from .institutional_decision_engine_v20 import build_institutional_decision

def register_institutional_decision_engine_routes(app, last_result_provider):
    def cur():
        value = last_result_provider() if callable(last_result_provider) else {}
        return value if isinstance(value, dict) else {}
    @app.get('/api/institutional-decision/status')
    def institutional_decision_status():
        x=build_institutional_decision(cur())
        return jsonify({k:x[k] for k in ('ok','version','semantic_version','evaluated_at','ticker','decision','bias','regime','confidence','headline','execution_eligible','blocking_reasons','evidence_coverage','agreement_score','guardrails')})
    @app.get('/api/institutional-decision/diagnostics')
    def institutional_decision_diagnostics(): return jsonify(build_institutional_decision(cur()))
    @app.get('/api/institutional-decision/scenarios')
    def institutional_decision_scenarios():
        x=build_institutional_decision(cur()); return jsonify({'ok':True,'version':x['version'],'scenarios':x['scenarios'],'bias':x['bias'],'confidence':x['confidence']})
    @app.get('/api/institutional-decision/evidence')
    def institutional_decision_evidence():
        x=build_institutional_decision(cur()); return jsonify({'ok':True,'version':x['version'],'evidence':x['evidence'],'conflicting_sources':x['conflicting_sources'],'agreement_score':x['agreement_score']})
    @app.get('/api/institutional-decision/strategy')
    def institutional_decision_strategy():
        x=build_institutional_decision(cur()); return jsonify({'ok':True,'version':x['version'],'strategy':x['strategy'],'execution_eligible':x['execution_eligible'],'blocking_reasons':x['blocking_reasons'],'guardrails':x['guardrails']})
