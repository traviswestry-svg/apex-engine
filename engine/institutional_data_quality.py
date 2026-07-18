"""APEX 13.0 Sprint 2 deterministic historical data-quality framework.

Scores immutable evidence packages only. It never queries market-data providers and
never invents missing observations. Quality results are append-only assessment
records; eligibility is fail-closed.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, os, sqlite3, uuid
from typing import Any, Dict, Iterable, Mapping, Optional
from . import institutional_evidence as evidence

VERSION = "13.0.0-sprint2"
SCHEMA_VERSION = 1
QUALITY_POLICY_VERSION = "apex.data-quality.v1"
DB_PATH = os.getenv("APEX_EVIDENCE_DB", evidence.DB_PATH)

REQUIRED_SNAPSHOTS = (
    "narrative", "consensus", "conviction", "confidence_attribution",
    "execution", "position_quality", "liquidity", "provider_health", "data_freshness",
)
CRITICAL_SNAPSHOTS = ("execution", "provider_health", "data_freshness")
GRADE_THRESHOLDS = ((95, "A"), (85, "B"), (70, "C"), (50, "D"), (0, "F"))
ELIGIBLE_GRADES = {"A", "B"}


def _now() -> str: return dt.datetime.now(dt.timezone.utc).isoformat()
def _json(v: Any) -> str: return json.dumps(v, sort_keys=True, separators=(",", ":"), default=str)
def _load(v: Any, default=None):
    try: return json.loads(v) if v else ({} if default is None else default)
    except Exception: return {} if default is None else default
def _hash(v: Any) -> str: return hashlib.sha256(_json(v).encode()).hexdigest()
def _conn():
    path = os.getenv("APEX_EVIDENCE_DB", DB_PATH)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    c = sqlite3.connect(path); c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL"); return c


def init_db() -> Dict[str, Any]:
    evidence.init_db()
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS data_quality_schema(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS data_quality_assessments(
          assessment_id TEXT PRIMARY KEY, recommendation_id TEXT NOT NULL, assessed_at TEXT NOT NULL,
          policy_version TEXT NOT NULL, score REAL NOT NULL, grade TEXT NOT NULL, status TEXT NOT NULL,
          eligible INTEGER NOT NULL, checks_json TEXT NOT NULL, defects_json TEXT NOT NULL,
          exclusions_json TEXT NOT NULL, assessment_hash TEXT NOT NULL UNIQUE);
        CREATE INDEX IF NOT EXISTS idx_dq_rec ON data_quality_assessments(recommendation_id,assessed_at);
        CREATE INDEX IF NOT EXISTS idx_dq_eligible ON data_quality_assessments(eligible,grade,assessed_at);
        CREATE TABLE IF NOT EXISTS data_quality_incidents(
          incident_id TEXT PRIMARY KEY, recommendation_id TEXT, detected_at TEXT NOT NULL,
          incident_type TEXT NOT NULL, severity TEXT NOT NULL, source TEXT NOT NULL,
          detail_json TEXT NOT NULL, resolved_at TEXT, resolution_json TEXT);
        CREATE INDEX IF NOT EXISTS idx_dq_incident ON data_quality_incidents(incident_type,severity,detected_at);
        """)
        c.execute("INSERT OR IGNORE INTO data_quality_schema VALUES(?,?)", (SCHEMA_VERSION, _now()))
    return {"ok": True, "schema_version": SCHEMA_VERSION, "policy_version": QUALITY_POLICY_VERSION}


def _present(v: Any) -> bool: return v not in (None, "", {}, [])

def _freshness_defects(freshness: Any) -> list[dict]:
    if not isinstance(freshness, Mapping) or not freshness:
        return [{"code": "MISSING_FRESHNESS", "severity": "CRITICAL", "source": "data_freshness"}]
    state = str(freshness.get("status") or freshness.get("state") or freshness.get("freshness_state") or "").upper()
    if state in {"STALE", "UNAVAILABLE", "DEGRADED", "EXPIRED"}:
        return [{"code": "STALE_OR_UNAVAILABLE_DATA", "severity": "CRITICAL", "source": "data_freshness", "state": state}]
    return []


def _provider_defects(provider: Any) -> list[dict]:
    if not isinstance(provider, Mapping) or not provider:
        return [{"code": "MISSING_PROVIDER_HEALTH", "severity": "CRITICAL", "source": "provider_health"}]
    defects = []
    overall = str(provider.get("status") or provider.get("state") or "").upper()
    if overall in {"FAIL", "FAILED", "DOWN", "UNAVAILABLE", "DEGRADED"}:
        defects.append({"code": "PROVIDER_HEALTH_FAILURE", "severity": "CRITICAL", "source": "provider_health", "state": overall})
    for name, value in provider.items():
        if isinstance(value, Mapping):
            state = str(value.get("status") or value.get("state") or "").upper()
            if state in {"FAIL", "FAILED", "DOWN", "UNAVAILABLE"}:
                defects.append({"code": "PROVIDER_UNAVAILABLE", "severity": "HIGH", "source": str(name), "state": state})
    return defects


def _timeline_defects(recommendation_id: str) -> list[dict]:
    events = evidence.timeline(recommendation_id)
    if not events:
        return [{"code": "MISSING_TIMELINE", "severity": "HIGH", "source": "evidence_timeline"}]
    seq = [int(x.get("sequence") or 0) for x in events]
    defects = []
    if seq != sorted(seq) or len(seq) != len(set(seq)):
        defects.append({"code": "TIMELINE_SEQUENCE_INVALID", "severity": "CRITICAL", "source": "evidence_timeline"})
    hashes = [x.get("integrity_hash") for x in events]
    if len(hashes) != len(set(hashes)):
        defects.append({"code": "DUPLICATE_TIMELINE_EVENT", "severity": "HIGH", "source": "evidence_timeline"})
    return defects


def assess(recommendation_id: str, *, persist: bool = True) -> Dict[str, Any]:
    init_db(); row = evidence.get(recommendation_id)
    if not row:
        return {"ok": False, "status": "UNAVAILABLE", "recommendation_id": recommendation_id,
                "score": None, "grade": None, "eligible_for_research": False,
                "defects": [{"code": "EVIDENCE_PACKAGE_UNAVAILABLE", "severity": "CRITICAL"}]}
    pkg = row.get("package") or {}; snaps = pkg.get("snapshots") or {}
    defects: list[dict] = []
    checks: Dict[str, Any] = {}
    for name in REQUIRED_SNAPSHOTS:
        present = _present(snaps.get(name)); checks[f"snapshot_{name}_present"] = present
        if not present:
            defects.append({"code": f"MISSING_{name.upper()}", "severity": "CRITICAL" if name in CRITICAL_SNAPSHOTS else "HIGH", "source": name})
    integ = evidence.validate(recommendation_id)
    checks["evidence_integrity_ready"] = integ.get("status") == "READY"
    if not checks["evidence_integrity_ready"]:
        defects.append({"code": "EVIDENCE_INTEGRITY_FAILED", "severity": "CRITICAL", "source": "evidence_package"})
    defects.extend(_freshness_defects(snaps.get("data_freshness")))
    defects.extend(_provider_defects(snaps.get("provider_health")))
    defects.extend(_timeline_defects(recommendation_id))
    # Deterministic weighted deductions. Critical defects also force exclusion.
    deduction = sum({"CRITICAL": 30, "HIGH": 15, "MEDIUM": 7, "LOW": 2}.get(d.get("severity"), 5) for d in defects)
    score = max(0.0, round(100.0 - deduction, 2))
    grade = next(g for threshold, g in GRADE_THRESHOLDS if score >= threshold)
    critical = [d for d in defects if d.get("severity") == "CRITICAL"]
    eligible = grade in ELIGIBLE_GRADES and not critical
    status = "READY" if eligible else ("INCOMPLETE" if row else "UNAVAILABLE")
    exclusions = [] if eligible else [d["code"] for d in defects if d.get("severity") in {"CRITICAL", "HIGH"}] or ["QUALITY_GRADE_BELOW_THRESHOLD"]
    result = {"ok": True, "recommendation_id": recommendation_id, "assessed_at": _now(),
              "policy_version": QUALITY_POLICY_VERSION, "score": score, "grade": grade,
              "status": status, "eligible_for_research": eligible, "checks": checks,
              "defects": defects, "exclusion_reasons": sorted(set(exclusions)),
              "message": "Eligible for historical research." if eligible else "Excluded from calibration and research until data-quality defects are resolved."}
    result["assessment_hash"] = _hash({k: result[k] for k in result if k not in {"assessed_at", "assessment_hash"}})
    if persist:
        with _conn() as c:
            old = c.execute("SELECT assessment_id FROM data_quality_assessments WHERE assessment_hash=?", (result["assessment_hash"],)).fetchone()
            if not old:
                c.execute("INSERT INTO data_quality_assessments VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                          (str(uuid.uuid4()), recommendation_id, result["assessed_at"], QUALITY_POLICY_VERSION,
                           score, grade, status, int(eligible), _json(checks), _json(defects),
                           _json(result["exclusion_reasons"]), result["assessment_hash"]))
    return result


def latest(recommendation_id: str) -> Optional[Dict[str, Any]]:
    init_db()
    with _conn() as c:
        r = c.execute("SELECT * FROM data_quality_assessments WHERE recommendation_id=? ORDER BY assessed_at DESC LIMIT 1", (recommendation_id,)).fetchone()
    if not r: return None
    return {"recommendation_id": r["recommendation_id"], "assessed_at": r["assessed_at"], "policy_version": r["policy_version"],
            "score": r["score"], "grade": r["grade"], "status": r["status"], "eligible_for_research": bool(r["eligible"]),
            "checks": _load(r["checks_json"]), "defects": _load(r["defects_json"], []), "exclusion_reasons": _load(r["exclusions_json"], []),
            "assessment_hash": r["assessment_hash"]}


def report() -> Dict[str, Any]:
    init_db()
    packages = evidence.status(); total = int(packages.get("total") or 0)
    with _conn() as c:
        rows = c.execute("""SELECT q.* FROM data_quality_assessments q JOIN
          (SELECT recommendation_id,MAX(assessed_at) assessed_at FROM data_quality_assessments GROUP BY recommendation_id) x
          ON q.recommendation_id=x.recommendation_id AND q.assessed_at=x.assessed_at""").fetchall()
    assessed = len(rows); eligible = sum(int(r["eligible"]) for r in rows)
    grades: Dict[str, int] = {}
    defects: Dict[str, int] = {}
    for r in rows:
        grades[r["grade"]] = grades.get(r["grade"], 0) + 1
        for d in _load(r["defects_json"], []): defects[d.get("code", "UNKNOWN")] = defects.get(d.get("code", "UNKNOWN"), 0) + 1
    status = "COLLECTING" if total == 0 else ("READY" if assessed == total and eligible == total else "DEGRADED")
    return {"status": status, "policy_version": QUALITY_POLICY_VERSION, "evidence_packages": total,
            "assessed": assessed, "unassessed": max(0, total-assessed), "eligible": eligible,
            "excluded": max(0, assessed-eligible), "eligibility_rate_pct": round(eligible*100/assessed, 2) if assessed else None,
            "grades": grades, "defect_counts": defects, "research_gate": "OPEN" if assessed and eligible == assessed else "FAIL_CLOSED"}


def assess_all(limit: int = 500) -> Dict[str, Any]:
    from . import recommendation_ledger as ledger
    rows = ledger.list_recommendations(limit=max(1, min(limit, 500)))
    results = [assess(r["recommendation_id"]) for r in rows if evidence.get(r["recommendation_id"])]
    return {"ok": True, "processed": len(results), "report": report()}
