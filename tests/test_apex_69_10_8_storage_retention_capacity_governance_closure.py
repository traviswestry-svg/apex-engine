from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from pathlib import Path

from engine import operational_runtime, storage_retention
from engine.storage_capacity_policy import classify_free_pct, policy

ROOT = Path(__file__).resolve().parents[1]


def _evidence_db(path: Path) -> None:
    with sqlite3.connect(path) as c:
        c.executescript(
            """
            CREATE TABLE decisions(decision_id TEXT PRIMARY KEY, observed_at TEXT, status TEXT, snapshot_json TEXT);
            CREATE TABLE price_samples(id INTEGER PRIMARY KEY, ticker TEXT, observed_at TEXT, price REAL);
            CREATE TABLE grading_results(id INTEGER PRIMARY KEY, decision_id TEXT, status TEXT);
            """
        )
        c.commit()


def test_release_truth_and_capacity_guardrails():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == manifest["semantic_version"] == manifest["application_version"] == "69.10.19"
    assert manifest["build_name"] == "Canonical Feature Sample P/L Excursion Linkage Closure"
    g = manifest["guardrails"]
    assert g["storage_capacity_policy_canonical"] is True
    assert g["storage_capacity_warn_free_pct_default"] == 25.0
    assert g["storage_capacity_critical_free_pct_default"] == 15.0
    assert g["storage_capacity_auto_delete"] is False
    assert g["storage_capacity_auto_vacuum"] is False
    assert g["storage_trigger_raw_observation_auto_prune"] is False


def test_capability_registry_is_aligned_and_operations_only():
    registry = (ROOT / "config/apex_capability_registry.yaml").read_text()
    assert "apex_version: 69.10.19" in registry
    assert "governed_storage_retention:" in registry
    assert 'version: "69.10.8"' in registry
    assert "engine.storage_capacity_policy" in registry
    assert "production_effect: OPERATIONS_ONLY" in registry
    assert "operator_maintenance_dry_run_default" in registry
    assert "raw_trigger_observation_auto_prune_forbidden" in registry


def test_canonical_capacity_thresholds_classify_production_boundary(monkeypatch):
    for key in (
        "APEX_STORAGE_WARN_FREE_PCT", "APEX_STORAGE_CRITICAL_FREE_PCT",
        "APEX_DISK_WARN_FREE_PCT", "APEX_DISK_CRITICAL_FREE_PCT",
    ):
        monkeypatch.delenv(key, raising=False)
    p = policy()
    assert p["warn_free_pct"] == 25.0
    assert p["critical_free_pct"] == 15.0
    assert classify_free_pct(26.0)["state"] == "PASS"
    assert classify_free_pct(20.0)["state"] == "WARNING"
    assert classify_free_pct(12.93)["state"] == "CRITICAL"


def test_legacy_disk_threshold_env_remains_backward_compatible(monkeypatch):
    monkeypatch.delenv("APEX_STORAGE_WARN_FREE_PCT", raising=False)
    monkeypatch.delenv("APEX_STORAGE_CRITICAL_FREE_PCT", raising=False)
    monkeypatch.setenv("APEX_DISK_WARN_FREE_PCT", "30")
    monkeypatch.setenv("APEX_DISK_CRITICAL_FREE_PCT", "12")
    p = policy()
    assert p["warn_free_pct"] == 30.0
    assert p["critical_free_pct"] == 12.0
    assert classify_free_pct(13.0)["state"] == "WARNING"


def test_storage_audit_reports_table_footprint_and_no_false_reclaim(monkeypatch, tmp_path):
    db = tmp_path / "apex_evidence_pipeline.db"
    _evidence_db(db)
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat()
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO decisions VALUES(?,?,?,?)", ("d1", old, "GRADED", "{}"))
        c.execute("INSERT INTO price_samples VALUES(1,'SPX',?,1.0)", (old,))
        c.execute("INSERT INTO grading_results VALUES(1,'d1','GRADED')")
        c.commit()
    quarantine = tmp_path / "apex_tracking.db.corrupt-20260720"
    quarantine.write_bytes(b"x" * 4096)
    os.utime(quarantine, (1, 1))

    monkeypatch.setattr(storage_retention, "DEFAULT_DB", str(db))
    monkeypatch.setattr(storage_retention, "storage_status", lambda: {
        "free_pct": 12.93, "free_bytes": 100, "total_bytes": 1000,
        "database_files": [], "state": "CRITICAL", "ok": False,
    })
    out = storage_retention.audit(tmp_path)
    assert out["storage_capacity"]["state"] == "CRITICAL"
    assert out["storage_capacity"]["automatic_cleanup"] is False
    assert out["operator_reclaimable_bytes"] == 4096
    assert out["database_footprints"]
    assert out["database_footprints"][0]["filesystem_reclaimed_by_audit"] == 0
    plan = out["evidence_pipeline"]["price_prune_plan"]
    assert plan["eligible_rows"] == 1
    assert plan["filesystem_reclaim_estimate_bytes"] is None
    assert out["guardrails"]["raw_trigger_observation_auto_prune"] is False


def test_runtime_storage_status_uses_canonical_capacity_policy(monkeypatch, tmp_path):
    class Usage:
        total = 1000
        used = 871
        free = 129
    monkeypatch.setattr(operational_runtime, "persistent_root", lambda: tmp_path)
    monkeypatch.setattr(operational_runtime.shutil, "disk_usage", lambda _root: Usage())
    out = operational_runtime.storage_status()
    assert out["free_pct"] == 12.9
    assert out["state"] == "CRITICAL"
    assert out["ok"] is False
    assert out["capacity_policy"]["critical_free_pct"] == 15.0


def test_operator_script_is_dry_run_by_default_and_no_vacuum():
    src = (ROOT / "scripts/apex_storage_maintenance.py").read_text()
    assert 'parser.add_argument("--apply", action="store_true"' in src
    assert 'default="audit"' in src
    assert "VACUUM(" not in src.upper()
    assert "cleanup_quarantined_backups(apply=args.apply)" in src
    assert "prune_mature_price_samples(apply=args.apply)" in src


def test_admin_storage_route_remains_read_only_v2():
    src = (ROOT / "app.py").read_text()
    start = src.index("def api_admin_storage_audit():")
    end = src.index('@app.get("/api/runtime/health")', start)
    block = src[start:end]
    assert '"apex.storage_audit.v2"' in block
    assert 'payload["read_only"] = True' in block
    assert 'payload["maintenance_applied"] = False' in block
    for forbidden in ("checkpoint_wals(", "cleanup_quarantined_backups(", "prune_mature_price_samples(", "VACUUM(", ".unlink("):
        assert forbidden not in block
