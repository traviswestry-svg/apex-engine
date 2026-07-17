"""Tests for the feature store records API — APEX 9 Step 5a.2.

The load-bearing property: inspection is generous, but no route ever hands back a
flat row containing a feature and a label together, and no rate is printed for a
neighbourhood too thin to support one.
"""
import os
import tempfile

import pytest
from flask import Flask

from engine import feature_store_db as D
from engine.feature_store import build_label_record, build_pre_decision_vector, Feature
from engine.feature_store_routes import register_feature_store_routes

SESSION = "2026-07-16"


@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setattr(D, "_DB_PATH", tmp.name)
    D.init_db()
    app = Flask(__name__)
    register_feature_store_routes(app)
    yield app.test_client()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def _t(i):
    """Valid ET wall-clock stamp for sample i (avoids seconds > 59)."""
    base = 10 * 3600 + 31 * 60 + 11
    s = base + i * 7
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _mk(sid, session=SESSION, dec=None, gamma="POSITIVE", auction="TRENDING",
        direction="BULLISH", premium=1_000_000.0, label=None):
    dec = dec or f"{session}T10:31:11"
    feats = [
        Feature("gamma_regime", gamma, dec, "replay_frame"),
        Feature("auction_state", auction, dec, "replay_frame"),
        Feature("ici", 72, dec, "replay_frame"),
        Feature("cluster_directional_interpretation", direction, dec, "flow_cluster"),
        Feature("cluster_total_premium", premium, dec, "flow_cluster"),
    ]
    D.write_features(build_pre_decision_vector(
        sample_id=sid, decision_time=dec, ticker="SPX", features=feats,
        session_date=session))
    if label:
        D.write_label(build_label_record(
            sample_id=sid, decision_time=dec, settled_at=f"{session}T16:00:00",
            labels=label, session_date=session))


# ── /samples — features only ──────────────────────────────────────────────
def test_samples_returns_feature_vectors(client):
    _mk("s_1")
    j = client.get("/api/feature_store/samples").get_json()
    assert j["count"] == 1
    assert j["samples"][0]["features"]["gamma_regime"] == "POSITIVE"


def test_samples_never_returns_labels(client):
    _mk("s_1", label={"mfe_dollars": 5000.0, "final_outcome": "TARGET_ONLY"})
    j = client.get("/api/feature_store/samples").get_json()
    blob = repr(j).lower()
    assert "mfe" not in blob and "target_only" not in blob
    assert "labels" not in j["samples"][0]


def test_samples_carries_availability_stamps(client):
    _mk("s_1")
    s = client.get("/api/feature_store/samples").get_json()["samples"][0]
    assert "feature_availability" in s
    assert s["feature_availability"]["gamma_regime"]["source"] == "replay_frame"
    assert "max_feature_lag_seconds" in s


def test_samples_filters_by_session(client):
    _mk("s_1", session="2026-07-14")
    _mk("s_2", session="2026-07-15")
    j = client.get("/api/feature_store/samples?session=2026-07-14").get_json()
    assert j["count"] == 1 and j["samples"][0]["sample_id"] == "s_1"


def test_samples_limit_is_capped(client):
    for i in range(5):
        _mk(f"s_{i}", dec=f"{SESSION}T{_t(i)}")
    assert client.get("/api/feature_store/samples?limit=2").get_json()["count"] == 2
    # absurd limit is clamped, not honoured
    j = client.get("/api/feature_store/samples?limit=99999").get_json()
    assert j["count"] == 5


def test_samples_handles_garbage_params(client):
    _mk("s_1")
    assert client.get("/api/feature_store/samples?limit=abc&offset=xyz").status_code == 200


def test_samples_empty_store(client):
    j = client.get("/api/feature_store/samples").get_json()
    assert j["count"] == 0 and j["samples"] == []


# ── /sample/<id> — halves stay separate ───────────────────────────────────
def test_sample_keeps_pre_decision_and_post_outcome_apart(client):
    _mk("s_1", label={"mfe_dollars": 5000.0, "final_outcome": "TARGET_ONLY"})
    s = client.get("/api/feature_store/sample/s_1").get_json()["sample"]
    assert "features" in s["pre_decision"]
    assert s["post_outcome"]["labels"]["final_outcome"] == "TARGET_ONLY"
    # the two are never merged into one dict
    assert "mfe_dollars" not in s["pre_decision"]["features"]
    assert "gamma_regime" not in s["post_outcome"]["labels"]


def test_sample_shows_null_outcome_before_settling(client):
    _mk("s_1")
    s = client.get("/api/feature_store/sample/s_1").get_json()["sample"]
    assert s["post_outcome"] is None      # normal during a live session
    assert s["pre_decision"]["features"]


def test_sample_says_only_pre_decision_was_knowable(client):
    _mk("s_1")
    s = client.get("/api/feature_store/sample/s_1").get_json()["sample"]
    assert "Only pre_decision was knowable" in s["note"]


def test_unknown_sample_returns_none_not_error(client):
    j = client.get("/api/feature_store/sample/nope").get_json()
    assert j["ok"] is True and j["sample"] is None


# ── /coverage — the number that gates 5b ──────────────────────────────────
def test_coverage_buckets_by_neighbourhood(client):
    _mk("s_1", gamma="POSITIVE", auction="TRENDING")
    _mk("s_2", gamma="POSITIVE", auction="TRENDING", dec=f"{SESSION}T10:32:11")
    _mk("s_3", gamma="NEGATIVE", auction="BALANCED", dec=f"{SESSION}T10:33:11")
    cov = client.get("/api/feature_store/coverage").get_json()["coverage"]
    assert cov["total_samples"] == 3
    assert cov["cell_count"] == 2
    top = cov["cells"][0]
    assert top["matched_sample_count"] == 2
    assert top["cell"]["gamma_regime"] == "POSITIVE"


def test_coverage_uses_the_classifiers_own_premium_bands(client):
    _mk("s_1", premium=5_000_000.0)                    # institutional
    _mk("s_2", premium=1_000.0, dec=f"{SESSION}T10:32:11")   # retail
    cov = client.get("/api/feature_store/coverage").get_json()["coverage"]
    bands = {c["cell"]["premium_band"] for c in cov["cells"]}
    assert bands == {"INSTITUTIONAL_SIZE", "RETAIL_SIZE"}


def test_coverage_withholds_the_rate_on_a_thin_cell(client):
    """A 3-sample cell has a win rate. Printing it is how fiction gets believed."""
    for i in range(3):
        _mk(f"s_{i}", dec=f"{SESSION}T{_t(i)}",
            label={"mfe_dollars": 100.0, "final_outcome": "TARGET_ONLY"})
    cell = client.get("/api/feature_store/coverage").get_json()["coverage"]["cells"][0]
    assert cell["matched_sample_count"] == 3
    assert cell["edge_claim_permitted"] is False
    assert cell["target_first_rate"] is None
    assert "below the threshold" in cell["rate_withheld_because"]
    assert cell["outcome_counts"]["TARGET_ONLY"] == 3      # counts ARE shown


def test_coverage_reports_a_rate_with_an_interval_once_permitted(client):
    for i in range(60):
        oc = "TARGET_ONLY" if i % 2 == 0 else "STOP_ONLY"
        _mk(f"s_{i}", dec=f"{SESSION}T{_t(i)}",
            label={"mfe_dollars": 100.0, "final_outcome": oc})
    cell = client.get("/api/feature_store/coverage").get_json()["coverage"]["cells"][0]
    assert cell["matched_sample_count"] == 60
    assert cell["edge_claim_permitted"] is True
    r = cell["target_first_rate"]
    assert r["low"] < r["point"] < r["high"]       # an interval, not a bare number
    assert r["n"] == 60


def test_coverage_counts_target_first_as_a_hit_but_not_stop_first(client):
    for i in range(50):
        oc = "TARGET_FIRST" if i < 40 else "STOP_FIRST"
        _mk(f"s_{i}", dec=f"{SESSION}T{_t(i)}",
            label={"mfe_dollars": 100.0, "final_outcome": oc})
    cell = client.get("/api/feature_store/coverage").get_json()["coverage"]["cells"][0]
    assert cell["target_first_rate"]["point"] == pytest.approx(0.8, abs=0.01)


def test_coverage_states_counts_are_per_neighbourhood(client):
    _mk("s_1")
    cov = client.get("/api/feature_store/coverage").get_json()["coverage"]
    assert "MATCHED NEIGHBOURHOOD" in cov["basis"]
    assert "not independent observations" in cov["basis"]


def test_coverage_accepts_custom_dims(client):
    _mk("s_1")
    cov = client.get("/api/feature_store/coverage?dims=gamma_regime").get_json()["coverage"]
    assert cov["dims"] == ["gamma_regime"]
    assert set(cov["cells"][0]["cell"]) == {"gamma_regime"}


def test_coverage_filters_by_session(client):
    _mk("s_1", session="2026-07-14")
    _mk("s_2", session="2026-07-15")
    cov = client.get("/api/feature_store/coverage?sessions=2026-07-14").get_json()["coverage"]
    assert cov["total_samples"] == 1


def test_coverage_counts_unlabelled_samples_but_not_their_outcomes(client):
    _mk("s_1")
    _mk("s_2", dec=f"{SESSION}T10:32:11",
        label={"mfe_dollars": 1.0, "final_outcome": "NEITHER"})
    cell = client.get("/api/feature_store/coverage").get_json()["coverage"]["cells"][0]
    assert cell["matched_sample_count"] == 2
    assert cell["labelled_count"] == 1


def test_coverage_on_empty_store(client):
    cov = client.get("/api/feature_store/coverage").get_json()["coverage"]
    assert cov["total_samples"] == 0 and cov["cells"] == []


def test_coverage_reports_how_many_cells_permit_claims(client):
    _mk("s_1")
    cov = client.get("/api/feature_store/coverage").get_json()["coverage"]
    assert cov["cells_permitting_edge_claims"] == 0


# ── the endpoint that must NOT exist ──────────────────────────────────────
def test_no_flat_training_data_endpoint(client):
    """A flat feature+label route would make the split enforcement bypassable."""
    for path in ("/api/feature_store/training_data", "/api/feature_store/pairs",
                 "/api/feature_store/export", "/api/feature_store/rows"):
        assert client.get(path).status_code == 404


def test_health_points_at_coverage_as_the_real_gate(client):
    h = client.get("/api/feature_store/health").get_json()["health"]
    assert "coverage" in h["readiness"]
    assert h["global_sample_quality"]["edge_claim_permitted"] is False


def test_health_exposes_writer_settings(client):
    h = client.get("/api/feature_store/health").get_json()["health"]
    assert h["writer"]["label_horizon"] == "session_close"
    assert "not the participant's actual targets" in h["writer"]["threshold_caveat"]
