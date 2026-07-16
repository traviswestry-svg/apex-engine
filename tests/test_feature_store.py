"""Tests for engine/feature_store.py + feature_store_db.py — APEX 9 Step 5a.

Every leakage control the spec names has a test here that asserts the store
REFUSES the leak — not that it warns, logs, or flags it. A feature vector that
cannot be proven non-leaking must not be produced at all.
"""
import os
import tempfile

import pytest

from engine.feature_store import (
    EXPLORATORY, FEATURE_SCHEMA_VERSION, INSUFFICIENT, LABEL_SCHEMA_VERSION,
    MODERATE, STRONGER, Feature, LeakageError, assert_chronological_split,
    assert_disjoint_sessions, assert_feature_admissible, build_label_record,
    build_pre_decision_vector, features_from_frame, frames_from_replay,
    make_sample_id, resolve_frame_at_or_before, sample_quality, wilson_interval,
)

DEC = "2026-07-16T10:31:02"


def _f(name="gamma_regime", value="POSITIVE", at="2026-07-16T10:30:00", **kw):
    return Feature(name=name, value=value, available_at=at, source="replay_frame", **kw)


def _vec(features=None, **kw):
    kw.setdefault("sample_id", "s_1")
    kw.setdefault("decision_time", DEC)
    kw.setdefault("ticker", "SPX")
    return build_pre_decision_vector(features=features or [_f()], **kw)


# ══════════════════════════════════════════════════════════════════════════
# SPEC-NAMED LEAKAGE CONTROLS — each must FAIL the write
# ══════════════════════════════════════════════════════════════════════════

# 1. MFE or MAE appears in live features
@pytest.mark.parametrize("name", ["mfe", "mfe_dollars", "mae", "mae_dollars",
                                  "time_to_mfe_seconds", "cluster_mfe_dollars",
                                  "max_favourable_excursion_mae"])
def test_mfe_or_mae_in_features_is_refused(name):
    with pytest.raises(LeakageError, match=r"mfe|mae|outcome|future|label record"):
        _vec([_f(name=name, value=1234.0)])


# 2. Final outcome appears in pre-trade inputs
@pytest.mark.parametrize("name", ["outcome", "final_outcome", "target_hit", "stop_hit",
                                  "result", "win", "estimated_pl_dollars",
                                  "final_return_pct"])
def test_outcome_in_features_is_refused(name):
    with pytest.raises(LeakageError):
        _vec([_f(name=name, value="WIN")])


# 3. End-of-day open interest used intraday
def test_eod_open_interest_as_intraday_feature_is_refused_by_name():
    with pytest.raises(LeakageError, match="eod_|future|closing"):
        _vec([_f(name="eod_open_interest", value=12000)])


def test_end_of_day_oi_is_refused_by_timing_even_if_renamed():
    """The name guard is a convenience; the timing rule is the real defence."""
    with pytest.raises(LeakageError, match="AFTER the decision"):
        _vec([_f(name="open_interest", value=12000,
                 at="2026-07-16T16:00:00")])          # published at the close


# 4. Revised historical data treated as contemporaneously available
def test_revised_value_without_revision_of_is_refused():
    with pytest.raises(LeakageError, match="revision_of"):
        _vec([_f(name="open_interest", value=12000, at="2026-07-16T10:30:00",
                 revised=True)])


def test_revision_that_predates_what_it_revises_is_refused():
    """This is exactly how EOD data gets smuggled into intraday features."""
    with pytest.raises(LeakageError, match="cannot predate"):
        _vec([_f(name="open_interest", value=12000,
                 at="2026-07-16T10:00:00", revised=True,
                 revision_of="2026-07-16T10:30:00")])


def test_properly_stamped_revision_is_admissible():
    v = _vec([_f(name="open_interest", value=12000,
                 at="2026-07-16T10:30:00", revised=True,
                 revision_of="2026-07-15T16:00:00")])
    assert v["feature_availability"]["open_interest"]["revised"] is True


# 5. Future GEX snapshots
def test_future_gex_snapshot_is_refused():
    with pytest.raises(LeakageError, match="AFTER the decision"):
        _vec([_f(name="gamma_regime", value="POSITIVE",
                 at="2026-07-16T10:31:05")])          # 3s after the decision


def test_gex_named_future_is_refused_by_name_too():
    with pytest.raises(LeakageError, match="future_"):
        _vec([_f(name="future_gex", value=1.2)])


# 6. Future volume-profile states
def test_future_volume_profile_is_refused():
    with pytest.raises(LeakageError, match="AFTER the decision"):
        _vec([_f(name="poc", value=6300.0, at="2026-07-16T11:00:00")])


def test_next_session_poc_is_refused_by_name():
    with pytest.raises(LeakageError, match="next_"):
        _vec([_f(name="next_session_poc", value=6310.0)])


# 7. Session-closing labels used before close
@pytest.mark.parametrize("name", ["session_close", "closing_price", "settlement",
                                  "settlement_price", "closing_open_interest"])
def test_session_closing_values_are_refused_as_features(name):
    with pytest.raises(LeakageError):
        _vec([_f(name=name, value=6305.0)])


def test_label_settling_before_the_decision_is_refused():
    with pytest.raises(LeakageError, match="cannot resolve before"):
        build_label_record(sample_id="s_1", decision_time=DEC,
                           settled_at="2026-07-16T10:00:00",
                           labels={"mfe_dollars": 100.0})


# 8. Train and evaluation sessions overlap improperly
def test_overlapping_train_and_eval_sessions_are_refused():
    with pytest.raises(LeakageError, match="share session"):
        assert_disjoint_sessions(["2026-07-14", "2026-07-15"], ["2026-07-15"])


def test_empty_split_is_refused():
    with pytest.raises(LeakageError, match="non-empty"):
        assert_disjoint_sessions(["2026-07-14"], [])


def test_evaluating_on_a_session_before_training_is_refused():
    """A random split leaks regime knowledge backwards."""
    with pytest.raises(LeakageError, match="not strictly after"):
        assert_chronological_split(["2026-07-15", "2026-07-16"], ["2026-07-14"])


def test_chronological_split_is_accepted():
    assert_chronological_split(["2026-07-14", "2026-07-15"], ["2026-07-16"])


# ══════════════════════════════════════════════════════════════════════════
# The timing rule itself
# ══════════════════════════════════════════════════════════════════════════
def test_feature_available_exactly_at_decision_time_is_admissible():
    """The boundary is inclusive: knowable AT the decision is knowable."""
    v = _vec([_f(at=DEC)])
    assert v["feature_availability"]["gamma_regime"]["lag_seconds"] == 0.0


def test_feature_one_second_after_decision_is_refused():
    with pytest.raises(LeakageError, match="AFTER the decision"):
        _vec([_f(at="2026-07-16T10:31:03")])


def test_feature_without_availability_timestamp_is_refused():
    with pytest.raises(LeakageError, match="available_at|availability"):
        _vec([Feature(name="gamma_regime", value="POSITIVE", available_at="",
                      source="replay_frame")])


def test_unparseable_availability_is_refused():
    with pytest.raises(LeakageError):
        _vec([_f(at="not-a-timestamp")])


def test_missing_decision_time_is_refused():
    with pytest.raises(LeakageError):
        build_pre_decision_vector(sample_id="s_1", decision_time="", ticker="SPX",
                                  features=[_f()])


def test_raw_dict_instead_of_feature_is_refused():
    """Anything without an availability stamp cannot be proven non-leaking."""
    with pytest.raises(LeakageError, match="availability timestamp"):
        assert_feature_admissible({"name": "gamma_regime", "value": "POSITIVE"}, DEC)


def test_feature_lag_is_recorded_per_field():
    v = _vec([_f(at="2026-07-16T10:26:02")])       # 5 minutes stale
    assert v["feature_availability"]["gamma_regime"]["lag_seconds"] == 300.0
    assert v["max_feature_lag_seconds"] == 300.0


def test_duplicate_feature_names_are_refused():
    with pytest.raises(LeakageError, match="duplicate"):
        _vec([_f(), _f(value="NEGATIVE")])


def test_empty_feature_vector_is_refused():
    # call the builder directly — the _vec helper defaults an empty list
    with pytest.raises(LeakageError, match="no features"):
        build_pre_decision_vector(sample_id="s_1", decision_time=DEC, ticker="SPX",
                                  features=[])


def test_sampling_artefact_is_refused_as_a_feature():
    """Step 4.1 limitation: `samples` reflects observation, not market activity."""
    with pytest.raises(LeakageError):
        _vec([_f(name="samples", value=12)])


# ══════════════════════════════════════════════════════════════════════════
# Point-in-time frame resolution (the join, and the boundary)
# ══════════════════════════════════════════════════════════════════════════
FRAMES = [
    {"captured_at": "2026-07-16T10:25:00", "snapshot": {"gamma_regime": "NEG"}},
    {"captured_at": "2026-07-16T10:30:00", "snapshot": {"gamma_regime": "POS"}},
    {"captured_at": "2026-07-16T10:35:00", "snapshot": {"gamma_regime": "FLIP"}},
]


def test_resolver_picks_the_newest_frame_at_or_before():
    fr = resolve_frame_at_or_before(FRAMES, DEC)
    assert fr["captured_at"] == "2026-07-16T10:30:00"


def test_resolver_never_picks_the_nearest_when_nearest_is_in_the_future():
    """A frame 3s after beats one 5min before on distance — and is a leak."""
    fr = resolve_frame_at_or_before(FRAMES, "2026-07-16T10:34:59")
    assert fr["captured_at"] == "2026-07-16T10:30:00"      # not 10:35


def test_resolver_accepts_a_frame_exactly_at_the_decision():
    fr = resolve_frame_at_or_before(FRAMES, "2026-07-16T10:30:00")
    assert fr["captured_at"] == "2026-07-16T10:30:00"


def test_resolver_returns_none_when_all_frames_are_future():
    assert resolve_frame_at_or_before(FRAMES, "2026-07-16T09:00:00") is None


def test_resolver_enforces_max_staleness():
    assert resolve_frame_at_or_before(FRAMES, DEC, max_staleness_seconds=30) is None
    assert resolve_frame_at_or_before(FRAMES, DEC, max_staleness_seconds=600) is not None


def test_resolver_handles_empty_and_garbage():
    assert resolve_frame_at_or_before([], DEC) is None
    assert resolve_frame_at_or_before([{"captured_at": "junk"}], DEC) is None
    assert resolve_frame_at_or_before(FRAMES, "junk") is None


def test_frames_from_replay_builds_absolute_timestamps():
    rows = [{"session_date": "2026-07-16", "frame_time": "10:30:00", "ticker": "SPX",
             "snapshot_json": '{"gamma_regime": "POS"}'}]
    fr = frames_from_replay(rows)
    assert fr[0]["captured_at"] == "2026-07-16T10:30:00"
    assert fr[0]["snapshot"]["gamma_regime"] == "POS"


def test_frames_from_replay_skips_rows_without_time():
    assert frames_from_replay([{"ticker": "SPX"}]) == []


def test_features_from_frame_stamps_the_frame_time():
    fr = frames_from_replay([{"session_date": "2026-07-16", "frame_time": "10:30:00",
                              "ticker": "SPX",
                              "snapshot_json": '{"gamma_regime":"POS","ici":72}'}])[0]
    feats = features_from_frame(fr)
    assert {f.name for f in feats} == {"gamma_regime", "ici"}
    assert all(f.available_at == "2026-07-16T10:30:00" for f in feats)


def test_features_from_frame_drops_outcome_fields():
    """Leak-grounds exclusion: outcome data must never become a feature."""
    fr = {"captured_at": "2026-07-16T10:30:00",
          "snapshot": {"gamma_regime": "POS", "mfe_dollars": 100.0,
                       "final_outcome": "WIN"}}
    names = {f.name for f in features_from_frame(fr)}
    assert names == {"gamma_regime"}


def test_features_from_frame_drops_prose_but_not_because_it_leaks():
    """Modelling-grounds exclusion: prose is not a leak, it is just not a feature."""
    fr = {"captured_at": "2026-07-16T10:30:00",
          "snapshot": {"gamma_regime": "POS", "executive_summary": "SPX grinding up...",
                       "coach_entry": 6300.0, "coach_t1": 6320.0}}
    names = {f.name for f in features_from_frame(fr)}
    assert names == {"gamma_regime"}


def test_apex_own_state_is_kept_as_features():
    """ici/grade/decision_state/recommendation were knowable at the frame.

    Conditioning on them is the point: it is how you learn whether APEX's own
    calls fare better in some regimes than others.
    """
    fr = {"captured_at": "2026-07-16T10:30:00",
          "snapshot": {"ici": 72, "grade": "A", "decision_state": "ARMED",
                       "recommendation": "ENTER_CALL", "coach_action": "ENTER",
                       "approved_side": "CALL"}}
    names = {f.name for f in features_from_frame(fr)}
    assert names == {"ici", "grade", "decision_state", "recommendation",
                     "coach_action", "approved_side"}


def test_non_feature_fields_are_separate_from_forbidden_ones():
    """The two exclusion reasons must not be conflated."""
    from engine.feature_store import FORBIDDEN_FEATURE_NAMES, NON_FEATURE_FIELDS
    assert not (FORBIDDEN_FEATURE_NAMES & NON_FEATURE_FIELDS)


def test_frame_features_flow_into_an_admissible_vector():
    fr = resolve_frame_at_or_before(FRAMES, DEC)
    v = _vec(features_from_frame(fr))
    assert v["features"]["gamma_regime"] == "POS"
    assert v["max_feature_lag_seconds"] == 62.0


# ══════════════════════════════════════════════════════════════════════════
# Labels
# ══════════════════════════════════════════════════════════════════════════
def test_label_record_accepts_outcome_fields():
    r = build_label_record(sample_id="s_1", decision_time=DEC,
                           settled_at="2026-07-16T16:00:00",
                           labels={"mfe_dollars": 5000.0, "mae_dollars": -1200.0,
                                   "target_hit": True, "duration_seconds": 900})
    assert r["labels"]["mfe_dollars"] == 5000.0
    assert r["schema_version"] == LABEL_SCHEMA_VERSION


def test_label_record_states_its_own_basis():
    r = build_label_record(sample_id="s_1", decision_time=DEC,
                           settled_at="2026-07-16T16:00:00", labels={"mfe_dollars": 1.0})
    assert "lower bounds" in r["label_basis"]
    assert "first observation" in r["label_basis"]


def test_unknown_label_field_is_refused():
    with pytest.raises(LeakageError, match="unknown label"):
        build_label_record(sample_id="s_1", decision_time=DEC,
                           settled_at="2026-07-16T16:00:00",
                           labels={"lucky_guess": 1})


def test_label_settling_at_the_decision_instant_is_allowed():
    r = build_label_record(sample_id="s_1", decision_time=DEC, settled_at=DEC,
                           labels={"mfe_dollars": 0.0})
    assert r["settled_at"] == DEC


# ══════════════════════════════════════════════════════════════════════════
# Sample-size honesty
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("n,tier,permitted", [
    (0, INSUFFICIENT, False), (19, INSUFFICIENT, False),
    (20, EXPLORATORY, False), (49, EXPLORATORY, False),
    (50, MODERATE, True), (199, MODERATE, True),
    (200, STRONGER, True), (5000, STRONGER, True),
])
def test_sample_quality_tiers(n, tier, permitted):
    q = sample_quality(n)
    assert q["tier"] == tier
    assert q["edge_claim_permitted"] is permitted


def test_sample_quality_says_the_count_is_per_neighbourhood():
    """The spec doesn't specify; global counts would bless a 3-sample cell."""
    q = sample_quality(250)
    assert "MATCHED NEIGHBOURHOOD" in q["basis"]
    assert "not the store total" in q["basis"]


def test_stronger_tier_still_warns_about_regime_correlation():
    assert "not independent" in sample_quality(500)["note"]


def test_wilson_interval_is_wide_at_small_n():
    narrow = wilson_interval(45, 50)
    wide = wilson_interval(9, 10)
    assert (wide["high"] - wide["low"]) > (narrow["high"] - narrow["low"])


def test_wilson_interval_stays_in_bounds_at_extremes():
    for k, n in ((0, 5), (5, 5), (0, 1), (1, 1)):
        ci = wilson_interval(k, n)
        assert 0.0 <= ci["low"] <= ci["high"] <= 1.0


def test_wilson_interval_handles_zero_samples():
    assert wilson_interval(0, 0) is None


# ══════════════════════════════════════════════════════════════════════════
# Persistence — two tables, and the only sanctioned join
# ══════════════════════════════════════════════════════════════════════════
@pytest.fixture()
def db(monkeypatch):
    from engine import feature_store_db as D
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setattr(D, "_DB_PATH", tmp.name)
    D.init_db()
    yield D
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def _sample(db, sid, session, dec, label=True):
    v = build_pre_decision_vector(sample_id=sid, decision_time=dec, ticker="SPX",
                                  features=[_f(at=dec)], session_date=session)
    db.write_features(v)
    if label:
        db.write_label(build_label_record(
            sample_id=sid, decision_time=dec, settled_at=f"{session}T16:00:00",
            labels={"mfe_dollars": 100.0, "mae_dollars": -50.0, "target_hit": True},
            session_date=session))
    return v


def test_features_and_labels_live_in_separate_tables(db):
    _sample(db, "s_1", "2026-07-14", "2026-07-14T10:31:02")
    import sqlite3
    c = sqlite3.connect(db._DB_PATH)
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "flow_features" in tables and "flow_labels" in tables
    # no view that pre-joins them
    views = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='view'")}
    assert not views


def test_feature_row_contains_no_label_fields(db):
    _sample(db, "s_1", "2026-07-14", "2026-07-14T10:31:02")
    got = db.get_features("s_1")
    blob = repr(got).lower()
    for leak in ("mfe", "mae", "target_hit", "outcome"):
        assert leak not in blob


def test_features_are_immutable_once_written(db):
    """A cluster mutates as late prints arrive; history must not be rewritten."""
    _sample(db, "s_1", "2026-07-14", "2026-07-14T10:31:02", label=False)
    v2 = build_pre_decision_vector(sample_id="s_1", decision_time="2026-07-14T10:31:02",
                                   ticker="SPX",
                                   features=[_f(value="CHANGED", at="2026-07-14T10:31:02")],
                                   session_date="2026-07-14")
    assert db.write_features(v2) is False           # refused
    assert db.get_features("s_1")["features"]["gamma_regime"] == "POSITIVE"


def test_labels_may_be_updated_as_excursions_widen(db):
    _sample(db, "s_1", "2026-07-14", "2026-07-14T10:31:02")
    db.write_label(build_label_record(
        sample_id="s_1", decision_time="2026-07-14T10:31:02",
        settled_at="2026-07-14T16:00:00",
        labels={"mfe_dollars": 9000.0}, session_date="2026-07-14"))
    pairs = db.load_training_pairs(train_sessions=["2026-07-14"],
                                   eval_sessions=["2026-07-15"])
    assert pairs["train"][0]["labels"]["mfe_dollars"] == 9000.0


def test_load_training_pairs_enforces_the_split(db):
    _sample(db, "s_1", "2026-07-14", "2026-07-14T10:31:02")
    with pytest.raises(LeakageError, match="share session"):
        db.load_training_pairs(train_sessions=["2026-07-14"],
                               eval_sessions=["2026-07-14"])


def test_load_training_pairs_enforces_chronology(db):
    with pytest.raises(LeakageError, match="not strictly after"):
        db.load_training_pairs(train_sessions=["2026-07-16"],
                               eval_sessions=["2026-07-14"])


def test_load_training_pairs_keeps_features_and_labels_in_named_subobjects(db):
    """So a caller can't sweep a label into a feature matrix with row.values()."""
    _sample(db, "s_1", "2026-07-14", "2026-07-14T10:31:02")
    _sample(db, "s_2", "2026-07-15", "2026-07-15T10:31:02")
    pairs = db.load_training_pairs(train_sessions=["2026-07-14"],
                                   eval_sessions=["2026-07-15"])
    row = pairs["train"][0]
    assert set(row["features"]) == {"gamma_regime"}
    assert "mfe_dollars" in row["labels"]
    assert "mfe_dollars" not in row["features"]


def test_unlabelled_samples_are_reported(db):
    _sample(db, "s_1", "2026-07-14", "2026-07-14T10:31:02", label=False)
    assert db.unlabelled_samples() == ["s_1"]
    assert db.health()["unlabelled"] == 1


def test_unlabelled_samples_are_excluded_from_training_pairs(db):
    _sample(db, "s_1", "2026-07-14", "2026-07-14T10:31:02", label=False)
    _sample(db, "s_2", "2026-07-14", "2026-07-14T10:32:02", label=True)
    _sample(db, "s_3", "2026-07-15", "2026-07-15T10:31:02")
    pairs = db.load_training_pairs(train_sessions=["2026-07-14"],
                                   eval_sessions=["2026-07-15"])
    assert [r["sample_id"] for r in pairs["train"]] == ["s_2"]


def test_health_reports_counts_and_the_separation_note(db):
    _sample(db, "s_1", "2026-07-14", "2026-07-14T10:31:02")
    h = db.health()
    assert h["feature_rows"] == 1 and h["label_rows"] == 1
    assert h["feature_sessions"] == 1
    assert "separate tables" in h["note"]


def test_store_degrades_non_fatally_when_not_ready(monkeypatch):
    from engine import feature_store_db as D
    monkeypatch.setattr(D, "_DB_READY", False)
    assert D.write_features({"sample_id": "x"}) is False
    assert D.get_features("x") is None
    assert D.load_training_pairs(train_sessions=["a"], eval_sessions=["b"]) == \
        {"train": [], "eval": []}


def test_sample_id_is_deterministic():
    a = make_sample_id(ticker="SPX", decision_time=DEC, cluster_key="SPX|CALL|exp|BULLISH")
    b = make_sample_id(ticker="SPX", decision_time=DEC, cluster_key="SPX|CALL|exp|BULLISH")
    c = make_sample_id(ticker="SPX", decision_time=DEC, cluster_key="SPX|PUT|exp|BULLISH")
    assert a == b and a != c


def test_vector_is_schema_versioned():
    assert _vec()["schema_version"] == FEATURE_SCHEMA_VERSION
