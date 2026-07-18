import datetime as dt
import pytest
from engine import institutional_evidence as ev
from engine import institutional_data_quality as dq
from engine import recommendation_ledger as ledger

@pytest.fixture
def isolated(tmp_path, monkeypatch):
    path=str(tmp_path/'evidence.db')
    monkeypatch.setattr(ev,'DB_PATH',path); monkeypatch.setattr(dq,'DB_PATH',path)
    monkeypatch.setenv('APEX_EVIDENCE_DB',path); monkeypatch.setenv('RECOMMENDATION_LEDGER_DB_PATH',str(tmp_path/'ledger.db'))
    ledger.init_db(); ev.init_db(); dq.init_db()

def seed(full=False):
    inst={}
    if full:
        inst={'market_narrative':{'headline':'Test'},'institutional_consensus':{'status':'READY'},'conviction':{'status':'READY'},
              'confidence_attribution':{'contributors':[{'source':'test'}]},'execution':{'score':90},'position_quality':{'score':90},
              'liquidity':{'score':90},'provider_health':{'status':'PASS'},'data_freshness':{'status':'FRESH'}}
    cap=ledger.build_capture(ticker='SPX',panel={'strategy':'CALL_DEBIT','confidence':72,'legs':{}},last_result={'market_state':{'price':6000}},captured_at=dt.datetime(2026,7,18,14,0,tzinfo=dt.timezone.utc))
    cap['snapshot_json'] = cap.get('snapshot_json')
    # inject institutional decision into persisted snapshot contract
    snap=cap['snapshot']; snap['institutional_decision']=inst; cap['snapshot']=snap
    ledger.record_recommendation(cap); ev.capture(cap['recommendation_id']); return cap['recommendation_id']

def test_missing_inputs_fail_closed(isolated):
    rid=seed(False); r=dq.assess(rid)
    assert r['eligible_for_research'] is False and r['grade'] in {'D','F'}
    assert 'MISSING_PROVIDER_HEALTH' in {x['code'] for x in r['defects']}

def test_complete_package_is_eligible(isolated):
    rid=seed(True); r=dq.assess(rid)
    assert r['eligible_for_research'] is True and r['grade']=='A'
    assert dq.latest(rid)['assessment_hash']==r['assessment_hash']

def test_assessment_is_deterministic_and_deduplicated(isolated):
    rid=seed(True); a=dq.assess(rid); b=dq.assess(rid)
    assert a['assessment_hash']==b['assessment_hash']

def test_unavailable_and_empty_report(isolated):
    assert dq.assess('missing')['status']=='UNAVAILABLE'
    assert dq.report()['status']=='COLLECTING'

def test_api_and_dashboard_smoke(isolated):
    rid=seed(True)
    import app as apex_app
    c=apex_app.app.test_client()
    for path in ['/api/data-quality/status',f'/api/data-quality/{rid}',f'/apex_os/data_quality']:
        assert c.get(path).status_code==200,path
    assert c.post(f'/api/data-quality/{rid}/assess').status_code==200
