from engine.trade_director_execution_desk import build_execution_plan, assess_order_update


def context():
    return {
        'trade_health': 82,
        'strategy_orchestration': {'decision_gate':'STRATEGY_SELECTED','selected_strategy':{'score':86}},
        'options_intelligence': {'decision_gate':'CONTRACT_CANDIDATE_SELECTED','best_contract':{
            'symbol':'SPXW_TEST','expiration':'2026-07-22','strike':6400,'side':'CALL','delta':.51,
            'bid':10.0,'ask':10.4,'mid':10.2,'score':88
        }},
        'session_intelligence': {'dynamic_position_sizing': {'recommended_contracts': 2}},
    }


def test_plan_ready_and_no_broker_call():
    p=build_execution_plan(context())
    assert p['decision_gate']=='READY_FOR_PHASE10_PREVIEW'
    assert p['order_plan']['quantity']==2
    assert p['execution_authority']['broker_called'] is False
    assert p['execution_authority']['phase10_confirmation_required'] is True


def test_stand_down_blocks():
    c=context(); c['strategy_orchestration']['decision_gate']='STAND_DOWN'
    p=build_execution_plan(c)
    assert p['decision_gate']=='BLOCKED'
    assert any('STAND_DOWN' in x for x in p['blockers'])


def test_partial_fill_quality():
    p=build_execution_plan(context())
    a=assess_order_update(p, {'filled_quantity':1,'average_fill_price':p['order_plan']['limit_price']+.05,'status':'PARTIAL'})
    assert a['lifecycle_state']=='PARTIALLY_FILLED'
    assert a['remaining_quantity']==1
    assert a['execution_quality_score'] < 100
