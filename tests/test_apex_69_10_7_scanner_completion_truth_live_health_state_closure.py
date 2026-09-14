import json
from pathlib import Path

from engine.scanner_runtime_truth import resolve_scanner_runtime


def test_release_truth_and_scanner_completion_guardrails():
    manifest = json.loads(Path('config/apex_release_manifest.json').read_text())
    assert manifest['apex_version'] == manifest['semantic_version'] == manifest['application_version'] == '69.10.9'
    assert manifest['build_name'] == 'Trigger Observatory Retention & Evidence Payload Governance'
    g = manifest['guardrails']
    assert g['scanner_completion_truth_separates_heartbeat_from_full_scan'] is True
    assert g['scanner_background_activity_substitutes_for_full_scan'] is False
    assert g['scanner_process_completion_timestamp_authoritative_when_heartbeat_fresh'] is True
    assert g['scanner_stale_threshold_relaxed'] is False
    assert g['scanner_fresh_heartbeat_can_mask_stale_full_scan'] is False
    assert g['scanner_lock_contention_observable'] is True
    assert g['scanner_lock_contention_bypasses_lock'] is False
    assert g['scanner_lock_contention_bounded_retry'] is True
    assert g['scanner_health_changes_trade_decisions'] is False
    assert g['scanner_health_changes_execution_authority'] is False

    registry = Path('config/apex_capability_registry.yaml').read_text()
    assert 'apex_version: 69.10.9' in registry
    assert 'scanner_completion_truth_live_health_state_closure:' in registry
    assert 'heartbeat_does_not_equal_full_scan_completion' in registry
    assert 'stale_threshold_unchanged' in registry
    assert 'lock_never_bypassed' in registry


def test_fresh_heartbeat_uses_explicit_full_scan_completion_truth():
    out = resolve_scanner_runtime(
        local_started=False,
        local_thread_alive=False,
        heartbeat={
            'available': True,
            'age_seconds': 3.0,
            'scanner_started': True,
            'thread_alive': True,
            'updated_at': '2026-09-14T19:38:55+00:00',
            'last_scan_at': '2026-09-14T17:31:03+00:00',
            'scan_completion_runtime': {
                'version': '69.10.7',
                'scan_attempts': 20,
                'scan_completed': 19,
                'scan_lock_skips': 1,
                'last_completed_at': '2026-09-14T19:35:00+00:00',
                'last_duration_seconds': 66.7,
                'last_result': 'COMPLETED',
            },
        },
        stale_after_seconds=45,
    )
    assert out['source'] == 'SCANNER_PROCESS_HEARTBEAT'
    assert out['heartbeat_fresh'] is True
    assert out['process_last_scan_at'] == '2026-09-14T19:35:00+00:00'
    assert out['process_last_scan_duration_seconds'] == 66.7
    assert out['process_scan_completion']['scan_completed'] == 19


def test_stale_heartbeat_cannot_export_completion_as_authoritative():
    out = resolve_scanner_runtime(
        local_started=False,
        local_thread_alive=False,
        heartbeat={
            'available': True,
            'age_seconds': 600.0,
            'scanner_started': True,
            'thread_alive': True,
            'scan_completion_runtime': {
                'last_completed_at': '2026-09-14T19:35:00+00:00',
                'last_duration_seconds': 66.7,
            },
        },
        stale_after_seconds=45,
    )
    assert out['heartbeat_fresh'] is False
    assert out['process_last_scan_at'] is None
    assert out['process_scan_completion'] == {}


def test_app_records_scan_completion_and_bounded_lock_retry_without_bypass():
    src = Path('app.py').read_text()
    assert '"version": "69.10.7"' in src
    assert '"scan_attempts": 0' in src
    assert '"scan_completed": 0' in src
    assert '"scan_failures": 0' in src
    assert '"scan_lock_skips": 0' in src
    assert '"scheduler_lock_retries": 0' in src
    assert 'SCAN_LOCK.acquire(blocking=False)' in src
    assert 'APEX_SCANNER_LOCK_RETRY_SECONDS' in src
    assert 'run_scan_once()' in src
    assert 'FULL_SCAN_STALLED' in src
    assert 'Background activity does not substitute for a completed full scan.' in src
    assert 'HEALTH_STALE_AFTER_S' in src


def test_scanner_worker_publishes_completion_runtime_in_canonical_heartbeat():
    src = Path('scanner_worker.py').read_text()
    assert '"scan_completion_runtime": apex_app.scanner_completion_runtime_status()' in src
    assert '"flow_learning_runtime": apex_app.flow_learning_runtime_status()' in src
