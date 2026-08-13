import sqlite3


from engine import level_transition_probability as ltpe


def test_learning_status_survives_legacy_partial_schema(tmp_path):
    db = str(tmp_path / "legacy.db")
    # Simulate a persistent Render DB created by an older schema.  In
    # particular, this table lacks graded/interaction_type/ts, which causes the
    # current CREATE INDEX IF NOT EXISTS statement to fail during initialization.
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE level_interactions (interaction_id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE level_outcomes (outcome_id TEXT PRIMARY KEY)")
        conn.commit()

    out = ltpe.learning_status(path=db)
    assert out["ok"] is False
    assert out["status"] == "DEGRADED"
    assert out["failure_stage"] is not None
    assert isinstance(out["diagnostics"], list) and out["diagnostics"]
    assert out["probability_policy"] == "EVIDENCE_ONLY_NO_FABRICATION"


def test_learning_status_healthy_store_still_reports_healthy(tmp_path):
    db = str(tmp_path / "healthy.db")
    out = ltpe.learning_status(path=db)
    assert out["ok"] is True
    assert out["status"] == "HEALTHY"
    assert out["diagnostics"] == []
    assert out["state"] == "COLLECTING"
