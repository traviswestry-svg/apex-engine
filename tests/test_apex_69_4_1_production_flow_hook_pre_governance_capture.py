import json
from pathlib import Path


def test_release_truth_6941():
    d=json.loads(Path('config/apex_release_manifest.json').read_text())
    assert tuple(map(int,d['apex_version'].split('.'))) >= (69,4,1)
    assert d['guardrails']['observational_no_trade_does_not_change_execution_authority'] is True
    assert d['guardrails']['observational_no_trade_excluded_from_adaptive_promotion'] is True
    assert d['guardrails']['canonical_flow_identity_mapping_required'] is True


def test_flow_live_path_uses_persisted_identity_mapping():
    src=Path('engine/flow_pl_pipeline.py').read_text()
    assert 'resolve_sample_identity' in src
    assert 'make_sample_id' not in src[src.index('APEX 69.4.1: live excursion capture'):src.index('sources.append(src)', src.index('APEX 69.4.1: live excursion capture'))]
    assert 'missing_feature=1' in src


def test_feature_writer_registers_exact_identity():
    src=Path('engine/feature_store_writer.py').read_text()
    assert 'register_sample_identity' in src
    assert 'FEATURE_STORE_WRITER' in src
    assert 'register_sample_identity' in src


def test_no_trade_can_be_observational_but_not_execution_actionable():
    from engine.historical_evidence_lifecycle import build_snapshot
    result={
      'session':'RTH',
      'institutional_decision_object':{
        'ticker':'SPX','timestamp':'2026-08-25T14:00:00+00:00','action':'NO_TRADE',
        'direction':'BULLISH','actionable':False,
        'market_state':{'price':6500.0},
        'institutional_thesis':{'dominant_direction':'BULLISH','state':'ACTIVE','current_thesis':'up'},
        'consensus':{'dominant_direction':'BULLISH'},
        'conviction':{'score':60,'raw_conviction':62,'calibrated_conviction':60},
      }
    }
    s=build_snapshot(result,session_state='RTH')
    assert s['action']=='NO_TRADE'
    assert s['actionable'] is False
    assert s['execution_actionable'] is False
    assert s['learning_eligible'] is True
    assert s['observational_only'] is True
    assert s['eligibility_reason']=='OBSERVATIONAL_DIRECTIONAL_THESIS'
    assert s['pre_governance_decision']['direction']=='BULLISH'


def test_observational_grades_do_not_feed_adaptive_learning_source_contract():
    src=Path('engine/outcome_grader.py').read_text()
    assert "if not bool(snap.get('observational_only'))" in src
