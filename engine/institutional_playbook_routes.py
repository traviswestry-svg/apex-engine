"""HTTP routes for APEX 23.3 Institutional Playbook Engine."""
from flask import jsonify, request
from .institutional_playbook_engine_v233 import build_institutional_playbooks

def register_institutional_playbook_routes(app, *, last_result_provider, history_provider=None):
    def result():
        last=last_result_provider() if callable(last_result_provider) else {}; history=history_provider() if callable(history_provider) else None
        return build_institutional_playbooks(last or {},history,before=request.args.get('before'))
    @app.get('/api/institutional-playbooks/status')
    def institutional_playbooks_status():
        x=result(); return jsonify({k:x[k] for k in ('ok','version','semantic_version','schema_version','evaluated_at','ticker','status','selected_playbook','execution_readiness','guardrails')})
    @app.get('/api/institutional-playbooks/diagnostics')
    def institutional_playbooks_diagnostics(): return jsonify(result())
    @app.get('/api/institutional-playbooks/rankings')
    def institutional_playbooks_rankings():
        x=result(); return jsonify({'ok':True,'version':x['version'],'selected_playbook':x['selected_playbook'],'ranked_playbooks':x['ranked_playbooks']})
    @app.get('/api/institutional-playbooks/selected')
    def institutional_playbooks_selected():
        x=result(); return jsonify({'ok':True,'version':x['version'],'selected_playbook':x['selected_playbook'],'execution_readiness':x['execution_readiness'],'context':x['context']})
    @app.get('/api/institutional-playbooks/guardrails')
    def institutional_playbooks_guardrails():
        x=result(); return jsonify({'ok':True,'version':x['version'],'guardrails':x['guardrails']})
