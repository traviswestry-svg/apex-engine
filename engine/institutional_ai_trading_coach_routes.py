"""HTTP routes for APEX 23.5 Institutional AI Trading Coach."""
from flask import jsonify, request
from .institutional_ai_trading_coach_v235 import behavioral_scorecard, build_trading_coach, record_review


def register_institutional_ai_trading_coach_routes(app, *, last_result_provider, history_provider=None):
    def result(phase="PRE_TRADE"):
        last = last_result_provider() if callable(last_result_provider) else {}
        history = history_provider() if callable(history_provider) else None
        payload = request.get_json(silent=True) or {} if request.method == "POST" else {}
        return build_trading_coach(last or {}, history, phase=phase, trade=payload, before=request.args.get("before"))

    @app.get('/api/trading-coach/status')
    def trading_coach_status():
        x=result(request.args.get('phase','PRE_TRADE')); return jsonify({k:x[k] for k in ('ok','version','semantic_version','schema_version','evaluated_at','ticker','phase','coaching','context','guardrails')})

    @app.get('/api/trading-coach/diagnostics')
    def trading_coach_diagnostics(): return jsonify(result(request.args.get('phase','PRE_TRADE')))

    @app.post('/api/trading-coach/pre-trade')
    def trading_coach_pre_trade(): return jsonify(result('PRE_TRADE'))

    @app.post('/api/trading-coach/active-trade')
    def trading_coach_active_trade(): return jsonify(result('ACTIVE_TRADE'))

    @app.post('/api/trading-coach/post-trade')
    def trading_coach_post_trade(): return jsonify(result('POST_TRADE'))

    @app.post('/api/trading-coach/reviews')
    def trading_coach_reviews(): return jsonify(record_review(request.get_json(silent=True) or {}))

    @app.get('/api/trading-coach/scorecard')
    def trading_coach_scorecard(): return jsonify(behavioral_scorecard(request.args.get('ticker','SPX')))
