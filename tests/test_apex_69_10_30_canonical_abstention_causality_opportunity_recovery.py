import json
import sqlite3
from pathlib import Path

from engine import abstention_causality as ac


def _db(tmp_path: Path):
    p=tmp_path/'e.db'; c=sqlite3.connect(p)
    c.executescript('''
    CREATE TABLE decision_effectiveness_attribution(
      decision_id TEXT PRIMARY KEY,captured_at TEXT,ticker TEXT,action_class TEXT,action TEXT,direction TEXT,
      confidence REAL,horizon_seconds INTEGER,directional_move REAL,mfe REAL,mae REAL,missed_opportunity INTEGER,
      protective_abstention INTEGER,gates_json TEXT,outcome_json TEXT,status TEXT);
    ''')
    return p,c


def _insert(c, did, at, missed, protective, direction='BULLISH'):
    gates=[
      {'gate':'decision_state','state':'NO_TRADE','blocked':True},
      {'gate':'institutional_decision_object.decision_state','state':'NO_TRADE','blocked':True},
      {'gate':'institutional_decision_object.engine_opinions[2].evidence_eligibility.state','state':'INELIGIBLE','blocked':False},
      {'gate':'dynamic_state.flow_excitation.state','state':'NO_FLOW','blocked':False},
    ]
    c.execute('INSERT INTO decision_effectiveness_attribution VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
      (did,at,'SPX','ABSTAIN','NO_TRADE',direction,80,300,10 if missed else -1,12 if missed else 0,-2,missed,protective,json.dumps(gates),'{}','GRADED'))


def test_mirrored_paths_collapse_and_contributors_are_not_promoted_to_blockers():
    x=ac._canonicalize_gates([
      {'gate':'decision_state','state':'NO_TRADE','blocked':True},
      {'gate':'institutional_decision_object.decision_state','state':'NO_TRADE','blocked':True},
      {'gate':'institutional_decision_object.engine_opinions[2].evidence_eligibility.state','state':'INELIGIBLE','blocked':False},
    ])
    assert x['families']['DECISION_AUTHORITY']['authoritative_block'] is True
    assert len(x['families']['DECISION_AUTHORITY']['explicit_block_paths']) == 2
    assert x['families']['EVIDENCE_ELIGIBILITY']['authoritative_block'] is False
    assert x['families']['EVIDENCE_ELIGIBILITY']['contributor_states']['INELIGIBLE'] == 1


def test_opportunity_cluster_deduplicates_repeated_scanner_observations(tmp_path):
    p,c=_db(tmp_path)
    _insert(c,'a','2026-10-02T13:25:00+00:00',1,0)
    _insert(c,'b','2026-10-02T13:27:00+00:00',1,0)
    _insert(c,'c','2026-10-02T13:31:00+00:00',1,0)  # > 5m from anchor => new cluster
    c.commit(); c.close()
    clusters=ac.opportunity_clusters(p)
    assert len(clusters)==2
    assert clusters[0]['observations']==2
    assert clusters[1]['observations']==1
    assert clusters[0]['cluster_id'].startswith('aoc_')


def test_summary_is_observational_and_separates_explicit_from_contributor(tmp_path):
    p,c=_db(tmp_path)
    _insert(c,'a','2026-10-02T13:25:00+00:00',1,0)
    _insert(c,'b','2026-10-02T13:40:00+00:00',0,1)
    c.commit(); c.close()
    s=ac.summary(p)
    assert s['counts']['missed_observations']==1
    assert s['counts']['protective_observations']==1
    assert s['opportunity_clusters']['count']==1
    assert s['governance']['changes_trade_decisions'] is False
    assert s['governance']['automatic_promotion'] is False
    fam={x['family']:x for x in s['family_effectiveness']}
    assert fam['DECISION_AUTHORITY']['explicitly_blocked_abstentions']==2
    assert fam['EVIDENCE_ELIGIBILITY']['explicitly_blocked_abstentions']==0


def test_release_metadata_ratchets_to_691031():
    root=Path(__file__).resolve().parents[1]
    m=json.loads((root/'config/apex_release_manifest.json').read_text())
    assert m['apex_version']==m['semantic_version']==m['application_version']=='69.10.32.1'
    assert m['build_name']=='Session Calendar Integrity Closure'
    registry=(root/'config/apex_capability_registry.yaml').read_text()
    assert 'apex_version: 69.10.32' in registry
    assert 'canonical_abstention_causality_opportunity_recovery_intelligence:' in registry
