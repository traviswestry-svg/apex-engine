"""Canonical release identity for regression tests."""
import json
from pathlib import Path
_MANIFEST = json.loads((Path(__file__).resolve().parent / 'config/apex_release_manifest.json').read_text())
CURRENT_APEX_VERSION = _MANIFEST['apex_version']
CURRENT_BUILD_NAME = _MANIFEST['build_name']
