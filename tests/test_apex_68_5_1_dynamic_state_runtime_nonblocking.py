import json
import time
from pathlib import Path

import engine.calibration_activation as activation
import engine.evidence_pipeline as evidence_pipeline
from engine.calibration_activation import activation_status, eligibility_readout
from engine.dynamic_state_policy import evaluate_dynamic_state_policy

ROOT = Path(__file__).resolve().parents[1]


def _ds():
    return {
        "available": True,
        "event_phase": {"phase": "PRE_EVENT"},
        "flow_excitation": {"available": False},
        "residual_pressure": {"available": False},
        "gamma_term_structure": {"available": False},
        "gamma_path": {"available": False},
    }


def test_release_truth_is_68_5_1():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    registry = (ROOT / "config/apex_capability_registry.yaml").read_text()
    assert manifest["apex_version"] == "68.5.1"
    assert manifest["build_name"] == "Dynamic-State Runtime Nonblocking Fix"
    assert manifest["guardrails"]["dynamic_state_observability_reads_nonblocking"] is True
    assert manifest["guardrails"]["calibration_read_paths_mutate_schema"] is False
    assert "apex_version: 68.5.1" in registry


def test_policy_fails_soft_when_activation_store_is_unavailable(monkeypatch):
    def unavailable(*args, **kwargs):
        raise TimeoutError("simulated busy evidence store")
    monkeypatch.setattr(activation, "_readonly_connect", unavailable)
    started = time.monotonic()
    out = evaluate_dynamic_state_policy({"direction": "BULLISH"}, dynamic_state=_ds())
    elapsed = time.monotonic() - started
    assert elapsed < 0.5
    assert out["threshold_adjustment_points"] == 3.0
    assert out["calibration_activation"]["active"] is False
    assert out["calibration_activation"]["status"] == "READ_UNAVAILABLE"
    assert out["suppress_new_alerts"] is False
    assert out["watch_only"] is False


def test_readout_functions_do_not_create_a_missing_database(tmp_path):
    db = tmp_path / "does_not_exist.db"
    a = activation_status(db)
    e = eligibility_readout(db)
    assert not db.exists()
    assert a["ok"] is False and a["status"] == "READ_UNAVAILABLE"
    assert e["ok"] is False and e["status"] == "READ_UNAVAILABLE"
    assert a["execution_authority"] is False
    assert e["execution_authority"] is False


def test_readout_uses_existing_store_without_mutating_policy(tmp_path):
    db = tmp_path / "e.db"
    # The writer path is still responsible for creating canonical schemas.
    with evidence_pipeline._connect(db):
        pass
    before = db.stat().st_size
    status = activation_status(db)
    readout = eligibility_readout(db)
    after = db.stat().st_size
    assert status["ok"] is True
    assert status["active_count"] == 0
    assert readout["ok"] is True
    assert readout["status"] == "HEURISTIC"
    assert after >= before


def test_canonical_persistence_exposes_per_connection_busy_timeout():
    text = (ROOT / "engine/canonical_persistence.py").read_text()
    assert "busy_timeout_ms: int | None = None" in text
    assert "effective_busy_timeout_ms" in text
