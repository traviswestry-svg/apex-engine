from engine.institutional_playbook_engine_v233 import build_institutional_playbooks

def test_playbooks_rank_and_guardrails():
    x=build_institutional_playbooks({'ticker':'SPX','price':6300,'expected_move':40,'trend_day_probability':80,'range_day_probability':20,'value_migration':'RISING','poc_migration':'RISING'})
    assert len(x['ranked_playbooks'])>=5
    assert x['ranked_playbooks'][0]['score']>=x['ranked_playbooks'][-1]['score']
    assert x['guardrails']['automatic_execution'] is False

def test_sparse_data_stands_down():
    x=build_institutional_playbooks({})
    assert x['status']=='LIMITED'
    assert x['execution_readiness']['eligible'] is False
