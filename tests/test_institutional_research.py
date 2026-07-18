import json
import sqlite3
import pytest

from engine import institutional_governance as gov
from engine import institutional_data_quality as quality
from engine import institutional_research as research


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(gov, 'DB_PATH', str(tmp_path/'governance.db'))
    monkeypatch.setattr(quality, 'DB_PATH', str(tmp_path/'quality.db'))
    monkeypatch.setattr(research, 'DB_PATH', str(tmp_path/'research.db'))
    monkeypatch.setattr(research, 'MIN_COHORT', 2)
    monkeypatch.setattr(research, 'MIN_COMPARISON_COHORTS', 2)
    monkeypatch.setattr(research, 'MATERIAL_GAP_PCT', 10)
    gov.init_db(); quality.init_db(); research.init_db()


def seed(rid, label, family, *, confidence=80, date='2026-07-01T15:00:00+00:00'):
    payload={'recommendation_id':rid,'outcome_label':label,'source':'TEST','data_quality':'VERIFIED','family':family,'regime':'TREND','confidence':confidence,'conviction':confidence,'consensus_grade':'A','graded_at':date,'execution_score':confidence}
    assert gov.ingest_outcome(payload)['ok']
    with sqlite3.connect(quality.DB_PATH) as c:
        c.execute("INSERT INTO data_quality_assessments VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(f'a-{rid}',rid,date,'test',100,'A','READY',1,'{}','[]','[]',f'h-{rid}'))


def ready(monkeypatch):
    monkeypatch.setattr(research.historical_readiness, 'build_report', lambda: {'status':'READY_FOR_CALIBRATION','counts':{'graded':8},'feature_unlocks':{'strategy_intelligence':True}})


def test_research_fails_closed_without_history(isolated, monkeypatch):
    monkeypatch.setattr(research.historical_readiness, 'build_report', lambda: {'status':'COLLECTING','counts':{'graded':0}})
    out=research.generate()
    assert out['status']=='COLLECTING'
    assert out['findings']==[]
    assert research.status()['automatic_live_changes'] is False


def test_research_generates_descriptive_finding_only_when_gated(isolated, monkeypatch):
    ready(monkeypatch)
    for i,label in enumerate(['WIN','WIN','WIN','WIN']): seed(f'a{i}',label,'FAMILY_A',date=f'2026-07-0{i+1}T15:00:00+00:00')
    for i,label in enumerate(['LOSS','LOSS','LOSS','LOSS']): seed(f'b{i}',label,'FAMILY_B',date=f'2026-07-1{i+1}T15:00:00+00:00')
    out=research.generate(actor='TEST')
    assert out['status']=='READY' and out['findings']
    finding=out['findings'][0]
    assert finding['policy_effect']=='NONE'
    stored=research.findings(finding_id=finding['finding_id'])
    assert stored['status']=='RESEARCH_ONLY'
    assert stored['evidence']['descriptive_only'] is True


def test_research_run_is_reproducible_and_deduplicated(isolated, monkeypatch):
    ready(monkeypatch)
    for i,label in enumerate(['WIN','WIN']): seed(f'a{i}',label,'A')
    for i,label in enumerate(['LOSS','LOSS']): seed(f'b{i}',label,'B')
    first=research.generate(); second=research.generate()
    assert first['dataset_hash']==second['dataset_hash']
    assert second['created'] is False
    assert first['run_id']==second['run_id']


def test_comparisons_report_sample_and_no_policy_effect(isolated, monkeypatch):
    ready(monkeypatch)
    for i,label in enumerate(['WIN','WIN']): seed(f'a{i}',label,'A')
    for i,label in enumerate(['LOSS','LOSS']): seed(f'b{i}',label,'B')
    out=research.comparisons('family')
    assert out['status']=='READY'
    assert out['sample_size']==4
    assert out['policy_effect']=='NONE' and out['causal_claim'] is False
    assert all('sample_size' in c and 'date_coverage' in c for c in out['cohorts'])


def test_research_routes_and_dashboard(isolated, monkeypatch):
    ready(monkeypatch)
    import app as apex_app
    client=apex_app.app.test_client()
    for path in ['/api/research/status','/api/research/findings','/api/research/comparisons?dimension=family','/api/research/runs','/apex_os/strategy_intelligence']:
        assert client.get(path).status_code==200,path
    assert client.post('/api/research/generate',json={'actor':'TEST'}).status_code in (200,201)
