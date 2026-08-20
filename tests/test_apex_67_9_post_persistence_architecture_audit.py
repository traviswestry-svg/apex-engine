from __future__ import annotations
import json
import re
from pathlib import Path
from engine.post_persistence_architecture_audit import snapshot

ROOT = Path(__file__).resolve().parents[1]


def test_679_audit_is_read_only_and_authority_free():
    s = snapshot()
    assert s["read_only"] is True
    assert s["decision_authority"] == "NONE"
    assert s["execution_authority"] == "NONE"
    assert s["status"] == "HEALTHY"


def test_679_inventory_matches_source_tree_direct_connects():
    expected_files=set(); expected_calls=0
    rx=re.compile(r"\bsqlite3\.connect\s*\(")
    for p in (ROOT / "engine").rglob("*.py"):
        if p.name in {"canonical_persistence.py", "post_persistence_architecture_audit.py"}:
            continue
        n=len(rx.findall(p.read_text(errors="ignore")))
        if n:
            expected_files.add(str(p.relative_to(ROOT))); expected_calls += n
    s=snapshot()["persistence"]
    assert s["remaining_direct_sqlite_files"] == len(expected_files)
    assert s["remaining_direct_sqlite_calls"] == expected_calls
    assert {x["module"] for x in s["direct_sqlite_sites"]} == expected_files


def test_679_high_consequence_review_remains_explicit():
    s=snapshot()["persistence"]
    high=set(s["by_tier"].get("HIGH_CONSEQUENCE_REVIEW", []))
    assert "engine/institutional_market_state_engine.py" in high
    assert "engine/institutional_order_flow_intelligence.py" in high
    assert "engine/level_transition_probability.py" in high
    assert s["high_consequence_file_count"] == len(high)


def test_679_release_and_registry_are_aligned():
    manifest=json.loads((ROOT/"config/apex_release_manifest.json").read_text())
    registry=(ROOT/"config/apex_capability_registry.yaml").read_text()
    assert manifest["apex_version"] >= "67.9.0"
    assert manifest["guardrails"]["post_persistence_architecture_audit_read_only"] is True
    assert "post_persistence_architecture_audit:" in registry
    section=registry.split("post_persistence_architecture_audit:",1)[1].split("\n  silent_degradation_coverage_wave2:",1)[0]
    import re
    m = re.search(r'version:\s*[\"\']?([0-9]+\.[0-9]+\.[0-9]+)', section)
    assert m is not None
    assert tuple(map(int, m.group(1).split('.'))) >= (67, 9, 0)
    assert "decision_authority: none" in section
    assert "no_execution_authority" in section


def test_679_dashboard_link_is_available():
    html=(ROOT/"templates/apex_os.html").read_text()
    assert '/apex_os/post-persistence-architecture-audit' in html
