"""Tests for engine/flow_pl.py + flow_pl_store.py — APEX 9 Step 4.

Covers every case the approved Step 4 spec requires. The guards that matter most:
never mark what cannot be marked, never let midpoint flatter a wide market, and
never present an uncertain package as a naked directional position.
"""
import os
import tempfile

import pytest

from engine.flow_classifier import classify_flow_events
from engine.flow_clusters import build_flow_clusters
from engine.flow_pl import (
    ASK, BID, CONSERVATIVE, DEFAULT_MARK_METHOD, FLOW_PL_VERSION, LONG, MIDPOINT,
    SHORT, THEORETICAL, THEORETICAL_PL_LABEL, UNKNOWN_SIDE, compute_cluster_pl,
    compute_event_pl, compute_mark, health, infer_multiplier, is_expired,
    resolve_position_side, years_to_expiry,
)


def _row(**over):
    r = {
        "time_et": "10:31:02", "ticker": "SPX", "contract_type": "CALL",
        "strike": 6300.0, "expiration": "2026-07-17", "premium": 500_000.0,
        "trade_price": 5.00, "contracts": 1000, "trade_side_code": "ABOVE_ASK",
        "consolidation_type": "SWEEP",
    }
    r.update(over)
    return r


def _ev(**over):
    return classify_flow_events([_row(**over)])["events"][0]


def _contract(**over):
    c = {"strike": 6300.0, "side": "CALL", "bid": 6.00, "ask": 6.20, "mid": 6.10,
         "last": 6.10, "volume": 5000, "open_interest": 12000, "iv": 0.18,
         "delta": 0.52, "spread_pct": 3.3, "liquidity_score": 92.0,
         "quote_age_seconds": 2.0, "source": "chain"}
    c.update(over)
    return c


# ── the required label ─────────────────────────────────────────────────────
def test_theoretical_label_is_present_on_every_event_payload():
    pl = compute_event_pl(_ev(), _contract())
    assert pl["label"] == THEORETICAL_PL_LABEL
    assert "actual position structure and realized performance are unknown" in pl["label"]


def test_theoretical_label_is_present_on_cluster_payload():
    ev = _ev()
    cl = build_flow_clusters([ev], min_prints=1)["clusters"][0]
    out = compute_cluster_pl(cl, [compute_event_pl(ev, _contract())])
    assert out["label"] == THEORETICAL_PL_LABEL


# ── position side resolution ───────────────────────────────────────────────
def test_ask_side_print_is_long():
    assert resolve_position_side(_ev(trade_side_code="ABOVE_ASK"))[0] == LONG
    assert resolve_position_side(_ev(trade_side_code="AT_ASK"))[0] == LONG


def test_bid_side_print_is_short():
    assert resolve_position_side(_ev(trade_side_code="AT_BID"))[0] == SHORT
    assert resolve_position_side(_ev(trade_side_code="BELOW_BID"))[0] == SHORT


def test_midpoint_print_has_no_observable_side_and_no_pl():
    """A signed P/L on a mid fill would be a coin flip dressed as analysis."""
    side, warn = resolve_position_side(_ev(trade_side_code="MID"))
    assert side == UNKNOWN_SIDE and "not observable" in warn
    pl = compute_event_pl(_ev(trade_side_code="MID"), _contract())
    assert pl["markable"] is False
    assert pl["estimated_pl_dollars"] is None


def test_missing_side_code_yields_no_pl():
    pl = compute_event_pl(_ev(trade_side_code=""), _contract())
    assert pl["markable"] is False and pl["estimated_pl_dollars"] is None


# ── P/L arithmetic ─────────────────────────────────────────────────────────
def test_long_pl_uses_bid_under_conservative_mark():
    # bought at 5.00, bid now 6.00 -> +1.00 x 1000 x 100 = +100,000
    pl = compute_event_pl(_ev(), _contract(bid=6.00, ask=6.20))
    assert pl["position_side"] == LONG
    assert pl["mark_methodology"] == CONSERVATIVE
    assert pl["current_mark"] == 6.00
    assert pl["estimated_pl_dollars"] == 100_000.0
    assert pl["estimated_return_pct"] == 20.0


def test_short_pl_uses_ask_under_conservative_mark():
    # sold at 5.00, ask now 6.20 -> -1.20 x 1000 x 100 = -120,000
    pl = compute_event_pl(_ev(trade_side_code="AT_BID"), _contract(bid=6.00, ask=6.20))
    assert pl["position_side"] == SHORT
    assert pl["current_mark"] == 6.20
    assert pl["estimated_pl_dollars"] == -120_000.0


def test_short_profits_when_premium_decays():
    pl = compute_event_pl(_ev(trade_side_code="AT_BID"), _contract(bid=1.00, ask=1.10))
    assert pl["estimated_pl_dollars"] == pytest.approx((5.00 - 1.10) * 1000 * 100)


def test_entry_mark_is_the_observed_print_price_not_a_model():
    pl = compute_event_pl(_ev(trade_price=4.25), _contract())
    assert pl["entry_mark"] == 4.25
    assert "observed execution price" in pl["entry_mark_basis"]


# ── mark methods ───────────────────────────────────────────────────────────
def test_all_five_mark_methods_are_supported():
    c = _contract()
    assert compute_mark(c, BID, LONG)[0] == 6.00
    assert compute_mark(c, ASK, LONG)[0] == 6.20
    assert compute_mark(c, MIDPOINT, LONG)[0] == 6.10
    assert compute_mark(c, CONSERVATIVE, LONG)[0] == 6.00
    theo, meth, _ = compute_mark(c, THEORETICAL, LONG, spot=6300.0, t_years=0.02,
                                 option_side="CALL")
    assert meth == THEORETICAL and theo is not None and theo > 0


def test_default_is_conservative_executable_mark():
    assert DEFAULT_MARK_METHOD == CONSERVATIVE


def test_conservative_marks_a_long_to_the_worse_side():
    assert compute_mark(_contract(), CONSERVATIVE, LONG)[0] == 6.00     # bid
    assert compute_mark(_contract(), CONSERVATIVE, SHORT)[0] == 6.20    # ask


def test_theoretical_mark_is_flagged_as_model_derived():
    _, _, warns = compute_mark(_contract(), THEORETICAL, LONG, spot=6300.0,
                               t_years=0.02, option_side="CALL")
    assert any("model-derived" in w for w in warns)


def test_theoretical_mark_unavailable_without_iv():
    mark, _, warns = compute_mark(_contract(iv=None), THEORETICAL, LONG, spot=6300.0,
                                  t_years=0.02, option_side="CALL")
    assert mark is None
    assert any("unavailable" in w for w in warns)


# ── midpoint inflation (why conservative is the default) ──────────────────
def test_midpoint_inflates_pl_on_a_wide_market_and_conservative_does_not():
    wide = _contract(bid=0.05, ask=5.00, mid=2.525, spread_pct=196.0, liquidity_score=20.0)
    mid_pl = compute_event_pl(_ev(), wide, method=MIDPOINT)
    cons_pl = compute_event_pl(_ev(), wide, method=CONSERVATIVE)
    # midpoint says -2.475/contract; conservative says -4.95/contract. Reality is
    # closer to the bid: you cannot sell at the middle of 0.05 x 5.00.
    assert mid_pl["current_mark"] == 2.525
    assert cons_pl["current_mark"] == 0.05
    assert cons_pl["estimated_pl_dollars"] < mid_pl["estimated_pl_dollars"]
    assert any("flatters" in w for w in mid_pl["warnings"])


def test_wide_spread_is_warned_under_any_method():
    wide = _contract(bid=0.05, ask=5.00, mid=2.525, spread_pct=196.0)
    pl = compute_event_pl(_ev(), wide)
    assert any("Wide market" in w for w in pl["warnings"])


# ── zero-bid contracts ─────────────────────────────────────────────────────
def test_zero_bid_marks_a_long_to_zero_and_warns():
    pl = compute_event_pl(_ev(), _contract(bid=0.0, ask=0.15, mid=0.075))
    assert pl["current_mark"] == 0.0
    assert pl["estimated_pl_dollars"] == -500_000.0      # total loss of premium
    assert any("Zero bid" in w for w in pl["warnings"])


# ── stale quotes ───────────────────────────────────────────────────────────
def test_stale_quote_is_flagged():
    pl = compute_event_pl(_ev(), _contract(quote_age_seconds=300.0))
    assert any("Stale quote" in w for w in pl["warnings"])
    assert pl["quote_freshness_seconds"] == 300.0


def test_fresh_quote_is_not_flagged_stale():
    pl = compute_event_pl(_ev(), _contract(quote_age_seconds=2.0))
    assert not any("Stale" in w for w in pl["warnings"])


# ── halted / illiquid contracts ────────────────────────────────────────────
def test_illiquid_contract_is_flagged():
    pl = compute_event_pl(_ev(), _contract(liquidity_score=12.0, volume=0, open_interest=3))
    assert any("Illiquid" in w for w in pl["warnings"])
    assert pl["liquidity_quality"] == 12.0


def test_halted_contract_with_no_quote_is_unmarkable():
    pl = compute_event_pl(_ev(), _contract(bid=None, ask=None, mid=None))
    assert pl["markable"] is False
    assert pl["estimated_pl_dollars"] is None


# ── missing quotes ─────────────────────────────────────────────────────────
def test_no_contract_at_all_is_unmarkable_not_zero():
    pl = compute_event_pl(_ev(), None)
    assert pl["markable"] is False
    assert pl["estimated_pl_dollars"] is None
    assert any("No chain quote" in w for w in pl["warnings"])


def test_missing_bid_makes_a_long_unmarkable_under_conservative():
    pl = compute_event_pl(_ev(), _contract(bid=None))
    assert pl["markable"] is False
    assert any("cannot be marked conservatively" in w for w in pl["warnings"])


# ── expired contracts ──────────────────────────────────────────────────────
def test_expired_contract_detected():
    assert is_expired("2020-01-01") is True
    assert is_expired("2099-01-01") is False
    assert is_expired(None) is False
    assert is_expired("garbage") is False


def test_years_to_expiry_is_none_for_expired():
    assert years_to_expiry("2020-01-01") is None
    assert years_to_expiry("garbage") is None
    assert years_to_expiry(None) is None


def test_zero_dte_still_has_nonzero_time_value():
    """A 0DTE contract has intraday life; t must not be zero (division blows up)."""
    import datetime as dt
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    t = years_to_expiry(today)
    assert t is not None and t > 0


# ── changing option multipliers ────────────────────────────────────────────
def test_standard_multiplier_inferred_silently():
    m, warn = infer_multiplier({"trade_price": 5.0, "contracts": 1000, "premium": 500_000.0})
    assert m == 100.0 and warn is None


def test_nonstandard_multiplier_is_inferred_and_warned():
    """Adjusted contracts exist; assuming 100 would misscale P/L by 10x."""
    m, warn = infer_multiplier({"trade_price": 5.0, "contracts": 1000, "premium": 50_000.0})
    assert m == 10.0
    assert "Non-standard contract multiplier" in warn


def test_uninferable_multiplier_falls_back_and_warns():
    m, warn = infer_multiplier({"trade_price": 0, "contracts": 0, "premium": 0})
    assert m == 100.0 and "not inferable" in warn


def test_odd_multiplier_falls_back_and_warns_about_misscaling():
    m, warn = infer_multiplier({"trade_price": 5.0, "contracts": 1000, "premium": 187_000.0})
    assert m == 100.0
    assert "may be misscaled" in warn


def test_multiplier_is_applied_to_pl():
    ev = _ev(premium=50_000.0)      # implies multiplier 10
    pl = compute_event_pl(ev, _contract(bid=6.00))
    assert pl["multiplier"] == 10.0
    assert pl["estimated_pl_dollars"] == 10_000.0    # 1.00 x 1000 x 10


# ── extreme volatility ─────────────────────────────────────────────────────
def test_extreme_move_does_not_break_pl():
    pl = compute_event_pl(_ev(trade_price=0.05), _contract(bid=95.0, ask=96.0))
    assert pl["markable"] is True
    assert pl["estimated_pl_dollars"] == pytest.approx((95.0 - 0.05) * 1000 * 100)
    assert pl["estimated_return_pct"] > 100_000


def test_extreme_iv_does_not_break_theoretical_mark():
    mark, _, _ = compute_mark(_contract(iv=5.0), THEORETICAL, LONG, spot=6300.0,
                              t_years=0.02, option_side="CALL")
    assert mark is None or mark >= 0


def test_negative_and_garbage_inputs_never_raise():
    for c in (_contract(bid=-1, ask=-2), _contract(iv=-0.5), {}, {"bid": "x", "ask": "y"}):
        pl = compute_event_pl(_ev(), c)
        assert pl["flow_pl_version"] == FLOW_PL_VERSION


# ── spread width / quote context ───────────────────────────────────────────
def test_spread_width_and_context_reported():
    pl = compute_event_pl(_ev(), _contract(bid=6.00, ask=6.20))
    assert pl["spread_width"] == pytest.approx(0.20)
    assert pl["spread_pct"] == 3.3
    assert pl["liquidity_quality"] == 92.0
    assert pl["quote_source"] == "chain"


# ── cluster P/L ────────────────────────────────────────────────────────────
def _cluster_of(rows):
    events = classify_flow_events(rows)["events"]
    cl = build_flow_clusters(events, min_prints=1)["clusters"][0]
    return cl, events


def test_cluster_pl_weights_entries_by_contract_quantity():
    rows = [_row(time_et="10:31:02", trade_price=5.00, contracts=1000, premium=500_000.0),
            _row(time_et="10:31:06", trade_price=6.00, contracts=500, premium=300_000.0)]
    cl, events = _cluster_of(rows)
    members = [compute_event_pl(e, _contract(bid=7.00, ask=7.10)) for e in events]
    out = compute_cluster_pl(cl, members)
    expected = (5.00 * 1000 + 6.00 * 500) / 1500
    assert out["weighted_entry_mark"] == pytest.approx(round(expected, 4))
    assert out["total_contracts_marked"] == 1500


def test_cluster_preserves_member_entry_time_and_mark():
    rows = [_row(time_et="10:31:02", trade_price=5.00),
            _row(time_et="10:31:06", trade_price=6.00)]
    cl, events = _cluster_of(rows)
    members = [compute_event_pl(e, _contract()) for e in events]
    out = compute_cluster_pl(cl, members)
    times = {m["entry_time_et"] for m in out["members"]}
    marks = {m["entry_mark"] for m in out["members"]}
    assert times == {"10:31:02", "10:31:06"}
    assert marks == {5.00, 6.00}


def test_cluster_reports_aggregate_and_member_level_pl():
    rows = [_row(time_et="10:31:02", trade_price=5.00, contracts=1000),
            _row(time_et="10:31:06", trade_price=5.00, contracts=1000)]
    cl, events = _cluster_of(rows)
    members = [compute_event_pl(e, _contract(bid=6.00)) for e in events]
    out = compute_cluster_pl(cl, members)
    assert out["estimated_pl_dollars"] == 200_000.0
    assert len(out["members"]) == 2
    assert all(m["estimated_pl_dollars"] == 100_000.0 for m in out["members"])


# ── partial cluster formation ──────────────────────────────────────────────
def test_partial_cluster_marks_only_what_it_can_and_says_so():
    rows = [_row(time_et="10:31:02", trade_price=5.00),
            _row(time_et="10:31:06", trade_price=5.00)]
    cl, events = _cluster_of(rows)
    members = [compute_event_pl(events[0], _contract(bid=6.00)),
               compute_event_pl(events[1], None)]      # no quote for the second
    out = compute_cluster_pl(cl, members)
    assert out["marked_member_count"] == 1
    assert out["unmarked_member_count"] == 1
    assert any("could not be marked" in w for w in out["warnings"])
    assert any("understates or overstates" in w for w in out["warnings"])


def test_cluster_with_no_markable_members_reports_none_not_zero():
    rows = [_row(time_et="10:31:02"), _row(time_et="10:31:06")]
    cl, events = _cluster_of(rows)
    members = [compute_event_pl(e, None) for e in events]
    out = compute_cluster_pl(cl, members)
    assert out["estimated_pl_dollars"] is None      # not 0.0 — absence, not flat
    assert out["marked_member_count"] == 0


# ── uncertain package construction (the spec's explicit requirement) ──────
def test_spread_leg_cluster_warns_package_construction_unknown():
    """An uncertain spread must not be presented as a naked directional bet."""
    rows = [_row(time_et="10:31:02", strike=6300.0, trade_price=5.00),
            _row(time_et="10:31:02", strike=6310.0, trade_price=4.00)]
    events = classify_flow_events(rows)["events"]
    cl = build_flow_clusters(events, min_prints=1)["clusters"][0]
    members = [compute_event_pl(e, _contract(bid=6.00)) for e in events]
    out = compute_cluster_pl(cl, members)
    assert out["package_construction_known"] is False
    assert any("package construction is unknown" in w for w in out["warnings"])
    assert any("does not describe the participant's actual risk" in w for w in out["warnings"])


def test_roll_cluster_warns_package_construction_unknown():
    rows = [_row(time_et="10:31:02", expiration="2026-07-17", trade_side_code="AT_BID"),
            _row(time_et="10:31:03", expiration="2026-08-21", trade_side_code="ABOVE_ASK",
                 trade_price=9.40)]
    events = classify_flow_events(rows)["events"]
    clusters = build_flow_clusters(events, min_prints=1)["clusters"]
    flagged = []
    for cl in clusters:
        members = [compute_event_pl(e, _contract(bid=6.00)) for e in events
                   if e["event_id"] in cl["member_event_ids"]]
        flagged.append(compute_cluster_pl(cl, members)["package_construction_known"])
    assert False in flagged


def test_clean_single_contract_cluster_is_not_falsely_flagged():
    rows = [_row(time_et="10:31:02", trade_price=5.00),
            _row(time_et="10:31:06", trade_price=5.10)]
    cl, events = _cluster_of(rows)
    members = [compute_event_pl(e, _contract(bid=6.00)) for e in events]
    out = compute_cluster_pl(cl, members)
    assert out["package_construction_known"] is True


# ── MFE / MAE store ────────────────────────────────────────────────────────
@pytest.fixture()
def store(monkeypatch):
    from engine import flow_pl_store as S
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setattr(S, "_DB_PATH", tmp.name)
    S.init_db()
    yield S
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def test_store_initialises_and_reports_ready(store):
    assert store.is_ready() is True
    assert store.health()["tracked_events"] == 0


def test_first_observation_creates_a_baseline(store):
    pl = compute_event_pl(_ev(), _contract(bid=6.00))
    r = store.record_observation(pl, cluster_key="k", session_date="2026-07-16", spot=6300.0,
                                 iv=0.18)
    assert r["first_sample"] is True and r["samples"] == 1
    assert store.health()["tracked_events"] == 1


def test_mfe_and_mae_widen_across_samples(store):
    ev = _ev()
    store.record_observation(compute_event_pl(ev, _contract(bid=6.00)), cluster_key="k")
    store.record_observation(compute_event_pl(ev, _contract(bid=9.00)), cluster_key="k")  # up
    store.record_observation(compute_event_pl(ev, _contract(bid=2.00)), cluster_key="k")  # down
    store.record_observation(compute_event_pl(ev, _contract(bid=5.50)), cluster_key="k")
    exc = store.get_excursions([ev["event_id"]])[ev["event_id"]]
    assert exc["mfe_dollars"] == pytest.approx((9.00 - 5.00) * 1000 * 100)
    assert exc["mae_dollars"] == pytest.approx((2.00 - 5.00) * 1000 * 100)
    assert exc["samples"] == 4


def test_excursions_report_time_to_mfe_and_mae(store):
    ev = _ev()
    store.record_observation(compute_event_pl(ev, _contract(bid=6.00)), cluster_key="k")
    store.record_observation(compute_event_pl(ev, _contract(bid=9.00)), cluster_key="k")
    exc = store.get_excursions([ev["event_id"]])[ev["event_id"]]
    assert exc["time_to_mfe_seconds"] is not None
    assert exc["time_to_mae_seconds"] is not None


def test_excursion_basis_states_it_is_from_first_observation(store):
    ev = _ev()
    store.record_observation(compute_event_pl(ev, _contract(bid=6.00)), cluster_key="k")
    exc = store.get_excursions([ev["event_id"]])[ev["event_id"]]
    assert "first observation" in exc["excursion_basis"]
    assert "never available" in exc["excursion_basis"]


def test_unmarkable_events_are_not_tracked(store):
    pl = compute_event_pl(_ev(trade_side_code="MID"), _contract())
    assert store.record_observation(pl) is None
    assert store.health()["tracked_events"] == 0


def test_late_print_is_tracked_independently(store):
    """Assignment of late prints: a new event_id tracks on its own baseline."""
    a = _ev(time_et="10:31:02", trade_price=5.00)
    b = _ev(time_et="10:31:03", trade_price=5.50)
    store.record_observation(compute_event_pl(a, _contract(bid=6.00)), cluster_key="k")
    store.record_observation(compute_event_pl(b, _contract(bid=6.00)), cluster_key="k")
    exc = store.get_excursions([a["event_id"], b["event_id"]])
    assert len(exc) == 2
    assert exc[a["event_id"]]["mfe_dollars"] != exc[b["event_id"]]["mfe_dollars"]


def test_get_excursions_handles_unknown_ids(store):
    assert store.get_excursions(["nope"]) == {}
    assert store.get_excursions([]) == {}


def test_store_survives_large_id_lists(store):
    """SQLite has a variable limit; chunking must not error."""
    assert store.get_excursions([f"id{i}" for i in range(1200)]) == {}


# ── health / diagnostics ───────────────────────────────────────────────────
def test_health_declares_limits_and_label():
    h = health()
    assert h["label"] == THEORETICAL_PL_LABEL
    assert h["default_mark_method"] == CONSERVATIVE
    assert len(h["known_limits"]) >= 5
    blob = " ".join(h["known_limits"]).lower()
    assert "multiplier" in blob and "midpoint" in blob and "strike window" in blob


def test_forbidden_language_never_appears():
    banned = ("guaranteed", "smart_money", "institution_accumulating", "confirmed profit",
              "actual profit")
    pl = compute_event_pl(_ev(), _contract())
    blob = repr(pl).lower()
    for t in banned:
        assert t not in blob
