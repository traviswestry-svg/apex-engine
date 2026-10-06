import json, sqlite3
from pathlib import Path
from engine import session_phase_excursion_attribution as sea


def _db(tmp_path):
    p=tmp_path/'e.db'; c=sqlite3.connect(p)
    c.executescript('''CREATE TABLE decision_effectiveness_attribution(
      decision_id TEXT PRIMARY KEY,captured_at TEXT,ticker TEXT,action_class TEXT,action TEXT,direction TEXT,
      confidence REAL,horizon_seconds INTEGER,directional_move REAL,mfe REAL,mae REAL,missed_opportunity INTEGER,
      protective_abstention INTEGER,gates_json TEXT,outcome_json TEXT,status TEXT);''')
    return p,c


def _add(c,did,at,missed,protective,mfe,mae):
    gates=[{'gate':'decision_state','state':'NO_TRADE','blocked':True}]
    c.execute('INSERT INTO decision_effectiveness_attribution VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
      (did,at,'SPX','ABSTAIN','NO_TRADE','BULLISH',70,300,5 if missed else -1,mfe,mae,missed,protective,json.dumps(gates),'{}','GRADED'))


def test_entry_anchor_projection_is_read_only_and_sign_consistent():
    x=sea.canonical_excursion(-0.77, 4.2)
    assert x['stored_mfe']==-0.77 and x['stored_mae']==4.2
    assert x['canonical_mfe']==0.0 and x['canonical_mae']==0.0
    assert x['projection_only'] is True


def test_session_phase_boundaries_are_new_york_time():
    assert sea.session_phase('2026-10-02T13:29:59+00:00')=='PREMARKET'
    assert sea.session_phase('2026-10-02T13:30:00+00:00')=='OPEN_DISCOVERY'
    assert sea.session_phase('2026-10-02T14:00:00+00:00')=='MORNING_DEVELOPMENT'
    assert sea.session_phase('2026-10-02T15:00:00+00:00')=='LATE_MORNING'
    assert sea.session_phase('2026-10-02T15:30:00+00:00')=='MIDDAY'
    assert sea.session_phase('2026-10-02T17:00:00+00:00')=='AFTERNOON'


def test_summary_preserves_evidence_and_attributes_both_classes(tmp_path):
    p,c=_db(tmp_path)
    _add(c,'m','2026-10-02T13:35:00+00:00',1,0,-1,3)
    _add(c,'p','2026-10-02T13:45:00+00:00',0,1,0,-2)
    c.commit(); c.close(); s=sea.summary(p)
    assert s['excursion_semantics']['stored_negative_mfe_rows']==1
    assert s['excursion_semantics']['stored_positive_mae_rows']==1
    assert s['excursion_semantics']['canonical_projection_status']=='CONSISTENT'
    assert s['excursion_semantics']['historical_rows_mutated'] is False
    op=[x for x in s['session_phase_attribution'] if x['session_phase']=='OPEN_DISCOVERY'][0]
    assert op['clusters']==2 and op['missed_clusters']==1 and op['protective_clusters']==1
    assert s['governance']['changes_trade_decisions'] is False
    assert s['governance']['changes_execution_authority'] is False


def test_release_metadata_ratchets_to_691032():
    root=Path(__file__).resolve().parents[1]
    m=json.loads((root/'config/apex_release_manifest.json').read_text())
    assert m['apex_version']==m['semantic_version']==m['application_version']=='69.10.36'
    assert m['build_name']=='Canonical Feature Lifecycle & Excursion Ownership Convergence'
    registry=(root/'config/apex_capability_registry.yaml').read_text()
    assert 'apex_version: 69.10.36' in registry
    assert 'canonical_excursion_session_phase_attribution:' in registry
