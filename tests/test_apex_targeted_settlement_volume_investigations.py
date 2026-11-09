from engine.settlement_gap_investigation import analyze as settlement
from engine.volume_auction_input_investigation import analyze as volume


def test_settlement_gap_exact_unmatched_not_recovered():
    report = {"canonical_settlement_cohort_summary": {"settlement_requested_ids": 1391,
              "requested_with_excursion": 0, "requested_without_excursion": 1391,
              "identity_map_only_requested": 1304, "feature_only_requested": 87,
              "excursion_not_requested": 10875},
              "canonical_pending_outcome_summary": {"awaiting_real_pl": 1304},
              "canonical_settlement_eligibility_38": {"partition_integrity": {
                   "feature_label_partition_valid": True,
                   "pending_evidence_partition_valid": True,
                   "excursion_feature_partition_valid": True},
                   "counts": {"unlabelled": 4169, "excursion_unlabelled": 0}}}
    output = settlement(report)
    assert output["state"] == "REQUESTED_COHORT_HAS_NO_EXACT_EXCURSIONS"
    assert output["existing_excursions_outside_requested_cohort"] == 10875
    assert output["requested_identity_only"] == 1304
    assert output["global_partition_integrity_verified"] is True
    assert not output["writes_evidence"] and not output["execution_authority"]


def test_settlement_gap_handles_empty_and_mixed_cohorts():
    assert settlement({})["state"] == "NO_SETTLEMENT_COHORT"
    assert settlement({"canonical_settlement_cohort_summary": {
        "settlement_requested_ids": 4, "requested_with_excursion": 2,
        "requested_without_excursion": 2}})["state"] == "MIXED_REQUESTED_COHORT_WITH_MISSING_EXCURSIONS"
    assert settlement({"canonical_settlement_cohort_summary": {
        "settlement_requested_ids": 4, "requested_with_excursion": 4}})["state"] == "EXACT_REQUESTED_EXCURSIONS_PRESENT"


def test_volume_timeout_distinct_from_frozen():
    result = volume(bundle={}, timed_out=["volume_profile"], duration_ms=5001,
                    fetch_timeout_seconds=5,
                    liveness={"components": [{"component": "auction", "status": "FROZEN"}]})
    assert result["state"] == "FETCH_TIMEOUT_OR_EXCEPTION"
    assert not result["provider_requests_added"]


def test_volume_frozen_with_bundle_needs_freshness_check():
    bundle = {"profile": {"source": "SPY_VOLUME_PROXY_SCALED_TO_SPX", "levels": {
        "poc": 7400, "vah": 7420, "val": 7390}, "quality_flags": ["SPY_VOLUME_PROXY_SCALED_TO_SPX"]},
        "auction": {"auction_state": "BALANCED"}}
    live = {"components": [{"component": "volume_profile", "status": "FROZEN"},
                           {"component": "auction", "status": "FROZEN"}]}
    result = volume(bundle=bundle, timed_out=[], duration_ms=132,
                    liveness=live)
    assert result["state"] == "UNCHANGED_COMPONENTS_NEED_SOURCE_FRESHNESS_CHECK"
    assert result["levels_present"] == {"poc": True, "vah": True, "val": True}
    assert result["profile_quality_flags"]
    assert not result["changes_trade_decisions"]


def test_volume_success_does_not_claim_independently_verified_freshness():
    assert volume(bundle={"profile": {"levels": {}}, "auction": {"state": "WAIT"}},
                  timed_out=[], duration_ms=32)["state"] == "INPUTS_PRESENT_NO_FAILURE_PROVEN"
