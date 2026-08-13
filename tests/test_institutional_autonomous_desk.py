from engine import institutional_autonomous_desk as e

def setup(monkeypatch,tmp_path):
 from engine import institutional_governance as gov
 monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'x.db'))

def create(evidence=None):
 return {'symbol':'SPX','recommendation_id':'r1','strategy':'OPENING_DRIVE','setup':{'side':'CALLS'},**(evidence or {})}

def ready_snapshot():
 return {'setup':{'side':'CALLS'},'tradeability':'TRADEABLE','portfolio_risk':{'risk_state':'NORMAL','permissions':{'new_entries_allowed':True}},'broker_sync':{'sync_state':'SYNCED','blocking_discrepancy_count':0}}

def test_trade_idempotency(monkeypatch,tmp_path):
 setup(monkeypatch,tmp_path); a=e.create_trade(create(),'k'); b=e.create_trade(create(),'k'); assert a['created'] and b['status']=='IMMUTABLE_EXISTS'

def test_valid_lifecycle_to_preview(monkeypatch,tmp_path):
 setup(monkeypatch,tmp_path); a=e.create_trade(create()); tid=a['desk_trade_id']; assert e.transition(tid,'SETUP_DETECTED')['ok']; assert e.transition(tid,'VALIDATING')['ok']; x=e.transition(tid,'READY_FOR_PREVIEW',ready_snapshot()); assert x['to_state']=='READY_FOR_PREVIEW'

def test_tradeability_blocks_preview(monkeypatch,tmp_path):
 setup(monkeypatch,tmp_path); tid=e.create_trade(create())['desk_trade_id']; e.transition(tid,'SETUP_DETECTED'); e.transition(tid,'VALIDATING'); x=e.transition(tid,'READY_FOR_PREVIEW',{'setup':{},'tradeability':'NOT_TRADEABLE'}); assert x['status']=='BLOCKED'

def test_authorization_requires_named_confirmation(monkeypatch,tmp_path):
 setup(monkeypatch,tmp_path); tid=e.create_trade(create())['desk_trade_id']; e.transition(tid,'SETUP_DETECTED'); e.transition(tid,'VALIDATING'); e.transition(tid,'READY_FOR_PREVIEW',ready_snapshot()); e.transition(tid,'AWAITING_CONFIRMATION'); x=e.transition(tid,'AUTHORIZED',{'confirmation_id':'c1'}); assert x['status']=='CONFIRMATION_REQUIRED'

def test_broker_flat_required(monkeypatch,tmp_path):
 setup(monkeypatch,tmp_path); tid=e.create_trade(create())['desk_trade_id'];
 # Walk through lifecycle
 for st,ev in [('SETUP_DETECTED',{}),('VALIDATING',{}),('READY_FOR_PREVIEW',ready_snapshot()),('AWAITING_CONFIRMATION',{}),('AUTHORIZED',{'confirmation_id':'c','confirmed_by':'Travis','explicit_acknowledgement':True}),('SUBMITTED',{'broker_order_id':'o'}),('FILLED',{}),('MANAGING',{}),('EXIT_PENDING',{})]: assert e.transition(tid,st,ev)['ok']
 assert e.transition(tid,'CLOSED',{})['status']=='BROKER_FLAT_REQUIRED'
 assert e.transition(tid,'CLOSED',{'broker_flat':True})['ok']

def test_safety_contract(monkeypatch,tmp_path):
 setup(monkeypatch,tmp_path); s=e.status(); assert s['autonomous_analysis_enabled'] and not s['automatic_order_submission_enabled'] and s['human_confirmation_required'] and not s['broker_mutation_enabled']
