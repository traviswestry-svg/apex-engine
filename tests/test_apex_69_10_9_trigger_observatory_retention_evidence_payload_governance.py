import json, sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_release_truth_and_guardrails():
    m=json.loads((ROOT/'config/apex_release_manifest.json').read_text())
    assert m['apex_version']==m['semantic_version']==m['application_version']=='69.10.9'
    assert m['build_name']=='Trigger Observatory Retention & Evidence Payload Governance'
    g=m['guardrails']
    assert g['automatic_trigger_pruning'] is False
    assert g['trigger_observatory_prune_explicit_apply_only'] is True
    assert g['trigger_observatory_open_rows_protected'] is True
    assert g['trigger_observatory_unlinked_rows_protected'] is True
    assert g['historical_trigger_rows_rewritten'] is False

def test_future_trigger_evidence_is_bounded(tmp_path):
    from engine.trigger_observatory import record_trigger, MAX_EVIDENCE_JSON_BYTES
    db=tmp_path/'triggers.db'
    huge={'decision':{'decision_id':'d1','action':'NO_TRADE','narrative':'x'*100000},'bulk':'y'*100000}
    out=record_trigger(source='TEST',trigger_type='ENTER',symbol='SPX',direction='BULLISH',price=6000,
                       source_event_key='bounded-1',decision_id='d1',evidence=huge,path=str(db))
    assert out['created'] is True
    with sqlite3.connect(db) as c:
        raw=c.execute('select evidence_json from observed_trade_triggers').fetchone()[0]
    assert len(raw.encode()) <= MAX_EVIDENCE_JSON_BYTES
    payload=json.loads(raw)
    assert payload['storage_projection']['projection_version']=='69.10.9'
    assert 'narrative' not in payload.get('decision',{})

def _seed_trigger_db(path):
    from engine.trigger_observatory import initialize_store
    initialize_store(str(path),reconcile=False)
    old=(datetime.now(timezone.utc)-timedelta(days=45)).isoformat(); now=datetime.now(timezone.utc).isoformat()
    def add(c,tid,event,status,decision,grade,when):
        c.execute("""insert into observed_trade_triggers(trigger_id,source_event_key,source,trigger_type,setup_family,symbol,direction,disposition,triggered_at,observed_at,blocker_codes_json,evidence_json,etrade_handoff_json,status,observation_count,observation_window_seconds,execution_authority,broker_mutation,production_effect,decision_id,canonical_grade_status,created_at,updated_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(tid,event,'TEST','ENTER','TEST','SPX','BULLISH','OBSERVED',when,when,'[]','{}','{}',status,1,300,0,0,'OBSERVATIONAL_ONLY',decision,grade,when,when))
    with sqlite3.connect(path) as c:
        add(c,'t1','e1','OBSERVED','d1','GRADED',old)
        add(c,'t2','e2','OBSERVED',None,None,old)
        add(c,'t3','e3','OBSERVING','d3',None,now)
        c.execute("insert into trade_trigger_price_observations(observation_id,trigger_id,observed_at,price,favorable_points,adverse_points,created_at) values('o1','t1',?,6001,1,0,?)",(old,old)); c.commit()

def test_trigger_retention_audit_and_explicit_prune(tmp_path):
    from engine.storage_retention import _trigger_retention_audit, prune_mature_trigger_observations
    db=tmp_path/'triggers.db'; _seed_trigger_db(db)
    audit=_trigger_retention_audit(db,30)
    assert audit['eligible_terminal_linked_graded_rows']==1
    assert audit['protected_old_unlinked_rows']==1
    dry=prune_mature_trigger_observations(db,30,apply=False)
    assert dry['eligible_rows']==1 and dry['deleted_rows']==0
    applied=prune_mature_trigger_observations(db,30,apply=True)
    assert applied['deleted_rows']==1 and applied['deleted_child_price_rows']==1
    with sqlite3.connect(db) as c:
        assert c.execute('select count(*) from observed_trade_triggers').fetchone()[0]==2

def test_decision_snapshot_hard_guardrail():
    from engine.evidence_pipeline import _persisted_snapshot_projection, MAX_PERSISTED_SNAPSHOT_BYTES
    snap={'decision_id':'d','timestamp':'2026-09-14T12:00:00+00:00','ticker':'SPX','action':'NO_TRADE','institutional_decision_object':{'action':'NO_TRADE'},'runtime_bulk':'z'*500000}
    projected=_persisted_snapshot_projection(snap)
    raw=json.dumps(projected,separators=(',',':'),sort_keys=True,default=str).encode()
    assert len(raw) <= MAX_PERSISTED_SNAPSHOT_BYTES
    assert projected['storage_projection']['hard_size_guardrail_applied'] is True
    assert 'runtime_bulk' not in projected
