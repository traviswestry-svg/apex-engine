import sqlite3
from pathlib import Path

from engine import evidence_accumulation_observatory as obs


def _db(path, schema, inserts=()):
    c=sqlite3.connect(path)
    c.executescript(schema)
    for sql, args in inserts:
        c.execute(sql,args)
    c.commit(); c.close()


def test_observatory_reports_hlce_lifecycle_without_mutation(tmp_path, monkeypatch):
    cal=tmp_path/'cal.db'
    _db(cal, '''
      CREATE TABLE daily_levels(registered_at TEXT);
      CREATE TABLE level_price_samples(ts TEXT);
      CREATE TABLE level_interactions(ts TEXT, graded INTEGER);
      CREATE TABLE level_outcomes(graded_at TEXT);
      CREATE TABLE calibration_statistics(id INTEGER);
    ''', [
      ("INSERT INTO daily_levels VALUES(?)",('2026-08-03T13:30:00+00:00',)),
      ("INSERT INTO level_price_samples VALUES(?)",('2026-08-03T13:31:00+00:00',)),
    ])
    monkeypatch.setattr(obs,'_resolved_paths',lambda:{'calibration':str(cal),'market_memory':None,'governance':None,'similarity':None,'research':None,'evidence':None})
    out=obs.build_observatory()
    c=out['stores']['calibration']
    assert c['counts']['daily_levels']==1
    assert c['counts']['price_samples']==1
    assert c['first_blocked_stage']=='INTERACTION_DETECTION'
    assert c['state']=='ACCUMULATING'
    assert out['guardrails']['decision_influence']=='NONE'


def test_cross_store_growth_is_visible(tmp_path, monkeypatch):
    paths={k:str(tmp_path/f'{k}.db') for k in ['calibration','market_memory','governance','similarity','research','evidence']}
    _db(paths['calibration'],'''CREATE TABLE daily_levels(registered_at TEXT); CREATE TABLE level_price_samples(ts TEXT); CREATE TABLE level_interactions(ts TEXT,graded INTEGER); CREATE TABLE level_outcomes(graded_at TEXT); CREATE TABLE calibration_statistics(id INTEGER);''')
    _db(paths['market_memory'],'''CREATE TABLE market_memory_sessions(observed_at TEXT,outcome_status TEXT);''',[("INSERT INTO market_memory_sessions VALUES(?,?)",('x','PENDING'))])
    _db(paths['governance'],'''CREATE TABLE historical_events(id INTEGER); CREATE TABLE graded_outcomes(graded_at TEXT); CREATE TABLE feature_vectors(id INTEGER); CREATE TABLE model_registry(id INTEGER); CREATE TABLE shadow_results(id INTEGER);''')
    _db(paths['similarity'],'''CREATE TABLE institutional_feature_vectors(observed_at TEXT); CREATE TABLE similarity_queries(id INTEGER);''')
    _db(paths['research'],'''CREATE TABLE research_runs(created_at TEXT); CREATE TABLE research_findings(id INTEGER);''')
    _db(paths['evidence'],'''CREATE TABLE evidence_packages(created_at TEXT); CREATE TABLE evidence_snapshots(id INTEGER); CREATE TABLE evidence_timeline(id INTEGER); CREATE TABLE evidence_integrity_results(id INTEGER);''',[("INSERT INTO evidence_packages VALUES(?)",('x',))])
    monkeypatch.setattr(obs,'_resolved_paths',lambda:paths)
    out=obs.build_observatory()
    assert out['stores']['market_memory']['state']=='ACCUMULATING'
    assert out['stores']['evidence']['state']=='ACCUMULATING'
    assert 'governance' in out['summary']['cold']
    assert out['state']=='PARTIAL_ACCUMULATION'


def test_missing_db_is_reported_not_created(tmp_path):
    missing=tmp_path/'never_create.db'
    out=obs._query(str(missing), {'x':'SELECT 1'})
    assert out['state']=='NOT_CREATED'
    assert not missing.exists()


def test_routes_register_and_remain_read_only(monkeypatch):
    import pytest
    Flask = pytest.importorskip("flask").Flask
    from engine import evidence_accumulation_routes as routes
    app=Flask(__name__)
    monkeypatch.setattr(routes,'build_observatory',lambda:{'ok':True,'state':'PARTIAL_ACCUMULATION','summary':{'accumulating':['calibration'],'cold':['governance'],'errors':[]},'generated_at':'x'})
    routes.register_evidence_accumulation_routes(app)
    client=app.test_client()
    r=client.get('/api/learning/evidence-readiness/health')
    assert r.status_code==200
    assert r.get_json()['state']=='PARTIAL_ACCUMULATION'
    methods={rule.rule:set(rule.methods) for rule in app.url_map.iter_rules()}
    assert methods['/api/learning/evidence-readiness'] <= {'GET','HEAD','OPTIONS'}
    assert methods['/api/learning/evidence-readiness/health'] <= {'GET','HEAD','OPTIONS'}
