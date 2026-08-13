import os
from engine.institutional_ai_trading_coach_v235 import build_trading_coach, record_review, behavioral_scorecard


def sample_last():
    return {'ticker':'SPX','spx':6000,'vix':16,'trend_day_probability':70,'range_day_probability':30}


def test_pre_trade_preserves_human_confirmation_gate():
    x=build_trading_coach(sample_last(),phase='PRE_TRADE',trade={})
    assert x['guardrails']['automatic_execution'] is False
    assert 'HUMAN_CONFIRMATION_REQUIRED' in x['coaching']['blockers']
    assert x['coaching']['recommendation'] in {'STAND_DOWN','REDUCE_SIZE','TAKE'}


def test_active_trade_exits_on_invalidation():
    x=build_trading_coach(sample_last(),phase='ACTIVE_TRADE',trade={'structure_invalidated':True})
    assert x['coaching']['recommendation']=='EXIT'
    assert 'EXIT_NOW' in x['coaching']['actions']


def test_active_trade_protects_after_tp1():
    x=build_trading_coach(sample_last(),phase='ACTIVE_TRADE',trade={'tp1_reached':True})
    assert x['coaching']['recommendation']=='PROTECT'
    assert 'BREAKEVEN_ELIGIBLE' in x['coaching']['actions']


def test_post_trade_separates_strategy_and_behavior():
    x=build_trading_coach(sample_last(),phase='POST_TRADE',trade={'chased':True,'premature_exit':True})
    assert x['coaching']['strategy_quality_separate_from_execution_quality'] is True
    assert 'CHASING' in x['coaching']['behavioral_flags']
    assert x['coaching']['overall_discipline_score'] < 100


def test_review_is_immutable_and_learning_is_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'coach.db'))
    payload={'phase':'POST_TRADE','ticker':'SPX','trade_id':'T1','playbook_id':'WAIT_FOR_CONFIRMATION'}
    a=record_review(payload); b=record_review(payload)
    assert a['status']=='RECORDED'
    assert a['learning_result'] is None
    assert b['status']=='IMMUTABLE_EXISTS'
    card=behavioral_scorecard('SPX')
    assert card['samples']==1
