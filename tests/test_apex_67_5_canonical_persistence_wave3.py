import json
from pathlib import Path

from engine.canonical_persistence import connection

ROOT = Path(__file__).resolve().parents[1]

MIGRATED = [
    "engine/adaptive_trade_management.py",
    "engine/broker_synchronized_position_state.py",
    "engine/confirmation_gated_execution.py",
    "engine/execution_reality_slippage.py",
    "engine/portfolio_risk_intelligence.py",
    "engine/premium_portfolio_risk_governor.py",
    "engine/trade_lifecycle_intelligence.py",
    "engine/premium_execution_orchestrator.py",
    "engine/institutional_execution_intelligence.py",
]


def test_wave3_execution_risk_position_modules_use_canonical_persistence():
    offenders = []
    for rel in MIGRATED:
        text = (ROOT / rel).read_text(encoding="utf-8")
        if "sqlite3.connect" in text:
            offenders.append(rel)
        assert "canonical_persistence import connect as canonical_connect" in text
        assert "canonical_connect(" in text
    assert offenders == []


def test_wave3_canonical_policy_still_enforces_wal_fk_and_busy_timeout(tmp_path):
    db = tmp_path / "wave3.db"
    with connection(db) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] > 0


def test_wave3_release_identity_and_guardrails():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == "67.5.0"
    assert manifest["build_name"] == "Canonical Persistence Migration Wave 3"
    guardrails = manifest["guardrails"]
    assert guardrails["canonical_persistence_wave3"] is True
    assert guardrails["execution_risk_position_store_migration_staged"] is True
    assert guardrails["persistence_schema_changes"] is False
    assert guardrails["persistence_path_changes"] is False
    assert guardrails["persistence_trading_logic_changes"] is False
    assert guardrails["persistence_risk_rule_changes"] is False
    assert guardrails["persistence_execution_authority_changes"] is False


def test_wave3_registry_declares_no_authority_expansion():
    text = (ROOT / "config/apex_capability_registry.yaml").read_text(encoding="utf-8")
    assert "apex_version: 67.5.0" in text
    assert "canonical_persistence_migration_wave3:" in text
    section = text.split("canonical_persistence_migration_wave3:", 1)[1].split("\n  silent_degradation_coverage_wave2:", 1)[0]
    assert 'version: "67.5.0"' in section
    assert "decision_authority: none" in section
    assert "no_execution_authority_change" in section
