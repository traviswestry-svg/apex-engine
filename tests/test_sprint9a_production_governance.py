import hashlib, json
from engine import institutional_governance as gov
from engine import shadow_validation
from engine import production_governance as pg


def seed(monkeypatch,tmp_path):
    db=str(tmp_path/'gov.db'); monkeypatch.setattr(gov,'DB_PATH',db); pg.init_db()
    cid='candidate-9a'; now='2026-07-18T12:00:00+00:00'
    with pg._conn() as c:
        c.execute("INSERT INTO model_registry(candidate_id,candidate_type,version,status,created_at,created_by,baseline_version,dataset_hash,config_json,metrics_json,limitations_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(cid,'WEIGHT','v1','SHADOW_ONLY',now,'TEST','champion-v1','hash','{}','{}','[]'))
        c.execute("INSERT INTO shadow_campaigns VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",('campaign-9a',cid,'champion-v1','READY_FOR_REVIEW',now,now,now,1,1,30,'[]','{}','v1','hash',None,'{}'))
        c.execute("INSERT INTO promotion_review_packages VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",('pkg-9a','campaign-9a',cid,now,'ELIGIBLE_FOR_PRODUCTION_REVIEW','{}','{}','{}','{}','[]','hash','READY'))
        c.execute("INSERT OR REPLACE INTO champion_registry VALUES(?,?,?,?,?,?)",('decision_weights','champion-v1',None,now,'TEST','{}'))
    return cid

def test_requires_eligible_package(monkeypatch,tmp_path):
    seed(monkeypatch,tmp_path)
    x=pg.create_promotion({'package_id':'missing'})
    assert not x['ok']

def test_three_roles_required_before_queue(monkeypatch,tmp_path):
    seed(monkeypatch,tmp_path)
    x=pg.create_promotion({'package_id':'pkg-9a','proposed_version':'challenger-v2'},actor='owner')
    pid=x['promotion_id']
    assert pg.queue(pid)['status']=='APPROVAL_REQUIRED'
    assert pg.decide(pid,'SYSTEM_ARCHITECTURE','APPROVE',actor='a')['status']=='PARTIALLY_APPROVED'
    assert pg.decide(pid,'TRADING_LOGIC','APPROVE',actor='b')['status']=='PARTIALLY_APPROVED'
    assert pg.decide(pid,'RISK_CONTROLS','APPROVE',actor='c')['status']=='APPROVED_FOR_QUEUE'
    q=pg.queue(pid,actor='owner')
    assert q['status']=='QUEUED_NOT_DEPLOYED' and q['production_effect']=='NONE'
    assert pg.status()['production_mutation_enabled'] is False

def test_duplicate_role_and_package_blocked(monkeypatch,tmp_path):
    seed(monkeypatch,tmp_path)
    pid=pg.create_promotion({'package_id':'pkg-9a'})['promotion_id']
    assert pg.decide(pid,'SYSTEM_ARCHITECTURE','APPROVE')['ok']
    assert not pg.decide(pid,'SYSTEM_ARCHITECTURE','APPROVE')['ok']
    assert not pg.create_promotion({'package_id':'pkg-9a'})['ok']

def test_rejection_is_terminal(monkeypatch,tmp_path):
    seed(monkeypatch,tmp_path)
    pid=pg.create_promotion({'package_id':'pkg-9a'})['promotion_id']
    r=pg.decide(pid,'RISK_CONTROLS','REJECT',note='risk failure')
    assert r['status']=='REJECTED'
    assert not pg.decide(pid,'TRADING_LOGIC','APPROVE')['ok']

def test_manifest_hash_and_dashboard_routes(monkeypatch,tmp_path):
    seed(monkeypatch,tmp_path)
    pid=pg.create_promotion({'package_id':'pkg-9a'})['promotion_id']
    for role in pg.REQUIRED_ROLES: pg.decide(pid,role,'APPROVE',actor=role)
    pg.queue(pid)
    m=pg.manifests()[0]
    assert hashlib.sha256(m['manifest_json'].encode()).hexdigest()==m['integrity_hash']
    routes=open('engine/institutional_roadmap_routes.py').read()
    assert "/api/production/status" in routes
    assert "/apex_os/production_governance" in routes
