from engine.trade_director_strategy_orchestration import build_strategy_orchestration


def test_bullish_trend_prefers_bullish_defined_risk():
    ctx = {
        'confidence': 82,
        'health_engine': {'score': 84},
        'cross_asset_intelligence': {'cross_asset_bias': 'BULLISH', 'regime': 'RISK_ON_EXPANSION', 'spx_confirmation_score': 78, 'confidence': 82, 'coverage_pct': 90, 'divergences': []},
        'market_memory': {'predictive_session_planner': {'confidence': 76, 'directional_bias': 'BULLISH'}},
        'session_intelligence': {'session': {'mode': 'ATTACK'}, 'risk_budget': {'remaining_risk': 1500, 'maximum_daily_risk': 2000}},
    }
    result = build_strategy_orchestration(ctx)
    assert result['selected_strategy']['direction'] == 'BULLISH'
    assert result['selected_strategy']['strategy'] in {'LONG_CALL', 'CALL_DEBIT_SPREAD', 'BULL_PUT_CREDIT_SPREAD'}
    assert result['execution_contract']['executable'] is False


def test_balanced_neutral_can_rank_iron_condor():
    ctx = {
        'confidence': 72, 'health_engine': {'score': 72},
        'cross_asset_intelligence': {'cross_asset_bias': 'NEUTRAL', 'regime': 'BALANCED_CONFIRMATION', 'spx_confirmation_score': 50, 'confidence': 72, 'coverage_pct': 85, 'divergences': []},
        'market_memory': {'predictive_session_planner': {'confidence': 70, 'directional_bias': 'NEUTRAL'}},
        'session_intelligence': {'session': {'mode': 'OBSERVATION'}, 'risk_budget': {'remaining_risk': 1600, 'maximum_daily_risk': 2000}},
    }
    result = build_strategy_orchestration(ctx)
    assert result['selected_strategy']['strategy'] == 'IRON_CONDOR'


def test_stop_trading_forces_stand_down():
    ctx = {
        'confidence': 90, 'health_engine': {'score': 90},
        'cross_asset_intelligence': {'cross_asset_bias': 'BULLISH', 'regime': 'RISK_ON_EXPANSION', 'spx_confirmation_score': 85, 'confidence': 90, 'coverage_pct': 95, 'divergences': []},
        'session_intelligence': {'session': {'mode': 'STOP_TRADING'}, 'risk_budget': {'remaining_risk': 0, 'maximum_daily_risk': 2000}},
    }
    result = build_strategy_orchestration(ctx)
    assert result['selected_strategy']['strategy'] == 'STAND_DOWN'
    assert result['decision_gate'] == 'STAND_DOWN'
