from engine.gamma_transition import gamma_model_integrity, gamma_models_comparable, regime_stability

BASE = dict(source='Q', model_id='M', model_version='1', calculation_method='CHAIN', gamma_unit='USD_PER_1PCT', gamma_flip=7800, flip_calculation_valid=True, continuity_state='CONTINUOUS', spot_synchronized_with_gamma=True)

def test_unknown_model_fails_closed():
    assert gamma_model_integrity({'gamma_flip':7800})['model_comparability_state'] == 'UNKNOWN'
    assert not gamma_models_comparable({'source':'Q'}, {'source':'Q'})

def test_method_and_units_must_match():
    assert gamma_models_comparable(BASE, dict(BASE))
    assert not gamma_models_comparable(BASE, dict(BASE, gamma_unit='CONTRACTS'))
    assert not gamma_models_comparable(BASE, dict(BASE, calculation_method='OI'))

def test_flip_level_requires_explicit_validity():
    assert gamma_model_integrity(BASE)['flip_calculation_valid'] is True
    assert gamma_model_integrity(dict(BASE, flip_calculation_valid=None))['level_validity_state'] == 'UNVERIFIED'

def test_churn_observed_with_synchronized_spot():
    from datetime import datetime, timedelta, timezone
    t=datetime(2026,10,9,14,0,tzinfo=timezone.utc)
    rows=[dict(BASE, observed_at=(t+timedelta(minutes=i)).isoformat(), underlying_spot=(7810 if i%2 else 7790)) for i in range(6)]
    result=regime_stability(rows[-1], rows[:-1])
    assert result['status']=='AVAILABLE'
    assert result['gamma_flip_crossings_5m']==5
    assert result['regime_churn_state']=='UNKNOWN'
    assert result['execution_authority'] is False

def test_missing_spot_or_gapped_history_not_zero_churn():
    a=dict(BASE, observed_at='2026-10-09T14:00:00+00:00', underlying_spot=7790)
    b=dict(BASE, observed_at='2026-10-09T14:01:00+00:00', underlying_spot=None)
    assert regime_stability(b,[a])['status']=='UNAVAILABLE'
    assert regime_stability(dict(b,underlying_spot=7810),[dict(a,continuity_state='GAPPED')])['status']=='UNAVAILABLE'


def test_same_provider_observation_different_model_has_distinct_identity():
    from engine.gamma_transition import snapshot_from_gamma
    gamma = {"net_gex": 10, "zero_gamma": 7800, "model_id": "A", "model_version": "1",
             "calculation_method": "OI", "gamma_unit": "USD"}
    a = snapshot_from_gamma(gamma, observed_at="2026-10-09T14:00:00Z", provider_observation_id="provider-1")
    b = snapshot_from_gamma({**gamma, "model_id": "B"}, observed_at="2026-10-09T14:00:00Z", provider_observation_id="provider-1")
    assert a["canonical_gamma_snapshot_id"] != b["canonical_gamma_snapshot_id"]

def test_legacy_identity_stays_unchanged_when_model_metadata_absent():
    from engine.gamma_transition import canonical_identity_basis
    basis = canonical_identity_basis({"ticker":"SPX", "observed_at":"2026-10-09T14:00:00Z"})
    assert "declared_model_metadata" not in basis

def test_no_churn_claim_from_short_window():
    from datetime import datetime, timedelta, timezone
    t=datetime(2026,10,9,14,0,tzinfo=timezone.utc)
    rows=[dict(BASE, observed_at=(t+timedelta(minutes=i)).isoformat(), underlying_spot=7810) for i in range(3)]
    result=regime_stability(rows[-1],rows[:-1])
    assert result["status"] == "AVAILABLE"
    assert result["gamma_flip_crossings_5m"] is None
    assert result["regime_churn_state"] == "UNKNOWN"
