import json
from pathlib import Path

from engine.canonical_persistence import connection

ROOT = Path(__file__).resolve().parents[1]

DECISION_STATE_MODULES = [
    "engine/thesis_lifecycle.py",
    "engine/canonical_session_context.py",
    "engine/range_intelligence.py",
]


def test_676_decision_state_modules_use_canonical_persistence():
    for rel in DECISION_STATE_MODULES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "sqlite3.connect" not in text, rel
        assert "canonical_persistence import connect as canonical_connect" in text, rel
        assert "canonical_connect(" in text, rel


def test_676_operational_runtime_is_compatibility_adapter_not_competing_policy():
    text = (ROOT / "engine/operational_runtime.py").read_text(encoding="utf-8")
    assert "sqlite3.connect" not in text
    assert "canonical_persistence import connect as canonical_connect" in text
    assert "return canonical_connect(" in text
    # Legacy helper must not independently own journal/busy/synchronous policy anymore.
    assert "PRAGMA journal_mode" not in text
    assert "PRAGMA busy_timeout" not in text
    assert "PRAGMA synchronous" not in text


def test_676_canonical_policy_still_applies_wal_fk_busy_timeout(tmp_path):
    db = tmp_path / "decision_state.db"
    with connection(db) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] > 0


def test_676_range_history_failures_are_structurally_observable():
    text = (ROOT / "engine/range_intelligence.py").read_text(encoding="utf-8")
    for operation in (
        "history_init",
        "capture_projection_persistence",
        "record_actuals_persistence",
        "history_read",
        "scorecard_read",
    ):
        assert f'"{operation}"' in text
    assert "record_degradation(" in text
    assert 'component="range_intelligence"' in text
    assert 'decision_authority_suppressed=False' in text


def test_676_release_identity_and_guardrails():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    version = tuple(int(part) for part in manifest["apex_version"].split("."))
    assert version >= (67, 6, 0)
    if version == (67, 6, 0):
        assert manifest["build_name"] == "Decision-State Persistence & Persistence Policy Closure"
    guardrails = manifest["guardrails"]
    assert guardrails["canonical_persistence_wave4_decision_state"] is True
    assert guardrails["decision_state_store_migration_staged"] is True
    assert guardrails["legacy_persistence_policy_closed"] is True
    assert guardrails["range_history_degradations_observable"] is True
    assert guardrails["decision_state_schema_changes"] is False
    assert guardrails["decision_state_path_changes"] is False
    assert guardrails["decision_state_logic_changes"] is False
    assert guardrails["decision_state_execution_authority_changes"] is False


def test_676_registry_declares_no_authority_expansion():
    text = (ROOT / "config/apex_capability_registry.yaml").read_text(encoding="utf-8")
    assert "apex_version:" in text
    assert "decision_state_persistence_policy_closure:" in text
    section = text.split("decision_state_persistence_policy_closure:", 1)[1].split(
        "\n  silent_degradation_coverage_wave2:", 1
    )[0]
    assert 'version: "67.6.0"' in section
    assert "decision_authority: none" in section
    assert "no_decision_logic_change" in section
    assert "no_execution_authority_change" in section
    assert "compatibility_adapter_only" in section
