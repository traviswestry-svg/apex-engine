"""Canonical product-version unification guards (originated in APEX 48.1).

These originally pinned the literal "48.1.0" on four surfaces, which meant every
release broke four tests. The unification INVARIANT — all surfaces report the
same version from the single release-manager authority — is what mattered, so
that is what is asserted here. The one pinned current-release literal lives in
tests/test_apex_48_2_version.py.
"""
from engine.release_manager import APP_VERSION, RELEASE_MANIFEST
from engine.production_observability import COMPONENT_VERSION, VERSION, integration_health, metrics_snapshot
from engine.release_manifest import manifest
from pathlib import Path
import re


def test_release_manager_is_the_single_authority():
    assert RELEASE_MANIFEST["apex_version"] == APP_VERSION
    assert re.fullmatch(r"\d+\.\d+\.\d+", APP_VERSION), APP_VERSION
    # Unification began at 48.1.0 — never regress below it.
    assert tuple(int(x) for x in APP_VERSION.split(".")) >= (48, 1, 0)


def test_observability_reports_product_and_component_versions_separately():
    metrics = metrics_snapshot()
    assert VERSION == APP_VERSION
    assert metrics["version"] == APP_VERSION
    assert metrics["apex_version"] == APP_VERSION
    assert metrics["component_version"] == COMPONENT_VERSION
    assert COMPONENT_VERSION != APP_VERSION  # component identity stays separate


def test_readiness_embeds_canonical_metrics_version():
    readiness = integration_health(capabilities={"example": True})
    assert readiness["metrics"]["version"] == APP_VERSION
    assert readiness["metrics"]["component_version"] == COMPONENT_VERSION


def test_release_manifest_and_operations_use_same_authority():
    payload = manifest()
    assert payload["apex_version"] == APP_VERSION
    source = Path("engine/operations_routes.py").read_text(encoding="utf-8")
    assert "from .release_manager import APP_VERSION" in source
    assert "VERSION = APP_VERSION" in source
