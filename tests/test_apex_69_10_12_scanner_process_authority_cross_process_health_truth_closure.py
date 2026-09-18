import json
from pathlib import Path

from engine.scanner_runtime_truth import resolve_scanner_runtime


def test_release_truth_and_authority_guardrails():
    manifest = json.loads(Path('config/apex_release_manifest.json').read_text())
    assert manifest['apex_version'] == manifest['semantic_version'] == manifest['application_version'] == '69.10.14'
    assert manifest['build_name'] == 'Canonical Gamma Evidence Identity & Decision-Time Provenance'
    g = manifest['guardrails']
    assert g['scanner_fresh_heartbeat_is_cross_process_authority'] is True
    assert g['scanner_process_false_state_overridden_by_web_local_true'] is False
    assert g['scanner_completion_runtime_uses_process_authority_when_heartbeat_fresh'] is True
    assert g['scanner_scan_in_progress_uses_process_authority_when_heartbeat_fresh'] is True
    assert g['scanner_process_phase_and_pid_observable'] is True
    assert g['scanner_authority_changes_trade_decisions'] is False
    assert g['scanner_authority_changes_execution_authority'] is False
    registry = Path('config/apex_capability_registry.yaml').read_text()
    assert 'apex_version: 69.10.14' in registry
    assert 'scanner_process_authority_cross_process_health_truth_closure:' in registry


def test_fresh_starting_heartbeat_is_authoritative_even_before_scanner_started():
    out = resolve_scanner_runtime(
        local_started=True,
        local_thread_alive=True,
        heartbeat={
            'available': True, 'age_seconds': 2.0, 'pid': 321,
            'phase': 'STARTING', 'scanner_started': False, 'thread_alive': False,
            'updated_at': '2026-09-15T13:30:01+00:00',
            'scan_completion_runtime': {'last_result': 'NOT_RUN', 'scan_attempts': 0},
        },
        stale_after_seconds=45,
    )
    assert out['source'] == 'SCANNER_PROCESS_HEARTBEAT'
    assert out['authority'] == 'SCANNER_PROCESS'
    assert out['effective_started'] is False
    assert out['effective_thread_alive'] is False
    assert out['process_phase'] == 'STARTING'
    assert out['process_pid'] == 321
    assert out['process_scan_completion']['last_result'] == 'NOT_RUN'


def test_fresh_running_heartbeat_exports_completion_and_scan_state():
    out = resolve_scanner_runtime(
        local_started=False,
        local_thread_alive=False,
        heartbeat={
            'available': True, 'age_seconds': 4.0, 'pid': 654,
            'phase': 'RUNNING', 'scanner_started': True, 'thread_alive': True,
            'updated_at': '2026-09-15T13:34:00+00:00',
            'scan_completion_runtime': {
                'scan_attempts': 3, 'scan_completed': 2, 'last_result': 'RUNNING',
                'scan_in_progress': True, 'scan_started_at': '2026-09-15T13:33:45+00:00',
                'last_completed_at': '2026-09-15T13:32:55+00:00',
                'last_duration_seconds': 71.2,
            },
        },
        stale_after_seconds=45,
    )
    assert out['effective_started'] is True
    assert out['effective_thread_alive'] is True
    assert out['process_scan_in_progress'] is True
    assert out['process_scan_started_at'] == '2026-09-15T13:33:45+00:00'
    assert out['process_last_scan_at'] == '2026-09-15T13:32:55+00:00'
    assert out['process_last_scan_duration_seconds'] == 71.2


def test_stale_heartbeat_cannot_override_local_fallback_or_export_process_completion():
    out = resolve_scanner_runtime(
        local_started=True,
        local_thread_alive=True,
        heartbeat={
            'available': True, 'age_seconds': 100.0, 'scanner_started': False,
            'thread_alive': False, 'scan_completion_runtime': {'scan_completed': 99},
        },
        stale_after_seconds=45,
    )
    assert out['source'] == 'WEB_PROCESS_LOCAL_STATE'
    assert out['authority'] == 'WEB_PROCESS_FALLBACK'
    assert out['effective_started'] is True
    assert out['effective_thread_alive'] is True
    assert out['process_scan_completion'] == {}


def test_health_consumes_process_authority_for_completion_and_in_progress_state():
    src = Path('app.py').read_text()
    assert '_scanner_runtime.get("authority") == "SCANNER_PROCESS"' in src
    assert 's_inprog = bool(_scanner_runtime.get("process_scan_in_progress")) if _process_authoritative else _local_inprog' in src
    assert '"scanner_state_authority": _scanner_runtime.get("authority")' in src
    assert '"scanner_process_phase": _scanner_runtime.get("process_phase")' in src
    assert '"scanner_process_pid": _scanner_runtime.get("process_pid")' in src
