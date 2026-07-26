"""APEX 48.1 regression tests for canonical product-version reporting."""
from engine.release_manager import APP_VERSION, RELEASE_MANIFEST
from engine.production_observability import COMPONENT_VERSION, VERSION, integration_health, metrics_snapshot
from engine.release_manifest import manifest
from pathlib import Path


def test_canonical_release_is_48_1():
    assert RELEASE_MANIFEST["apex_version"] == "48.1.0"
    assert APP_VERSION == "48.1.0"


def test_observability_reports_product_and_component_versions_separately():
    metrics = metrics_snapshot()
    assert VERSION == "48.1.0"
    assert metrics["version"] == "48.1.0"
    assert metrics["apex_version"] == "48.1.0"
    assert metrics["component_version"] == "10.1.0_PRODUCTION_OBSERVABILITY"
    assert COMPONENT_VERSION == "10.1.0_PRODUCTION_OBSERVABILITY"


def test_readiness_embeds_canonical_metrics_version():
    readiness = integration_health(capabilities={"example": True})
    assert readiness["metrics"]["version"] == "48.1.0"
    assert readiness["metrics"]["component_version"] == COMPONENT_VERSION


def test_release_manifest_and_operations_use_same_authority():
    payload = manifest()
    assert payload["apex_version"] == "48.1.0"
    source = Path("engine/operations_routes.py").read_text(encoding="utf-8")
    assert "from .release_manager import APP_VERSION" in source
    assert "VERSION = APP_VERSION" in source
