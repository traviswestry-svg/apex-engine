"""Read-only APEX 19.2-19.5 routes."""
from flask import jsonify
from .institutional_dealer_positioning_engine import build_dealer_positioning
from .institutional_options_flow_engine import build_options_flow_intelligence
from .institutional_probability_engine import build_probability_engine
from .adaptive_learning_engine_v2 import build_adaptive_learning_v2
from .institutional_market_structure_engine import build_institutional_market_structure

def register_institutional_intelligence_suite_routes(app, *, last_result_provider):
    def cur():
        x=last_result_provider() or {}; return x if isinstance(x,dict) else {}
    @app.get('/api/dealer-positioning/status')
    def dealer_status(): return jsonify(build_dealer_positioning(cur()))
    @app.get('/api/dealer-positioning/diagnostics')
    def dealer_diag(): return jsonify(build_dealer_positioning(cur()))
    @app.get('/api/options-flow-intelligence/status')
    def flow_status(): return jsonify(build_options_flow_intelligence(cur()))
    @app.get('/api/options-flow-intelligence/diagnostics')
    def flow_diag(): return jsonify(build_options_flow_intelligence(cur()))
    @app.get('/api/institutional-probability/status')
    def prob_status():
        x=cur(); d=build_dealer_positioning(x); f=build_options_flow_intelligence(x); s=build_institutional_market_structure(x)
        return jsonify(build_probability_engine(x,d,f,s))
    @app.get('/api/institutional-probability/diagnostics')
    def prob_diag():
        x=cur(); return jsonify(build_probability_engine(x,build_dealer_positioning(x),build_options_flow_intelligence(x),build_institutional_market_structure(x)))
    @app.get('/api/adaptive-learning-v2/status')
    def learning_status(): return jsonify(build_adaptive_learning_v2(cur()))
    @app.get('/api/adaptive-learning-v2/diagnostics')
    def learning_diag(): return jsonify(build_adaptive_learning_v2(cur()))
