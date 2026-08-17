import json
from pathlib import Path

from engine.architecture_integrity import snapshot

ROOT = Path(__file__).resolve().parents[1]


def test_release_metadata_is_current_and_not_stale():
    m = json.loads((ROOT / "config" / "apex_release_manifest.json").read_text())
    version = str(m["apex_version"])
    major = version.split(".", 1)[0]
    assert major.isdigit()
    assert m["build_name"]
    assert m["release_series"] == f"APEX {major}"
    assert m["released_at"] >= "2026-08-17"


def test_registry_contains_recent_architecture_layers():
    text = (ROOT / "config" / "apex_capability_registry.yaml").read_text()
    for capability in (
        "historical_effectiveness_observatory",
        "confidence_calibration_audit",
        "canonical_persistence",
        "silent_degradation_observability",
        "architecture_integrity",
    ):
        assert f"  {capability}:" in text
    assert '  breadth_regime:' in text
    assert '    version: "66.9.0"' in text


def test_architecture_snapshot_is_clean_after_repo_cleanup():
    d = snapshot()
    assert d["identity_aligned"] is True
    assert d["missing_modules"] == []
    assert d["duplicate_routes"] == []
    assert d["cleanup_violations"] == []
    assert d["status"] == "HEALTHY"
    assert d["execution_authority"] == "NONE"
