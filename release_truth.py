"""Canonical release identity for regression tests."""
import json
from pathlib import Path
RELEASE_MANIFEST = json.loads((Path(__file__).resolve().parent / 'config/apex_release_manifest.json').read_text())
CURRENT_APEX_VERSION = RELEASE_MANIFEST['apex_version']
CURRENT_BUILD_NAME = RELEASE_MANIFEST['build_name']
