import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_6781_release_identity_and_guardrails():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == "67.8.1"
    assert manifest["build_name"] == "CI Regression Fix — Deterministic BPSPX Freshness Fixture"
    g = manifest["guardrails"]
    assert g["bpspx_ci_fixture_clock_deterministic"] is True
    assert g["bpspx_freshness_governance_preserved"] is True
    assert g["breadth_regime_production_logic_changes"] is False
    assert g["breadth_regime_threshold_changes"] is False
    assert g["breadth_regime_authority_changes"] is False


def test_6781_registry_release_identity_is_ratcheted():
    text = (ROOT / "config/apex_capability_registry.yaml").read_text(encoding="utf-8")
    assert "apex_version: 67.8.1" in text
    section = text.split("  release_manifest:", 1)[1].split("\n  breadth_regime:", 1)[0]
    assert 'version: "67.8.1"' in section


def test_6781_breadth_route_fixture_has_deterministic_clock():
    text = (ROOT / "tests/test_breadth_regime.py").read_text(encoding="utf-8")
    assert "def test_routes_expose_dashboard_payload(monkeypatch):" in text
    assert 'monkeypatch.setattr(' in text
    assert '"build_breadth_regime"' in text
    assert "lambda context: build_breadth_regime(context, now=NOW)" in text
    # The production engine itself must not be altered to make CI green.
    engine = (ROOT / "engine/breadth_regime.py").read_text(encoding="utf-8")
    assert 'VERSION = "66.9.0"' in engine
    assert 'if not freshness["usable"]:' in engine
    assert '"state": "DATA_LIMITED"' in engine
