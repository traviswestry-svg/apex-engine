from datetime import datetime, timezone
import pytest
from engine.execution.paper_lifecycle_validation import validate_scenario

C={'ticker':'SPX','right':'CALL','expiration':'2026-10-26','strike':6000}
Q={'decision_id':'d1','contract':C,'quantity':1,'entry_limit':'5','canonical_persisted':True,'server_approved':True}
def ev(i, typ, n=1, p='5'):
    return {'event_id':str(i),'type':typ,'decision_id':'d1','contract':dict(C),
            'quantity':n,'price':p,'at':'2026-10-26T10:00:00-04:00'}
def run(events, **kw): return validate_scenario(dict(Q),events,prior_verified_daily_pnl='0',**kw)

def test_complete_synthetic_lifecycle_is_never_authority():
    r=run([ev(1,'ENTRY_FILL'),ev(2,'EXIT_FILL',p='6')]); assert r['open_quantity']==0
    assert r['modeled_pnl_not_broker_verified']=='100' and r['verified_realized_pnl'] is None
    assert not r['may_send_order'] and not r['broker_fill_verified']
def test_partial_fill_unresolved_exit():
    q=dict(Q,quantity=2)
    r=validate_scenario(q,[ev(1,'ENTRY_PARTIAL_FILL')],prior_verified_daily_pnl='0')
    assert 'POSITION_EXIT_UNVERIFIED' in r['blockers']
def test_rejection():
    r=run([ev(1,'ENTRY_REJECTED',0)]); assert 'NO_ENTRY_FILL' in r['blockers']
def test_cancellation_after_partial_entry():
    r=run([ev(1,'ENTRY_PARTIAL_FILL'),ev(2,'ENTRY_CANCELLED',0),ev(3,'EXIT_FILL')]); assert r['open_quantity']==0
def test_out_of_order_exit_rejected():
    with pytest.raises(ValueError,match='ORPHAN'): run([ev(1,'EXIT_FILL')])
def test_duplicate_event_rejected():
    with pytest.raises(ValueError,match='DUPLICATE'): run([ev(1,'ENTRY_FILL'),ev(1,'EXIT_FILL')])
def test_contract_or_decision_mismatch_rejected():
    e=ev(1,'ENTRY_FILL'); e['contract']['strike']=6100
    with pytest.raises(ValueError,match='MISMATCH'): run([e])
def test_overfill_rejected():
    with pytest.raises(ValueError,match='OVERFILL'): run([ev(1,'ENTRY_FILL',2)])
def test_unknown_real_pnl_fails_closed():
    r=validate_scenario(dict(Q),[ev(1,'ENTRY_FILL'),ev(2,'EXIT_FILL')]); assert 'VERIFIED_DAILY_PNL_UNAVAILABLE' in r['blockers']
def test_model_loss_limit_not_verified_risk():
    r=run([ev(1,'ENTRY_FILL',p='10'),ev(2,'EXIT_FILL',p='1')],daily_loss_limit='500')
    assert 'MODEL_DAILY_LOSS_LIMIT_BREACH' in r['blockers'] and not r['daily_loss_enforced']
def test_price_and_risk_validation():
    with pytest.raises(ValueError,match='ENTRY_RISK'): validate_scenario(dict(Q,entry_limit='30'),[],prior_verified_daily_pnl='0')
def test_no_external_dispatch_import():
    import inspect, engine.execution.paper_lifecycle_validation as m
    source=inspect.getsource(m)
    assert 'requests.post(' not in source and 'urllib.request' not in source
