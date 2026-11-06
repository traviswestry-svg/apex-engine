"""Focused evidence-independence baseline validation (research audit)."""
from engine.flow_surprise import evaluate_flow_surprise
from engine import feature_store_db


def _row(session, stamp=None):
    return {"session_date": session, "decision_time": stamp or f"{session}T10:05:00",
            "features": {"cluster_expiration": session, "cluster_total_premium": 100000,
                         "cluster_total_contracts": 100, "cluster_duration_seconds": 50}}


def _out(rows):
    return evaluate_flow_surprise(
        {"cluster_id": "c", "expiration": "2026-11-06", "total_premium": 150000,
         "total_contracts": 150, "duration_seconds": 50},
        session_date="2026-11-06", decision_time="2026-11-06T10:10:00",
        historical_rows=rows)


def test_no_same_session_or_future_baseline_even_when_20_observations():
    for day in ("2026-11-06", "2026-11-09"):
        result = _out([_row(day) for _ in range(20)])
        assert result["status"] == "INSUFFICIENT_HISTORY"
        assert result["baseline_sample_size"] == 0


def test_only_prior_session_records_survive_mixed_history():
    result = _out([_row("2026-11-05") for _ in range(20)] +
                  [_row("2026-11-06") for _ in range(80)] +
                  [_row("2026-11-09") for _ in range(80)])
    assert result["status"] == "AVAILABLE"
    assert result["baseline_sample_size"] == 20
    assert result["behavioral_authority"] is False


def test_timestamp_session_identity_mismatch_is_excluded():
    result = _out([_row("2026-11-05", "2026-11-09T10:05:00") for _ in range(20)])
    assert result["baseline_sample_size"] == 0


def test_db_query_excludes_same_and_future_sessions_before_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(feature_store_db, "_DB_PATH", str(tmp_path / "flow.db"))
    monkeypatch.setattr(feature_store_db, "_DB_READY", False)
    assert feature_store_db.init_db()
    for day in ("2026-11-05", "2026-11-06", "2026-11-09"):
        v = {"sample_id": day, "ticker": "SPX", "session_date": day,
             "decision_time": f"{day}T10:05:00", "features": {"cluster_expiration": day},
             "feature_availability": {}, "max_feature_lag_seconds": 0,
             "feature_count": 1, "schema_version": "audit"}
        assert feature_store_db.write_features(v)
    rows = feature_store_db.historical_feature_rows(ticker="SPX", limit=1,
                                                    before_session_date="2026-11-06")
    assert len(rows) == 1 and rows[0]["session_date"] == "2026-11-05"
