"""Canonical release identity for regression tests."""
import json
from pathlib import Path
CURRENT_APEX_VERSION = json.loads((Path(__file__).resolve().parent / 'config/apex_release_manifest.json').read_text())['apex_version']
CURRENT_BUILD_NAME = json.loads((Path(__file__).resolve().parent / 'config/apex_release_manifest.json').read_text())['build_name']
