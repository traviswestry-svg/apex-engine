from engine import institutional_governance as gov
from engine import production_governance as pg
from engine import canary_deployment as cd
from engine import institutional_release_manager as rm


def seed(monkeypatch,tmp_path,with_canary=True):
    db=str(tmp_path/'gov.db'); monkeypatch.setattr(gov,'DB_PATH',db); rm.init_db(); now='2026-07-18T12:00:00+00:00'; cid='candidate-9c'
    with rm._conn() as c:
        c.execute("INSERT INTO model_registry(candidate_id,candidate_type,version,status,created_at,created_by,baseline_version,dataset_hash,config_json,metrics_json,limitations_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(cid,'WEIGHT','v3','SHADOW_ONLY',now,'TEST','champion-v1','hash','{}','{}','[]'))
        c.execute("INSERT INTO shadow_campaigns VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",('campaign-9c',cid,'champion-v1','READY_FOR_REVIEW',now,now,now,1,1,30,'[]','{}','v1','hash',None,'{}'))
        c.execute("INSERT INTO promotion_review_packages VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",('pkg-9c','campaign-9c',cid,now,'ELIGIBLE_FOR_PRODUCTION_REVIEW','{}','{}','{}','{}','[]','hash','READY'))
        c.execute("INSERT OR REPLACE INTO champion_registry VALUES(?,?,?,?,?,?)",('decision_weights','champion-v1',None,now,'TEST','{}'))
    pid=pg.create_promotion({'package_id':'pkg-9c','proposed_version':'challenger-v3'})['promotion_id']
    for role in pg.REQUIRED_ROLES: pg.decide(pid,role,'APPROVE',actor=role)
    mid=pg.queue(pid)['manifest_id']
    canid=None
    if with_canary: canid=cd.create({'manifest_id':mid,'exposure_pct':5})['canary_id']
    return mid,canid


def test_release_requires_approved_manifest_and_matching_canary(monkeypatch,tmp_path):
    mid,cid=seed(monkeypatch,tmp_path)
    assert not rm.create({'manifest_id':'missing'})['ok']
    x=rm.create({'manifest_id':mid,'canary_id':cid,'release_name':'9C release'})
    assert x['ok'] and x['status']=='OPEN'
    assert rm.release(x['release_id'])['challenger_version']=='challenger-v3'


def test_release_identity_is_unique_and_immutable(monkeypatch,tmp_path):
    mid,cid=seed(monkeypatch,tmp_path)
    first=rm.create({'manifest_id':mid,'canary_id':cid})
    assert first['ok']
    assert not rm.create({'manifest_id':mid,'canary_id':cid})['ok']
    assert len(first['integrity_hash'])==64


def test_health_uses_real_canary_records(monkeypatch,tmp_path):
    mid,cid=seed(monkeypatch,tmp_path); rid=rm.create({'manifest_id':mid,'canary_id':cid})['release_id']
    cd.transition(cid,'start'); cd.route(cid,'rec-a',record=True); cd.health(cid,{'samples':1,'error_rate':0,'divergence_rate':0,'consecutive_errors':0})
    h=rm.capture_health(rid)
    assert h['ok'] and h['metrics']['routing_samples']==1
    assert rm.health_snapshots(rid)[0]['source']['real_events_only'] is True


def test_close_requires_terminal_canary_and_never_replaces_champion(monkeypatch,tmp_path):
    mid,cid=seed(monkeypatch,tmp_path); rid=rm.create({'manifest_id':mid,'canary_id':cid})['release_id']
    cd.transition(cid,'start')
    assert not rm.close(rid)['ok']
    cd.transition(cid,'complete')
    x=rm.close(rid,actor='owner')
    assert x['ok'] and x['champion_replaced'] is False


def test_routes_and_dashboard_present():
    routes=open('engine/institutional_roadmap_routes.py').read()
    assert '/api/production/releases/status' in routes
    assert '/api/production/releases/<release_id>/health' in routes
    assert '/apex_os/release_manager' in routes
    assert 'Automatic Champion Replacement' in open('templates/institutional_release_manager.html').read()
