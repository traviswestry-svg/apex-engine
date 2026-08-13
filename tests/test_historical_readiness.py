import json
import sqlite3
import pytest
from engine import institutional_evidence as ev
from engine import institutional_data_quality as dq
from engine import institutional_governance as gov
from engine import historical_readiness as hr

@pytest.fixture
def isolated(monkeypatch,tmp_path):
    monkeypatch.setattr(ev,'DB_PATH',str(tmp_path/'evidence.db'))
    monkeypatch.setattr(dq,'DB_PATH',str(tmp_path/'evidence.db'))
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'governance.db'))
    monkeypatch.setattr(hr.ledger,'list_recommendations',lambda limit=10000: [])
    ev.init_db(); dq.init_db(); gov.init_db()

def seed():
    package={'canonical_decision':{'strategy':'CALL','market_state':'TREND','ticker':'SPX'},'snapshots':{}}
    with sqlite3.connect(ev.DB_PATH) as c:
        c.execute("INSERT INTO evidence_packages VALUES(?,?,?,?,?,?,?,?,?)",('p1','r1','2026-07-01T14:00:00+00:00','v1','13','READY',json.dumps(package),'h',None))
        c.execute("INSERT INTO data_quality_assessments VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",('a1','r1','2026-07-01T14:01:00+00:00','v1',95,'A','READY',1,'{}','[]','[]','q'))
    gov.ingest_outcome({'recommendation_id':'r1','outcome_label':'WIN','source':'TEST','data_quality':'VERIFIED','graded_at':'2026-07-01T20:00:00+00:00'})

def test_report_collects_real_counts_and_remains_insufficient(isolated,monkeypatch):
    seed(); monkeypatch.setattr(hr,'MIN_GRADED',50); monkeypatch.setattr(hr,'MIN_ELIGIBLE',25); monkeypatch.setattr(hr,'MIN_DATE_DAYS',20)
    r=hr.build_report()
    assert r['counts']['collected']==1 and r['counts']['graded']==1 and r['counts']['eligible']==1
    assert r['status']=='INSUFFICIENT_HISTORY'
    assert r['feature_unlocks']['confidence_calibration'] is False
    assert r['feature_unlocks']['automatic_production_changes'] is False

def test_empty_state_is_collecting(isolated):
    r=hr.build_report()
    assert r['status']=='COLLECTING' and r['counts'].get('graded',0)==0

def test_degraded_history_when_exclusion_rate_is_high(isolated,monkeypatch):
    package={'canonical_decision':{'strategy':'PUT'},'snapshots':{}}
    with sqlite3.connect(ev.DB_PATH) as c:
        c.execute("INSERT INTO evidence_packages VALUES(?,?,?,?,?,?,?,?,?)",('p2','r2','2026-07-02T14:00:00+00:00','v1','13','READY',json.dumps(package),'h2',None))
        c.execute("INSERT INTO data_quality_assessments VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",('a2','r2','2026-07-02T14:01:00+00:00','v1',40,'F','INCOMPLETE',0,'{}','[{\"code\":\"MISSING_PROVIDER_HEALTH\"}]','[\"MISSING_PROVIDER_HEALTH\"]','q2'))
    monkeypatch.setattr(hr,'MAX_EXCLUSION_RATE',25)
    assert hr.build_report()['status']=='DEGRADED_HISTORY'

def test_routes_and_dashboard(isolated):
    import app as apex_app
    c=apex_app.app.test_client()
    for path in ['/api/historical-readiness/status','/api/historical-readiness/report','/api/historical-readiness/coverage','/api/historical-readiness/gates','/apex_os/historical_readiness']:
        assert c.get(path).status_code==200,path
