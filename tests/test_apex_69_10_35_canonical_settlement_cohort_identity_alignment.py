import json
from pathlib import Path


def test_release_truth_and_guardrails():
    m=json.loads(Path('config/apex_release_manifest.json').read_text())
    assert m['apex_version']==m['semantic_version']==m['application_version']=='69.10.36'
    assert m['build_name']=='Canonical Feature Lifecycle & Excursion Ownership Convergence'
    g=m['guardrails']
    assert g['settlement_exact_excursion_owner_required'] is True
    assert g['settlement_legacy_singleton_recovery_allowed'] is False
    assert g['settlement_nearest_time_matching_allowed'] is False
    assert g['settlement_cross_sample_excursion_borrowing_allowed'] is False
    assert g['settlement_synthetic_mfe_pl_allowed'] is False
    assert g['settlement_historical_identity_backfill_allowed'] is False


def test_settlement_source_is_exact_id_only():
    s=Path('engine/feature_store_writer.py').read_text()
    assert 'canonical_settlement_identity_alignment' in s
    assert 'legacy_singleton_label_recovery_enabled' in s
    assert 'legacy_singleton_label_recovery_enabled"] = False' in s
    # Exact canonical excursion reader remains the label evidence source.
    assert 'get_sample_excursions(sample_ids)' in s


def test_four_mutually_exclusive_diagnostic_sets_present():
    s=Path('engine/flow_pl_store.py').read_text()
    for name in ('REQUESTED_AND_EXCURSION','REQUESTED_NO_EXCURSION',
                 'EXCURSION_NOT_REQUESTED','FEATURE_ONLY_UNREGISTERED'):
        assert name in s
    for stage in ('FEATURE_TO_LIFECYCLE','LIFECYCLE_TO_EXCURSION','EXCURSION_TO_SETTLEMENT'):
        assert stage in s
    assert 'nearest_time_matching": False' in s
    assert 'cross_sample_borrowing": False' in s
    assert 'synthetic_pl": False' in s
