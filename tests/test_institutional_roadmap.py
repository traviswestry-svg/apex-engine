import os
import pytest

from engine import institutional_governance as gov
from engine.institutional_narrative import build_consensus_gauge, build_conviction

@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(gov, 'DB_PATH', str(tmp_path/'governance.db'))
    gov.init_db()
    return tmp_path

def test_empty_history_is_honest(isolated):
    r=gov.history_report(minimum=5)
    assert r['status']=='COLLECTING' and r['sample_size']==0 and not r['eligible']
    s=gov.scorecard()
    assert s['available'] is False and s['metrics']=={}

def test_immutable_outcome_contract(isolated):
    body={'recommendation_id':'r1','outcome_label':'WIN','source':'BROKER_CONFIRMED','data_quality':'VERIFIED','realized_pnl':100}
    assert gov.ingest_outcome(body)['ok']
    second=gov.ingest_outcome(body)
    assert not second['ok'] and second['status']=='APPROVAL_REQUIRED'

def test_history_threshold_and_quality_gate(isolated):
    for i in range(3):
        assert gov.ingest_outcome({'recommendation_id':f'r{i}','outcome_label':'WIN','source':'TEST_REAL_CONTRACT','data_quality':'VERIFIED'})['ok']
    assert gov.history_report(minimum=4)['status']=='INSUFFICIENT_HISTORY'
    assert gov.history_report(minimum=3)['status']=='READY_FOR_CALIBRATION'

def test_feature_hash_deterministic_and_versioned(isolated):
    a=gov.create_vector({'b':2,'a':1},feature_version='v1')
    b=gov.create_vector({'a':1,'b':2},feature_version='v1')
    c=gov.create_vector({'a':1,'b':2},feature_version='v2')
    assert a['feature_hash']==b['feature_hash']
    assert a['feature_hash']!=c['feature_hash']

def test_similarity_enforces_lookahead(isolated):
    old=gov.create_vector({'x':1.0},observed_at='2026-01-01T00:00:00+00:00')
    base=gov.create_vector({'x':1.1},observed_at='2026-01-02T00:00:00+00:00')
    future=gov.create_vector({'x':1.1},observed_at='2026-01-03T00:00:00+00:00')
    r=gov.similarity(base['vector_id'])
    ids={m['vector_id'] for m in r['matches']}
    assert old['vector_id'] in ids and future['vector_id'] not in ids
    assert r['look_ahead_guard']['enforced'] is True and r['outcome_performance'] is None

def test_learning_disabled_and_candidate_gated(isolated):
    status=gov.learning_status()
    assert status['status']=='DISABLED' and status['automatic_promotion'] is False
    c=gov.register_candidate('WEIGHT_OPTIMIZATION',{'weights':{'flow':1.1}})
    assert c['status']=='DISABLED'
    approved=gov.approve_candidate(c['candidate_id'],actor='tester')
    assert not approved['ok'] and approved['status']=='DISABLED'

def test_rollback_and_audit(isolated):
    c=gov.register_candidate('CALIBRATION',{})
    r=gov.rollback(c['candidate_id'],actor='tester',note='safety')
    assert r['rollback_complete']
    assert any(e['action']=='ROLLBACK' for e in gov.audits())

def test_consensus_disagreement_and_too_few_fail_closed():
    few=build_consensus_gauge({'institutional_intelligence':{'bias':'BULLISH'}})
    assert few['status']=='DEGRADED' and few['policy_guidance']=='DO_NOT_TRADE'
    mixed=build_consensus_gauge({'institutional_intelligence':{'bias':'BULLISH'},'auction_intelligence':{'bias':'BEARISH'},'flow_intelligence_2':{'flow_bias':'BULLISH'},'structure':{'bias':'BEARISH'}})
    assert mixed['institutional_divergence_warning'] is True
    assert mixed['contradiction_severity'] in {'MATERIAL','SEVERE'}

def test_conviction_blocking_condition():
    out=build_conviction({'institutional_intelligence':{'confidence':90}})
    assert out['fail_closed'] is True
    assert 'INSUFFICIENT_RELIABLE_ENGINES' in out['blocking_conditions']

def test_api_and_dashboard_smoke(isolated, monkeypatch):
    import app as apex_app
    monkeypatch.setattr(gov, 'DB_PATH', str(isolated/'api.db'))
    client=apex_app.app.test_client()
    for path in ['/api/history/status','/api/history/scorecard','/api/research/status','/api/learning/status','/api/learning/candidates','/api/narrative','/api/consensus','/api/conviction']:
        res=client.get(path); assert res.status_code==200, path
    assert client.get('/apex_os/institutional_research').status_code==200
    assert client.get('/apex_os/adaptive_learning').status_code==200
