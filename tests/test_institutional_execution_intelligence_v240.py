from engine.institutional_execution_intelligence_v240 import build_execution_intelligence, create_lifecycle, transition_lifecycle, replay_lifecycle, journal


def test_execution_intelligence_is_advisory_and_has_levels():
    x=build_execution_intelligence({'ticker':'SPX','spx':6000},{'entry_price':6000,'stop_price':5995,'direction':'CALL'})
    assert x['version'].startswith('17.0.0')
    assert x['guardrails']['broker_mutation'] is False
    assert x['levels']['tp1']==6005
    assert x['levels']['tp3']==6010


def test_lifecycle_requires_confirmation_for_entry(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'execution.db'))
    created=create_lifecycle({'ticker':'SPX','spx':6000},{'entry_price':6000,'stop_price':5995})
    lid=created['lifecycle_id']
    bad=transition_lifecycle(lid,{'to_state':'ENTERED'})
    assert bad['ok'] is False
    approved=transition_lifecycle(lid,{'to_state':'APPROVED'})
    assert approved['ok'] is True
    entered=transition_lifecycle(lid,{'to_state':'ENTERED','human_confirmed':True})
    assert entered['ok'] is True
    protected=transition_lifecycle(lid,{'to_state':'PROTECTED','event_type':'TP1_REACHED'})
    assert protected['ok'] is True
    exited=transition_lifecycle(lid,{'to_state':'EXITED','realized_r':1.5})
    assert exited['ok'] is True
    replay=replay_lifecycle(lid)
    assert replay['event_count']==5
    assert replay['timeline'][-1]['to_state']=='EXITED'
    assert journal('SPX')['count']==1


def test_invalid_transition_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'execution2.db'))
    created=create_lifecycle({'ticker':'SPX'},{})
    out=transition_lifecycle(created['lifecycle_id'],{'to_state':'EXITED'})
    assert out['error']=='INVALID_STATE_TRANSITION'
