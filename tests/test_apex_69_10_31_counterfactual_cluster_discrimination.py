import json, sqlite3
from pathlib import Path
from engine import counterfactual_cluster_discrimination as ccd


def _db(tmp_path):
    p=tmp_path/'e.db'; c=sqlite3.connect(p)
    c.executescript('''CREATE TABLE decision_effectiveness_attribution(
      decision_id TEXT PRIMARY KEY,captured_at TEXT,ticker TEXT,action_class TEXT,action TEXT,direction TEXT,
      confidence REAL,horizon_seconds INTEGER,directional_move REAL,mfe REAL,mae REAL,missed_opportunity INTEGER,
      protective_abstention INTEGER,gates_json TEXT,outcome_json TEXT,status TEXT);''')
    return p,c


def _add(c,did,at,missed,protective,confidence=70,direction='BULLISH',mae=-1):
    gates=[{'gate':'decision_state','state':'NO_TRADE','blocked':True},{'gate':'dynamic_state.flow_excitation.state','state':'NO_FLOW','blocked':False}]
    c.execute('INSERT INTO decision_effectiveness_attribution VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
      (did,at,'SPX','ABSTAIN','NO_TRADE',direction,confidence,300,8 if missed else -2,9 if missed else 0,mae,missed,protective,json.dumps(gates),'{}','GRADED'))


def test_both_classes_use_identical_anchor_horizon_clustering(tmp_path):
    p,c=_db(tmp_path)
    _add(c,'m1','2026-10-02T13:25:00+00:00',1,0); _add(c,'m2','2026-10-02T13:27:00+00:00',1,0)
    _add(c,'p1','2026-10-02T13:25:30+00:00',0,1); _add(c,'p2','2026-10-02T13:27:30+00:00',0,1)
    c.commit(); c.close(); xs=ccd.clusters(p)
    assert len(xs)==2
    assert {x['classification'] for x in xs}=={'MISSED_OPPORTUNITY','PROTECTIVE_ABSTENTION'}
    assert all(x['observations']==2 for x in xs)


def test_discrimination_is_base_rate_adjusted_and_decision_time_only(tmp_path):
    p,c=_db(tmp_path)
    _add(c,'m','2026-10-02T13:35:00+00:00',1,0,95)
    _add(c,'p','2026-10-02T14:35:00+00:00',0,1,55)
    c.commit(); c.close(); s=ccd.summary(p)
    assert s['cluster_counts']['missed']==1 and s['cluster_counts']['protective']==1
    assert s['cluster_counts']['baseline_missed_rate_pct']==50.0
    assert s['governance']['decision_time_features_only_for_discrimination'] is True
    assert s['governance']['outcome_excursions_excluded_from_discriminators'] is True
    assert s['governance']['automatic_promotion'] is False


def test_excursion_semantics_fail_closed_without_repair(tmp_path):
    p,c=_db(tmp_path); _add(c,'m','2026-10-02T13:35:00+00:00',1,0,70,mae=5); c.commit(); c.close()
    s=ccd.summary(p)
    assert s['excursion_semantics']['status']=='INCONSISTENT'
    assert s['excursion_semantics']['positive_mae_rows']==1
    assert s['excursion_semantics']['excursions_eligible_as_discriminators'] is False


def test_release_metadata_ratchets_to_691031():
    root=Path(__file__).resolve().parents[1]
    m=json.loads((root/'config/apex_release_manifest.json').read_text())
    assert m['apex_version']==m['semantic_version']==m['application_version']=='69.10.32.1'
    assert m['build_name']=='Session Calendar Integrity Closure'
    registry=(root/'config/apex_capability_registry.yaml').read_text()
    assert 'apex_version: 69.10.32' in registry
    assert 'counterfactual_cluster_discrimination_intelligence:' in registry
