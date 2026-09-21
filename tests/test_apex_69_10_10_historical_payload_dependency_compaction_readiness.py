import json
import sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_release_truth_and_compaction_guardrails():
    manifest=json.loads((ROOT/'config/apex_release_manifest.json').read_text())
    assert manifest['apex_version']==manifest['semantic_version']==manifest['application_version']=='69.10.16'
    assert manifest['build_name']=='Canonical Settlement Identity & Decision Gamma Linkage Closure'
    g=manifest['guardrails']
    assert g['historical_payload_dependency_audit'] is True
    assert g['historical_payload_compaction_readiness_read_only'] is True
    assert g['historical_payload_rewrite_enabled'] is False
    assert g['historical_payload_archival_sidecar_required_before_lossy_rewrite'] is True
    registry=(ROOT/'config/apex_capability_registry.yaml').read_text()
    assert 'apex_version: 69.10.16' in registry
    assert 'historical_evidence_payload_dependency_compaction_readiness:' in registry


def _trigger_db(path):
    from engine.trigger_observatory import initialize_store
    initialize_store(str(path), reconcile=False)
    huge={'decision':{'decision_id':'d1','action':'NO_TRADE','narrative':'x'*100000},'bulk':'y'*100000,
          'entry_premium':12.5,'pine':{'target1_premium':14.0}}
    with sqlite3.connect(path) as c:
        c.execute("""INSERT INTO observed_trade_triggers(
            trigger_id,source_event_key,source,trigger_type,setup_family,symbol,direction,disposition,
            triggered_at,observed_at,blocker_codes_json,evidence_json,etrade_handoff_json,status,
            observation_count,observation_window_seconds,execution_authority,broker_mutation,
            production_effect,decision_id,canonical_grade_status,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ('t1','e1','TEST','ENTER','TEST','SPX','BULLISH','OBSERVED','2026-08-25T12:00:00+00:00',
             '2026-08-25T12:00:00+00:00','[]',json.dumps(huge),'{}','OBSERVED',1,300,0,0,
             'OBSERVATIONAL_ONLY','d1','GRADED','2026-08-25T12:00:00+00:00','2026-08-25T12:00:00+00:00'))
        c.commit()


def _evidence_db(path):
    from engine.evidence_pipeline import _connect
    huge={'decision_id':'d1','timestamp':'2026-08-25T12:00:00+00:00','ticker':'SPX','action':'NO_TRADE',
          'direction':'NEUTRAL','learning_eligible':False,'eligibility_reason':'TEST',
          'institutional_decision_object':{'action':'NO_TRADE','narrative':'x'*200000},
          'runtime_bulk':'z'*300000}
    with _connect(path) as c:
        c.execute("INSERT INTO decisions(decision_id,observed_at,ticker,session,direction,action,entry_price,confidence,learning_eligible,snapshot_json,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  ('d1','2026-08-25T12:00:00+00:00','SPX','RTH','NEUTRAL','NO_TRADE',None,50,0,json.dumps(huge),'GRADED'))
        c.commit()


def test_bounded_read_only_compaction_readiness_reports_savings_and_blocks_rewrite(tmp_path):
    from engine.historical_payload_compaction import audit_historical_payload_compaction
    t=tmp_path/'trigger.db'; e=tmp_path/'evidence.db'
    _trigger_db(t); _evidence_db(e)
    before_t=t.read_bytes(); before_e=e.read_bytes()
    out=audit_historical_payload_compaction(trigger_path=t,evidence_path=e,exhaustive=False,sample_limit=10)
    assert out['ok'] is True and out['mode']=='READ_ONLY_BOUNDED'
    assert out['compaction_readiness']['ready_for_historical_rewrite'] is False
    assert out['compaction_readiness']['state']=='FOUNDATION_IMPLEMENTED_AWAITING_ARCHIVE_AND_SHADOW_VALIDATION'
    assert out['trigger_observatory']['logical_reduction_bytes_scanned'] > 0
    assert out['evidence_pipeline']['logical_reduction_bytes_scanned'] > 0
    assert out['guardrails']['historical_rows_mutated'] is False
    assert out['guardrails']['payload_values_exposed'] is False
    assert t.read_bytes()==before_t and e.read_bytes()==before_e


def test_exhaustive_operator_scan_is_exact_but_still_read_only(tmp_path):
    from engine.historical_payload_compaction import audit_historical_payload_compaction
    t=tmp_path/'trigger.db'; e=tmp_path/'evidence.db'
    _trigger_db(t); _evidence_db(e)
    out=audit_historical_payload_compaction(trigger_path=t,evidence_path=e,exhaustive=True)
    assert out['mode']=='READ_ONLY_EXHAUSTIVE'
    assert out['trigger_observatory']['estimate_is_exact'] is True
    assert out['evidence_pipeline']['estimate_is_exact'] is True
    assert out['compaction_readiness']['destructive_in_place_rewrite_recommended'] is False


def test_dependency_contract_captures_source_verified_consumers():
    from engine.historical_payload_compaction import TRIGGER_EVIDENCE_DEPENDENCIES, DECISION_SNAPSHOT_DEPENDENCIES
    assert 'engine.trigger_observatory.history' in TRIGGER_EVIDENCE_DEPENDENCIES['full_payload_consumers']
    assert 'engine.trigger_observatory.trade_visualization._premium_projection' in TRIGGER_EVIDENCE_DEPENDENCIES['field_consumers']
    assert 'engine.outcome_grader' in DECISION_SNAPSHOT_DEPENDENCIES['field_consumers']
    assert 'engine.dynamic_state_outcome_calibration' in DECISION_SNAPSHOT_DEPENDENCIES['field_consumers']


def test_operator_cli_exposes_read_only_exhaustive_action():
    text=(ROOT/'scripts/apex_storage_maintenance.py').read_text()
    assert 'payload-compaction-readiness' in text
    assert 'audit_historical_payload_compaction(exhaustive=True)' in text
    assert 'parser.error("payload-compaction-readiness is read-only; --apply is not supported")' in text
