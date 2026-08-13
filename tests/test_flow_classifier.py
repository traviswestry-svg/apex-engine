"""Tests for engine/flow_classifier.py — APEX 9 Step 2.

Covers every case the approved Step 2 spec requires, plus the guard that matters
most: the classifier must never present a hypothesis as a fact.
"""
import pytest

from engine.flow_classifier import (
    AGGRESSIVE_BUY, AGGRESSIVE_SELL, AMBIGUOUS, BLOCK, BUY, COMPLETE,
    CLASSIFIER_VERSION, DEGRADED, DIRECTIONAL_UNCERTAIN, INSTITUTIONAL_SIZE,
    LIKELY_ROLL, PARTIAL, PASSIVE_MID, POSSIBLE_CLOSING, POSSIBLE_HEDGE,
    POSSIBLE_OPENING, POSSIBLE_VOLATILITY_TRADE, RETAIL_SIZE_NOISE, SELL,
    SINGLE_LEG, SPLIT, SPREAD_LEG_CANDIDATE, SWEEP, UNKNOWN_AGGRESSION,
    classify_flow_event, classify_flow_events, make_event_id,
)


def _row(**over):
    """A normalized flow_tape row (the classifier's only input shape)."""
    r = {
        "time_et": "10:31:02",
        "ticker": "SPX",
        "contract_type": "CALL",
        "strike": 6300.0,
        "expiration": "2026-07-17",
        "premium": 500_000.0,
        "trade_price": 5.25,
        "contracts": 950,
        "trade_side_code": "ABOVE_ASK",
        "consolidation_type": "SWEEP",
        "aggressor_side": "BUY",
        "tape_label": "BUY_SWEEP",
        "importance_score": 88,
    }
    r.update(over)
    return r


def _one(row, **kw):
    return classify_flow_event(row, **kw)


def _intents(ev):
    return {i["intent"] for i in ev["possible_intents"]}


def _excluded(ev):
    return {i["intent"] for i in ev["excluded_intents"]}


# ── ask-side sweeps ────────────────────────────────────────────────────────
def test_ask_side_sweep_is_aggressive_buy_and_bullish_lean():
    ev = _one(_row(trade_side_code="ABOVE_ASK", consolidation_type="SWEEP"))
    assert ev["classification"] == SWEEP
    assert ev["execution_aggression"] == AGGRESSIVE_BUY
    assert ev["directional_bias"] == "BULLISH"
    assert ev["data_quality"] == COMPLETE
    assert ev["classification_confidence"] >= 0.9


def test_at_ask_sweep_is_buy_not_aggressive_buy():
    ev = _one(_row(trade_side_code="AT_ASK"))
    assert ev["execution_aggression"] == BUY
    assert ev["directional_bias"] == "BULLISH"
    # a lift at the ask is less aggressive than paying through it
    assert ev["directional_confidence"] < 0.60


# ── bid-side sweeps ────────────────────────────────────────────────────────
def test_bid_side_call_sweep_leans_bearish():
    ev = _one(_row(trade_side_code="BELOW_BID", consolidation_type="SWEEP"))
    assert ev["classification"] == SWEEP
    assert ev["execution_aggression"] == AGGRESSIVE_SELL
    assert ev["directional_bias"] == "BEARISH"   # calls being sold


def test_bid_side_put_sweep_leans_bullish():
    ev = _one(_row(contract_type="PUT", trade_side_code="AT_BID"))
    assert ev["execution_aggression"] == SELL
    assert ev["directional_bias"] == "BULLISH"   # puts being sold


def test_ask_side_put_sweep_leans_bearish():
    ev = _one(_row(contract_type="PUT", trade_side_code="ABOVE_ASK"))
    assert ev["directional_bias"] == "BEARISH"


# ── blocks / splits / single-leg ───────────────────────────────────────────
def test_block_classification():
    ev = _one(_row(consolidation_type="BLOCK"))
    assert ev["classification"] == BLOCK


def test_split_classification():
    ev = _one(_row(consolidation_type="SPLIT"))
    assert ev["classification"] == SPLIT


def test_single_leg_when_no_consolidation_tag_with_moderate_confidence():
    ev = _one(_row(consolidation_type=""))
    assert ev["classification"] == SINGLE_LEG
    # absence of a tag is weaker evidence than a positive tag — must not claim 0.95
    assert ev["classification_confidence"] < 0.7


def test_unrecognised_consolidation_is_ambiguous():
    ev = _one(_row(consolidation_type="WEIRD_NEW_TYPE"))
    assert ev["classification"] == AMBIGUOUS
    assert ev["classification_confidence"] <= 0.3


# ── same-timestamp multi-exchange activity ─────────────────────────────────
def test_same_timestamp_multi_exchange_sweep_is_provider_reported_not_inferred():
    """We have no exchange field; a SWEEP is trusted as provider-reported."""
    res = classify_flow_events([
        _row(time_et="10:31:02", trade_price=5.25, contracts=400),
        _row(time_et="10:31:02", trade_price=5.30, contracts=550),
    ])
    assert res["count"] == 2
    for ev in res["events"]:
        assert ev["classification"] == SWEEP
        assert ev["observable_facts"]["exchange_count"] is None   # never fabricated
        assert "provider tagged" in " ".join(ev["evidence"]).lower()


# ── multi-leg candidates (spread) ──────────────────────────────────────────
def test_spread_leg_candidate_detected_and_dampens_directional_confidence():
    res = classify_flow_events([
        _row(strike=6300.0, trade_side_code="ABOVE_ASK", trade_price=5.25),
        _row(strike=6320.0, trade_side_code="AT_BID", trade_price=2.10),
    ])
    a, b = res["events"]
    assert SPREAD_LEG_CANDIDATE in _intents(a)
    assert SPREAD_LEG_CANDIDATE in _intents(b)
    # a leg's standalone direction is unreliable — must be flagged and damped
    assert DIRECTIONAL_UNCERTAIN in _intents(a)
    assert a["directional_confidence"] <= 0.30


def test_spread_candidate_carries_related_event_ids_for_auditability():
    res = classify_flow_events([
        _row(strike=6300.0), _row(strike=6320.0, trade_price=2.10),
    ])
    a = res["events"][0]
    spread = [i for i in a["possible_intents"] if i["intent"] == SPREAD_LEG_CANDIDATE][0]
    assert spread["related_event_ids"]
    assert spread["related_event_ids"][0] == res["events"][1]["event_id"]


def test_volatility_structure_candidate_call_plus_put_same_expiry():
    res = classify_flow_events([
        _row(contract_type="CALL", strike=6300.0),
        _row(contract_type="PUT", strike=6300.0, trade_price=4.10),
    ])
    assert POSSIBLE_VOLATILITY_TRADE in _intents(res["events"][0])


# ── rolls ──────────────────────────────────────────────────────────────────
def test_likely_roll_needs_opposing_print_in_another_expiration():
    res = classify_flow_events([
        _row(expiration="2026-07-17", trade_side_code="AT_BID", trade_price=5.25),
        _row(expiration="2026-08-21", trade_side_code="ABOVE_ASK", trade_price=9.40),
    ])
    a, b = res["events"]
    assert LIKELY_ROLL in _intents(a) and LIKELY_ROLL in _intents(b)
    roll = [i for i in a["possible_intents"] if i["intent"] == LIKELY_ROLL][0]
    assert roll["confidence"] < 1.0
    assert "cannot be proven" in roll["basis"]     # never asserted as fact


def test_no_roll_when_same_expiration():
    res = classify_flow_events([
        _row(expiration="2026-07-17", trade_side_code="AT_BID"),
        _row(expiration="2026-07-17", trade_side_code="ABOVE_ASK", trade_price=9.40),
    ])
    assert LIKELY_ROLL not in _intents(res["events"][0])


def test_no_roll_when_outside_pair_window():
    res = classify_flow_events([
        _row(time_et="10:31:02", expiration="2026-07-17", trade_side_code="AT_BID"),
        _row(time_et="10:45:00", expiration="2026-08-21", trade_side_code="ABOVE_ASK"),
    ])
    assert LIKELY_ROLL not in _intents(res["events"][0])


def test_unrelated_prints_are_not_forced_into_a_relationship():
    """Different tickers must never pair, however close in time."""
    res = classify_flow_events([
        _row(ticker="SPX", expiration="2026-07-17", trade_side_code="AT_BID"),
        _row(ticker="QQQ", expiration="2026-08-21", trade_side_code="ABOVE_ASK"),
    ])
    for ev in res["events"]:
        assert LIKELY_ROLL not in _intents(ev)
        assert SPREAD_LEG_CANDIDATE not in _intents(ev)


# ── likely hedges ──────────────────────────────────────────────────────────
def test_possible_hedge_is_low_confidence_and_states_it_is_indistinguishable():
    ev = _one(_row(contract_type="PUT", strike=6100.0, trade_side_code="ABOVE_ASK",
                   premium=900_000.0), spot=6300.0)
    intents = [i for i in ev["possible_intents"] if i["intent"] == POSSIBLE_HEDGE]
    assert intents, "OTM institutional put buy should raise a hedge hypothesis"
    h = intents[0]
    assert h["confidence"] <= 0.35
    assert "not observable" in h["basis"] or "not distinguishable" in h["basis"]


def test_hedge_hypothesis_coexists_with_directional_hypothesis():
    """Protective and bearish puts are identical on the tape — offer both."""
    ev = _one(_row(contract_type="PUT", strike=6100.0, trade_side_code="ABOVE_ASK",
                   premium=900_000.0), spot=6300.0)
    assert POSSIBLE_HEDGE in _intents(ev)
    assert "possible_directional_position" in _intents(ev)


def test_retail_put_buy_raises_no_hedge_hypothesis():
    ev = _one(_row(contract_type="PUT", strike=6100.0, premium=5_000.0,
                   trade_side_code="ABOVE_ASK"), spot=6300.0)
    assert POSSIBLE_HEDGE not in _intents(ev)


# ── ambiguous midpoint executions ──────────────────────────────────────────
def test_midpoint_execution_is_directionally_uncertain():
    ev = _one(_row(trade_side_code="MID"))
    assert ev["execution_aggression"] == PASSIVE_MID
    assert ev["directional_bias"] == "UNCERTAIN"
    assert ev["directional_confidence"] <= 0.10
    assert DIRECTIONAL_UNCERTAIN in _intents(ev)


# ── missing open interest (always) ─────────────────────────────────────────
def test_opening_and_closing_are_always_excluded_never_guessed():
    ev = _one(_row())
    assert POSSIBLE_OPENING in _excluded(ev)
    assert POSSIBLE_CLOSING in _excluded(ev)
    assert POSSIBLE_OPENING not in _intents(ev)
    assert POSSIBLE_CLOSING not in _intents(ev)
    assert any("open interest" in w.lower() for w in ev["warnings"])


def test_open_interest_recorded_as_absent_not_zero():
    ev = _one(_row())
    assert ev["observable_facts"]["open_interest"] is None


# ── stale quotes / delayed prints ──────────────────────────────────────────
def test_delayed_print_is_flagged_and_downgrades_quality():
    # print at 10:31:02, "now" is 10:40:00 → ~9 minutes old
    ev = _one(_row(time_et="10:31:02"), as_of_secs=10 * 3600 + 40 * 60)
    assert any("delayed print" in w.lower() for w in ev["warnings"])
    assert ev["data_quality"] == PARTIAL


def test_fresh_print_is_not_flagged_delayed():
    ev = _one(_row(time_et="10:31:02"), as_of_secs=10 * 3600 + 31 * 60 + 30)
    assert not any("delayed" in w.lower() for w in ev["warnings"])
    assert ev["data_quality"] == COMPLETE


def test_quote_at_trade_is_absent_so_no_spread_quality_claim():
    ev = _one(_row())
    assert ev["observable_facts"]["quote_at_trade"] is None
    assert ev["observable_facts"]["implied_volatility"] is None


def test_unparseable_timestamp_degrades_and_disables_pairing():
    ev = _one(_row(time_et="not-a-time"))
    assert any("timestamp" in w.lower() for w in ev["warnings"])
    assert ev["data_quality"] in (PARTIAL, DEGRADED)


# ── missing execution side (the fabrication guard) ─────────────────────────
def test_missing_trade_side_code_yields_unknown_not_a_guess():
    """flow_tape falls back to CALL->BUY; the classifier must NOT inherit that."""
    ev = _one(_row(trade_side_code="", aggressor_side="BUY", tape_label="BUY_SWEEP"))
    assert ev["execution_aggression"] == UNKNOWN_AGGRESSION
    assert ev["directional_bias"] == "UNCERTAIN"
    assert ev["directional_confidence"] == 0.0
    assert ev["data_quality"] == DEGRADED
    assert DIRECTIONAL_UNCERTAIN in _intents(ev)


def test_unrecognised_trade_side_code_is_unknown():
    ev = _one(_row(trade_side_code="SOMETHING_NEW"))
    assert ev["execution_aggression"] == UNKNOWN_AGGRESSION
    assert ev["data_quality"] == DEGRADED


# ── zero-volume / malformed events ─────────────────────────────────────────
@pytest.mark.parametrize("bad", [
    {"contracts": 0},
    {"premium": 0},
    {"ticker": ""},
    {"contract_type": "STOCK"},
    {"contracts": None, "premium": None},
])
def test_malformed_events_are_ambiguous_and_degraded(bad):
    ev = _one(_row(**bad))
    assert ev["classification"] == AMBIGUOUS
    assert ev["classification_confidence"] == 0.0
    assert ev["data_quality"] == DEGRADED
    assert ev["possible_intents"] == []          # no interpretation attempted
    assert ev["warnings"]


def test_classifier_never_raises_on_garbage():
    for junk in ({}, {"ticker": None}, {"premium": "abc", "contracts": "xyz"}):
        ev = classify_flow_event(junk)
        assert ev["classifier_version"] == CLASSIFIER_VERSION
        assert ev["data_quality"] == DEGRADED


# ── size classification ────────────────────────────────────────────────────
def test_institutional_size():
    assert _one(_row(premium=900_000.0))["size_class"] == INSTITUTIONAL_SIZE


def test_retail_size_noise():
    assert _one(_row(premium=5_000.0))["size_class"] == RETAIL_SIZE_NOISE


# ── classification versioning ──────────────────────────────────────────────
def test_every_event_is_version_stamped():
    res = classify_flow_events([_row(), _row(strike=6320.0, trade_price=2.1)])
    for ev in res["events"]:
        assert ev["classifier_version"] == CLASSIFIER_VERSION
    assert res["classifier_version"] == CLASSIFIER_VERSION


def test_event_id_is_deterministic_across_runs():
    r = _row()
    assert make_event_id(r) == make_event_id(dict(r))
    first = classify_flow_events([r])["events"][0]["event_id"]
    second = classify_flow_events([dict(r)])["events"][0]["event_id"]
    assert first == second


def test_event_id_changes_when_identifying_fields_change():
    base = make_event_id(_row())
    assert make_event_id(_row(strike=6305.0)) != base
    assert make_event_id(_row(contracts=951)) != base
    assert make_event_id(_row(time_et="10:31:03")) != base


def test_event_id_is_independent_of_derived_fields():
    """Derived values must not affect identity — ids stay stable across versions."""
    base = make_event_id(_row())
    assert make_event_id(_row(importance_score=1, tape_label="X", aggressor_side="Z")) == base


# ── certainty-layer separation (the core architectural rule) ───────────────
def test_three_certainty_layers_are_stored_separately():
    ev = _one(_row())
    # layer 1 — observable, provider-sourced
    assert ev["observable_facts"]["trade_side_code"] == "ABOVE_ASK"
    # layer 2 — derived
    assert ev["classification"] == SWEEP and ev["execution_aggression"] == AGGRESSIVE_BUY
    # layer 3 — hypotheses, never in facts
    assert isinstance(ev["possible_intents"], list)
    assert all("confidence" in i and "basis" in i for i in ev["possible_intents"])
    for key in ("possible_intents", "excluded_intents"):
        assert key not in ev["observable_facts"]


def test_no_intent_is_ever_asserted_with_certainty():
    res = classify_flow_events([
        _row(), _row(strike=6320.0, trade_price=2.1, trade_side_code="AT_BID"),
        _row(contract_type="PUT", strike=6100.0, premium=900_000.0),
    ])
    for ev in res["events"]:
        for intent in ev["possible_intents"]:
            if intent["intent"] == DIRECTIONAL_UNCERTAIN:
                continue      # uncertainty itself may be stated with confidence
            assert intent["confidence"] < 1.0, f"{intent['intent']} asserted as certain"


def test_forbidden_marketing_language_never_appears():
    """Spec §32 / Step 2 language rule — no fabricated institutional intent."""
    banned = ("institution_accumulating", "smart_money", "confirmed_opening_position",
              "confirmed institutional", "guaranteed", "certain profit")
    res = classify_flow_events([
        _row(), _row(contract_type="PUT", strike=6100.0, premium=900_000.0,
                     trade_side_code="ABOVE_ASK"),
    ])
    blob = repr(res).lower()
    for term in banned:
        assert term not in blob, f"forbidden label {term!r} present in classifier output"


# ── batch behaviour ────────────────────────────────────────────────────────
def test_classify_batch_does_not_mutate_caller_rows():
    rows = [_row(), _row(strike=6320.0, trade_price=2.1)]
    before = [dict(r) for r in rows]
    classify_flow_events(rows)
    assert rows == before      # read-only toward upstream data


def test_empty_batch_is_available_and_empty():
    res = classify_flow_events([])
    assert res["available"] is True and res["count"] == 0 and res["events"] == []


def test_summary_counts_and_states_its_own_limits():
    res = classify_flow_events([
        _row(), _row(consolidation_type="BLOCK", trade_price=2.1, strike=6320.0),
    ])
    s = res["summary"]
    assert s["by_classification"].get(SWEEP) == 1
    assert s["by_classification"].get(BLOCK) == 1
    assert "not evidence" in s["note"].lower()


# ── pair index (performance optimisation must not change semantics) ────────
def test_pair_window_boundary_is_inclusive_and_exclusive_correctly():
    """Bucketed indexing must honour the same +/-window as a full scan."""
    inside = classify_flow_events([
        _row(time_et="10:31:02", expiration="2026-07-17", trade_side_code="AT_BID"),
        _row(time_et="10:31:04", expiration="2026-08-21", trade_side_code="ABOVE_ASK"),
    ])
    assert LIKELY_ROLL in _intents(inside["events"][0])   # 2s == window

    outside = classify_flow_events([
        _row(time_et="10:31:02", expiration="2026-07-17", trade_side_code="AT_BID"),
        _row(time_et="10:31:05", expiration="2026-08-21", trade_side_code="ABOVE_ASK"),
    ])
    assert LIKELY_ROLL not in _intents(outside["events"][0])   # 3s > window


def test_pairing_still_works_in_a_large_batch():
    """Guards the index: a pair must still be found among many unrelated prints."""
    noise = [_row(time_et=f"09:{m:02d}:00", strike=6000.0 + m, trade_price=1.0 + m)
             for m in range(50)]
    pair = [
        _row(time_et="10:31:02", expiration="2026-07-17", trade_side_code="AT_BID"),
        _row(time_et="10:31:03", expiration="2026-08-21", trade_side_code="ABOVE_ASK",
             trade_price=9.4),
    ]
    res = classify_flow_events(noise + pair)
    found = [e for e in res["events"] if LIKELY_ROLL in _intents(e)]
    assert len(found) == 2


def test_different_tickers_never_share_a_time_bucket():
    res = classify_flow_events([
        _row(ticker="SPX", time_et="10:31:02", expiration="2026-07-17", trade_side_code="AT_BID"),
        _row(ticker="SPY", time_et="10:31:02", expiration="2026-08-21", trade_side_code="ABOVE_ASK"),
    ])
    for ev in res["events"]:
        assert LIKELY_ROLL not in _intents(ev)
