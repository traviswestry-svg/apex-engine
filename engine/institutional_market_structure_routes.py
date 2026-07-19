"""Read-only APEX 19.1 Institutional Market Structure routes."""
from flask import jsonify
from .institutional_market_structure_engine import VERSION, build_institutional_market_structure

def register_institutional_market_structure_routes(app, *, last_result_provider):
    def current():
        value=last_result_provider() or {}
        return value if isinstance(value,dict) else {}
    @app.get('/api/institutional-market-structure/status')
    def ims_status():
        p=build_institutional_market_structure(current())
        return jsonify({k:p[k] for k in ('ok','version','evaluated_at','ticker','state','direction','warnings','day_type_probability','guardrails')})
    @app.get('/api/institutional-market-structure/diagnostics')
    def ims_diagnostics(): return jsonify(build_institutional_market_structure(current()))
    @app.get('/api/institutional-market-structure/profiles')
    def ims_profiles():
        p=build_institutional_market_structure(current()); return jsonify({'ok':True,'version':VERSION,**p['multi_timeframe_profiles']})
    @app.get('/api/institutional-market-structure/levels')
    def ims_levels():
        p=build_institutional_market_structure(current()); return jsonify({'ok':True,'version':VERSION,**p['structure_levels']})
    @app.get('/api/institutional-market-structure/auction')
    def ims_auction():
        p=build_institutional_market_structure(current()); return jsonify({'ok':True,'version':VERSION,'opening_type':p['opening_type'],'auction_defects':p['auction_defects'],'acceptance_rejection':p['acceptance_rejection'],'poc_value_migration':p['poc_value_migration']})
