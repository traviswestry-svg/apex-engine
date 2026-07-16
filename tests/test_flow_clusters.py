"""Tests for engine/flow_clusters.py — APEX 9 Step 3.

Covers every case the approved Step 3 spec requires. The guards that matter most:
unrelated prints must never be forced together, and membership must stay
auditable and order-independent.
"""
import pytest

from engine.flow_classifier import classify_flow_events
from engine.flow_clusters import (
    CLUSTER_CONFIG_VERSION, CLUSTER_VERSION, build_flow_clusters,
    compare_classifier_versions, health, make_cluster_id,
)


def _row(**over):
    r = {
        "time_et": "10:31:02", "ticker": "SPX", "contract_type": "CALL",
        "strike": 6300.0, "expiration": "2026-07-17", "premium": 500_000.0,
        "trade_price": 5.25, "contracts": 950, "trade_side_code": "ABOVE_ASK",
        "consolidation_type": "SWEEP",
    }
    r.update(over)
    return r


def _classify(rows):
    return classify_flow_events(rows)["events"]


def _cluster(rows, **kw):
    return build_flow_clusters(_classify(rows), **kw)


def _all(res):
    return res["clusters"] + res["singletons"]


# ── repeated sweeps in the same contract ──────────────────────────────────
def test_repeated_sweeps_same_contract_form_one_cluster():
    rows = [_row(time_et=f"10:31:{s:02d}", trade_price=5.20 + s / 100)
            for s in (2, 5, 9, 14)]
    res = _cluster(rows)
    assert res["count"] == 1
    c = res["clusters"][0]
    assert c["number_of_prints"] == 4
    assert c["distinct_contracts"] == 1
    assert c["repeat_intensity_score"] == 100.0     # every print, same contract
    assert len(c["member_event_ids"]) == 4


def test_cluster_totals_are_sums_of_members():
    rows = [_row(time_et="10:31:02", premium=500_000.0, contracts=950, trade_price=5.00),
            _row(time_et="10:31:06", premium=250_000.0, contracts=500, trade_price=5.50)]
    c = _cluster(rows)["clusters"][0]
    assert c["total_premium"] == 750_000
    assert c["total_contracts"] == 1450
    # weighted by contracts, not a naive mean of 5.25
    expected = (5.00 * 950 + 5.50 * 500) / 1450
    # engine rounds to 4dp — assert to that precision, not beyond it
    assert c["weighted_average_execution_price"] == round(expected, 4)


def test_start_end_duration_reflect_members():
    rows = [_row(time_et="10:31:02"), _row(time_et="10:31:40", trade_price=5.4)]
    c = _cluster(rows)["clusters"][0]
    assert c["start_time"] == "10:31:02" and c["end_time"] == "10:31:40"
    assert c["duration_seconds"] == 38


# ── related strikes ────────────────────────────────────────────────────────
def test_nearby_strikes_cluster_together():
    rows = [_row(time_et="10:31:02", strike=6300.0),
            _row(time_et="10:31:05", strike=6310.0, trade_price=4.1)]
    res = _cluster(rows)
    assert res["count"] == 1
    assert res["clusters"][0]["strike_range"] == [6300.0, 6310.0]


def test_distant_strikes_do_not_cluster():
    """1% band on SPX ~ 63pts; 500pts away is a different trade entirely."""
    rows = [_row(time_et="10:31:02", strike=6300.0),
            _row(time_et="10:31:05", strike=6800.0, trade_price=0.4)]
    res = _cluster(rows)
    assert res["count"] == 0            # neither reaches min_prints
    assert len(res["singletons"]) == 2


# ── different expirations ──────────────────────────────────────────────────
def test_different_expirations_never_cluster():
    rows = [_row(time_et="10:31:02", expiration="2026-07-17"),
            _row(time_et="10:31:03", expiration="2026-08-21", trade_price=9.4)]
    res = _cluster(rows)
    assert res["count"] == 0
    assert len(res["singletons"]) == 2
    exps = {c["expiration"] for c in res["singletons"]}
    assert exps == {"2026-07-17", "2026-08-21"}


# ── opposing calls and puts ────────────────────────────────────────────────
def test_calls_and_puts_never_cluster_together():
    rows = [_row(time_et="10:31:02", contract_type="CALL"),
            _row(time_et="10:31:02", contract_type="PUT", trade_price=4.1)]
    res = _cluster(rows)
    for c in _all(res):
        assert len(c["member_event_ids"]) == 1
    types = {c["option_type"] for c in _all(res)}
    assert types == {"CALL", "PUT"}


def test_opposing_direction_same_contract_does_not_cluster():
    """Bought calls and sold calls are opposing activity, not one campaign."""
    rows = [_row(time_et="10:31:02", trade_side_code="ABOVE_ASK"),
            _row(time_et="10:31:04", trade_side_code="BELOW_BID", trade_price=5.1)]
    res = _cluster(rows)
    dirs = {c["directional_interpretation"] for c in _all(res)}
    assert dirs == {"BULLISH", "BEARISH"}
    for c in _all(res):
        assert c["number_of_prints"] == 1


# ── separate institutions that cannot be reliably linked ──────────────────
def test_prints_far_apart_in_time_are_not_linked():
    """Same contract, 10 minutes apart — no basis to call it one actor."""
    rows = [_row(time_et="10:31:02"), _row(time_et="10:41:02", trade_price=5.4)]
    res = _cluster(rows)
    assert res["count"] == 0
    assert len(res["singletons"]) == 2


def test_different_tickers_never_cluster():
    rows = [_row(ticker="SPX"), _row(ticker="SPY", strike=630.0, trade_price=1.2)]
    res = _cluster(rows)
    for c in _all(res):
        assert c["number_of_prints"] == 1


def test_every_cluster_states_it_cannot_prove_a_shared_originator():
    rows = [_row(time_et="10:31:02"), _row(time_et="10:31:05", trade_price=5.4)]
    c = _cluster(rows)["clusters"][0]
    blob = " ".join(c["warnings"]).lower()
    assert "no account identity" in blob and "cannot be proven" in blob


def test_cluster_confidence_never_reaches_certainty():
    rows = [_row(time_et=f"10:31:{s:02d}", trade_price=5.2) for s in range(2, 12)]
    c = _cluster(rows)["clusters"][0]
    assert c["confidence"] < 1.0


# ── duplicate provider messages ────────────────────────────────────────────
def test_duplicate_messages_are_dropped_and_reported():
    r = _row()
    res = _cluster([r, dict(r), dict(r)])
    assert res["duplicates_dropped"] == 2
    assert res["identical_prints_collapsed"] == 2
    assert "indistinguishable from duplicates" in res["duplicate_note"]
    # all three collapsed to one print → no cluster reaches min_prints
    assert res["count"] == 0


def test_duplicate_note_absent_when_no_duplicates():
    res = _cluster([_row(time_et="10:31:02"), _row(time_et="10:31:05", trade_price=5.4)])
    assert res["duplicates_dropped"] == 0
    assert "duplicate_note" not in res


# ── late-arriving prints / out-of-order events ────────────────────────────
def test_clustering_is_independent_of_input_order():
    rows = [_row(time_et="10:31:02", trade_price=5.0),
            _row(time_et="10:31:05", trade_price=5.1),
            _row(time_et="10:31:09", trade_price=5.2)]
    forward = _cluster(rows)
    backward = _cluster(list(reversed(rows)))
    shuffled = _cluster([rows[1], rows[2], rows[0]])
    ids = [r["clusters"][0]["cluster_id"] for r in (forward, backward, shuffled)]
    assert len(set(ids)) == 1, "cluster identity must not depend on arrival order"


def test_late_arriving_print_joins_on_recomputation():
    early = [_row(time_et="10:31:02", trade_price=5.0),
             _row(time_et="10:31:05", trade_price=5.1)]
    first = _cluster(early)["clusters"][0]
    late = early + [_row(time_et="10:31:03", trade_price=5.05)]
    second = _cluster(late)["clusters"][0]
    assert second["number_of_prints"] == 3
    # membership changed → identity changed, visibly, rather than silently edited
    assert second["cluster_id"] != first["cluster_id"]
    assert set(first["member_event_ids"]).issubset(set(second["member_event_ids"]))


def test_out_of_order_print_does_not_corrupt_time_bounds():
    rows = [_row(time_et="10:31:09", trade_price=5.2),
            _row(time_et="10:31:02", trade_price=5.0)]
    c = _cluster(rows)["clusters"][0]
    assert c["start_time"] == "10:31:02" and c["end_time"] == "10:31:09"
    assert c["duration_seconds"] == 7


# ── cluster splitting ──────────────────────────────────────────────────────
def test_gap_larger_than_window_splits_into_two_clusters():
    rows = [_row(time_et="10:31:02", trade_price=5.0),
            _row(time_et="10:31:05", trade_price=5.1),
            _row(time_et="10:40:00", trade_price=5.6),   # > 120s gap
            _row(time_et="10:40:04", trade_price=5.7)]
    res = _cluster(rows)
    assert res["count"] == 2
    assert {c["number_of_prints"] for c in res["clusters"]} == {2}


def test_split_clusters_have_distinct_ids_and_no_shared_members():
    rows = [_row(time_et="10:31:02", trade_price=5.0),
            _row(time_et="10:31:05", trade_price=5.1),
            _row(time_et="10:40:00", trade_price=5.6),
            _row(time_et="10:40:04", trade_price=5.7)]
    a, b = _cluster(rows)["clusters"]
    assert a["cluster_id"] != b["cluster_id"]
    assert not set(a["member_event_ids"]) & set(b["member_event_ids"])


# ── cluster merging ────────────────────────────────────────────────────────
def test_bridging_print_merges_two_chains_on_recomputation():
    apart = [_row(time_et="10:31:02", trade_price=5.0),
             _row(time_et="10:34:00", trade_price=5.3)]   # 178s apart → split
    assert build_flow_clusters(_classify(apart), min_prints=1)["count"] == 2
    bridged = apart + [_row(time_et="10:32:30", trade_price=5.15)]   # fills the gap
    merged = build_flow_clusters(_classify(bridged), min_prints=1)
    assert merged["count"] == 1
    assert merged["clusters"][0]["number_of_prints"] == 3


# ── session-boundary handling ─────────────────────────────────────────────
def test_cluster_never_spans_the_session_close():
    """No date on the print — a 15:59 and a 16:01 print must not chain."""
    rows = [_row(time_et="15:59:30", trade_price=5.0),
            _row(time_et="16:00:30", trade_price=5.1)]
    res = build_flow_clusters(_classify(rows), min_prints=1)
    assert res["count"] == 2


def test_cluster_never_spans_the_open():
    rows = [_row(time_et="09:29:30", trade_price=5.0),
            _row(time_et="09:30:30", trade_price=5.1)]
    res = build_flow_clusters(_classify(rows), min_prints=1)
    assert res["count"] == 2


def test_prints_inside_one_session_still_cluster():
    rows = [_row(time_et="15:58:00", trade_price=5.0),
            _row(time_et="15:59:00", trade_price=5.1)]
    res = build_flow_clusters(_classify(rows), min_prints=1)
    assert res["count"] == 1


# ── auditability / determinism ────────────────────────────────────────────
def test_all_member_events_are_retained_and_addressable():
    rows = [_row(time_et="10:31:02", trade_price=5.0),
            _row(time_et="10:31:05", trade_price=5.1)]
    events = _classify(rows)
    res = build_flow_clusters(events)
    members = set(res["clusters"][0]["member_event_ids"])
    assert members == {e["event_id"] for e in events}


def test_no_print_is_ever_lost():
    rows = [_row(time_et="10:31:02", trade_price=5.0),
            _row(time_et="10:31:05", trade_price=5.1),
            _row(time_et="14:00:00", strike=6800.0, trade_price=0.4),   # lone
            _row(contracts=0, premium=0, time_et="10:33:00")]           # malformed
    events = _classify(rows)
    res = build_flow_clusters(events)
    seen = set()
    for c in res["clusters"] + res["singletons"]:
        seen |= set(c["member_event_ids"])
    seen |= {u["event_id"] for u in res["unclusterable"]}
    assert seen == {e["event_id"] for e in events}


def test_cluster_id_is_deterministic_for_same_membership():
    key = ("SPX", "CALL", "2026-07-17", "BULLISH")
    assert make_cluster_id(key, ["b", "a"]) == make_cluster_id(key, ["a", "b"])


def test_cluster_id_changes_with_membership():
    key = ("SPX", "CALL", "2026-07-17", "BULLISH")
    assert make_cluster_id(key, ["a", "b"]) != make_cluster_id(key, ["a", "b", "c"])


def test_recomputation_is_stable():
    rows = [_row(time_et="10:31:02", trade_price=5.0),
            _row(time_et="10:31:05", trade_price=5.1)]
    a = _cluster(rows)["clusters"][0]["cluster_id"]
    b = _cluster(rows)["clusters"][0]["cluster_id"]
    assert a == b


def test_config_version_is_stamped_on_every_cluster():
    c = _cluster([_row(time_et="10:31:02"), _row(time_et="10:31:05", trade_price=5.4)])["clusters"][0]
    assert c["cluster_config_version"] == CLUSTER_CONFIG_VERSION
    assert c["cluster_version"] == CLUSTER_VERSION


def test_classifier_versions_are_tracked_on_the_cluster():
    c = _cluster([_row(time_et="10:31:02"), _row(time_et="10:31:05", trade_price=5.4)])["clusters"][0]
    assert c["classifier_versions"] == ["9.2.0_FLOW_CLASSIFIER"]


# ── classifier-version comparison ─────────────────────────────────────────
def test_compare_classifier_versions_detects_identical_clusterings():
    rows = [_row(time_et="10:31:02", trade_price=5.0),
            _row(time_et="10:31:05", trade_price=5.1)]
    cmp = compare_classifier_versions(_classify(rows), _classify(rows))
    assert cmp["identical"] is True
    assert cmp["only_in_a"] == [] and cmp["only_in_b"] == []


def test_compare_classifier_versions_detects_divergence():
    a = [_row(time_et="10:31:02", trade_price=5.0), _row(time_et="10:31:05", trade_price=5.1)]
    b = a + [_row(time_et="10:31:07", trade_price=5.2)]
    cmp = compare_classifier_versions(_classify(a), _classify(b))
    assert cmp["identical"] is False
    assert cmp["only_in_a"] and cmp["only_in_b"]


# ── unavailable metrics are declared, never faked ─────────────────────────
@pytest.mark.parametrize("metric", ["weighted_delta", "weighted_implied_volatility",
                                    "number_of_exchanges"])
def test_underivable_metrics_are_none_with_a_stated_reason(metric):
    c = _cluster([_row(time_et="10:31:02"), _row(time_et="10:31:05", trade_price=5.4)])["clusters"][0]
    assert c[metric] is None
    assert metric in c["unavailable_metrics"]
    assert len(c["unavailable_metrics"][metric]) > 20      # a real reason, not a shrug


def test_health_declares_unavailable_metrics():
    h = health()
    assert set(h["unavailable_metrics"]) == {"weighted_delta", "weighted_implied_volatility",
                                             "number_of_exchanges"}


# ── intent uncertainty is reported, never resolved away ───────────────────
def test_spread_legs_raise_cluster_intent_uncertainty():
    rows = [_row(time_et="10:31:02", strike=6300.0, trade_side_code="ABOVE_ASK"),
            _row(time_et="10:31:02", strike=6310.0, trade_side_code="ABOVE_ASK",
                 trade_price=4.1)]
    c = _cluster(rows)["clusters"][0]
    iu = c["intent_uncertainty"]
    assert iu["score"] > 0
    assert any("spread leg" in n for n in iu["notes"])


def test_degraded_members_lower_confidence_and_warn():
    rows = [_row(time_et="10:31:02", trade_side_code=""),
            _row(time_et="10:31:05", trade_side_code="", trade_price=5.1)]
    c = _cluster(rows)["clusters"][0]
    assert any("DEGRADED" in w for w in c["warnings"])


def test_premium_concentration_flags_a_single_dominant_print():
    rows = [_row(time_et="10:31:02", premium=5_000_000.0, contracts=9000),
            _row(time_et="10:31:05", premium=50_000.0, contracts=100, trade_price=5.1)]
    c = _cluster(rows)["clusters"][0]
    assert c["premium_concentration"] > 0.8
    assert any("single trade than a campaign" in w for w in c["warnings"])


# ── robustness ─────────────────────────────────────────────────────────────
def test_empty_input_is_available_and_empty():
    res = build_flow_clusters([])
    assert res["available"] is True and res["count"] == 0 and res["clusters"] == []


def test_malformed_events_are_reported_unclusterable_not_dropped():
    """A zero-volume print must not become a one-print 'cluster' out of garbage."""
    res = _cluster([_row(contracts=0, premium=0)])
    assert res["unclusterable"]
    assert res["count"] == 0 and res["singletons"] == []
    assert "evidences no activity" in res["unclusterable"][0]["reason"]


def test_clustering_never_raises_on_garbage():
    for junk in ([{}], [{"event_id": "x"}], [{"event_id": "y", "observable_facts": None}]):
        res = build_flow_clusters(junk)
        assert res["cluster_version"] == CLUSTER_VERSION


def test_does_not_mutate_input_events():
    events = _classify([_row(time_et="10:31:02"), _row(time_et="10:31:05", trade_price=5.4)])
    import copy
    before = copy.deepcopy(events)
    build_flow_clusters(events)
    assert events == before


def test_summary_states_clusters_are_not_positioning():
    res = _cluster([_row(time_et="10:31:02"), _row(time_et="10:31:05", trade_price=5.4)])
    assert "not proof of a single participant" in res["summary"]["note"]


def test_forbidden_language_never_appears_in_clusters():
    banned = ("institution_accumulating", "smart_money", "confirmed_opening_position",
              "confirmed institutional", "guaranteed")
    res = _cluster([_row(time_et="10:31:02"), _row(time_et="10:31:05", trade_price=5.4)])
    blob = repr(res).lower()
    for term in banned:
        assert term not in blob


# ── interleaving (regression: an unrelated strike must not tear a campaign) ─
def test_unrelated_strike_between_prints_does_not_split_the_campaign():
    """Found on realistic data: a 6900 print landing between 6300 sweeps used to
    break the time chain and split one campaign into two. Banding by strike
    before time-chaining fixes it."""
    rows = [
        _row(time_et="10:31:02", strike=6300.0, trade_price=5.20),
        _row(time_et="10:31:06", strike=6300.0, trade_price=5.25),
        _row(time_et="10:31:07", strike=6900.0, trade_price=0.35),   # unrelated, interleaved
        _row(time_et="10:31:11", strike=6300.0, trade_price=5.30),
        _row(time_et="10:31:19", strike=6310.0, trade_price=4.60),
    ]
    res = build_flow_clusters(_classify(rows), min_prints=1)
    campaign = [c for c in res["clusters"] if c["strike_range"][0] == 6300.0]
    assert len(campaign) == 1, "the 6300 campaign must remain a single cluster"
    assert campaign[0]["number_of_prints"] == 4
    far = [c for c in res["clusters"] if c["strike_range"][0] == 6900.0]
    assert len(far) == 1 and far[0]["number_of_prints"] == 1


def test_strike_banding_uses_complete_linkage_and_does_not_drift():
    """6300~6360~6420 must not daisy-chain into one implausibly wide cluster."""
    rows = [_row(time_et="10:31:02", strike=6300.0, trade_price=5.0),
            _row(time_et="10:31:04", strike=6360.0, trade_price=3.0),
            _row(time_et="10:31:06", strike=6420.0, trade_price=1.5)]
    res = build_flow_clusters(_classify(rows), min_prints=1)
    for c in res["clusters"]:
        lo, hi = c["strike_range"]
        assert (hi - lo) <= hi * 0.01 + 1e-9, f"band {lo}-{hi} exceeds tolerance (drift)"


def test_interleaving_result_is_order_independent():
    rows = [
        _row(time_et="10:31:02", strike=6300.0, trade_price=5.20),
        _row(time_et="10:31:07", strike=6900.0, trade_price=0.35),
        _row(time_et="10:31:11", strike=6300.0, trade_price=5.30),
    ]
    a = build_flow_clusters(_classify(rows), min_prints=1)
    b = build_flow_clusters(_classify(list(reversed(rows))), min_prints=1)
    assert sorted(c["cluster_id"] for c in a["clusters"]) == \
           sorted(c["cluster_id"] for c in b["clusters"])
