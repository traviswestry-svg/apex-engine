import json
from pathlib import Path
from engine import evening_recap


def test_release_metadata_and_no_authority():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / 'config/apex_release_manifest.json').read_text())
    assert manifest['apex_version'] == manifest['semantic_version'] == manifest['application_version'] == '69.10.37'
    g = manifest['guardrails']
    assert g['automatic_order_submission'] is False
    assert g['forecast_diagnostics_no_execution_authority'] is True
    assert g['forecast_diagnostics_no_historical_backfill'] is True


def test_diagnostic_persistence_and_immutable_legacy(tmp_path, monkeypatch):
    monkeypatch.setattr(evening_recap, 'DB_PATH', str(tmp_path / 'governance.db'))
    date = '2026-10-12'
    assert evening_recap.morning_archive_status(date)['diagnostic_persistence']['state'] == 'NOT_ARCHIVED'
    diagnostic = {'schema_version':'69.10.37','capture_stage':'MORNING_DETERMINISTIC_PRE_OUTCOME',
                  'authority':'DIAGNOSTIC_ONLY_NO_FORECAST_OR_EXECUTION_CHANGE'}
    payload = {'target_session_date':date,'session_date':date,'generated_at':'2026-10-12T08:15:00-04:00',
               'session_context':{'brief_mode':'PREMARKET'},'structured':{'spot':7800,
               'forecast_regime':'Balanced Auction','expected_move':{'one_sigma':30},
               'forecast_provenance_diagnostics':diagnostic}}
    saved = evening_recap.save_morning_snapshot(payload)
    assert saved['is_official'] is True
    assert evening_recap.morning_archive_status(date)['diagnostic_persistence']['state'] == 'PERSISTED_VERIFIED'
    frozen = evening_recap.get_morning_snapshot(date)
    assert frozen['structured']['forecast_provenance_diagnostics'] == diagnostic
    assert evening_recap.verify_canonical_forecast(frozen,date)['ok'] is True
    # A later revision cannot overwrite the official diagnostic or forecast identity.
    revised = dict(payload, generated_at='2026-10-12T08:20:00-04:00', structured={'spot':9999})
    assert evening_recap.save_morning_snapshot(revised)['is_official'] is False
    assert evening_recap.get_morning_snapshot(date) == frozen
    assert evening_recap.morning_archive_status(date)['forecast_id'] == saved['forecast_id']


def test_legacy_missing_diagnostics_is_not_reconstructed(tmp_path, monkeypatch):
    monkeypatch.setattr(evening_recap, 'DB_PATH', str(tmp_path / 'governance.db'))
    date='2026-10-13'
    payload={'target_session_date':date,'session_date':date,'generated_at':'2026-10-13T08:15:00-04:00',
             'session_context':{'brief_mode':'PREMARKET'},'structured':{'spot':7800}}
    assert evening_recap.save_morning_snapshot(payload)['is_official']
    status=evening_recap.morning_archive_status(date)
    assert status['diagnostic_persistence']['state']=='LEGACY_MISSING_NO_BACKFILL'
    assert 'forecast_provenance_diagnostics' not in evening_recap.get_morning_snapshot(date)['structured']
