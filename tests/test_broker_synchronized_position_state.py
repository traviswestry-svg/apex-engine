from engine import broker_synchronized_position_state as b

def sample():
 return {'broker_snapshot':{'broker':'ETRADE','account_id':'PRIMARY','observed_at':'2026-07-18T14:00:00+00:00','source_status':'CONNECTED','account':{'account_value':60000,'buying_power':30000},'positions':[{'symbol':'SPXW','side':'LONG','quantity':1,'average_price':10,'market_price':12}],'orders':[],'fills':[]},'apex_state':{'positions':[{'symbol':'SPXW','side':'LONG','quantity':1,'entry_price':10}]}}

def test_synced():
 x=b.reconcile(sample()); assert x['sync_state']=='SYNCED' and x['discrepancy_count']==0

def test_quantity_mismatch():
 p=sample(); p['apex_state']['positions'][0]['quantity']=2; x=b.reconcile(p); assert x['sync_state']=='DRIFT_DETECTED'; assert any(d['type']=='POSITION_QUANTITY_MISMATCH' for d in x['discrepancies'])

def test_missing_broker_position_blocks():
 p=sample(); p['broker_snapshot']['positions']=[]; x=b.reconcile(p); assert x['blocking_discrepancy_count']==1

def test_unavailable():
 p=sample(); p['broker_snapshot']['source_status']='ERROR'; assert b.reconcile(p)['sync_state']=='BROKER_UNAVAILABLE'

def test_immutable(monkeypatch,tmp_path):
 from engine import institutional_governance as gov
 monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'x.db')); p=sample(); a=b.record(p); z=b.record(p); assert a['created'] and z['status']=='IMMUTABLE_EXISTS'

def test_safety():
 s=b.status(); assert s['read_only'] and not s['broker_order_submission_enabled'] and not s['position_mutation_enabled']
