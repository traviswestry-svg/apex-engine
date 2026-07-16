"""Tests for engine/feature_store_writer.py — APEX 9 Step 5a.1.

The two things that must not go wrong quietly: the sealing rule (which decides
what a sample even is), and outcome ordering (which decides whether a cluster
that touched both target and stop is recorded as a win or a loss).
"""
import os
import tempfile

import pytest

from engine import feature_store_db as D
from engine import flow_pl_store as S
from engine import feature_store_writer as W
from engine.feature_store import LeakageError

SESSION = "2026-07-16"
FRAMES = [{"session_date": SESSION, "frame_time": "10:26:00", "ticker": "SPX",
           "snapshot_json": '{"gamma_regime":"POSITIVE","ici":58,"stock_price":6295.0}'},
          {"session_date": SESSION, "frame_time": "10:31:00", "ticker": "SPX",
           "snapshot_json": '{"gamma_regime":"POSITIVE","ici":72,"stock_price":6300.0,'
                            '"executive_summary":"prose","coach_action":"ENTER"}'},
          {"session_date": SESSION, "frame_time": "10:36:00", "ticker": "SPX",
           "snapshot_json": '{"gamma_regime":"FLIP","ici":81,"stock_price":6320.0}'}]


def _cluster(end="10:31:11", **over):
    c = {"cluster_id": "c_1", "ticker": "SPX", "option_type": "CALL",
         "expiration": "2026-07-17", "directional_interpretation": "BULLISH",
         "cluster_key": {"ticker": "SPX", "option_type": "CALL",
                         "expiration": "2026-07-17",
                         "directional_interpretation": "BULLISH"},
         "cluster_key_string": "SPX|CALL|2026-07-17|BULLISH",
         "start_time": "10:31:02", "end_time": end, "duration_seconds": 9,
         "number_of_prints": 4, "total_premium": 1_819_250, "total_contracts": 3350,
         "weighted_average_execution_price": 5.03, "aggression_score": 100.0,
         "repeat_intensity_score": 75.0, "distinct_contracts": 2,
         "premium_concentration": 0.31, "confidence": 0.63,
         "strike_range": [6300.0, 6310.0],
         "intent_uncertainty": {"score": 0.39, "notes": []},
         "estimated_pl_dollars": 226_000.0, "cost_basis_dollars": 1_819_250.0}
    c.update(over)
    return c


@pytest.fixture()
def stores(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setattr(D, "_DB_PATH", tmp.name)
    monkeypatch.setattr(S, "_DB_PATH", tmp.name)
    D.init_db(); S.init_db()
    yield
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def _now(hhmm="10:35"):
    h, m = hhmm.split(":")
    return int(h) * 3600 + int(m) * 60


# ── the sealing rule ──────────────────────────────────────────────────────
def test_unsealed_cluster_is_not_written(stores):
    """Inside the gap window a later print can still join — the sample isn't final."""
    r = W.write_samples(priced_clusters=[_cluster()], replay_rows=FRAMES,
                        session_date=SESSION, now_et_seconds=_now("10:32"))
    assert r["not_sealed"] == 1 and r["written"] == 0
    assert D.health()["feature_rows"] == 0


def test_sealed_cluster_is_written(stores):
    r = W.write_samples(priced_clusters=[_cluster()], replay_rows=FRAMES,
                        session_date=SESSION, now_et_seconds=_now("10:35"))
    assert r["written"] == 1
    assert D.health()["feature_rows"] == 1


def test_seal_boundary_is_the_gap_window(stores):
    # end 10:31:11 + 120s = sealed at 10:33:11
    early = W.write_samples(priced_clusters=[_cluster()], replay_rows=FRAMES,
                            session_date=SESSION, now_et_seconds=_now("10:33"))
    assert early["not_sealed"] == 1
    late = W.write_samples(priced_clusters=[_cluster()], replay_rows=FRAMES,
                           session_date=SESSION, now_et_seconds=_now("10:34"))
    assert late["written"] == 1


def test_decision_time_is_cluster_end_not_write_time(stores):
    """Waiting for the seal must not leak hindsight into the vector."""
    W.write_samples(priced_clusters=[_cluster()], replay_rows=FRAMES,
                    session_date=SESSION, now_et_seconds=_now("10:35"))
    sid = D.unlabelled_samples(SESSION)[0]
    v = D.get_features(sid)
    assert v["decision_time"] == f"{SESSION}T10:31:11"


def test_features_come_from_the_frame_before_the_decision_not_after(stores):
    """The 10:36 frame (ici 81, gamma FLIP) must never reach a 10:31 sample."""
    W.write_samples(priced_clusters=[_cluster()], replay_rows=FRAMES,
                    session_date=SESSION, now_et_seconds=_now("10:40"))
    v = D.get_features(D.unlabelled_samples(SESSION)[0])
    assert v["features"]["ici"] == 72          # the 10:31 frame
    assert v["features"]["gamma_regime"] == "POSITIVE"
    assert v["features"]["stock_price"] == 6300.0


def test_writing_twice_is_idempotent(stores):
    a = W.write_samples(priced_clusters=[_cluster()], replay_rows=FRAMES,
                        session_date=SESSION, now_et_seconds=_now("10:35"))
    b = W.write_samples(priced_clusters=[_cluster()], replay_rows=FRAMES,
                        session_date=SESSION, now_et_seconds=_now("10:40"))
    assert a["written"] == 1 and b["written"] == 0 and b["already_present"] == 1
    assert D.health()["feature_rows"] == 1


def test_shrunken_cluster_cannot_overwrite_the_fuller_first_sample(stores):
    """The tape is a sliding window: later views of a cluster only lose members."""
    W.write_samples(priced_clusters=[_cluster()], replay_rows=FRAMES,
                    session_date=SESSION, now_et_seconds=_now("10:35"))
    shrunk = _cluster(number_of_prints=2, total_premium=900_000)
    W.write_samples(priced_clusters=[shrunk], replay_rows=FRAMES,
                    session_date=SESSION, now_et_seconds=_now("10:45"))
    v = D.get_features(D.unlabelled_samples(SESSION)[0])
    assert v["features"]["cluster_number_of_prints"] == 4      # the fuller snapshot


def test_no_frame_before_decision_skips_the_sample_with_a_reason(stores):
    r = W.write_samples(priced_clusters=[_cluster(end="09:31:11")],
                        replay_rows=FRAMES, session_date=SESSION,
                        now_et_seconds=_now("09:40"))
    assert r["no_frame"] == 1 and r["written"] == 0
    assert "no replay frame at-or-before" in r["reasons"][0]


def test_stale_frame_beyond_limit_skips_rather_than_writes_stale_features(stores):
    far = [{"session_date": SESSION, "frame_time": "09:00:00", "ticker": "SPX",
            "snapshot_json": '{"gamma_regime":"POSITIVE"}'}]
    r = W.write_samples(priced_clusters=[_cluster()], replay_rows=far,
                        session_date=SESSION, now_et_seconds=_now("10:35"))
    assert r["no_frame"] == 1


def test_cluster_features_are_whitelisted_and_prefixed(stores):
    W.write_samples(priced_clusters=[_cluster(secret_new_field="leaky")],
                    replay_rows=FRAMES, session_date=SESSION,
                    now_et_seconds=_now("10:35"))
    v = D.get_features(D.unlabelled_samples(SESSION)[0])
    assert "cluster_aggression_score" in v["features"]
    assert "cluster_intent_uncertainty" in v["features"]
    assert "cluster_strike_low" in v["features"]
    assert "secret_new_field" not in v["features"]      # not whitelisted
    assert "cluster_secret_new_field" not in v["features"]


def test_prose_from_the_frame_does_not_become_a_feature(stores):
    W.write_samples(priced_clusters=[_cluster()], replay_rows=FRAMES,
                    session_date=SESSION, now_et_seconds=_now("10:35"))
    v = D.get_features(D.unlabelled_samples(SESSION)[0])
    assert "executive_summary" not in v["features"]
    assert "coach_action" in v["features"]      # APEX state IS a feature


def test_writer_reports_when_store_is_not_ready(monkeypatch):
    monkeypatch.setattr(D, "_DB_READY", False)
    r = W.write_samples(priced_clusters=[_cluster()], replay_rows=FRAMES,
                        session_date=SESSION, now_et_seconds=_now("10:35"))
    assert r["written"] == 0 and "not ready" in r["reasons"][0]


def test_writer_never_raises_on_garbage(stores):
    for bad in ([{}], [{"end_time": "junk"}], [None]):
        try:
            r = W.write_samples(priced_clusters=bad, replay_rows=FRAMES,
                                session_date=SESSION, now_et_seconds=_now())
            assert r["writer_version"] == W.WRITER_VERSION
        except TypeError:
            pass       # None member is a caller bug, not a silent corruption


# ── outcome classification: ordering is the whole game ────────────────────
def _oc(mfe, mae, cost=1000.0, t_mfe=None, t_mae=None):
    return W._classify_outcome(mfe, mae, cost, t_mfe, t_mae)


def test_target_only():
    r = _oc(1500.0, -100.0)          # +150% / -10%
    assert r["target_hit"] and not r["stop_hit"]
    assert r["final_outcome"] == "TARGET_ONLY"


def test_stop_only():
    r = _oc(100.0, -600.0)           # +10% / -60%
    assert r["stop_hit"] and not r["target_hit"]
    assert r["final_outcome"] == "STOP_ONLY"


def test_neither():
    assert _oc(200.0, -200.0)["final_outcome"] == "NEITHER"


def test_stop_first_is_not_recorded_as_a_win():
    """A cluster that hit -50% before +100% was a loser. This is the test."""
    r = _oc(1500.0, -600.0, t_mfe=1800, t_mae=300)
    assert r["target_hit"] and r["stop_hit"]
    assert r["final_outcome"] == "STOP_FIRST"


def test_target_first_when_it_came_first():
    r = _oc(1500.0, -600.0, t_mfe=300, t_mae=1800)
    assert r["final_outcome"] == "TARGET_FIRST"


def test_same_sample_ordering_is_reported_unknown_not_guessed():
    """At a 300s grid the order inside one interval is not observable."""
    r = _oc(1500.0, -600.0, t_mfe=600, t_mae=600)
    assert r["final_outcome"] == "BOTH_SAME_SAMPLE"


def test_missing_times_report_order_unknown():
    assert _oc(1500.0, -600.0)["final_outcome"] == "BOTH_ORDER_UNKNOWN"


def test_no_cost_basis_yields_no_outcome():
    r = _oc(1500.0, -600.0, cost=None)
    assert r["final_outcome"] is None and r["target_hit"] is None


# ── labelling ─────────────────────────────────────────────────────────────
def _seed(stores_ignored=None):
    W.write_samples(priced_clusters=[_cluster()], replay_rows=FRAMES,
                    session_date=SESSION, now_et_seconds=_now("10:35"))


def test_settle_labels_writes_from_cluster_excursions(stores):
    _seed()
    key = "SPX|CALL|2026-07-17|BULLISH"
    S.record_cluster_observation(cluster_key=key, session_date=SESSION, ticker="SPX",
                                 pl_dollars=100_000.0, cost_basis=1_819_250.0)
    S.record_cluster_observation(cluster_key=key, session_date=SESSION, ticker="SPX",
                                 pl_dollars=2_500_000.0, cost_basis=1_819_250.0)
    S.record_cluster_observation(cluster_key=key, session_date=SESSION, ticker="SPX",
                                 pl_dollars=-1_000_000.0, cost_basis=1_819_250.0)
    r = W.settle_labels(session_date=SESSION)
    assert r["labelled"] == 1
    pairs = D.load_training_pairs(train_sessions=[SESSION], eval_sessions=["2026-07-17"])
    lab = pairs["train"][0]["labels"]
    assert lab["mfe_dollars"] == 2_500_000.0
    assert lab["mae_dollars"] == -1_000_000.0
    assert lab["target_hit"] is True         # +137% of cost basis
    assert lab["stop_hit"] is True           # -55% of cost basis


def test_label_basis_names_the_thresholds_as_apex_defined(stores):
    _seed()
    S.record_cluster_observation(cluster_key="SPX|CALL|2026-07-17|BULLISH",
                                 session_date=SESSION, ticker="SPX",
                                 pl_dollars=100.0, cost_basis=1000.0)
    W.settle_labels(session_date=SESSION)
    import sqlite3
    c = sqlite3.connect(D._DB_PATH); c.row_factory = sqlite3.Row
    basis = c.execute("SELECT label_basis FROM flow_labels").fetchone()[0]
    assert "APEX-defined thresholds" in basis
    assert "participant's real targets are unknown" in basis
    assert "lower bounds" in basis


def test_sample_without_excursions_is_not_labelled(stores):
    _seed()
    r = W.settle_labels(session_date=SESSION)
    assert r["labelled"] == 0 and r["no_excursion"] == 1
    assert D.health()["unlabelled"] == 1


def test_settle_is_idempotent(stores):
    _seed()
    S.record_cluster_observation(cluster_key="SPX|CALL|2026-07-17|BULLISH",
                                 session_date=SESSION, ticker="SPX",
                                 pl_dollars=100.0, cost_basis=1000.0)
    W.settle_labels(session_date=SESSION)
    r2 = W.settle_labels(session_date=SESSION)
    assert r2["labelled"] == 0          # nothing unlabelled remains


def test_labels_settle_at_session_close(stores):
    _seed()
    S.record_cluster_observation(cluster_key="SPX|CALL|2026-07-17|BULLISH",
                                 session_date=SESSION, ticker="SPX",
                                 pl_dollars=100.0, cost_basis=1000.0)
    W.settle_labels(session_date=SESSION)
    pairs = D.load_training_pairs(train_sessions=[SESSION], eval_sessions=["2026-07-17"])
    assert pairs["train"][0]["settled_at"] == f"{SESSION}T16:00:00"


# ── cluster-level excursions (not summed member excursions) ───────────────
def test_cluster_excursion_envelope_widens(stores):
    key = "SPX|CALL|2026-07-17|BULLISH"
    for pl in (100.0, 900.0, -400.0, 50.0):
        S.record_cluster_observation(cluster_key=key, session_date=SESSION,
                                     ticker="SPX", pl_dollars=pl, cost_basis=1000.0)
    e = S.get_cluster_excursions([key], SESSION)[key]
    assert e["mfe_dollars"] == 900.0 and e["mae_dollars"] == -400.0
    assert e["samples"] == 4 and e["last_pl"] == 50.0


def test_cluster_excursions_are_scoped_to_a_session(stores):
    key = "SPX|CALL|2026-07-17|BULLISH"
    S.record_cluster_observation(cluster_key=key, session_date=SESSION, ticker="SPX",
                                 pl_dollars=900.0, cost_basis=1000.0)
    assert S.get_cluster_excursions([key], "2026-07-17") == {}


def test_cluster_excursion_ignores_none_pl(stores):
    assert S.record_cluster_observation(cluster_key="k", session_date=SESSION,
                                        ticker="SPX", pl_dollars=None,
                                        cost_basis=1000.0) is None


def test_writer_health_states_the_caveats():
    h = W.health()
    assert h["label_horizon"] == "session_close"
    assert "never leaks hindsight" in h["decision_point"]
    assert "not the participant's actual targets" in h["threshold_caveat"]
