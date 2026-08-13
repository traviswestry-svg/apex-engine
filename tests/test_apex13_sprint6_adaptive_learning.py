import pytest
from engine import institutional_governance as gov

@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(gov, 'DB_PATH', str(tmp_path/'governance.db'))
    monkeypatch.setattr(gov, 'MIN_GRADED', 2)
    gov.init_db()
    return tmp_path

def _eligible_history():
    for i in range(2):
        assert gov.ingest_outcome({'recommendation_id':f'r{i}','outcome_label':'WIN','source':'BROKER_CONFIRMED','data_quality':'VERIFIED'})['ok']

def test_learning_fail_closed_without_history(isolated):
    s=gov.learning_status()
    assert s['status']=='DISABLED'
    assert s['automatic_promotion'] is False
    c=gov.register_candidate('WEIGHT_OPTIMIZATION',{'flow':1.1})
    assert c['status']=='DISABLED'
    assert gov.approve_candidate(c['candidate_id'],actor='tester')['status']=='DISABLED'

def test_candidate_evaluation_requires_reproducible_splits_and_guards(isolated):
    _eligible_history()
    c=gov.register_candidate('WEIGHT_OPTIMIZATION',{'flow':1.1},dataset_hash='abc')
    assert c['status']=='DRAFT'
    bad=gov.record_offline_evaluation(c['candidate_id'],{'dataset_hash':'abc','splits':{'train':[]}})
    assert not bad['ok']
    good=gov.record_offline_evaluation(c['candidate_id'],{
        'dataset_hash':'abc','methodology':{'walk_forward':True,'look_ahead_guard':True},
        'splits':{'train':['a'],'validation':['b'],'test':['c']},
        'baseline_metrics':{},'candidate_metrics':{},'comparison':{},'limitations':['insufficient sample for performance claim']})
    assert good['ok'] and good['production_effect']=='NONE'
    assert len(gov.evaluations(c['candidate_id']))==1

def test_human_approval_shadow_and_rollback_are_governed(isolated):
    _eligible_history()
    c=gov.register_candidate('CONSENSUS_WEIGHTS',{'auction':1.0},dataset_hash='d1')
    gov.record_offline_evaluation(c['candidate_id'],{'dataset_hash':'d1','methodology':{'walk_forward':True,'look_ahead_guard':True},'splits':{'train':['a'],'validation':['b'],'test':['c']}})
    assert gov.submit_candidate(c['candidate_id'],actor='researcher')['ok']
    approved=gov.approve_candidate(c['candidate_id'],actor='reviewer',note='shadow only')
    assert approved['status']=='SHADOW_ONLY'
    shadow=gov.record_shadow_result(c['candidate_id'],{'decision':'HOLD'},{'decision':'ENTER'},{'different':True},data_quality='VERIFIED')
    assert shadow['production_changed'] is False
    rb=gov.rollback(c['candidate_id'],actor='reviewer',note='test rollback',restored_version='prod-v1')
    assert rb['rollback_complete'] and rb['production_changed'] is False
    actions={e['action'] for e in gov.audits()}
    assert {'APPROVE_FOR_SHADOW','SHADOW_OBSERVATION','ROLLBACK'} <= actions

def test_drift_is_informational_and_audited(isolated):
    r=gov.record_drift('regime_mix','HIGH',{'psi':0.31},production_version='v1')
    assert r['status']=='DEGRADED'
    assert gov.drift()[0]['evidence']['psi']==0.31
    assert any(e['action']=='DRIFT_DETECTED' for e in gov.audits())

def test_api_and_dashboard_smoke(isolated, monkeypatch):
    import app as apex_app
    monkeypatch.setattr(gov, 'DB_PATH', str(isolated/'api.db'))
    client=apex_app.app.test_client()
    for path in ['/api/learning/status','/api/learning/readiness','/api/learning/candidates','/api/learning/evaluations','/api/learning/shadow','/api/learning/drift','/api/learning/approvals','/api/learning/rollbacks','/api/learning/audit']:
        assert client.get(path).status_code==200, path
    assert client.get('/apex_os/adaptive_learning').status_code==200
