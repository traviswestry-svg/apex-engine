import re
from pathlib import Path

from engine.release_manifest import RELEASE_MANIFEST
from engine.release_manager import APPLICATION_VERSION, SEMANTIC_VERSION
from engine.version import APPLICATION_VERSION as ENGINE_APPLICATION_VERSION


_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_REGISTRY = Path(__file__).resolve().parents[1] / "config" / "apex_capability_registry.yaml"


def _registry_apex_version() -> str:
    """Read only the top-level registry release identity without adding PyYAML."""
    for raw in _REGISTRY.read_text(encoding="utf-8").splitlines():
        if raw.startswith("apex_version:"):
            return raw.split(":", 1)[1].strip().strip("'\"")
    raise AssertionError("config/apex_capability_registry.yaml is missing top-level apex_version")


def test_current_manifest_is_canonical_release():
    """Canonical release surfaces must agree; the test must not hard-code a release.

    A release bump is valid when the manifest, runtime version module, release manager,
    and capability registry all move together. Hard-coding yesterday's version here
    turns a successful release bump into a false CI regression.
    """
    manifest_version = str(RELEASE_MANIFEST["apex_version"])

    assert _SEMVER_RE.fullmatch(manifest_version), manifest_version
    assert APPLICATION_VERSION == manifest_version
    assert SEMANTIC_VERSION == manifest_version
    assert ENGINE_APPLICATION_VERSION == manifest_version
    assert _registry_apex_version() == manifest_version
