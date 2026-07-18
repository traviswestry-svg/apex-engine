import importlib
import os
from datetime import datetime, timedelta, timezone


def setup_mod(tmp_path, monkeypatch):
    monkeypatch.setenv('APEX_GOVERNANCE_DB', str(tmp_path/'gov.db'))
    monkeypatch.setenv('APEX_OPTIMIZER_MIN_ROWS','10')
    import engine.institutional_governance as gov
    import engine.offline_weight_optimization as opt
    importlib.reload(gov); importlib.reload(opt)
    return gov,opt

def seed(gov,n=30):
    base=datetime(2026,1,1,tzinfo=timezone.utc)
    for i in range(n):
        win=i%3!=0
        gov.ingest_outcome({'recommendation_id':f'r{i}','graded_at':(base+timedelta(days=i)).isoformat(),'outcome_label':'WIN' if win else 'LOSS','realized_pnl':100 if win else -100,'realized_r':1 if win else -1,'family':'TREND','regime':'TREND','confidence':80 if win else 40,'conviction':70 if win else 30,'consensus_grade':'A','data_quality':'VERIFIED','source':'TEST'})

def test_fail_closed_without_history(tmp_path,monkeypatch):
    gov,opt=setup_mod(tmp_path,monkeypatch)
    p=opt.run_optimization()
    assert not p['ok'] and p['status']=='INSUFFICIENT_HISTORY' and p['production_effect']=='NONE'

def test_optimization_is_reproducible_and_shadow_only(tmp_path,monkeypatch):
    gov,opt=setup_mod(tmp_path,monkeypatch); seed(gov)
    a=opt.run_optimization(actor='TEST'); b=opt.run_optimization(actor='TEST')
    assert a['dataset_hash']==b['dataset_hash']
    assert a['selected']['weights']==b['selected']['weights']
    assert a['split_manifest']['look_ahead_protection'] is True
    assert a['production_effect']=='NONE'

def test_shadow_scorecard_is_descriptive(tmp_path,monkeypatch):
    gov,opt=setup_mod(tmp_path,monkeypatch); seed(gov,60)
    p=opt.run_optimization(actor='TEST'); cid=p['candidate_id']
    gov.submit_candidate(cid,actor='TEST'); gov.approve_candidate(cid,actor='HUMAN')
    gov.record_shadow_result(cid,{'score':60},{'score':65},{},data_quality='GOOD')
    card=opt.build_shadow_scorecard(cid)
    assert card['ok'] and card['comparison']['outcome_performance_available'] is False
    assert card['production_effect']=='NONE'

def test_routes_and_dashboard(tmp_path,monkeypatch):
    gov,opt=setup_mod(tmp_path,monkeypatch); seed(gov)
    import app as appmod
    client=appmod.app.test_client()
    assert client.get('/api/learning/optimization/status').status_code==200
    assert client.get('/apex_os/offline_optimization').status_code==200
