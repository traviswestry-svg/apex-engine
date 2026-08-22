import json
import sqlite3
from pathlib import Path

import engine.calibration_activation as activation
from engine.dynamic_state_calibration_governance import governance_overview
from engine.dynamic_state_outcome_calibration import calibration_summary

ROOT = Path(__file__).resolve().parents[1]


def test_release_truth_is_68_5_2():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    registry = (ROOT / "config/apex_capability_registry.yaml").read_text()
    assert manifest["apex_version"] == "68.5.2"
    assert manifest["build_name"] == "Calibration Governance Read Availability Fix"
    assert manifest["guardrails"]["calibration_read_availability_classified"] is True
    assert manifest["guardrails"]["missing_calibration_store_is_degraded"] is False
    assert "apex_version: 68.5.2" in registry


def test_missing_store_is_truthful_empty_state(tmp_path):
    db = tmp_path / "missing.db"
    gov = governance_overview(db)
    act = activation.activation_status(db)
    elig = activation.eligibility_readout(db)
    cal = calibration_summary(db)
    assert not db.exists()
    for out in (gov, act, elig, cal):
        assert out["ok"] is True
        assert out["status"] == "MISSING_DB"
        assert out["degraded"] is False
        assert out["initialized"] is False
    assert elig["eligibility_mode"] == "HEURISTIC"


def test_existing_db_without_governance_schema_is_not_degraded(tmp_path):
    db = tmp_path / "empty.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE decisions(id TEXT)")
    conn.commit(); conn.close()
    gov = governance_overview(db)
    assert gov["ok"] is True
    assert gov["status"] == "EMPTY_NOT_INITIALIZED"
    assert gov["degraded"] is False
    assert gov["read_available"] is True
    assert gov["initialized"] is False
    assert gov["counts"]["APPROVED"] == 0


def test_busy_is_distinguished_from_generic_read_error(tmp_path):
    db = tmp_path / "busy.db"
    sqlite3.connect(db).close()
    busy = activation._read_availability(db, sqlite3.OperationalError("database is locked"))
    err = activation._read_availability(db, sqlite3.OperationalError("disk I/O error"))
    assert busy["status"] == "BUSY" and busy["degraded"] is True
    assert err["status"] == "READ_ERROR" and err["degraded"] is True


def test_missing_db_classification_does_not_create_file(tmp_path):
    db = tmp_path / "never-created.db"
    state = activation._read_availability(db)
    assert state["status"] == "MISSING_DB"
    assert state["reason"] == "STORE_NOT_CREATED_YET"
    assert not db.exists()
