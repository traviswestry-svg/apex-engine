import json
from pathlib import Path

from engine import flow_pl_store


def _use_db(monkeypatch, tmp_path):
    db = tmp_path / "tracking.db"
    monkeypatch.setattr(flow_pl_store, "_DB_PATH", str(db))
    assert flow_pl_store.init_db()
    return db


def test_release_truth_and_guardrails():
    d = json.loads(Path("config/apex_release_manifest.json").read_text())
    assert d["apex_version"] == "69.10.22"
    assert d["build_name"] == "Canonical Feature Sample Excursion Ownership Closure"
    g = d["guardrails"]
    assert g["excursion_write_readback_required"] is True
    assert g["excursion_write_readback_exact_sample_id_only"] is True
    assert g["excursion_write_readback_writes_evidence"] is False
    assert g["excursion_write_readback_reconstructs_identity"] is False


def test_insert_is_immediately_visible_through_settlement_reader(monkeypatch, tmp_path):
    db = _use_db(monkeypatch, tmp_path)
    sid = "s_691020_insert"
    cap = flow_pl_store.record_sample_excursion(
        sample_id=sid, session_date="2026-09-24", ticker="SPX",
        pl_dollars=25.0, cost_basis=100.0,
        decision_time="2026-09-24T10:00:00",
        legacy_cluster_key="SPX|CALL|2026-09-24|BULLISH")
    assert cap and cap["first_sample"] is True
    assert cap["readback_verified"] is True
    assert cap["readback_db_path"] == str(db.resolve())
    assert sid in flow_pl_store.get_sample_excursions([sid])
    h = flow_pl_store.excursion_write_readback_health()
    assert h["write_commits"] == 1
    assert h["readback_attempts"] == 1
    assert h["readback_verified"] == 1
    assert h["readback_missing"] == 0
    assert h["last_sample_id"] == sid
    assert h["last_table"] == "flow_sample_excursions"
    assert h["reader"] == "get_sample_excursions"


def test_update_is_immediately_visible_through_same_exact_reader(monkeypatch, tmp_path):
    _use_db(monkeypatch, tmp_path)
    sid = "s_691020_update"
    kwargs = dict(sample_id=sid, session_date="2026-09-24", ticker="SPX",
                  cost_basis=100.0, decision_time="2026-09-24T10:01:00",
                  legacy_cluster_key="SPX|PUT|2026-09-24|BEARISH")
    assert flow_pl_store.record_sample_excursion(pl_dollars=-10.0, **kwargs)
    cap = flow_pl_store.record_sample_excursion(pl_dollars=30.0, **kwargs)
    assert cap and cap["first_sample"] is False and cap["readback_verified"] is True
    row = flow_pl_store.get_sample_excursions([sid])[sid]
    assert row["samples"] == 2
    assert row["mfe_dollars"] == 30.0
    h = flow_pl_store.excursion_write_readback_health()
    assert h["write_commits"] == 2 and h["readback_verified"] == 2
    assert h["last_write_mode"] == "UPDATE"


def test_readback_failure_is_not_counted_as_success(monkeypatch, tmp_path):
    _use_db(monkeypatch, tmp_path)
    real_reader = flow_pl_store.get_sample_excursions
    monkeypatch.setattr(flow_pl_store, "get_sample_excursions", lambda ids: {})
    cap = flow_pl_store.record_sample_excursion(
        sample_id="s_unreadable", session_date="2026-09-24", ticker="SPX",
        pl_dollars=5.0, cost_basis=100.0, decision_time="2026-09-24T10:02:00",
        legacy_cluster_key="K")
    assert cap is None
    h = flow_pl_store.excursion_write_readback_health()
    assert h["readback_missing"] == 1
    # Restore the public reader and prove the test did not delete or synthesize evidence.
    monkeypatch.setattr(flow_pl_store, "get_sample_excursions", real_reader)
    assert "s_unreadable" in flow_pl_store.get_sample_excursions(["s_unreadable"])
