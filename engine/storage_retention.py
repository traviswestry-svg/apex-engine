"""APEX 69.4.3.1 — governed storage retention and maintenance.

Operational only. Never deletes canonical decisions, outcomes, feature vectors,
excursions, calibration evidence, or active SQLite databases.
"""
from __future__ import annotations
import datetime as dt
import os, re, sqlite3
from pathlib import Path
from typing import Any
from .operational_runtime import persistent_root, storage_status
from .evidence_pipeline import DEFAULT_DB

VERSION = "69.4.3.1"
QUARANTINE_RE = re.compile(r"\.corrupt-(\d{8,14})(?:\.bak)?$")
PRICE_RETENTION_DAYS = int(os.getenv("APEX_EVIDENCE_PRICE_RETENTION_DAYS", "14"))
QUARANTINE_RETENTION_DAYS = int(os.getenv("APEX_CORRUPT_DB_RETENTION_DAYS", "14"))


def _age_days(path: Path, now: dt.datetime) -> float:
    return max(0.0, (now.timestamp() - path.stat().st_mtime) / 86400.0)


def audit(root: str | Path | None = None) -> dict[str, Any]:
    root = Path(root) if root else persistent_root()
    now = dt.datetime.now(dt.timezone.utc)
    files=[]; reclaimable=0
    for p in sorted(root.glob("*.db*")):
        try: size=p.stat().st_size
        except OSError: continue
        name=p.name; cls="CANONICAL_ACTIVE_DB"; eligible=False; reason="canonical evidence/state preserved"
        if name.endswith("-wal") or name.endswith("-shm"):
            cls="SQLITE_TRANSIENT"; reason="managed by SQLite; checkpoint only, never unlink while active"
        elif ".corrupt-" in name:
            cls="QUARANTINED_CORRUPT_DB"; age=_age_days(p,now); eligible=age >= QUARANTINE_RETENTION_DAYS
            reason=f"quarantined by db_resilience; operator-removable after {QUARANTINE_RETENTION_DAYS}d retention"
            if eligible: reclaimable += size
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
                try:
                    rows=c.execute("SELECT name, SUM(pgsize) bytes FROM dbstat GROUP BY name ORDER BY bytes DESC").fetchall()
                    evidence["table_bytes"]=[{"name":r[0],"bytes":r[1]} for r in rows]
                except sqlite3.DatabaseError:
                    evidence["table_bytes_unavailable"]=True
        except Exception as exc: evidence["audit_error"]=f"{type(exc).__name__}: {exc}"
    return {"ok":True,"version":VERSION,"storage":storage_status(),"files":files,"operator_reclaimable_bytes":reclaimable,"evidence_pipeline":evidence,
            "guardrails":{"automatic_delete":False,"automatic_vacuum":False,"canonical_evidence_delete":False,"human_approval_required":True,"no_fabrication":True}}


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
