import importlib.util
import json
from pathlib import Path

_MODULE = Path(__file__).resolve().parents[1] / 'engine' / 'heartbeat_payload_budget.py'
spec = importlib.util.spec_from_file_location('apex_heartbeat_payload_budget', _MODULE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_compact_preserves_key_settlement_truth_and_source():
    original = {'feature_label_settlement': {
        'enabled': True, 'runs': 5, 'last_result': {
            'pending': 1254, 'labelled': 0, 'state': 'NO_LABELS_CREATED',
            'canonical_pending_outcome_summary': {'awaiting_real_pl': 1168, 'feature_only_unregistered': 86},
            'session_reports': [{'diagnostic_samples': list(range(3000))}] * 30,
        }}}
    result = module.compact_scanner_heartbeat(original)
    compact = result['feature_label_settlement']
    assert compact['enabled'] and compact['runs'] == 5
    assert compact['last_result']['pending'] == 1254
    assert compact['last_result']['canonical_pending_outcome_summary']['awaiting_real_pl'] == 1168
    assert compact['last_result']['session_reports_omitted_from_heartbeat'] == 30
    assert 'session_reports' not in compact['last_result']
    assert len(json.dumps(result)) < 1500
    assert 'session_reports' in original['feature_label_settlement']['last_result']


def test_historical_decision_samples_omitted_without_changing_counts():
    original = {'historical_evidence_lifecycle': {
        'readiness': {'decisions_recorded': 123},
        'live_actionability_capture_audit': {'current_release_rows': 15,
            'recent_decisions': [{'id': n} for n in range(1000)],
            'current_release_recent_decisions': [{'id': n} for n in range(300)]},
    }}
    projection = module.compact_scanner_heartbeat(original)['historical_evidence_lifecycle']
    assert projection['readiness']['decisions_recorded'] == 123
    audit = projection['live_actionability_capture_audit']
    assert audit['current_release_rows'] == 15
    assert audit['recent_decisions_omitted_from_heartbeat'] == 1000
    assert audit['current_release_recent_decisions_omitted_from_heartbeat'] == 300
    assert 'recent_decisions' not in audit
    assert len(original['historical_evidence_lifecycle']['live_actionability_capture_audit']['recent_decisions']) == 1000


def test_other_scanner_fields_and_identity_unchanged():
    original = {'pid': 41, 'process_start_ticks': 123456, 'phase': 'RUNNING',
                'scan_completion_runtime': {'scan_completed': 90}}
    compact = module.compact_scanner_heartbeat(original)
    for key, val in original.items():
        assert compact[key] == val
    assert compact['heartbeat_payload_budget']['execution_authority'] is False


def test_malformed_partial_optional_fields_do_not_fail():
    for value in (None, {}, [], 'bad', {'last_result': 'bad'}):
        out = module.compact_scanner_heartbeat({'feature_label_settlement': value})
        assert out['feature_label_settlement'] == value


def test_actual_heartbeat_writer_is_bounded_and_readable(monkeypatch, tmp_path):
    from engine import operational_runtime
    monkeypatch.setenv('APEX_SCANNER_HEARTBEAT_PATH', str(tmp_path / 'heartbeat.json'))
    settlement = {'state': 'COMPLETED', 'last_result': {
        'state': 'NO_LABELS_CREATED', 'pending': 1254, 'labelled': 0,
        'session_reports': [{'sample_ids': list(range(10000))} for _ in range(30)]}}
    lifecycle = {'live_actionability_capture_audit': {
        'current_release_rows': 9,
        'recent_decisions': [{'sample_id': i} for i in range(10000)]}}
    operational_runtime.write_scanner_heartbeat({
        'scanner_started': True, 'feature_label_settlement': settlement,
        'historical_evidence_lifecycle': lifecycle,
    })
    heartbeat = operational_runtime.read_scanner_heartbeat()
    assert heartbeat['available'] is True
    assert heartbeat['scanner_started'] is True
    assert heartbeat['feature_label_settlement']['last_result']['pending'] == 1254
    assert heartbeat['feature_label_settlement']['last_result']['session_reports_omitted_from_heartbeat'] == 30
    assert heartbeat['historical_evidence_lifecycle']['live_actionability_capture_audit']['recent_decisions_omitted_from_heartbeat'] == 10000
    assert (tmp_path / 'heartbeat.json').stat().st_size < 4000
    assert len(settlement['last_result']['session_reports']) == 30
