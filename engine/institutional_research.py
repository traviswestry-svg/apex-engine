"""APEX 13.0 Sprint 5 — governed Institutional Research Intelligence.

Descriptive, reproducible research over immutable real outcomes only. The service never
queries providers, never invents performance, and never changes live trading policy.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3
import uuid
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional

from . import historical_readiness
from . import institutional_data_quality as quality
from . import institutional_governance as governance

VERSION = "13.0.5"
SCHEMA_VERSION = 1
RESEARCH_SCHEMA = "apex.institutional.research.v1"
DB_PATH = os.getenv("APEX_RESEARCH_DB", os.path.join(os.path.dirname(os.path.dirname(__file__)), "apex_research.db"))
MIN_COHORT = int(os.getenv("APEX_RESEARCH_MIN_COHORT", "20"))
MIN_COMPARISON_COHORTS = int(os.getenv("APEX_RESEARCH_MIN_COMPARISON_COHORTS", "2"))
MATERIAL_GAP_PCT = float(os.getenv("APEX_RESEARCH_MATERIAL_GAP_PCT", "10"))
DIMENSIONS = ("family", "regime", "consensus_grade", "confidence_band", "conviction_band", "execution_band")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _load(value: Any, default: Any = None) -> Any:
    if value in (None, ""):
        return {} if default is None else default
    try:
        return json.loads(value)
    except Exception:
        return {} if default is None else default


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> Dict[str, Any]:
    with _conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS research_schema(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS research_runs(
          run_id TEXT PRIMARY KEY,
          run_type TEXT NOT NULL,
          status TEXT NOT NULL,
          dataset_hash TEXT NOT NULL,
          eligibility_json TEXT NOT NULL,
          parameters_json TEXT NOT NULL,
          sample_size INTEGER NOT NULL,
          date_start TEXT,
          date_end TEXT,
          created_at TEXT NOT NULL,
          build_version TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_research_runs_time ON research_runs(created_at);
        CREATE INDEX IF NOT EXISTS idx_research_runs_hash ON research_runs(dataset_hash,run_type);
        CREATE TABLE IF NOT EXISTS research_findings(
          finding_id TEXT PRIMARY KEY,
          run_id TEXT NOT NULL,
          dimension TEXT NOT NULL,
          finding_type TEXT NOT NULL,
          status TEXT NOT NULL,
          evidence_strength TEXT NOT NULL,
          title TEXT NOT NULL,
          summary TEXT NOT NULL,
          sample_size INTEGER NOT NULL,
          date_start TEXT,
          date_end TEXT,
          evidence_json TEXT NOT NULL,
          limitations_json TEXT NOT NULL,
          policy_effect TEXT NOT NULL DEFAULT 'NONE',
          created_at TEXT NOT NULL,
          build_version TEXT NOT NULL,
          FOREIGN KEY(run_id) REFERENCES research_runs(run_id)
        );
        CREATE INDEX IF NOT EXISTS idx_research_findings_run ON research_findings(run_id);
        CREATE INDEX IF NOT EXISTS idx_research_findings_dimension ON research_findings(dimension,created_at);
        """)
        conn.execute("INSERT OR IGNORE INTO research_schema VALUES(?,?)", (SCHEMA_VERSION, _now()))
    return {"ok": True, "schema_version": SCHEMA_VERSION, "db_path": DB_PATH}


def _band(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "UNKNOWN"
    if number < 40:
        return "LOW"
    if number < 60:
        return "MODERATE"
    if number < 75:
        return "HIGH"
    if number < 90:
        return "VERY_HIGH"
    return "EXTREME"


def _eligible_ids() -> set[str]:
    quality.init_db()
    try:
        with sqlite3.connect(quality.DB_PATH) as conn:
            rows = conn.execute("SELECT recommendation_id FROM data_quality_assessments WHERE eligible=1").fetchall()
        return {str(row[0]) for row in rows}
    except sqlite3.Error:
        return set()


def _dataset() -> List[Dict[str, Any]]:
    governance.init_db()
    eligible = _eligible_ids()
    with sqlite3.connect(governance.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM graded_outcomes ORDER BY graded_at,recommendation_id").fetchall()
    result: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if item["recommendation_id"] not in eligible:
            continue
        if str(item.get("data_quality") or "").upper() not in {"GOOD", "VERIFIED"}:
            continue
        item["family"] = str(item.get("family") or "UNKNOWN").upper()
        item["regime"] = str(item.get("regime") or "UNKNOWN").upper()
        item["consensus_grade"] = str(item.get("consensus_grade") or "UNKNOWN").upper()
        item["confidence_band"] = _band(item.get("confidence"))
        item["conviction_band"] = _band(item.get("conviction"))
        payload = _load(item.get("payload_json"))
        item["execution_band"] = _band(payload.get("execution_score"))
        result.append(item)
    return result


def _is_win(label: Any) -> Optional[bool]:
    value = str(label or "").upper()
    if value in {"WIN", "PROFIT", "TARGET", "SUCCESS"}:
        return True
    if value in {"LOSS", "STOP", "FAILURE"}:
        return False
    return None


def _cohort(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    items = list(rows)
    binary = [_is_win(row.get("outcome_label")) for row in items]
    binary = [value for value in binary if value is not None]
    pnl = [float(row["realized_pnl"]) for row in items if row.get("realized_pnl") is not None]
    r_values = [float(row["realized_r"]) for row in items if row.get("realized_r") is not None]
    dates = [str(row.get("graded_at")) for row in items if row.get("graded_at")]
    return {
        "sample_size": len(items),
        "resolved_directional_sample": len(binary),
        "directional_accuracy_pct": round(sum(1 for value in binary if value) / len(binary) * 100, 2) if binary else None,
        "average_realized_pnl": round(sum(pnl) / len(pnl), 4) if pnl else None,
        "average_realized_r": round(sum(r_values) / len(r_values), 4) if r_values else None,
        "date_coverage": {"start": min(dates) if dates else None, "end": max(dates) if dates else None},
        "statistically_insufficient": len(items) < MIN_COHORT,
    }


def status() -> Dict[str, Any]:
    init_db()
    readiness = historical_readiness.build_report()
    rows = _dataset()
    if readiness.get("status") != "READY_FOR_CALIBRATION":
        state = "INSUFFICIENT_HISTORY" if rows else "COLLECTING"
    elif len(rows) < MIN_COHORT * MIN_COMPARISON_COHORTS:
        state = "INSUFFICIENT_HISTORY"
    else:
        state = "READY"
    with _conn() as conn:
        run_count = conn.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0]
        finding_count = conn.execute("SELECT COUNT(*) FROM research_findings").fetchone()[0]
    return {
        "schema_version": RESEARCH_SCHEMA,
        "build_version": VERSION,
        "status": state,
        "eligible_outcome_count": len(rows),
        "minimum_cohort": MIN_COHORT,
        "minimum_comparison_cohorts": MIN_COMPARISON_COHORTS,
        "readiness": readiness,
        "run_count": run_count,
        "finding_count": finding_count,
        "research_only": True,
        "automatic_live_changes": False,
        "automatic_suppression": False,
        "automatic_strategy_promotion": False,
        "limitations": [] if state == "READY" else ["Research findings remain unavailable until real eligible history satisfies all gates."],
    }


def comparisons(dimension: str) -> Dict[str, Any]:
    dimension = str(dimension or "").lower()
    if dimension not in DIMENSIONS:
        return {"ok": False, "status": "UNAVAILABLE", "error": "unsupported_dimension", "supported_dimensions": list(DIMENSIONS)}
    state = status()
    rows = _dataset()
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(dimension) or "UNKNOWN")].append(row)
    cohorts = []
    for name, values in sorted(grouped.items()):
        metrics = _cohort(values)
        cohorts.append({"name": name, **metrics, "eligible_for_comparison": metrics["sample_size"] >= MIN_COHORT})
    eligible = [cohort for cohort in cohorts if cohort["eligible_for_comparison"]]
    return {
        "ok": True,
        "status": "READY" if state["status"] == "READY" and len(eligible) >= MIN_COMPARISON_COHORTS else state["status"],
        "dimension": dimension,
        "sample_size": len(rows),
        "cohorts": cohorts,
        "eligible_cohort_count": len(eligible),
        "minimum_cohort": MIN_COHORT,
        "descriptive_only": True,
        "causal_claim": False,
        "policy_effect": "NONE",
    }


def generate(*, actor: str = "SYSTEM") -> Dict[str, Any]:
    init_db()
    state = status()
    rows = _dataset()
    dataset_payload = [{key: row.get(key) for key in ("recommendation_id", "graded_at", "outcome_label", "realized_pnl", "realized_r", *DIMENSIONS)} for row in rows]
    dataset_hash = _hash(dataset_payload)
    existing = None
    with _conn() as conn:
        existing = conn.execute("SELECT run_id FROM research_runs WHERE run_type='STRATEGY_COMPARISON' AND dataset_hash=? ORDER BY created_at DESC LIMIT 1", (dataset_hash,)).fetchone()
    if existing:
        return {"ok": True, "status": state["status"], "created": False, "run_id": existing["run_id"], "dataset_hash": dataset_hash, "findings": findings(run_id=existing["run_id"])}

    run_id = str(uuid.uuid4())
    dates = [str(row.get("graded_at")) for row in rows if row.get("graded_at")]
    eligibility = {"research_status": state["status"], "historical_readiness": state["readiness"].get("status"), "minimum_cohort": MIN_COHORT}
    with _conn() as conn:
        conn.execute(
            "INSERT INTO research_runs VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, "STRATEGY_COMPARISON", state["status"], dataset_hash, _json(eligibility), _json({"dimensions": DIMENSIONS, "material_gap_pct": MATERIAL_GAP_PCT}), len(rows), min(dates) if dates else None, max(dates) if dates else None, _now(), VERSION),
        )
    governance.audit("GENERATE_RESEARCH_RUN", "research_run", run_id, new={"status": state["status"], "dataset_hash": dataset_hash, "sample_size": len(rows)}, explanation="Reproducible research-only comparison run", actor=actor)
    if state["status"] != "READY":
        return {"ok": True, "status": state["status"], "created": True, "run_id": run_id, "dataset_hash": dataset_hash, "findings": [], "message": "Run recorded; findings withheld because evidence gates are not satisfied."}

    created: List[Dict[str, Any]] = []
    for dimension in DIMENSIONS:
        comparison = comparisons(dimension)
        eligible = [cohort for cohort in comparison["cohorts"] if cohort["eligible_for_comparison"] and cohort["directional_accuracy_pct"] is not None]
        if len(eligible) < MIN_COMPARISON_COHORTS:
            continue
        ranked = sorted(eligible, key=lambda cohort: (-cohort["directional_accuracy_pct"], cohort["name"]))
        best, worst = ranked[0], ranked[-1]
        gap = round(best["directional_accuracy_pct"] - worst["directional_accuracy_pct"], 2)
        if gap < MATERIAL_GAP_PCT:
            continue
        evidence_strength = "MODERATE" if min(best["sample_size"], worst["sample_size"]) < MIN_COHORT * 2 else "STRONG"
        title = f"Material descriptive separation by {dimension.replace('_', ' ')}"
        summary = f"{best['name']} exceeded {worst['name']} by {gap:.2f} percentage points in directional accuracy across eligible historical outcomes."
        evidence_payload = {"dimension": dimension, "best": best, "worst": worst, "gap_pct_points": gap, "dataset_hash": dataset_hash, "descriptive_only": True}
        limitations = ["Observational result; not causal.", "No live policy or strategy change is authorized.", "Performance may vary by regime and date coverage."]
        finding_id = str(uuid.uuid4())
        with _conn() as conn:
            conn.execute(
                "INSERT INTO research_findings VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (finding_id, run_id, dimension, "DESCRIPTIVE_SEPARATION", "RESEARCH_ONLY", evidence_strength, title, summary, best["sample_size"] + worst["sample_size"], min(filter(None, [best["date_coverage"]["start"], worst["date_coverage"]["start"]]), default=None), max(filter(None, [best["date_coverage"]["end"], worst["date_coverage"]["end"]]), default=None), _json(evidence_payload), _json(limitations), "NONE", _now(), VERSION),
            )
        created.append({"finding_id": finding_id, "dimension": dimension, "title": title, "summary": summary, "evidence_strength": evidence_strength, "policy_effect": "NONE"})
    return {"ok": True, "status": "READY", "created": True, "run_id": run_id, "dataset_hash": dataset_hash, "findings": created, "research_only": True}


def findings(*, finding_id: Optional[str] = None, run_id: Optional[str] = None, limit: int = 100) -> Any:
    init_db()
    sql = "SELECT * FROM research_findings"
    args: List[Any] = []
    if finding_id:
        sql += " WHERE finding_id=?"; args.append(finding_id)
    elif run_id:
        sql += " WHERE run_id=?"; args.append(run_id)
    sql += " ORDER BY created_at DESC LIMIT ?"; args.append(max(1, min(int(limit), 500)))
    with _conn() as conn:
        rows = conn.execute(sql, args).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["evidence"] = _load(item.pop("evidence_json"))
        item["limitations"] = _load(item.pop("limitations_json"), [])
        result.append(item)
    return result[0] if finding_id and result else (None if finding_id else result)


def runs(limit: int = 100) -> List[Dict[str, Any]]:
    init_db()
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM research_runs ORDER BY created_at DESC LIMIT ?", (max(1, min(int(limit), 500)),)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["eligibility"] = _load(item.pop("eligibility_json"))
        item["parameters"] = _load(item.pop("parameters_json"))
        result.append(item)
    return result
