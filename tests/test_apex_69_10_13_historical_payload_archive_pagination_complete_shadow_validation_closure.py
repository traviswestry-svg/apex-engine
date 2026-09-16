import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _trigger_db(path: Path, n: int = 12):
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE observed_trade_triggers(trigger_id TEXT PRIMARY KEY, triggered_at TEXT, evidence_json TEXT NOT NULL)")
        for i in range(n):
            c.execute("INSERT INTO observed_trade_triggers VALUES(?,?,?)", (f't{i:03d}', f'2026-09-01T00:{i:02d}:00Z', json.dumps({'canonical_decision_id': f'd{i}', 'decision': {'decision_id': f'd{i}'}})))


def test_release_identity_and_registry_alignment():
    m = json.loads((ROOT/'config/apex_release_manifest.json').read_text())
    assert m['apex_version'] == m['semantic_version'] == m['application_version'] == '69.10.13'
    assert m['build_name'] == 'Historical Payload Archive Pagination & Complete Shadow Validation Closure'
    g = m['guardrails']
    assert g['historical_payload_archive_resumable_batches'] is True
    assert g['historical_payload_archive_batch_max_rows'] == 500
    assert g['historical_payload_shadow_validation_paginated'] is True
    registry = (ROOT/'config/apex_capability_registry.yaml').read_text()
    assert 'apex_version: 69.10.13' in registry
    assert 'historical_payload_archive_pagination_complete_shadow_validation_closure:' in registry


def test_archive_batches_progress_to_next_unarchived_rows(tmp_path):
    from engine.historical_payload_archive import archive_batch, archive_status
    source, archive = tmp_path/'trigger.db', tmp_path/'archive.db'
    _trigger_db(source, 12)
    first = archive_batch(payload_type='TRIGGER_EVIDENCE', source_path=source, archive_path=archive, limit=5, apply=True)
    assert first['rows_archived'] == 5 and first['remaining_rows'] == 7 and first['archive_complete'] is False
    second = archive_batch(payload_type='TRIGGER_EVIDENCE', source_path=source, archive_path=archive, limit=5, apply=True)
    assert second['archived_rows_before'] == 5 and second['rows_archived'] == 5 and second['remaining_rows'] == 2
    third = archive_batch(payload_type='TRIGGER_EVIDENCE', source_path=source, archive_path=archive, limit=5, apply=True)
    assert third['rows_archived'] == 2 and third['remaining_rows'] == 0 and third['archive_complete'] is True
    assert archive_status(archive)['rows'] == 12


def test_shadow_validation_pages_cover_entire_source(tmp_path):
    from engine.historical_payload_archive import archive_batch, shadow_validate
    source, archive = tmp_path/'trigger.db', tmp_path/'archive.db'
    _trigger_db(source, 12)
    while True:
        out = archive_batch(payload_type='TRIGGER_EVIDENCE', source_path=source, archive_path=archive, limit=5, apply=True)
        if out['archive_complete']:
            break
    pages = [shadow_validate(payload_type='TRIGGER_EVIDENCE', source_path=source, archive_path=archive, limit=5, offset=o) for o in (0,5,10)]
    assert [p['rows_checked'] for p in pages] == [5,5,2]
    assert all(p['archive_misses'] == 0 and p['mismatches'] == [] and p['projection_errors'] == 0 for p in pages)
    assert pages[0]['validation_complete'] is False
    assert pages[-1]['validation_complete'] is True
    assert pages[-1]['next_offset'] == 12


def test_batch_ceiling_remains_500(tmp_path):
    from engine.historical_payload_archive import archive_batch
    source, archive = tmp_path/'trigger.db', tmp_path/'archive.db'
    _trigger_db(source, 2)
    out = archive_batch(payload_type='TRIGGER_EVIDENCE', source_path=source, archive_path=archive, limit=5000, apply=False)
    assert out['batch_limit'] == 500
    assert out['rows_considered'] == 2
    assert out['canonical_source_mutated'] is False
