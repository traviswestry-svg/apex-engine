from pathlib import Path

from engine import feature_store_writer as W
from engine import historical_evidence_lifecycle as H


def test_release_versions_are_69_0_1():
    assert H.VERSION == "69.0.1"
    assert H.SCHEMA_VERSION == "apex.historical_evidence_lifecycle.v1.1"
    assert "apex_version: 69.0.1" in Path("config/apex_capability_registry.yaml").read_text()
    assert '"apex_version": "69.0.1"' in Path("config/apex_release_manifest.json").read_text()


def test_lifecycle_route_prefers_fresh_scanner_heartbeat_runtime():
    src = Path("engine/evidence_accumulation_routes.py").read_text()
    assert 'payload["runtime_source"] = "SCANNER_HEARTBEAT"' in src
    assert 'payload["web_local_runtime"] = web_local_runtime' in src
    assert 'hb.get("historical_evidence_lifecycle")' in src
    assert 'hb.get("feature_label_settlement")' in src
    assert '"runtime_telemetry_authority": "SCANNER_HEARTBEAT_WHEN_FRESH"' in src


def test_settle_labels_reports_missing_excursion_reason(monkeypatch):
    monkeypatch.setattr(W.feature_store_db, "is_ready", lambda: True)
    monkeypatch.setattr(W.flow_pl_store, "is_ready", lambda: True)
    monkeypatch.setattr(W.feature_store_db, "unlabelled_samples", lambda session_date: ["sample-1"])
    monkeypatch.setattr(W.feature_store_db, "get_features", lambda sid: {
        "sample_id": sid,
        "ticker": "SPX",
        "decision_time": "2026-08-21T10:00:00-04:00",
        "features": {
            "cluster_option_type": "CALL",
            "cluster_expiration": "2026-08-21",
            "cluster_directional_interpretation": "BULLISH",
        },
    })
    monkeypatch.setattr(W.flow_pl_store, "get_cluster_excursions", lambda keys, session_date: {})
    out = W.settle_labels(session_date="2026-08-21")
    assert out["pending"] == 1
    assert out["vectors_loaded"] == 1
    assert out["missing_excursion_row"] == 1
    assert out["no_excursion"] == 1
    assert out["labelled"] == 0
    assert out["state"] == "NO_LABELS_CREATED"


def test_settle_labels_reports_missing_mfe_separately(monkeypatch):
    monkeypatch.setattr(W.feature_store_db, "is_ready", lambda: True)
    monkeypatch.setattr(W.flow_pl_store, "is_ready", lambda: True)
    monkeypatch.setattr(W.feature_store_db, "unlabelled_samples", lambda session_date: ["sample-1"])
    monkeypatch.setattr(W.feature_store_db, "get_features", lambda sid: {
        "sample_id": sid,
        "ticker": "SPX",
        "decision_time": "2026-08-21T10:00:00-04:00",
        "features": {
            "cluster_option_type": "CALL",
            "cluster_expiration": "2026-08-21",
            "cluster_directional_interpretation": "BULLISH",
        },
    })
    monkeypatch.setattr(W.flow_pl_store, "get_cluster_excursions", lambda keys, session_date: {
        keys[0]: {"mfe_dollars": None, "mae_dollars": -10.0, "cost_basis": 100.0}
    })
    out = W.settle_labels(session_date="2026-08-21")
    assert out["excursion_rows_found"] == 1
    assert out["missing_mfe"] == 1
    assert out["missing_excursion_row"] == 0
    assert out["labelled"] == 0


def test_pending_settlement_aggregates_reason_counts(monkeypatch):
    monkeypatch.setattr(W.feature_store_db, "is_ready", lambda: True)
    monkeypatch.setattr(W.feature_store_db, "sessions", lambda family: ["2026-08-20", "2026-08-21"])
    monkeypatch.setattr(W.feature_store_db, "unlabelled_samples", lambda session_date: [f"{session_date}-1"])
    monkeypatch.setattr(W, "settle_labels", lambda session_date, ticker="SPX": {
        "pending": 1, "vectors_loaded": 1, "excursion_rows_found": 0,
        "labelled": 0, "no_excursion": 1, "missing_feature_vector": 0,
        "missing_excursion_row": 1, "missing_mfe": 0, "missing_cost_basis": 0,
        "leakage_rejected": 0, "write_failures": 0, "skipped": 0,
        "state": "NO_LABELS_CREATED",
    })
    out = W.settle_pending_labels(before_session_date="2026-08-22")
    assert out["sessions_checked"] == 2
    assert out["sessions_with_unlabelled"] == 2
    assert out["pending"] == 2
    assert out["missing_excursion_row"] == 2
    assert out["state"] == "UNLABELLED_REMAINS"
