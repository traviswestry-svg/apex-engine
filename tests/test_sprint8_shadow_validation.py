import importlib
from datetime import datetime, timedelta, timezone


def setup_mod(tmp_path, monkeypatch):
    monkeypatch.setenv('APEX_GOVERNANCE_DB', str(tmp_path/'gov.db'))
    import engine.institutional_governance as gov
    import engine.shadow_validation as sv
    importlib.reload(gov); importlib.reload(sv)
    gov.MIN_GRADED=2
    return gov,sv

def approved_candidate(gov):
    for i in range(2):
        gov.ingest_outcome({'recommendation_id':f'h{i}','outcome_label':'WIN','source':'TEST','data_quality':'VERIFIED'})
    c=gov.register_candidate('WEIGHT_OPTIMIZATION',{'confidence':.6},dataset_hash='d1')
    gov.record_offline_evaluation(c['candidate_id'],{'dataset_hash':'d1','methodology':{'walk_forward':True,'look_ahead_guard':True},'splits':{'train':['a'],'validation':['b'],'test':['c']}})
    gov.submit_candidate(c['candidate_id'],actor='research')
    gov.approve_candidate(c['candidate_id'],actor='human')
    return c['candidate_id']

def test_campaign_requires_shadow_approval(tmp_path,monkeypatch):
    gov,sv=setup_mod(tmp_path,monkeypatch)
    c=gov.register_candidate('WEIGHT_OPTIMIZATION',{})
    p=sv.create_campaign(c['candidate_id'],{})
    assert not p['ok'] and p['status']=='APPROVAL_REQUIRED'

def test_campaign_capture_scorecard_and_finalize(tmp_path,monkeypatch):
    gov,sv=setup_mod(tmp_path,monkeypatch); cid=approved_candidate(gov)
    p=sv.create_campaign(cid,{'required_sessions':2,'required_recommendations':2,'max_divergence_rate':1.0})
    campaign=p['campaign_id']; assert sv.transition(campaign,'start',actor='human')['status']=='ACTIVE'
    base=datetime(2026,7,1,tzinfo=timezone.utc)
    for i,(y,ps,cs) in enumerate([('WIN',.7,.8),('LOSS',.3,.2)]):
        r=sv.record_observation(campaign,{'recommendation_id':f'r{i}','observed_at':(base+timedelta(days=i)).isoformat(),'session_date':(base+timedelta(days=i)).date().isoformat(),'regime':'TREND','strategy_family':'TREND','data_quality':'VERIFIED','production':{'score':ps,'recommendation':'ENTER'},'candidate':{'score':cs,'recommendation':'ENTER'},'outcome_label':y})
        assert r['ok'] and r['production_changed'] is False
    assert sv.coverage(campaign)['complete'] is True
    assert sv.scorecard(campaign)['graded_count']==2
    f=sv.finalize(campaign,actor='human')
    assert f['ok'] and f['production_effect']=='NONE'
    assert sv.packages()[0]['summary']['production_effect']=='NONE'

def test_kill_switch_pauses_only_campaign(tmp_path,monkeypatch):
    gov,sv=setup_mod(tmp_path,monkeypatch); cid=approved_candidate(gov)
    p=sv.create_campaign(cid,{'required_sessions':1,'required_recommendations':1,'max_divergence_rate':0.0})
    campaign=p['campaign_id']; sv.transition(campaign,'start')
    sv.record_observation(campaign,{'recommendation_id':'x','data_quality':'VERIFIED','production':{'score':.7,'recommendation':'ENTER'},'candidate':{'score':.7,'recommendation':'HOLD'}})
    assert sv._campaign(campaign)['status']=='PAUSED'
    assert gov.candidates(cid)['status']=='SHADOW_ONLY'

def test_champion_registry_never_auto_replaces(tmp_path,monkeypatch):
    gov,sv=setup_mod(tmp_path,monkeypatch)
    x=sv.champion_challenger()
    assert x['champion']['champion_version']=='PRODUCTION_CURRENT'
    assert x['automatic_replacement'] is False and x['production_effect']=='NONE'

def test_routes_and_dashboard(tmp_path,monkeypatch):
    gov,sv=setup_mod(tmp_path,monkeypatch)
    import app as appmod
    client=appmod.app.test_client()
    assert client.get('/api/learning/shadow-campaigns').status_code==200
    assert client.get('/api/learning/promotion-packages').status_code==200
    assert client.get('/api/learning/champion-challenger').status_code==200
    assert client.get('/apex_os/shadow_validation').status_code==200
