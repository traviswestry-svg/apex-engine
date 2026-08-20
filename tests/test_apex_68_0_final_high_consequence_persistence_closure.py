from __future__ import annotations

import json
from pathlib import Path

from engine.post_persistence_architecture_audit import snapshot

ROOT = Path(__file__).resolve().parents[1]

HIGH_CONSEQUENCE = {
    "adaptive_portfolio_calibration.py",
    "confidence_attribution_engine.py",
    "decision_outcome_forecast.py",
    "feature_store_db.py",
    "institutional_autonomous_desk.py",
    "institutional_market_state_engine.py",
    "institutional_order_flow_intelligence.py",
    "level_transition_probability.py",
    "live_operations.py",
    "premium_discipline.py",
    "premium_strategy_routes.py",
    "trade_director_change_control.py",
    "trade_director_data_lineage.py",
}


def test_release_identity_is_68_0():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == "68.0.0"
    assert manifest["build_name"] == "Final High-Consequence Persistence Closure"
    assert manifest["release_series"] == "APEX 68"


def test_high_consequence_modules_use_canonical_persistence():
    for name in HIGH_CONSEQUENCE:
        source = (ROOT / "engine" / name).read_text()
        assert "sqlite3.connect(" not in source, name
        assert "canonical_persistence" in source, name


def test_audit_has_no_high_consequence_direct_sqlite():
    report = snapshot()
    assert report["persistence"]["high_consequence_file_count"] == 0
    assert report["audit_state"] != "HIGH_CONSEQUENCE_REMAINS"


def test_68_capability_registered():
    registry = (ROOT / "config/apex_capability_registry.yaml").read_text()
    assert "apex_version: 68.0.0" in registry
    assert "final_high_consequence_persistence_closure:" in registry
    assert 'version: "68.0.0"' in registry
