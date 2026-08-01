from pathlib import Path

from engine.runtime_consolidation import build_consolidation_audit, clear_consolidation_audit_cache
from engine.runtime_dependency_map import build_dependency_map, clear_dependency_map_cache

ROOT = Path(__file__).resolve().parents[1]


def test_dependency_map_uses_complete_root_support_graph():
    clear_dependency_map_cache()
    payload = build_dependency_map()
    assert payload["schema_version"] == "65.4"
    assert payload["summary"]["monday_critical_missing"] == []
    assert payload["summary"]["monday_critical_not_active"] == []
    # apex_engines.py is imported by app.py and must participate in reachability.
    by_module = {row["module"]: row for row in payload["engines"]}
    assert by_module["engine.confidence_attribution"]["classification"] == "ACTIVE"


def test_consolidation_audit_never_auto_deletes_static_orphans():
    clear_consolidation_audit_cache()
    payload = build_consolidation_audit()
    assert payload["ok"] is True
    assert payload["schema_version"] == "65.4"
    assert payload["summary"]["automatic_deletions"] == 0
    assert payload["policy"]["automatic_deletions"] is False
    assert all(row["safe_to_delete"] is False for row in payload["candidates"])


def test_package_initializer_and_misplaced_test_are_protected():
    payload = build_consolidation_audit()
    by_module = {row["module"]: row for row in payload["candidates"]}
    if "engine.brokers" in by_module:
        assert by_module["engine.brokers"]["action"] == "RETAIN_PACKAGE_SENTINEL"
    if "engine.director.test_active_trade_director" in by_module:
        assert by_module["engine.director.test_active_trade_director"]["action"] == "MOVE_TO_TESTS"


def test_render_uses_canonical_wsgi_composition_boundary():
    start = (ROOT / "start_render.sh").read_text()
    composition = (ROOT / "engine/application_composition.py").read_text()
    assert "gunicorn wsgi:app" in start
    assert "APEX_COMPOSITION_BOUNDARY" in composition
    assert "APEX_STABILIZATION_BUILD" in composition


def test_consolidation_endpoint_is_registered_and_critical():
    app_text = (ROOT / "app.py").read_text()
    assert '@app.get("/api/runtime/consolidation")' in app_text
    assert '("GET", "/api/runtime/consolidation")' in app_text
