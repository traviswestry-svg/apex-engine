from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_app_imports_urlparse_for_diagnostic_transport():
    source = (ROOT / "app.py").read_text()
    tree = ast.parse(source)
    imports = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "urllib.parse"]
    assert any(any(alias.name == "urlparse" for alias in n.names) for n in imports)
    assert "parsed = urlparse(url)" in source

def test_69_6_2_release_truth():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == manifest["semantic_version"] == manifest["application_version"] == "69.7.1"
    assert manifest["guardrails"]["tick_momentum_diagnostic_probe_urlparse_import_present"] is True
    registry = (ROOT / "config/apex_capability_registry.yaml").read_text()
    assert "apex_version: 69.7.1" in registry
    assert 'version: "69.7.1"' in registry

def test_probe_guardrails_remain_fail_closed():
    source = (ROOT / "engine/tick_momentum_feed.py").read_text()
    assert '"diagnostic_probe_only": True' in source
    assert '"evidence_ingestion_permitted": False' in source
    assert '"execution_authority": False' in source
    assert '"production_effect": "NONE"' in source
