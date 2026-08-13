from engine import sandbox_execution_validation as e

def setup(monkeypatch,tmp_path):
 from engine import institutional_governance as gov
 monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'x.db'))

def payload():
 return {'account_id':'PRIMARY','osi_key':'SPXW260718C06400000',
  'configuration':{'oauth_configured':True,'account_id_key':'abc','mode':'SANDBOX'},
  'gates':{'broker_sync_state':'SYNCED','tradeability':'TRADEABLE','risk_passed':True,'risk_state':'NORMAL'},
  'preview':{'ok':True,'preview_id':'p1'},
  'confirmation':{'acknowledgement':True,'confirmed_by':'Travis','intent_id':'i1','preview_record_id':'pr1'},
  'submission':{'ok':True,'order_id':'o1'},'tracking':{'order_status':'FILLED'},
  'reconciliation':{'fill_reconciled':True,'position_synced':True,'management_handoff':True},
  'failure_drills':{'duplicate_submission_prevented':True,'kill_switch_verified':True}}

def test_full_certification_passes(monkeypatch,tmp_path):
 setup(monkeypatch,tmp_path); x=e.evaluate(payload()); assert x['status']=='PASSED' and x['certification_score']==100

def test_invalid_symbol_blocks(monkeypatch,tmp_path):
 setup(monkeypatch,tmp_path); p=payload(); p['osi_key']='BAD'; x=e.evaluate(p); assert x['status']=='BLOCKED' and 'OPTION_SYMBOL_VALID' in x['blocking_checks']

def test_missing_oauth_blocks(monkeypatch,tmp_path):
 setup(monkeypatch,tmp_path); p=payload(); p['configuration']['oauth_configured']=False; x=e.evaluate(p); assert 'OAUTH_CONFIGURED' in x['blocking_checks']

def test_record_is_immutable(monkeypatch,tmp_path):
 setup(monkeypatch,tmp_path); p=payload(); p['run_id']='r1'; a=e.record(p); b=e.record(p); assert a['created'] and b['status']=='IMMUTABLE_EXISTS'

def test_partial_fill_is_trackable(monkeypatch,tmp_path):
 setup(monkeypatch,tmp_path); p=payload(); p['tracking']['order_status']='PARTIAL'; p['reconciliation']['fill_reconciled']=False; x=e.evaluate(p); assert x['status']=='PARTIAL'

def test_safety_contract(monkeypatch,tmp_path):
 setup(monkeypatch,tmp_path); s=e.status(); assert s['sandbox_only'] and not s['live_trading_enabled'] and s['human_confirmation_required']
