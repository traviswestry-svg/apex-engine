from engine import confirmation_gated_execution as e

def intent(): return {'symbol':'SPXW','osi_key':'SPXW260718C06400000','action':'BUY_OPEN','quantity':1,'order_type':'LIMIT','limit_price':10,'max_risk':1000}
def gates(): return {'tradeability':'TRADEABLE','portfolio_risk':{'risk_state':'NORMAL','permissions':{'new_entries_allowed':True}},'broker_sync':{'sync_state':'SYNCED','blocking_discrepancy_count':0}}
def setup(monkeypatch,tmp_path):
 from engine import institutional_governance as gov
 monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'x.db'))

def test_intent_idempotency(monkeypatch,tmp_path):
 setup(monkeypatch,tmp_path); a=e.create_intent(intent(),'k'); b=e.create_intent(intent(),'k'); assert a['created'] and b['status']=='IMMUTABLE_EXISTS'
def test_preview_blocked(monkeypatch,tmp_path):
 setup(monkeypatch,tmp_path); a=e.create_intent(intent()); x=e.preview(a['intent_id'],{'tradeability':'NOT_TRADEABLE'}); assert x['status']=='BLOCKED'
def test_confirmation_required(monkeypatch,tmp_path):
 setup(monkeypatch,tmp_path); a=e.create_intent(intent()); p=e.preview(a['intent_id'],gates(),{'preview_id':'p1'}); x=e.confirm(a['intent_id'],p['preview_record_id'],'',False); assert x['status']=='CONFIRMATION_REQUIRED'
def test_disabled_execution(monkeypatch,tmp_path):
 setup(monkeypatch,tmp_path); monkeypatch.delenv('APEX_CONFIRMATION_GATED_EXECUTION_ENABLED',raising=False); a=e.create_intent(intent()); p=e.preview(a['intent_id'],gates(),{'preview_id':'p1'}); c=e.confirm(a['intent_id'],p['preview_record_id'],'Travis',True); x=e.execute(a['intent_id'],c['confirmation_id'],gates()); assert x['status']=='EXECUTION_DISABLED'
def test_confirmed_one_time_execution(monkeypatch,tmp_path):
 setup(monkeypatch,tmp_path); monkeypatch.setenv('APEX_CONFIRMATION_GATED_EXECUTION_ENABLED','true'); a=e.create_intent(intent()); p=e.preview(a['intent_id'],gates(),{'preview_id':'p1'}); c=e.confirm(a['intent_id'],p['preview_record_id'],'Travis',True); fn=lambda i,c:{'ok':True,'order_id':'o1'}; x=e.execute(a['intent_id'],c['confirmation_id'],gates(),fn); y=e.execute(a['intent_id'],c['confirmation_id'],gates(),fn); assert x['status']=='SUBMITTED' and y['status']=='IDEMPOTENT_REPLAY'
def test_safety(monkeypatch,tmp_path):
 setup(monkeypatch,tmp_path); s=e.status(); assert not s['automatic_execution_enabled'] and s['explicit_human_confirmation_required'] and s['preview_required']
