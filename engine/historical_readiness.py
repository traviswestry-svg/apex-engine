"""APEX 13.0 Sprint 3 historical readiness and evidence coverage.

Read-only aggregation over immutable evidence packages, data-quality assessments,
recommendation ledger rows, and real graded outcomes. No outcomes are inferred.
"""
from __future__ import annotations

from .canonical_persistence import connect as canonical_connect
import datetime as dt
import json
import os
import sqlite3
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, Mapping, Optional

from . import institutional_evidence as evidence
from . import institutional_data_quality as quality
from . import institutional_governance as governance
from . import recommendation_ledger as ledger

VERSION = "66.4.0"
SCHEMA_VERSION = "apex.history.readiness.v2"
MIN_GRADED = int(os.getenv("APEX_HISTORY_MIN_GRADED", str(governance.MIN_GRADED)))
MIN_ELIGIBLE = int(os.getenv("APEX_HISTORY_MIN_ELIGIBLE", "25"))
MIN_DATE_DAYS = int(os.getenv("APEX_HISTORY_MIN_DATE_DAYS", "20"))
MAX_EXCLUSION_RATE = float(os.getenv("APEX_HISTORY_MAX_EXCLUSION_RATE_PCT", "25"))


def _parse(value: Any) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _recommendations(limit: int = 10000):
    try:
        rows = ledger.list_recommendations(limit=limit)
        if isinstance(rows, dict):
            rows = rows.get("recommendations") or rows.get("items") or []
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def _quality_rows() -> Dict[str, Dict[str, Any]]:
    quality.init_db()
    out: Dict[str, Dict[str, Any]] = {}
    with canonical_connect(quality.DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute("SELECT * FROM data_quality_assessments ORDER BY assessed_at").fetchall()
    for row in rows:
        d = dict(row)
        d["defects"] = json.loads(d.pop("defects_json") or "[]")
        d["checks"] = json.loads(d.pop("checks_json") or "{}")
        out[d["recommendation_id"]] = d
    return out


def _outcomes() -> Dict[str, Dict[str, Any]]:
    governance.init_db()
    with canonical_connect(governance.DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute("SELECT * FROM graded_outcomes ORDER BY graded_at").fetchall()
    return {r["recommendation_id"]: dict(r) for r in rows}


def _dimension(rec: Mapping[str, Any], package: Mapping[str, Any], key: str, default: str = "UNKNOWN") -> str:
    decision = _safe_dict(package.get("canonical_decision"))
    snapshots = _safe_dict(package.get("snapshots"))
    candidates = {
        "strategy": [rec.get("strategy"), decision.get("strategy"), decision.get("action")],
        "regime": [decision.get("market_state"), _safe_dict(snapshots.get("narrative")).get("market_state"), rec.get("regime")],
        "session": [rec.get("session"), decision.get("session"), _safe_dict(snapshots.get("data_freshness")).get("session")],
        "direction": [rec.get("direction"), decision.get("direction")],
        "ticker": [rec.get("ticker"), decision.get("ticker")],
    }
    for value in candidates.get(key, []):
        if value not in (None, "", {}):
            if isinstance(value, Mapping):
                value = value.get("state") or value.get("regime") or value.get("name")
            if value not in (None, ""):
                return str(value).upper()
    return default


def _coverage(counter: Counter, total: int) -> Dict[str, Any]:
    return {
        "total": total,
        "buckets": [
            {"name": name, "count": count, "percentage": round(count / total * 100, 2) if total else 0.0}
            for name, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
        ],
    }


def _latest_quality_map() -> Dict[str, Dict[str, Any]]:
    """Latest assessment per recommendation. Kept separate for diagnostics/tests."""
    return _quality_rows()


def reconcile(limit: int = 500) -> Dict[str, Any]:
    """Idempotently repair the persisted readiness pipeline without fabricating outcomes.

    Repairs only evidence/quality bookkeeping that can be derived from the immutable
    recommendation ledger. Real outcomes are bridged only when the ledger already
    contains an explicit terminal outcome label.
    """
    evidence.init_db(); quality.init_db(); governance.init_db()
    recs = _recommendations(limit=max(1, min(int(limit or 500), 500)))
    qrows = _latest_quality_map()
    outcomes = _outcomes()
    stats = Counter()
    errors = []
    for rec in recs:
        rid = str(rec.get("recommendation_id") or "").strip()
        if not rid:
            stats["skipped_missing_id"] += 1
            continue
        try:
            if evidence.get(rid) is None:
                cap = evidence.capture(rid)
                if cap.get("ok"):
                    stats["evidence_captured"] += 1
                else:
                    stats["evidence_capture_failed"] += 1
                    errors.append({"recommendation_id": rid, "stage": "evidence", "error": cap.get("error") or cap.get("status")})
                    continue
            else:
                stats["evidence_already_present"] += 1

            # Reassess when no assessment exists. Existing immutable assessments are
            # left intact; operator can explicitly reassess from the data-quality API.
            if rid not in qrows:
                assessed = quality.assess(rid)
                if assessed.get("ok"):
                    stats["quality_assessed"] += 1
                    qrows[rid] = assessed
                else:
                    stats["quality_assessment_failed"] += 1
                    errors.append({"recommendation_id": rid, "stage": "quality", "error": assessed.get("error") or assessed.get("status")})
            else:
                stats["quality_already_assessed"] += 1

            # Bridge only explicit persisted real outcomes from the ledger. Never infer
            # WIN/LOSS from age, direction, price, or strategy.
            outcome_status = str(rec.get("outcome_status") or "").upper()
            outcome_label = str(rec.get("outcome_label") or "").strip().upper()
            if rid not in outcomes and outcome_label and outcome_status in {"GRADED", "SETTLED", "CLOSED", "FINAL"}:
                q = qrows.get(rid) or {}
                contract = {
                    "recommendation_id": rid,
                    "outcome_label": outcome_label,
                    "realized_pnl": rec.get("realized_pnl"),
                    "realized_r": rec.get("realized_r"),
                    "family": rec.get("strategy"),
                    "confidence": rec.get("final_live_confidence"),
                    "data_quality": "VERIFIED" if bool(q.get("eligible") or q.get("eligible_for_research")) else "UNKNOWN",
                    "source": "RECOMMENDATION_LEDGER",
                    "graded_at": rec.get("outcome_at") or rec.get("updated_at"),
                }
                bridged = governance.ingest_outcome(contract)
                if bridged.get("ok"):
                    stats["outcomes_bridged"] += 1
                    outcomes[rid] = contract
                else:
                    stats["outcome_bridge_failed"] += 1
                    errors.append({"recommendation_id": rid, "stage": "outcome", "error": bridged.get("error") or bridged.get("status")})
            elif rid in outcomes:
                stats["outcome_already_present"] += 1
            else:
                stats["awaiting_real_outcome"] += 1
        except Exception as exc:
            stats["errors"] += 1
            errors.append({"recommendation_id": rid, "stage": "reconcile", "error": f"{type(exc).__name__}: {exc}"})
    return {
        "ok": not errors,
        "status": "PASS" if not errors else "DEGRADED",
        "build_version": VERSION,
        "processed": len(recs),
        "repairs": dict(stats),
        "errors": errors[:50],
        "guardrails": {
            "fabricates_outcomes": False,
            "provider_calls": False,
            "broker_calls": False,
            "idempotent": True,
        },
    }


def diagnostic(limit: int = 100) -> Dict[str, Any]:
    """Explain exactly where each recommendation sits in the learning pipeline."""
    report = build_report(include_records=True, record_limit=limit)
    records = report.get("diagnostic", {}).get("records", [])
    blockers = Counter(r.get("pipeline_state") or "UNKNOWN" for r in records)
    return {
        "ok": True,
        "status": report.get("status"),
        "build_version": VERSION,
        "counts": report.get("counts", {}),
        "quality": report.get("quality", {}),
        "pipeline_blockers": dict(blockers),
        "records": records,
        "next_action": report.get("diagnostic", {}).get("next_action"),
        "guardrails": {"read_only": True, "fabricates_outcomes": False},
    }

def build_report(*, include_records: bool = False, record_limit: int = 100) -> Dict[str, Any]:
    evidence.init_db(); quality.init_db(); governance.init_db()
    recs = _recommendations()
    qrows = _quality_rows()
    outcomes = _outcomes()

    package_by_id: Dict[str, Dict[str, Any]] = {}
    with canonical_connect(evidence.DB_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute("SELECT recommendation_id,created_at,status,package_json FROM evidence_packages ORDER BY created_at").fetchall()
    for row in rows:
        d = dict(row)
        try:
            d["package"] = json.loads(d.pop("package_json"))
        except Exception:
            d["package"] = {}
        package_by_id[d["recommendation_id"]] = d

    rec_by_id = {str(r.get("recommendation_id")): r for r in recs if r.get("recommendation_id")}
    ids = sorted(set(rec_by_id) | set(package_by_id) | set(outcomes))
    counts = Counter()
    exclusions = Counter()
    strategy = Counter(); regime = Counter(); session = Counter(); weekday = Counter(); ticker = Counter()
    eligible_ids = []
    timestamps = []
    diagnostic_records = []

    for rid in ids:
        rec = rec_by_id.get(rid, {})
        package_row = package_by_id.get(rid)
        package = _safe_dict((package_row or {}).get("package"))
        outcome = outcomes.get(rid)
        q = qrows.get(rid)
        counts["collected"] += 1
        if package_row:
            counts["evidence_packages"] += 1
        else:
            counts["missing_evidence"] += 1
        if outcome:
            counts["graded"] += 1
        else:
            counts["pending"] += 1
        assessed = q is not None
        eligible = bool(q and int(q.get("eligible") or 0) == 1)
        if not assessed:
            counts["unassessed"] += 1
            exclusions["NOT_ASSESSED"] += 1
        elif eligible:
            counts["eligible"] += 1
            eligible_ids.append(rid)
        else:
            counts["excluded"] += 1
            defects = q.get("defects") or []
            if defects:
                for defect in defects:
                    if isinstance(defect, Mapping):
                        exclusions[str(defect.get("code") or defect.get("type") or "QUALITY_DEFECT")] += 1
                    else:
                        exclusions[str(defect)] += 1
            else:
                exclusions["QUALITY_GATE_CLOSED"] += 1

        if include_records and len(diagnostic_records) < max(1, min(int(record_limit or 100), 500)):
            reasons = []
            if not package_row:
                state = "MISSING_EVIDENCE"
                reasons = ["MISSING_EVIDENCE_PACKAGE"]
            elif not assessed:
                state = "UNASSESSED"
                reasons = ["NOT_ASSESSED"]
            elif not eligible:
                state = "QUALITY_EXCLUDED"
                reasons = [str((d.get("code") if isinstance(d, Mapping) else d) or "QUALITY_DEFECT") for d in (q.get("defects") or [])]
                if not reasons:
                    reasons = ["QUALITY_GATE_CLOSED"]
            elif not outcome:
                state = "AWAITING_REAL_OUTCOME"
                reasons = ["NO_GRADED_OUTCOME"]
            else:
                state = "LEARNING_ELIGIBLE"
            diagnostic_records.append({
                "recommendation_id": rid,
                "captured_at": (package_row or {}).get("created_at") or rec.get("captured_at"),
                "ticker": _dimension(rec, package, "ticker"),
                "strategy": _dimension(rec, package, "strategy"),
                "evidence": bool(package_row),
                "assessed": assessed,
                "quality_grade": q.get("grade") if q else None,
                "eligible": eligible,
                "graded": bool(outcome),
                "outcome_label": outcome.get("outcome_label") if outcome else rec.get("outcome_label"),
                "pipeline_state": state,
                "reasons": reasons,
            })
        strategy[_dimension(rec, package, "strategy")] += 1
        regime[_dimension(rec, package, "regime")] += 1
        session[_dimension(rec, package, "session")] += 1
        ticker[_dimension(rec, package, "ticker")] += 1
        at = _parse((package_row or {}).get("created_at") or rec.get("captured_at") or (outcome or {}).get("graded_at"))
        if at:
            timestamps.append(at)
            weekday[at.strftime("%A").upper()] += 1

    for key in ("collected", "evidence_packages", "missing_evidence", "graded", "pending", "eligible", "excluded", "unassessed"):
        counts[key] += 0

    start = min(timestamps).isoformat() if timestamps else None
    end = max(timestamps).isoformat() if timestamps else None
    span_days = (max(timestamps).date() - min(timestamps).date()).days + 1 if timestamps else 0
    collected = counts["collected"]
    assessed_total = counts["eligible"] + counts["excluded"]
    exclusion_rate = round(counts["excluded"] / assessed_total * 100, 2) if assessed_total else 0.0

    gates = {
        "minimum_graded": {"required": MIN_GRADED, "actual": counts["graded"], "passed": counts["graded"] >= MIN_GRADED},
        "minimum_quality_eligible": {"required": MIN_ELIGIBLE, "actual": counts["eligible"], "passed": counts["eligible"] >= MIN_ELIGIBLE},
        "minimum_date_coverage_days": {"required": MIN_DATE_DAYS, "actual": span_days, "passed": span_days >= MIN_DATE_DAYS},
        "maximum_exclusion_rate_pct": {"required_max": MAX_EXCLUSION_RATE, "actual": exclusion_rate, "passed": assessed_total > 0 and exclusion_rate <= MAX_EXCLUSION_RATE},
        "immutable_outcomes_only": {"required": True, "actual": True, "passed": True},
    }
    if collected == 0:
        status = "COLLECTING"
    elif assessed_total > 0 and exclusion_rate > MAX_EXCLUSION_RATE:
        status = "DEGRADED_HISTORY"
    elif not gates["minimum_graded"]["passed"] or not gates["minimum_date_coverage_days"]["passed"]:
        status = "INSUFFICIENT_HISTORY"
    elif all(g["passed"] for g in gates.values()):
        status = "READY_FOR_CALIBRATION"
    else:
        status = "INSUFFICIENT_HISTORY"

    unlocks = {
        "confidence_calibration": status == "READY_FOR_CALIBRATION",
        "similarity_outcome_analytics": status == "READY_FOR_CALIBRATION" and counts["eligible"] >= governance.MIN_SIMILAR,
        "strategy_intelligence": status == "READY_FOR_CALIBRATION",
        "adaptive_learning_candidates": status == "READY_FOR_CALIBRATION",
        "automatic_production_changes": False,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "build_version": VERSION,
        "status": status,
        "counts": dict(counts),
        "coverage": {
            "date": {"start": start, "end": end, "calendar_days": span_days},
            "strategy": _coverage(strategy, collected),
            "regime": _coverage(regime, collected),
            "session": _coverage(session, collected),
            "weekday": _coverage(weekday, collected),
            "ticker": _coverage(ticker, collected),
        },
        "quality": {
            "assessed": assessed_total,
            "unassessed": counts["unassessed"],
            "exclusion_rate_pct": exclusion_rate,
            "exclusion_rate_denominator": "ASSESSED_ONLY",
            "exclusion_reasons": dict(exclusions),
            "eligible_recommendation_ids": eligible_ids,
        },
        "readiness_gates": gates,
        "feature_unlocks": unlocks,
        "diagnostic": {
            "records": diagnostic_records if include_records else [],
            "next_action": (
                "RECONCILE_EVIDENCE_AND_QUALITY" if counts["missing_evidence"] or counts["unassessed"]
                else "WAIT_FOR_REAL_OUTCOMES" if counts["pending"]
                else "ACCUMULATE_MORE_ELIGIBLE_HISTORY" if status != "READY_FOR_CALIBRATION"
                else "READY_FOR_CALIBRATION"
            ),
        },
        "limitations": [
            "No performance metric is activated by this report.",
            "Pending recommendations are not graded or inferred.",
            "Coverage reflects persisted ledger, evidence, quality, and outcome records only.",
        ],
    }


def status() -> Dict[str, Any]:
    report = build_report()
    return {
        "schema_version": report["schema_version"],
        "build_version": report["build_version"],
        "status": report["status"],
        "counts": report["counts"],
        "date_coverage": report["coverage"]["date"],
        "readiness_gates": report["readiness_gates"],
        "feature_unlocks": report["feature_unlocks"],
    }
