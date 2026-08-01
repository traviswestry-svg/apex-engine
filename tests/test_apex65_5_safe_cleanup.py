from pathlib import Path

from engine.runtime_consolidation import build_consolidation_audit, clear_consolidation_audit_cache
from engine.runtime_dependency_map import build_dependency_map, clear_dependency_map_cache

ROOT = Path(__file__).resolve().parents[1]


def test_no_test_modules_live_under_runtime_engine_package():
    offenders = [str(p.relative_to(ROOT)) for p in (ROOT / "engine").rglob("test_*.py")]
    assert offenders == []


def test_proven_dead_modules_are_removed():
    for rel in (
        "engine/conviction_calibrator.py",
        "engine/decision_contract.py",
        "engine/evidence_matrix.py",
        "engine/director/test_active_trade_director.py",
    ):
        assert not (ROOT / rel).exists(), rel
    assert (ROOT / "tests/test_active_trade_director.py").exists()


def test_legacy_roadmap_registration_isolated_behind_canonical_boundary():
    app_text = (ROOT / "app.py").read_text()
    registry = (ROOT / "engine/institutional_route_registry.py").read_text()
    assert "from engine.institutional_route_registry import register_institutional_compatibility_routes" in app_text
    assert "from engine.institutional_roadmap_routes import register_institutional_roadmap_routes" not in app_text
    assert "register_institutional_roadmap_routes" in registry


def test_dependency_map_remains_monday_safe_after_cleanup():
    clear_dependency_map_cache()
    payload = build_dependency_map()
    assert payload["schema_version"] == "65.5"
    assert payload["summary"]["monday_critical_missing"] == []
    assert payload["summary"]["monday_critical_not_active"] == []
    modules = {row["module"] for row in payload["engines"]}
    assert "engine.conviction_calibrator" not in modules
    assert "engine.decision_contract" not in modules
    assert "engine.evidence_matrix" not in modules
    assert "engine.director.test_active_trade_director" not in modules


def test_consolidation_audit_no_longer_lists_removed_candidates():
    clear_dependency_map_cache()
    clear_consolidation_audit_cache()
    payload = build_consolidation_audit()
    assert payload["schema_version"] == "65.5"
    modules = {row["module"] for row in payload["candidates"]}
    assert "engine.conviction_calibrator" not in modules
    assert "engine.decision_contract" not in modules
    assert "engine.evidence_matrix" not in modules
    assert "engine.director.test_active_trade_director" not in modules
