import datetime as dt
import pytest
from engine import institutional_evidence as ev
from engine import recommendation_ledger as ledger

@pytest.fixture
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(ev,'DB_PATH',str(tmp_path/'evidence.db'))
    monkeypatch.setenv('RECOMMENDATION_LEDGER_DB_PATH',str(tmp_path/'ledger.db'))
    ledger.init_db(); ev.init_db(); return tmp_path

def seed():
    cap=ledger.build_capture(ticker='SPX',panel={'strategy':'CALL_DEBIT','confidence':72,'legs':{}},last_result={'market_state':{'price':6000}},captured_at=dt.datetime(2026,7,18,14,0,tzinfo=dt.timezone.utc))
    ledger.record_recommendation(cap); return cap['recommendation_id']

def test_capture_is_immutable_and_deterministic(isolated):
    rid=seed(); a=ev.capture(rid); b=ev.capture(rid)
    assert a['created'] is True and b['created'] is False
    assert a['integrity_hash']==b['integrity_hash']
    assert ev.get(rid)['package']['immutable'] is True

def test_timeline_append_only(isolated):
    rid=seed(); ev.capture(rid); ev.append_event(rid,'RISK_INCREASED',previous_state={'risk':'LOW'},new_state={'risk':'HIGH'},evidence={'flow':'reversed'},explanation='Flow reversed')
    events=ev.timeline(rid)
    assert [x['event_type'] for x in events]==['RECOMMENDATION_CREATED','RISK_INCREASED']
    assert events[-1]['previous_state']['risk']=='LOW'

def test_integrity_and_missing(isolated):
    assert ev.validate('missing')['status']=='UNAVAILABLE'
    rid=seed(); ev.capture(rid); r=ev.validate(rid)
    assert r['status']=='READY' and all(r['checks'].values())

def test_status_empty_and_collecting(isolated):
    assert ev.status()['status']=='COLLECTING'

def test_api_and_case_file_smoke(isolated,monkeypatch):
    rid=seed(); ev.capture(rid)
    import app as apex_app
    client=apex_app.app.test_client()
    for path in [f'/api/evidence/{rid}',f'/api/evidence/{rid}/timeline',f'/api/evidence/{rid}/integrity',f'/api/evidence/{rid}/metadata','/api/evidence/status',f'/apex_os/evidence/{rid}']:
        assert client.get(path).status_code==200,path
