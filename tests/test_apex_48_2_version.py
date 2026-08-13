"""APEX canonical release consistency.

No version literal is hard-coded in this file, so a release bump can never turn
these tests stale. They fail only when a version surface drifts out of sync with
the single source of truth, config/apex_release_manifest.json.

Version lives in three places in the source tree:
  * config/apex_release_manifest.json   -- the source of truth
  * config/apex_capability_registry.yaml -- a hand-maintained restatement
  * engine/version.py                    -- now DERIVED from the manifest
and is re-exposed at runtime by engine.release_manager / engine.release_manifest.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from engine.release_manifest import RELEASE_MANIFEST
from engine.release_manager import APPLICATION_VERSION, SEMANTIC_VERSION
from engine.version import APPLICATION_VERSION as VERSION_MODULE_APPLICATION_VERSION

_ROOT = Path(__file__).resolve().parents[1]
_MANIFEST_PATH = _ROOT / "config" / "apex_release_manifest.json"
_REGISTRY_PATH = _ROOT / "config" / "apex_capability_registry.yaml"


def _manifest_version_on_disk() -> str:
    data = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    return str(data["apex_version"]).strip()


def _registry_version_on_disk() -> str:
    # Top-level `apex_version:` key. Parsed with a regex to avoid a PyYAML
    # dependency, matching engine.release_manifest's own no-PyYAML stance.
    for line in _REGISTRY_PATH.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^apex_version:\s*(.+?)\s*$", line)
        if m:
            return m.group(1).strip().strip("'\"")
    raise AssertionError("apex_version key not found in apex_capability_registry.yaml")


def test_release_version_literals_agree_in_source_tree():
    """The hand-maintained version literals in the tree must match the manifest.

    This is the drift guard. Bumping a release means editing the manifest and the
    capability registry; if one is missed, this fails loudly instead of shipping a
    split-brain release identity.
    """
    canonical = _manifest_version_on_disk()
    assert canonical, "config/apex_release_manifest.json has no apex_version"
    assert _registry_version_on_disk() == canonical, (
        "apex_capability_registry.yaml apex_version does not match the release manifest"
    )


def test_current_manifest_is_canonical_release():
    """Every runtime version surface agrees with the loaded manifest.

    Anchored on the loaded manifest so it honors the documented APEX_VERSION
    emergency override; when that override is absent, the loaded value must also
    equal the manifest file on disk.
    """
    expected = RELEASE_MANIFEST["apex_version"]
    assert expected, "loaded release manifest has no apex_version"
    assert APPLICATION_VERSION == expected
    assert SEMANTIC_VERSION == expected
    assert VERSION_MODULE_APPLICATION_VERSION == expected

    if not os.getenv("APEX_VERSION"):
        assert expected == _manifest_version_on_disk()
