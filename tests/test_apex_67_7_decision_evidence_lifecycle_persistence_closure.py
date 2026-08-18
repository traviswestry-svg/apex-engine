import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MIGRATED_MODULES = [
    "engine/director/store.py",
    "engine/institutional_execution_intelligence_v240.py",
    "engine/institutional_data_quality.py",
    "engine/recommendation_ledger.py",
    "engine/trade_director_market_memory.py",
    "engine/trade_director_institutional_intent.py",
    "engine/trade_director_session_allocation.py",
    "engine/flow_pl_store.py",
    "engine/institutional_expectancy_intelligence.py",
    "engine/liquidity_intelligence.py",
]


def test_677_decision_evidence_lifecycle_stores_use_canonical_persistence():
    for rel in MIGRATED_MODULES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "sqlite3.connect" not in text, rel
        assert "canonical_persistence import connect as canonical_connect" in text, rel
        assert "canonical_connect(" in text, rel


def test_677_director_store_nonfatal_failures_are_observable():
    text = (ROOT / "engine/director/store.py").read_text(encoding="utf-8")
    assert "record_degradation(" in text
    for operation in ("init_store", "log_directive", "recent_directives"):
        assert f'operation="{operation}"' in text
    assert "decision_authority_suppressed=False" in text


def test_677_flow_pl_nonfatal_persistence_failures_are_observable():
    text = (ROOT / "engine/flow_pl_store.py").read_text(encoding="utf-8")
    assert "record_degradation(" in text
    for operation in (
        "init_db", "record_observation", "get_excursions",
        "record_cluster_observation", "get_cluster_excursions",
    ):
        assert f'operation="{operation}"' in text
    assert "decision_authority_suppressed=False" in text


def test_677_release_identity_and_guardrails():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    version = tuple(int(part) for part in manifest["apex_version"].split("."))
    assert version >= (67, 7, 0)
    if version == (67, 7, 0):
        assert manifest["build_name"] == "Decision Evidence & Lifecycle Persistence Closure"
    g = manifest["guardrails"]
    assert g["canonical_persistence_wave5_decision_evidence"] is True
    assert g["decision_evidence_lifecycle_store_migration_staged"] is True
    assert g["decision_evidence_degradations_observable"] is True
    assert g["decision_evidence_schema_changes"] is False
    assert g["decision_evidence_path_changes"] is False
    assert g["decision_evidence_logic_changes"] is False
    assert g["decision_evidence_execution_authority_changes"] is False


def test_677_registry_declares_no_authority_expansion():
    text = (ROOT / "config/apex_capability_registry.yaml").read_text(encoding="utf-8")
    assert "apex_version:" in text
    assert "decision_evidence_lifecycle_persistence_closure:" in text
    section = text.split("decision_evidence_lifecycle_persistence_closure:", 1)[1].split(
        "\n  silent_degradation_coverage_wave2:", 1
    )[0]
    assert 'version: "67.7.0"' in section
    assert "decision_authority: none" in section
    assert "no_schema_migration" in section
    assert "no_database_relocation" in section
    assert "no_decision_logic_change" in section
    assert "no_execution_authority_change" in section
    assert "observability_only" in section
