from pathlib import Path
import json

import engine.calibration_activation as activation
import engine.dynamic_state_calibration_governance as governance


def test_release_identity_and_guardrails_are_ratcheted():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "config" / "apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == "68.5.3"
    assert manifest["build_name"] == "Calibration Governance Store Initialization Closure"
    guards = manifest["guardrails"]
    assert guards["calibration_governance_startup_initialization"] is True
    assert guards["calibration_governance_get_initialization"] is False
    assert guards["calibration_governance_durable_render_path"] is True
    assert guards["calibration_governance_initialization_idempotent"] is True
    assert guards["calibration_governance_initialization_changes_execution_authority"] is False


def test_controlled_initializer_creates_governance_schema(tmp_path):
    db = tmp_path / "fresh" / "evidence.db"
    assert not db.exists()
    out = activation.initialize_governance_store(db)
    assert out["ok"] is True
    assert out["status"] == "READY"
    assert out["initialized"] is True
    assert out["created_store"] is True
    assert out["execution_authority"] is False
    assert all(out["tables"].values())

    view = governance.governance_overview(db)
    assert view["ok"] is True
    assert view["status"] == "READY"
    assert view["initialized"] is True
    assert view["read_available"] is True
    assert view["degraded"] is False


def test_initializer_is_idempotent(tmp_path):
    db = tmp_path / "evidence.db"
    first = activation.initialize_governance_store(db)
    second = activation.initialize_governance_store(db)
    assert first["ok"] is True and second["ok"] is True
    assert second["created_store"] is False
    assert second["status"] == "READY"
    assert all(second["tables"].values())


def test_read_paths_do_not_initialize_missing_store(tmp_path):
    db = tmp_path / "missing.db"
    out = governance.governance_overview(db)
    assert out["status"] == "MISSING_DB"
    assert out["initialized"] is False
    assert out["degraded"] is False
    assert not db.exists()


def test_evidence_default_uses_persistent_path_resolver():
    root = Path(__file__).resolve().parents[1]
    source = (root / "engine" / "evidence_pipeline.py").read_text()
    assert 'persistent_sqlite_path("APEX_EVIDENCE_PIPELINE_DB", "apex_evidence_pipeline.db")' in source
    app_source = (root / "app.py").read_text()
    assert "initialize_governance_store(_calibration_governance_db)" in app_source
    assert "APEX 68.5.3 Calibration Governance Store initialized" in app_source
