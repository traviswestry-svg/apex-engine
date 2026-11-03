"""Provider calculation-universe changes must not produce artificial transitions."""
from engine.gamma_transition import (
    canonical_identity_basis, compute_transition, gamma_coverage_comparability,
    gamma_models_comparable, init_db, observe_gamma_transition, snapshot_from_gamma,
)

MODEL = dict(source='QUANTDATA', model_id='Q', model_version='1',
             calculation_method='CHAIN', gamma_unit='USD')


def test_legacy_coverage_unknown_preserves_existing_model_comparability():
    assert gamma_coverage_comparability(MODEL, MODEL)['state'] == 'UNKNOWN'
    assert gamma_models_comparable(MODEL, MODEL)


def test_changed_and_one_sided_coverage_fail_closed():
    a = dict(MODEL, calculation_universe_id='SPX-ALL-STRIKES')
    b = dict(MODEL, calculation_universe_id='SPX-NEAR-MONEY')
    assert gamma_coverage_comparability(a, b)['changed_fields'] == ['calculation_universe_id']
    assert not gamma_models_comparable(a, b)
    assert gamma_coverage_comparability(a, MODEL)['state'] == 'INCOMPLETE'
    assert not gamma_models_comparable(a, MODEL)
    assert gamma_models_comparable(a, dict(a))


def test_coverage_participates_in_new_identity_but_not_legacy_identity():
    original = canonical_identity_basis(dict(MODEL, observed_at='2026-10-30T13:30:00Z'))
    assert 'declared_coverage_metadata' not in original
    gamma = dict(MODEL, net_gex=100, calculation_universe_id='FULL')
    one = snapshot_from_gamma(gamma, observed_at='2026-10-30T13:30:00Z')
    two = snapshot_from_gamma(dict(gamma, calculation_universe_id='REDUCED'), observed_at='2026-10-30T13:30:00Z')
    assert one['canonical_gamma_snapshot_id'] != two['canonical_gamma_snapshot_id']
    assert one['calculation_universe_id'] == 'FULL'


def test_transition_after_universe_change_does_not_calculate_false_gex_velocity(tmp_path):
    db = str(tmp_path / 'gamma.db')
    assert init_db(db)
    first = dict(MODEL, net_gex=100, zero_gamma=5800, calculation_universe_id='FULL')
    second = dict(first, net_gex=150, calculation_universe_id='REDUCED')
    observe_gamma_transition(first, db_path=db, observed_at='2026-10-30T13:30:00Z')
    latest = observe_gamma_transition(second, db_path=db, observed_at='2026-10-30T13:45:00Z')
    assert latest['net_gex_change_15m'] is None
    assert latest['coverage_comparability_15m'] == 'CHANGED'
    assert latest['gamma_flip_velocity'] is None
