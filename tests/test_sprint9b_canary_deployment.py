from engine import institutional_governance as gov
from engine import shadow_validation
from engine import production_governance as pg
from engine import canary_deployment as cd


def seed(monkeypatch,tmp_path):
    db=str(tmp_path/'gov.db'); monkeypatch.setattr(gov,'DB_PATH',db); cd.init_db(); now='2026-07-18T12:00:00+00:00'; cid='candidate-9b'
    with cd._conn() as c:
        c.execute("INSERT INTO model_registry(candidate_id,candidate_type,version,status,created_at,created_by,baseline_version,dataset_hash,config_json,metrics_json,limitations_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(cid,'WEIGHT','v2','SHADOW_ONLY',now,'TEST','champion-v1','hash','{}','{}','[]'))
        c.execute("INSERT INTO shadow_campaigns VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",('campaign-9b',cid,'champion-v1','READY_FOR_REVIEW',now,now,now,1,1,30,'[]','{}','v1','hash',None,'{}'))
        c.execute("INSERT INTO promotion_review_packages VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",('pkg-9b','campaign-9b',cid,now,'ELIGIBLE_FOR_PRODUCTION_REVIEW','{}','{}','{}','{}','[]','hash','READY'))
        c.execute("INSERT OR REPLACE INTO champion_registry VALUES(?,?,?,?,?,?)",('decision_weights','champion-v1',None,now,'TEST','{}'))
    pid=pg.create_promotion({'package_id':'pkg-9b','proposed_version':'challenger-v2'})['promotion_id']
    for role in pg.REQUIRED_ROLES: pg.decide(pid,role,'APPROVE',actor=role)
    manifest_id=pg.queue(pid)['manifest_id']
    return manifest_id


def test_requires_queued_manifest_and_bounded_exposure(monkeypatch,tmp_path):
    mid=seed(monkeypatch,tmp_path)
    assert not cd.create({'manifest_id':'missing'})['ok']
    assert not cd.create({'manifest_id':mid,'exposure_pct':25})['ok']
    x=cd.create({'manifest_id':mid,'exposure_pct':5})
    assert x['ok'] and x['status']=='PENDING_START'


def test_champion_until_human_start(monkeypatch,tmp_path):
    mid=seed(monkeypatch,tmp_path); cid=cd.create({'manifest_id':mid})['canary_id']
    r=cd.route(cid,'rec-1')
    assert r['routed_to']=='CHAMPION' and r['production_effect']=='CHAMPION_ONLY'
    assert cd.transition(cid,'start',actor='owner')['status']=='ACTIVE'


def test_deterministic_routing_and_scope(monkeypatch,tmp_path):
    mid=seed(monkeypatch,tmp_path); cid=cd.create({'manifest_id':mid,'exposure_pct':10,'strategy_families':['BREAKOUT'],'regimes':['TREND']})['canary_id']; cd.transition(cid,'start')
    a=cd.route(cid,'same-rec',{'strategy_family':'BREAKOUT','regime':'TREND'},record=False)
    b=cd.route(cid,'same-rec',{'strategy_family':'BREAKOUT','regime':'TREND'},record=False)
    assert a['bucket']==b['bucket'] and a['routed_to']==b['routed_to']
    out=cd.route(cid,'other',{'strategy_family':'MEAN_REVERSION','regime':'TREND'},record=False)
    assert out['routed_to']=='CHAMPION' and not out['eligible']


def test_health_breach_automatic_rollback(monkeypatch,tmp_path):
    mid=seed(monkeypatch,tmp_path); cid=cd.create({'manifest_id':mid,'exposure_pct':1,'minimum_health_samples':10,'max_error_rate':0.05})['canary_id']; cd.transition(cid,'start')
    r=cd.health(cid,{'samples':20,'error_rate':0.20,'divergence_rate':0.1,'consecutive_errors':0})
    assert r['status']=='ROLLED_BACK' and r['active_version']=='champion-v1'
    assert cd.route(cid,'rec-after')['routed_to']=='CHAMPION'
    assert cd.rollbacks()[0]['automatic']==1


def test_routes_and_dashboard_present():
    routes=open('engine/institutional_roadmap_routes.py').read()
    assert '/api/production/canary/status' in routes
    assert '/api/production/canaries/<canary_id>/rollback' in routes
    assert '/apex_os/canary_deployment' in routes
    assert 'Automatic Full Rollout' in open('templates/canary_deployment.html').read()
