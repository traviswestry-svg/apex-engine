import json
from pathlib import Path


def test_release_truth_69_10_16():
    root = Path(__file__).resolve().parents[1]
    m = json.loads((root / "config/apex_release_manifest.json").read_text())
    assert m["apex_version"] == m["semantic_version"] == m["application_version"] == "69.10.20"
    assert m["build_name"] == "Canonical Excursion Write-to-Settlement Read Closure"
    g = m["guardrails"]
    assert g["canonical_settlement_identity_recovery"] == "EXACT_REGISTERED_TUPLE_ONLY"
    assert g["settlement_recovery_reconstructs_sample_id"] is False
    assert g["decision_gamma_latest_substitution_allowed"] is False


def test_exact_identity_resolution_never_uses_coarse_latest(tmp_path, monkeypatch):
    from engine import flow_pl_store as store
    db = tmp_path / "tracking.db"
    monkeypatch.setattr(store, "_DB_PATH", str(db))
    store._DB_READY = False
    assert store.init_db()
    assert store.register_sample_identity(sample_id="s_old", session_date="2026-09-21",
        legacy_cluster_key="SPX|CALL|2026-09-21|BULLISH", decision_time="2026-09-21T10:00:00")
    assert store.register_sample_identity(sample_id="s_new", session_date="2026-09-21",
        legacy_cluster_key="SPX|CALL|2026-09-21|BULLISH", decision_time="2026-09-21T10:05:00")
    exact = store.resolve_exact_sample_identity(session_date="2026-09-21",
        legacy_cluster_key="SPX|CALL|2026-09-21|BULLISH", decision_time="2026-09-21T10:00:00")
    assert exact["sample_id"] == "s_old"
    assert store.resolve_exact_sample_identity(session_date="2026-09-21",
        legacy_cluster_key="SPX|CALL|2026-09-21|BULLISH", decision_time="2026-09-21T10:03:00") is None


def test_later_real_pl_can_recover_exact_registered_sample(tmp_path, monkeypatch):
    from engine import flow_pl_store as store
    db = tmp_path / "tracking.db"
    monkeypatch.setattr(store, "_DB_PATH", str(db))
    store._DB_READY = False
    assert store.init_db()
    key = "SPX|CALL|2026-09-21|BULLISH"
    dt = "2026-09-21T10:00:00"
    assert store.register_sample_identity(sample_id="s_exact", session_date="2026-09-21",
        legacy_cluster_key=key, decision_time=dt)
    identity = store.resolve_exact_sample_identity(session_date="2026-09-21", legacy_cluster_key=key, decision_time=dt)
    assert identity and identity["sample_id"] == "s_exact"
    out = store.record_sample_excursion(sample_id=identity["sample_id"], session_date="2026-09-21",
        ticker="SPX", pl_dollars=125.0, cost_basis=500.0, decision_time=dt, legacy_cluster_key=key)
    assert out and out["first_sample"] is True
    rows = store.get_sample_excursions(["s_exact"])
    assert rows["s_exact"]["mfe_dollars"] == 125.0


def test_flow_pipeline_uses_exact_registered_identity_not_reconstruction():
    src = (Path(__file__).resolve().parents[1] / "engine/flow_pl_pipeline.py").read_text()
    assert "resolve_exact_sample_identity" in src
    assert 'decision_time = f"{session}T{cl.get(\'end_time\')}"' in src
    assert "make_sample_id" not in src


def test_composition_propagates_exact_gamma_transition_before_capture():
    src = (Path(__file__).resolve().parents[1] / "app.py").read_text()
    propagate = 'result["gamma_transition"] = dict(flow_snapshot["gamma_transition"])'
    capture = "_apex69_capture_decision(result, session_state=_session_state_now)"
    assert propagate in src and capture in src
    assert src.index(propagate) < src.index(capture)


def test_frozen_gamma_linkage_uses_carried_identity_without_latest_substitution(tmp_path, monkeypatch):
    from engine import gamma_transition as gt
    from engine.historical_evidence_lifecycle import build_snapshot
    db = tmp_path / "gamma.db"
    monkeypatch.setenv("DB_PATH", str(db))
    gamma = {"net_gex": 100.0, "gamma_flip": 6000.0, "gamma_regime": "POSITIVE"}
    transition = gt.observe_gamma_transition(gamma, observed_at="2026-09-21T13:30:00Z",
        received_at="2026-09-21T13:30:01Z", db_path=str(db))
    result = {
        "ticker": "SPX", "gamma_transition": transition,
        "institutional_decision_object": {"ticker": "SPX", "timestamp": "2026-09-21T13:30:05Z",
            "action": "NO_TRADE", "direction": "BULLISH", "actionable": False},
    }
    snap = build_snapshot(result, session_state="MARKET_OPEN")
    assert snap["canonical_gamma_snapshot_id"] == transition["canonical_gamma_snapshot_id"]
    assert snap["gamma_evidence"]["linkage_status"] == "LINKED"
    assert snap["gamma_evidence"]["later_gamma_substitution_allowed"] is False
