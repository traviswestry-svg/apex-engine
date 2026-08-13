import sqlite3
from engine import institutional_governance as gov
from engine import decision_intelligence_core as core
from engine import institutional_replay_2 as replay


def sample():
    return {'ticker':'SPX','decision_state':'ENTER','market_state':{'ticker':'SPX'},'recommendation':{'action':'ENTER','strategy':'CALL'},'evidence':{'auction':{'state':'ACCEPTED_HIGHER'}},'provider_health':{'polygon':True}}


def test_replay_is_immutable_and_idempotent(monkeypatch,tmp_path):
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'a.db')); cap=core.capture(sample(),recommendation_id='r-105a')
    a=replay.create(cap['decision_id']); b=replay.create(cap['decision_id'])
    assert a['created'] is True and b['status']=='IMMUTABLE_EXISTS' and a['integrity_hash']==b['integrity_hash']


def test_replay_blocks_future_information_and_outcome(monkeypatch,tmp_path):
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'a.db')); cap=core.capture(sample(),recommendation_id='r-105b')
    replay.create(cap['decision_id']); out=replay.get(cap['decision_id'])
    assert out['replay']['future_information_included'] is False and out['replay']['outcome'] is None
    assert all(f['look_ahead_blocked'] for f in out['replay']['frames'])


def test_replay_preserves_ordered_decision_evolution(monkeypatch,tmp_path):
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'a.db')); cap=core.capture(sample(),recommendation_id='r-105c')
    rec=core.get(cap['decision_id'])
    with sqlite3.connect(gov.DB_PATH) as c:
        c.execute("DELETE FROM decision_timeline_records WHERE decision_id=?",(cap['decision_id'],))
        c.execute("INSERT INTO decision_timeline_records VALUES(?,?,?,?,?,?,?)",('t1',cap['decision_id'],'2026-07-18T13:58:00+00:00','EVIDENCE_ADDED','{"confidence":70,"recommendation":"WATCH"}','test','h1'))
        c.execute("INSERT INTO decision_timeline_records VALUES(?,?,?,?,?,?,?)",('t2',cap['decision_id'],rec['observed_at'],'DECISION_CAPTURED','{"confidence":82,"recommendation":"CALL"}','test','h2'))
    replay.create(cap['decision_id']); frames=replay.get(cap['decision_id'])['replay']['frames']
    assert [f['confidence'] for f in frames]==[70,82] and frames[-1]['recommendation']=='CALL'


def test_status_is_non_mutating(monkeypatch,tmp_path):
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'a.db')); s=replay.status()
    assert s['production_effect']=='NONE' and not s['decision_mutation_enabled'] and not s['confidence_mutation_enabled']


def test_routes_and_dashboard_exist():
    routes=open('engine/institutional_roadmap_routes.py').read(); html=open('templates/institutional_replay_2.html').read()
    assert '/api/replay2/<identifier>/build' in routes and '/api/replay2/status' in routes and '/apex_os/institutional_replay' in routes
    assert 'Look-ahead blocked' in html and 'Outcomes excluded' in html
