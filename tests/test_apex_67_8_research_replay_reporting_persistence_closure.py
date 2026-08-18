import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MIGRATED_MODULES = [
    "engine/evening_archive_schema.py",
    "engine/evening_recap.py",
    "engine/report_archive.py",
    "engine/evidence_audit.py",
    "engine/evidence_accumulation_observatory.py",
    "engine/institutional_research.py",
    "engine/historical_readiness.py",
    "engine/institutional_replay_v242.py",
    "engine/institutional_replay_2.py",
    "engine/institutional_research_lab.py",
    "engine/institutional_research_lab_v243.py",
    "engine/institutional_similarity.py",
]


def test_678_research_replay_reporting_stores_use_canonical_persistence():
    for rel in MIGRATED_MODULES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "sqlite3.connect" not in text, rel
        assert "canonical_persistence import connect as canonical_connect" in text, rel
        assert "canonical_connect(" in text, rel


def test_678_read_only_diagnostics_remain_strictly_read_only():
    for rel in (
        "engine/evidence_audit.py",
        "engine/evidence_accumulation_observatory.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "read_only=True" in text, rel
        assert "wal=False" in text, rel
        assert "heal=False" in text, rel


def test_678_release_identity_and_guardrails():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == "67.8.0"
    assert manifest["build_name"] == "Research, Replay & Reporting Persistence Closure"
    g = manifest["guardrails"]
    assert g["canonical_persistence_wave6_research_replay_reporting"] is True
    assert g["research_replay_reporting_store_migration_staged"] is True
    assert g["research_replay_reporting_read_only_semantics_preserved"] is True
    assert g["research_replay_reporting_schema_changes"] is False
    assert g["research_replay_reporting_path_changes"] is False
    assert g["research_replay_reporting_logic_changes"] is False
    assert g["research_replay_reporting_decision_authority_changes"] is False
    assert g["research_replay_reporting_execution_authority_changes"] is False


def test_678_registry_declares_no_authority_expansion():
    text = (ROOT / "config/apex_capability_registry.yaml").read_text(encoding="utf-8")
    assert "apex_version: 67.8.0" in text
    assert "research_replay_reporting_persistence_closure:" in text
    section = text.split("research_replay_reporting_persistence_closure:", 1)[1].split(
        "\n  silent_degradation_coverage_wave2:", 1
    )[0]
    assert 'version: "67.8.0"' in section
    assert "decision_authority: none" in section
    assert "no_schema_migration" in section
    assert "no_database_relocation" in section
    assert "no_decision_authority_change" in section
    assert "no_execution_authority_change" in section
    assert "preserve_read_only_diagnostics" in section
