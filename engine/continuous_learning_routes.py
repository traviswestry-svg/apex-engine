"""HTTP routes for APEX 23.4 Continuous Learning & Confidence Calibration."""
from flask import jsonify, request
from .continuous_learning_calibration_v234 import build_continuous_learning, record_outcome

def register_continuous_learning_routes(app, *, last_result_provider, history_provider=None):
    def result():
        last=last_result_provider() if callable(last_result_provider) else {}; history=history_provider() if callable(history_provider) else None
        return build_continuous_learning(last or {},history,before=request.args.get('before'))
    @app.get('/api/continuous-learning/status')
    def continuous_learning_status():
        x=result(); return jsonify({k:x[k] for k in ('ok','version','semantic_version','schema_version','evaluated_at','ticker','status','calibration','confidence','drift','guardrails')})
    @app.get('/api/continuous-learning/diagnostics')
    def continuous_learning_diagnostics(): return jsonify(result())
    @app.get('/api/continuous-learning/calibration')
    def continuous_learning_calibration():
        x=result(); return jsonify({'ok':True,'version':x['version'],'calibration':x['calibration'],'confidence':x['confidence']})
    @app.get('/api/continuous-learning/performance')
    def continuous_learning_performance():
        x=result(); return jsonify({'ok':True,'version':x['version'],'performance':x['performance'],'drift':x['drift']})
    @app.get('/api/continuous-learning/recommendations')
    def continuous_learning_recommendations():
        x=result(); return jsonify({'ok':True,'version':x['version'],'recommendations':x['recommendations'],'guardrails':x['guardrails']})
    @app.post('/api/continuous-learning/outcomes')
    def continuous_learning_outcomes():
        return jsonify(record_outcome(request.get_json(silent=True) or {}))
