"""APEX 69.4.3 — governed storage retention and maintenance.

Operational only. Never deletes canonical decisions, outcomes, feature vectors,
excursions, calibration evidence, or active SQLite databases.
"""
from __future__ import annotations
import datetime as dt
import hashlib, json, os, re, sqlite3
from pathlib import Path
from typing import Any
from .operational_runtime import persistent_root, storage_status
from .evidence_pipeline import DEFAULT_DB
from .release_manager import APP_VERSION
from .storage_capacity_policy import classify_free_pct, policy as storage_capacity_policy
from .historical_payload_compaction import audit_historical_payload_compaction

VERSION = APP_VERSION
QUARANTINE_RE = re.compile(r"\.corrupt-(\d{8,14})(?:\.bak)?$")
PRICE_RETENTION_DAYS = int(os.getenv("APEX_EVIDENCE_PRICE_RETENTION_DAYS", "14"))
QUARANTINE_RETENTION_DAYS = int(os.getenv("APEX_CORRUPT_DB_RETENTION_DAYS", "14"))
TRIGGER_RETENTION_DAYS = int(os.getenv("APEX_TRIGGER_OBSERVATORY_RETENTION_DAYS", "30"))
TRIGGER_DB = Path(os.getenv("APEX_TRIGGER_OBSERVATORY_DB", str(persistent_root() / "apex_trigger_observatory.db")))

DECISION_AUDIT_SAMPLE_LIMIT = 20




def _sqlite_footprint(path: Path) -> dict[str, Any]:
    """Read-only SQLite allocation and per-table diagnostics.

    Free-list pages are reusable *inside* SQLite and are not represented as
    filesystem bytes reclaimed.  No checkpoint, VACUUM, DELETE, or schema
    mutation is performed by this audit helper.
    """
    out: dict[str, Any] = {"name": path.name, "path": str(path), "exists": path.exists()}
    if not path.exists():
        return out
    try:
        out["file_bytes"] = path.stat().st_size
    except OSError:
        out["file_bytes"] = None
    try:
        uri = f"file:{path.resolve().as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=5) as c:
            page_count = int(c.execute("PRAGMA page_count").fetchone()[0] or 0)
            page_size = int(c.execute("PRAGMA page_size").fetchone()[0] or 0)
            freelist = int(c.execute("PRAGMA freelist_count").fetchone()[0] or 0)
            out.update({
                "page_count": page_count,
                "page_size": page_size,
                "allocated_page_bytes": page_count * page_size,
                "freelist_pages": freelist,
                "sqlite_reusable_page_bytes": freelist * page_size,
                "filesystem_reclaimed_by_audit": 0,
            })
            try:
                rows = c.execute(
                    "SELECT name, SUM(pgsize) bytes FROM dbstat GROUP BY name ORDER BY bytes DESC"
                ).fetchall()
                out["top_objects"] = [
                    {"name": str(r[0]), "bytes": int(r[1] or 0)} for r in rows[:20]
                ]
            except sqlite3.DatabaseError:
                out["top_objects_unavailable"] = True
    except Exception as exc:
        out["audit_error"] = f"{type(exc).__name__}: {exc}"
    return out


def _price_prune_plan(path: str | Path = DEFAULT_DB, retention_days: int = PRICE_RETENTION_DAYS) -> dict[str, Any]:
    """Read-only eligibility plan for bounded evidence price-sample pruning."""
    db = Path(path)
    out: dict[str, Any] = {
        "path": str(db),
        "retention_days": max(1, int(retention_days)),
        "exists": db.exists(),
        "apply": False,
        "filesystem_reclaim_estimate_bytes": None,
        "note": "DELETE reuses SQLite pages internally; filesystem bytes are not promised without VACUUM.",
    }
    if not db.exists():
        return out
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max(1, int(retention_days)))).isoformat()
    try:
        uri = f"file:{db.resolve().as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=5) as c:
            pending = c.execute("SELECT MIN(observed_at) FROM decisions WHERE status='PENDING'").fetchone()[0]
            safe_cutoff = min(cutoff, pending) if pending else cutoff
            eligible = int(c.execute("SELECT COUNT(*) FROM price_samples WHERE observed_at < ?", (safe_cutoff,)).fetchone()[0])
            out.update({
                "eligible_rows": eligible,
                "safe_cutoff_exclusive": safe_cutoff,
                "pending_decision_floor": pending,
                "canonical_decisions_protected": True,
                "grading_results_protected": True,
            })
    except Exception as exc:
        out["audit_error"] = f"{type(exc).__name__}: {exc}"
    return out


def _capacity_governance(storage: dict[str, Any], *, reclaimable_quarantine_bytes: int, wal_bytes: int) -> dict[str, Any]:
    classified = classify_free_pct(storage.get("free_pct"))
    try:
        total = int(storage.get("total_bytes") or 0)
        free = int(storage.get("free_bytes") or 0)
    except (TypeError, ValueError):
        total = free = 0
    warn_target = int(total * (float(classified["warn_free_pct"]) / 100.0)) if total else 0
    critical_target = int(total * (float(classified["critical_free_pct"]) / 100.0)) if total else 0
    actions: list[dict[str, Any]] = []
    if classified["state"] == "CRITICAL":
        actions.append({
            "priority": "P0",
            "action": "INCREASE_PERSISTENT_DISK_CAPACITY",
            "reason": "Free capacity is at or below the canonical critical threshold; in-place VACUUM remains prohibited.",
            "automatic": False,
        })
    if reclaimable_quarantine_bytes > 0:
        actions.append({
            "priority": "P1",
            "action": "REVIEW_MATURE_QUARANTINED_DB_ARTIFACTS",
            "eligible_bytes": int(reclaimable_quarantine_bytes),
            "automatic": False,
            "requires_explicit_apply": True,
        })
    if wal_bytes > 0:
        actions.append({
            "priority": "P1",
            "action": "REVIEW_SQLITE_WAL_CHECKPOINT",
            "wal_bytes": int(wal_bytes),
            "automatic": False,
            "requires_explicit_apply": True,
        })
    actions.append({
        "priority": "P1" if classified["state"] in {"WARNING", "CRITICAL"} else "P2",
        "action": "REVIEW_MATURE_EVIDENCE_PRICE_SAMPLE_PRUNE",
        "automatic": False,
        "requires_explicit_apply": True,
        "filesystem_reclaim_promised": False,
    })
    return {
        **classified,
        "free_bytes": free,
        "total_bytes": total,
        "bytes_to_warn_headroom": max(0, warn_target - free),
        "bytes_to_critical_boundary": max(0, critical_target - free),
        "automatic_cleanup": False,
        "automatic_vacuum": False,
        "actions": actions,
    }

def _decision_storage_amplification(c: sqlite3.Connection) -> dict[str, Any]:
    """Read-only size diagnostics for decisions.snapshot_json.

    The aggregate is computed in SQLite. Only a bounded set of the largest and
    latest rows is parsed in Python, so the endpoint does not materialize the
    entire evidence ledger in application memory. Payload values are never
    returned; only byte counts and hashes are exposed.
    """
    agg = c.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(LENGTH(snapshot_json)),0) total_bytes, "
        "COALESCE(AVG(LENGTH(snapshot_json)),0) avg_bytes, COALESCE(MAX(LENGTH(snapshot_json)),0) max_bytes "
        "FROM decisions"
    ).fetchone()
    latest = c.execute(
        "SELECT decision_id,observed_at,LENGTH(snapshot_json) bytes FROM decisions "
        "ORDER BY observed_at DESC LIMIT ?", (DECISION_AUDIT_SAMPLE_LIMIT,)
    ).fetchall()
    largest = c.execute(
        "SELECT decision_id,observed_at,snapshot_json,LENGTH(snapshot_json) bytes FROM decisions "
        "ORDER BY LENGTH(snapshot_json) DESC LIMIT ?", (DECISION_AUDIT_SAMPLE_LIMIT,)
    ).fetchall()
    key_bytes: dict[str, int] = {}
    key_hashes: dict[str, dict[str, int]] = {}
    projection_versions: dict[str, int] = {}
    for row in largest:
        try:
            snap = json.loads(row["snapshot_json"] or "{}")
        except Exception:
            continue
        if not isinstance(snap, dict):
            continue
        projection = snap.get("storage_projection")
        if isinstance(projection, dict):
            v = str(projection.get("projection_version") or "UNKNOWN")
            projection_versions[v] = projection_versions.get(v, 0) + 1
        for key, value in snap.items():
            try:
                raw = json.dumps(value, default=str, separators=(",", ":"), sort_keys=True).encode("utf-8")
            except Exception:
                continue
            key = str(key)
            key_bytes[key] = key_bytes.get(key, 0) + len(raw)
            digest = hashlib.sha256(raw).hexdigest()
            key_hashes.setdefault(key, {})[digest] = key_hashes.setdefault(key, {}).get(digest, 0) + 1
    repeated = []
    for key, hashes in key_hashes.items():
        repeats = max(hashes.values()) if hashes else 0
        if repeats > 1:
            repeated.append({"key": key, "max_identical_occurrences_in_largest_sample": repeats})
    repeated.sort(key=lambda x: (-x["max_identical_occurrences_in_largest_sample"], x["key"]))
    top_keys = sorted(key_bytes.items(), key=lambda kv: kv[1], reverse=True)[:20]
    return {
        "rows": int(agg["n"]),
        "snapshot_json_total_bytes": int(agg["total_bytes"] or 0),
        "snapshot_json_average_bytes": round(float(agg["avg_bytes"] or 0), 2),
        "snapshot_json_max_bytes": int(agg["max_bytes"] or 0),
        "latest_rows": [{"decision_id": r["decision_id"], "observed_at": r["observed_at"], "bytes": int(r["bytes"] or 0)} for r in latest],
        "largest_rows": [{"decision_id": r["decision_id"], "observed_at": r["observed_at"], "bytes": int(r["bytes"] or 0)} for r in largest],
        "largest_sample_top_level_bytes": [{"key": k, "bytes": v} for k, v in top_keys],
        "repeated_top_level_values_in_largest_sample": repeated[:20],
        "storage_projection_versions_in_largest_sample": projection_versions,
        "payload_values_exposed": False,
        "historical_rows_mutated": False,
    }


def _trigger_retention_audit(path: str | Path = TRIGGER_DB, retention_days: int = TRIGGER_RETENTION_DAYS) -> dict[str, Any]:
    db = Path(path); days=max(1,int(retention_days)); cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=days)).isoformat()
    out={"path":str(db),"exists":db.exists(),"retention_days":days,"safe_cutoff_exclusive":cutoff,"apply":False}
    if not db.exists(): return out
    try:
        uri=f"file:{db.resolve().as_posix()}?mode=ro"
        with sqlite3.connect(uri,uri=True,timeout=5) as c:
            c.row_factory=sqlite3.Row
            agg=c.execute("SELECT COUNT(*) n,MIN(triggered_at) oldest,MAX(triggered_at) newest,COALESCE(SUM(LENGTH(evidence_json)),0) evidence_bytes,COALESCE(AVG(LENGTH(evidence_json)),0) avg_evidence,COALESCE(MAX(LENGTH(evidence_json)),0) max_evidence FROM observed_trade_triggers").fetchone()
            statuses=[dict(r) for r in c.execute("SELECT status,COUNT(*) count FROM observed_trade_triggers GROUP BY status ORDER BY count DESC")]
            eligible=int(c.execute("SELECT COUNT(*) FROM observed_trade_triggers WHERE triggered_at < ? AND status IN ('OBSERVED','OBSERVATION_WINDOW_INCOMPLETE') AND decision_id IS NOT NULL AND canonical_grade_status IS NOT NULL",(cutoff,)).fetchone()[0])
            protected_open=int(c.execute("SELECT COUNT(*) FROM observed_trade_triggers WHERE status='OBSERVING'").fetchone()[0])
            protected_unlinked=int(c.execute("SELECT COUNT(*) FROM observed_trade_triggers WHERE triggered_at < ? AND status IN ('OBSERVED','OBSERVATION_WINDOW_INCOMPLETE') AND (decision_id IS NULL OR canonical_grade_status IS NULL)",(cutoff,)).fetchone()[0])
            out.update({"rows":int(agg['n']),"oldest_triggered_at":agg['oldest'],"newest_triggered_at":agg['newest'],"evidence_json_total_bytes":int(agg['evidence_bytes'] or 0),"evidence_json_average_bytes":round(float(agg['avg_evidence'] or 0),2),"evidence_json_max_bytes":int(agg['max_evidence'] or 0),"status_counts":statuses,"eligible_terminal_linked_graded_rows":eligible,"protected_open_rows":protected_open,"protected_old_unlinked_rows":protected_unlinked,"open_rows_protected":True,"unlinked_rows_protected":True,"canonical_grade_required_for_prune":True,"automatic_prune":False,"vacuum_performed":False,"filesystem_reclaim_promised":False})
    except Exception as exc: out['audit_error']=f"{type(exc).__name__}: {exc}"
    return out

def prune_mature_trigger_observations(path: str | Path = TRIGGER_DB, retention_days: int = TRIGGER_RETENTION_DAYS, *, apply: bool=False) -> dict[str, Any]:
    """Operator-only bounded prune of mature terminal, canonically linked+graded triggers. No VACUUM."""
    db=Path(path); days=max(1,int(retention_days)); cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=days)).isoformat()
    if not db.exists(): return {"ok":True,"apply":apply,"exists":False,"eligible_rows":0,"deleted_rows":0}
    with sqlite3.connect(str(db),timeout=15) as c:
        where="triggered_at < ? AND status IN ('OBSERVED','OBSERVATION_WINDOW_INCOMPLETE') AND decision_id IS NOT NULL AND canonical_grade_status IS NOT NULL"
        ids=[r[0] for r in c.execute(f"SELECT trigger_id FROM observed_trade_triggers WHERE {where}",(cutoff,)).fetchall()]
        child=0
        if ids:
            marks=','.join('?' for _ in ids); child=int(c.execute(f"SELECT COUNT(*) FROM trade_trigger_price_observations WHERE trigger_id IN ({marks})",ids).fetchone()[0])
            if apply:
                c.execute(f"DELETE FROM trade_trigger_price_observations WHERE trigger_id IN ({marks})",ids)
                c.execute(f"DELETE FROM observed_trade_triggers WHERE trigger_id IN ({marks})",ids); c.commit()
        return {"ok":True,"apply":apply,"exists":True,"retention_days":days,"safe_cutoff_exclusive":cutoff,"eligible_rows":len(ids),"eligible_child_price_rows":child,"deleted_rows":len(ids) if apply else 0,"deleted_child_price_rows":child if apply else 0,"vacuum_performed":False,"filesystem_reclaim_promised":False,"open_rows_protected":True,"unlinked_rows_protected":True,"human_approval_required":True}


def _age_days(path: Path, now: dt.datetime) -> float:
    return max(0.0, (now.timestamp() - path.stat().st_mtime) / 86400.0)


def audit(root: str | Path | None = None) -> dict[str, Any]:
    root = Path(root) if root else persistent_root()
    now = dt.datetime.now(dt.timezone.utc)
    files=[]; reclaimable=0; wal_bytes=0
    active_dbs: list[Path] = []
    for p in sorted(root.glob("*.db*")):
        try: size=p.stat().st_size
        except OSError: continue
        name=p.name; cls="CANONICAL_ACTIVE_DB"; eligible=False; reason="canonical evidence/state preserved"
        if name.endswith("-wal") or name.endswith("-shm"):
            cls="SQLITE_TRANSIENT"; reason="managed by SQLite; checkpoint only, never unlink while active"
            if name.endswith("-wal"):
                wal_bytes += size
        elif ".corrupt-" in name:
            cls="QUARANTINED_CORRUPT_DB"; age=_age_days(p,now); eligible=age >= QUARANTINE_RETENTION_DAYS
            reason=f"quarantined by db_resilience; operator-removable after {QUARANTINE_RETENTION_DAYS}d retention"
            if eligible: reclaimable += size
        elif name.endswith(".db"):
            active_dbs.append(p)
        files.append({"name":name,"bytes":size,"classification":cls,"operator_cleanup_eligible":eligible,"reason":reason})
    evidence={"path":str(DEFAULT_DB),"exists":Path(DEFAULT_DB).exists(),"price_retention_days":PRICE_RETENTION_DAYS}
    if Path(DEFAULT_DB).exists():
        try:
            uri=f"file:{Path(DEFAULT_DB).resolve().as_posix()}?mode=ro"
            with sqlite3.connect(uri,uri=True,timeout=5) as c:
                c.row_factory=sqlite3.Row
                evidence["counts"]={t:c.execute(f"SELECT COUNT(*) n FROM {t}").fetchone()[0] for t in ("decisions","price_samples","grading_results")}
                evidence["oldest_price_sample_at"]=c.execute("SELECT MIN(observed_at) FROM price_samples").fetchone()[0]
                evidence["newest_price_sample_at"]=c.execute("SELECT MAX(observed_at) FROM price_samples").fetchone()[0]
                evidence["pending_decisions"]=c.execute("SELECT COUNT(*) FROM decisions WHERE status='PENDING'").fetchone()[0]
                evidence["decision_storage_amplification"]=_decision_storage_amplification(c)
                try:
                    rows=c.execute("SELECT name, SUM(pgsize) bytes FROM dbstat GROUP BY name ORDER BY bytes DESC").fetchall()
                    evidence["table_bytes"]=[{"name":r[0],"bytes":r[1]} for r in rows]
                except sqlite3.DatabaseError:
                    evidence["table_bytes_unavailable"]=True
        except Exception as exc: evidence["audit_error"]=f"{type(exc).__name__}: {exc}"
    evidence["price_prune_plan"] = _price_prune_plan(DEFAULT_DB, PRICE_RETENTION_DAYS)
    trigger_retention = _trigger_retention_audit(TRIGGER_DB, TRIGGER_RETENTION_DAYS)
    historical_payload_compaction = audit_historical_payload_compaction(
        trigger_path=TRIGGER_DB, evidence_path=DEFAULT_DB, exhaustive=False
    )
    storage = storage_status()
    capacity = _capacity_governance(storage, reclaimable_quarantine_bytes=reclaimable, wal_bytes=wal_bytes)
    db_footprints = [_sqlite_footprint(p) for p in sorted(active_dbs)]
    largest_databases = sorted(
        [{"name": x.get("name"), "bytes": int(x.get("file_bytes") or 0)} for x in db_footprints],
        key=lambda x: x["bytes"], reverse=True
    )[:10]
    return {
        "ok":True,"version":VERSION,"storage":storage,"storage_capacity":capacity,
        "capacity_policy":storage_capacity_policy(),
        "files":files,"operator_reclaimable_bytes":reclaimable,"wal_bytes":wal_bytes,
        "largest_databases":largest_databases,"database_footprints":db_footprints,
        "evidence_pipeline":evidence,"trigger_observatory_retention":trigger_retention,
        "historical_payload_compaction":historical_payload_compaction,
        "guardrails":{
            "automatic_delete":False,"automatic_vacuum":False,"canonical_evidence_delete":False,
            "human_approval_required":True,"no_fabrication":True,"capacity_warning_observational_only":True,
            "capacity_policy_canonical":True,"filesystem_reclaim_not_inferred_from_sqlite_delete":True,
            "active_database_unlink_forbidden":True,"raw_trigger_observation_auto_prune":False,
            "trigger_prune_explicit_apply_only":True,"trigger_open_rows_protected":True,"trigger_unlinked_rows_protected":True,
            "historical_payload_compaction_read_only":True,"historical_payload_rewrite_enabled":False,
        },
    }


def prune_mature_price_samples(path: str | Path = DEFAULT_DB, retention_days: int = PRICE_RETENTION_DAYS, *, apply: bool=False) -> dict[str,Any]:
    """Prune only forward price observations older than retention and older than every pending decision.

    DELETE frees SQLite pages for reuse; it is intentionally not followed by VACUUM because low free disk
    makes VACUUM unsafe. Canonical decisions and grading results are untouched.
    """
    cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=max(1,int(retention_days)))).isoformat()
    with sqlite3.connect(str(path),timeout=15) as c:
        pending=c.execute("SELECT MIN(observed_at) FROM decisions WHERE status='PENDING'").fetchone()[0]
        safe_cutoff=min(cutoff,pending) if pending else cutoff
        eligible=c.execute("SELECT COUNT(*) FROM price_samples WHERE observed_at < ?",(safe_cutoff,)).fetchone()[0]
        if apply and eligible:
            c.execute("DELETE FROM price_samples WHERE observed_at < ?",(safe_cutoff,)); c.commit()
        return {"ok":True,"apply":apply,"eligible_rows":eligible,"deleted_rows":eligible if apply else 0,"safe_cutoff_exclusive":safe_cutoff,
                "pending_decision_floor":pending,"vacuum_performed":False,"canonical_decisions_deleted":0,"grading_results_deleted":0}


def cleanup_quarantined_backups(root: str | Path | None=None, retention_days: int=QUARANTINE_RETENTION_DAYS, *, apply: bool=False) -> dict[str,Any]:
    root=Path(root) if root else persistent_root(); now=dt.datetime.now(dt.timezone.utc); items=[]; reclaimed=0
    for p in sorted(root.glob("*.corrupt-*")):
        try: age=_age_days(p,now); size=p.stat().st_size
        except OSError: continue
        if age < retention_days: continue
        items.append({"name":p.name,"bytes":size,"age_days":round(age,1)})
        if apply: p.unlink(); reclaimed += size
    return {"ok":True,"apply":apply,"eligible":items,"reclaimed_bytes":reclaimed,"human_approval_required":True}


def checkpoint_wals(root: str | Path | None=None, *, apply: bool=False) -> dict[str,Any]:
    root=Path(root) if root else persistent_root(); results=[]
    for wal in sorted(root.glob("*.db-wal")):
        db=Path(str(wal)[:-4]); before=wal.stat().st_size if wal.exists() else 0
        item={"database":db.name,"wal_bytes_before":before,"apply":apply}
        if apply and db.exists():
            try:
                with sqlite3.connect(str(db),timeout=15) as c: item["checkpoint"]=list(c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone())
                item["wal_bytes_after"]=wal.stat().st_size if wal.exists() else 0
            except Exception as exc: item["error"]=f"{type(exc).__name__}: {exc}"
        results.append(item)
    return {"ok":True,"apply":apply,"results":results}
