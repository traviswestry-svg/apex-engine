from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from engine.post_persistence_architecture_audit import snapshot

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "config" / "apex_capability_registry.yaml"
MANIFEST_PATH = ROOT / "config" / "apex_release_manifest.json"
ROUTES_PATH = ROOT / "engine" / "market_microstructure_routes.py"
STORE_PATH = ROOT / "engine" / "market_microstructure_store.py"

EXPECTED_MODULES = {
    "engine.market_microstructure",
    "engine.market_microstructure_ingest",
    "engine.market_microstructure_store",
    "engine.market_microstructure_calibration",
    "engine.market_microstructure_routes",
}
EXPECTED_ROUTES = {
    "/api/microstructure/capability",
    "/api/microstructure/health",
    "/api/microstructure/analyze",
    "/api/microstructure/ingest",
    "/api/microstructure/state",
    "/api/microstructure/history",
    "/api/microstructure/heatmap",
    "/api/microstructure/integrity",
    "/api/microstructure/calibration",
    "/api/microstructure/promotion-readiness",
    "/api/microstructure/shadow-confirmation",
    "/api/microstructure/outcomes",
}


def _registry_capability():
    registry = yaml.safe_load(REGISTRY_PATH.read_text())
    assert tuple(map(int, registry["apex_version"].split("."))) >= (69, 4, 2)
    return registry["capabilities"]["market_microstructure_governance_truth_closure"]


def test_microstructure_is_canonically_registered_with_deployed_surface_accounted_for():
    cap = _registry_capability()
    assert set(cap["deployed_modules"]) == EXPECTED_MODULES
    assert set(cap["api_routes"]) == EXPECTED_ROUTES

    route_source = ROUTES_PATH.read_text()
    deployed = set(re.findall(r'@app\.(?:get|post|put|patch|delete)\("(/api/microstructure/[^"?]+)"\)', route_source))
    assert deployed == EXPECTED_ROUTES

    for module in EXPECTED_MODULES:
        path = ROOT / (module.replace(".", "/") + ".py")
        assert path.exists(), module


def test_registry_preserves_observational_non_authority_truths():
    cap = _registry_capability()
    assert cap["status"] == "observational"
    assert cap["observational_only"] is True
    assert cap["decision_authority"] == "none"
    assert cap["execution_authority"] == "none"
    assert cap["production_effect"] == "NONE"
    assert cap["real_l2_mbo_required"] is True
    assert cap["synthetic_depth_allowed"] is False
    assert cap["aggregate_futures_bars_are_depth_substitute"] is False
    assert cap["shadow_calibration_only"] is True
    assert cap["automatic_promotion"] is False
    assert cap["operator_approval_alone_activates_production"] is False


def test_release_manifest_ratchets_microstructure_preservation_guardrails():
    manifest = json.loads(MANIFEST_PATH.read_text())
    assert tuple(map(int, manifest["apex_version"].split("."))) >= (69, 4, 2)
    if manifest["apex_version"] == "69.4.2":
        assert manifest["build_name"] == "Microstructure Governance Truth Closure"
    g = manifest["guardrails"]
    expected = {
        "microstructure_observational_only": True,
        "microstructure_changes_trade_decisions": False,
        "microstructure_changes_execution_authority": False,
        "microstructure_production_effect": "NONE",
        "microstructure_real_l2_mbo_required": True,
        "microstructure_synthetic_depth_allowed": False,
        "microstructure_aggregate_bars_are_depth_substitute": False,
        "microstructure_shadow_calibration_only": True,
        "microstructure_automatic_promotion": False,
        "microstructure_operator_approval_alone_activates_production": False,
        "microstructure_persistence_classification": "SPECIALIZED_OBSERVATIONAL_BUFFER",
        "microstructure_canonical_high_consequence_persistence_required": False,
        "microstructure_direct_sqlite_exception_approved": True,
        "microstructure_high_consequence_state": False,
        "microstructure_evidence_store_merge_deferred": True,
    }
    for key, value in expected.items():
        assert g[key] == value, key


def test_specialized_direct_sqlite_is_explicitly_classified_without_migration():
    source = STORE_PATH.read_text()
    assert "sqlite3.connect(self.path, timeout=5.0)" in source
    assert 'PRAGMA journal_mode=WAL' in source
    assert 'PRAGMA synchronous=NORMAL' in source

    cap = _registry_capability()["persistence"]
    assert cap["classification"] == "SPECIALIZED_OBSERVATIONAL_BUFFER"
    assert cap["canonical_high_consequence_persistence_required"] is False
    assert cap["direct_sqlite_exception_approved"] is True
    assert cap["high_consequence_state"] is False
    assert cap["decision_authority"] == "none"
    assert cap["execution_authority"] == "none"

    report = snapshot()["persistence"]
    site = next(x for x in report["direct_sqlite_sites"] if x["module"] == "engine/market_microstructure_store.py")
    assert site["tier"] == "SPECIALIZED_OBSERVATIONAL_BUFFER"
    assert site["specialized_persistence"]["direct_sqlite_exception_approved"] is True
    assert site["specialized_persistence"]["high_consequence_state"] is False
    assert site["specialized_persistence"]["decision_authority"] == "NONE"
    assert site["specialized_persistence"]["execution_authority"] == "NONE"
    assert site["specialized_persistence"]["production_effect"] == "NONE"


def test_existing_microstructure_build_documents_are_preserved_and_future_merge_is_note_only():
    for name in (
        "APEX_68_7_0_MARKET_MICROSTRUCTURE_INTELLIGENCE_FOUNDATION.md",
        "APEX_68_8_0_MICROSTRUCTURE_DEPTH_PERSISTENCE.md",
        "APEX_68_9_0_MICROSTRUCTURE_CALIBRATION_PROMOTION_GOVERNANCE.md",
    ):
        assert (ROOT / name).exists()
    doc = (ROOT / "APEX_69_4_2_MICROSTRUCTURE_GOVERNANCE_TRUTH_CLOSURE.md").read_text()
    assert "Decision Outcome Attribution and Microstructure Shadow Calibration" in doc
    assert "does not merge these stores" in doc
