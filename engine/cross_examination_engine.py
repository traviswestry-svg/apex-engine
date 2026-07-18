"""APEX 14 Sprint 10.6: Institutional Cross-Examination Engine.

Deterministically assembles evidence-backed answers from immutable Decision
Intelligence artifacts. It performs no free-form inference, confidence
recalculation, recommendation mutation, or look-ahead analysis.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sqlite3
import uuid
from typing import Any

from . import institutional_governance as gov
from . import decision_intelligence_center as dic
from . import institutional_replay_2 as replay2

VERSION = "14.0.10.6"
SCHEMA_VERSION = "apex.cross_examination.v1"
EVIDENCE_NOT_AVAILABLE = "Evidence Not Available"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _load(value: Any, default: Any = None) -> Any:
    if value in (None, ""):
        return [] if default == [] else ({} if default is None else default)
    try:
        return json.loads(value)
    except Exception:
        return [] if default == [] else ({} if default is None else default)


def _conn():
    c = sqlite3.connect(gov.DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init_db() -> dict[str, Any]:
    gov.init_db()
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS cross_examination_records(
          examination_id TEXT PRIMARY KEY,
          decision_id TEXT NOT NULL,
          explainability_id TEXT NOT NULL,
          question TEXT NOT NULL,
          normalized_question TEXT NOT NULL,
          intent TEXT NOT NULL,
          answer_json TEXT NOT NULL,
          evidence_refs_json TEXT NOT NULL,
          schema_version TEXT NOT NULL,
          engine_version TEXT NOT NULL,
          integrity_hash TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(decision_id, normalized_question),
          FOREIGN KEY(decision_id) REFERENCES decision_intelligence_records(decision_id)
        );
        CREATE INDEX IF NOT EXISTS idx_cross_exam_decision ON cross_examination_records(decision_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_cross_exam_created ON cross_examination_records(created_at);
        """)
    return {"ok": True, "schema_version": SCHEMA_VERSION, "build_version": VERSION}


def normalize_question(question: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9%+\- ]", " ", str(question or "").lower())).strip()


def route_question(question: str) -> str:
    q = normalize_question(question)
    if not q:
        return "UNSUPPORTED"
    if any(x in q for x in ("compare", "difference between", "versus", " vs ")):
        return "COMPARISON"
    if any(x in q for x in ("what changed", "when did", "timeline", "at 9", "at 10", "evolve")):
        return "TIMELINE"
    if any(x in q for x in ("which version", "production", "canary", "release", "schema", "governance", "hash")):
        return "GOVERNANCE"
    if any(x in q for x in ("what would", "invalidate", "invalidation", "change the decision", "become calls", "become puts")):
        return "INVALIDATION"
    if any(x in q for x in ("risk", "danger", "penalty", "penalties")):
        return "RISK"
    if any(x in q for x in ("why not", "argued against", "conflict", "opposing", "against the trade")):
        return "CONFLICT"
    if any(x in q for x in ("confidence", "conviction", "lowered", "reduced", "only ")):
        return "CONFIDENCE"
    if any(x in q for x in ("why", "support", "evidence", "reason", "recommended")):
        return "RATIONALE"
    if any(x in q for x in ("replay", "reconstruct")):
        return "REPLAY"
    return "UNSUPPORTED"


def _refs(package: dict[str, Any], *, include_timeline: bool = False) -> dict[str, Any]:
    refs = {
        "decision_id": package["summary"].get("decision_id"),
        "explainability_id": package["summary"].get("explainability_id"),
        "decision_integrity_hash": package.get("governance", {}).get("decision_integrity_hash"),
        "graph_integrity_hash": package.get("governance", {}).get("graph_integrity_hash"),
        "evidence_ids": sorted({x.get("source_ref") for x in package.get("supporting_evidence", []) + package.get("conflicting_evidence", []) if x.get("source_ref")}),
    }
    if include_timeline:
        refs["timeline_ids"] = [x.get("timeline_event_id") for x in package.get("timeline", []) if x.get("timeline_event_id")]
    return refs


def _unavailable(intent: str, package: dict[str, Any], detail: str) -> tuple[dict[str, Any], dict[str, Any]]:
    answer = {"status": "EVIDENCE_NOT_AVAILABLE", "headline": EVIDENCE_NOT_AVAILABLE, "detail": detail, "intent": intent, "no_inference_generated": True}
    return answer, _refs(package)


def _answer(package: dict[str, Any], intent: str, question: str) -> tuple[dict[str, Any], dict[str, Any]]:
    summary = package["summary"]
    if intent == "RATIONALE":
        support = package.get("supporting_evidence") or []
        if not support:
            return _unavailable(intent, package, "No immutable supporting evidence exists for this decision.")
        return ({"status": "ANSWERED", "intent": intent, "headline": f"{summary.get('recommendation') or 'Decision'} was supported by {len(support)} immutable evidence items.",
                 "recommendation": summary.get("recommendation"), "canonical_confidence": summary.get("canonical_confidence"),
                 "supporting_evidence": support, "conflicting_evidence": package.get("conflicting_evidence") or [],
                 "decision_quality": summary.get("decision_quality")}, _refs(package))
    if intent == "CONFIDENCE":
        conf = package.get("confidence")
        if not conf:
            return _unavailable(intent, package, "No immutable confidence-attribution analysis exists.")
        return ({"status": "ANSWERED", "intent": intent, "headline": f"Canonical confidence remained {summary.get('canonical_confidence')}; contributors were reported without recalculation.",
                 "canonical_confidence": summary.get("canonical_confidence"), "deterministic_total": conf.get("deterministic_total"),
                 "totals": conf.get("totals"), "ranked_contributors": conf.get("ranked_contributors"),
                 "strongest_support": conf.get("strongest_support"), "strongest_conflict": conf.get("strongest_conflict"),
                 "reconciliation_status": conf.get("reconciliation_status")}, _refs(package))
    if intent == "CONFLICT":
        conflict = package.get("conflicting_evidence") or []
        if not conflict:
            return _unavailable(intent, package, "No immutable conflicting evidence exists for this decision.")
        return ({"status": "ANSWERED", "intent": intent, "headline": f"{len(conflict)} immutable items argued against or reduced conviction.", "conflicting_evidence": conflict}, _refs(package))
    if intent == "RISK":
        risk = package.get("risk") or {}
        drivers = risk.get("drivers") or []
        if not drivers and not risk.get("level"):
            return _unavailable(intent, package, "No immutable risk assessment exists.")
        return ({"status": "ANSWERED", "intent": intent, "headline": f"Risk was recorded as {risk.get('level') or 'UNAVAILABLE'}.", "risk": risk, "invalidation": package.get("invalidation") or []}, _refs(package))
    if intent == "INVALIDATION":
        invalidation = package.get("invalidation") or []
        if not invalidation:
            return _unavailable(intent, package, "No immutable invalidation conditions exist; no counterfactual was invented.")
        return ({"status": "ANSWERED", "intent": intent, "headline": "The stored invalidation conditions define what would negate the decision.", "invalidation": invalidation, "counterfactual_inference_generated": False}, _refs(package))
    if intent == "TIMELINE":
        timeline = package.get("timeline") or []
        if not timeline:
            return _unavailable(intent, package, "No immutable decision timeline exists.")
        return ({"status": "ANSWERED", "intent": intent, "headline": f"The decision contains {len(timeline)} ordered timeline events.", "timeline": timeline}, _refs(package, include_timeline=True))
    if intent == "GOVERNANCE":
        govdata = package.get("governance") or {}
        if not govdata:
            return _unavailable(intent, package, "No immutable governance metadata exists.")
        return ({"status": "ANSWERED", "intent": intent, "headline": "The decision is traceable through immutable governance identifiers and hashes.", "governance": govdata}, _refs(package))
    if intent == "REPLAY":
        rep = replay2.get(summary["decision_id"])
        if not rep.get("ok"):
            return _unavailable(intent, package, "Institutional Replay 2.0 has not been built for this decision.")
        return ({"status": "ANSWERED", "intent": intent, "headline": f"Replay contains {rep.get('frame_count')} decision-time frames with look-ahead blocked.", "replay_id": rep.get("replay_id"), "replay": rep.get("replay"), "limitations": rep.get("limitations")}, {**_refs(package), "replay_id": rep.get("replay_id"), "replay_integrity_hash": rep.get("integrity_hash")})
    return _unavailable(intent, package, "The question is outside the deterministic question taxonomy.")


def ask(identifier: str, question: str, actor: str = "SYSTEM", persist: bool = True) -> dict[str, Any]:
    init_db()
    package = dic.dashboard(identifier)
    if not package.get("ok"):
        return {"ok": False, "status": "UNAVAILABLE", "error": "decision_not_found"}
    normalized = normalize_question(question)
    if not normalized:
        return {"ok": False, "status": "INVALID_REQUEST", "error": "question_required"}
    intent = route_question(question)
    answer, refs = _answer(package, intent, question)
    decision_id = package["summary"]["decision_id"]
    with _conn() as c:
        existing = c.execute("SELECT * FROM cross_examination_records WHERE decision_id=? AND normalized_question=?", (decision_id, normalized)).fetchone()
    if existing:
        row = dict(existing)
        return {"ok": True, "status": "IMMUTABLE_EXISTS", "created": False, "examination_id": row["examination_id"], "decision_id": decision_id,
                "intent": row["intent"], "question": row["question"], "answer": _load(row["answer_json"]), "evidence_refs": _load(row["evidence_refs_json"]),
                "integrity_hash": row["integrity_hash"], "created_at": row["created_at"], "production_effect": "NONE"}
    payload = {"decision_id": decision_id, "normalized_question": normalized, "intent": intent, "answer": answer, "evidence_refs": refs,
               "schema_version": SCHEMA_VERSION, "engine_version": VERSION}
    integrity_hash = hashlib.sha256(_json(payload).encode()).hexdigest()
    examination_id = str(uuid.uuid4())
    created_at = _now()
    if persist:
        with _conn() as c:
            c.execute("INSERT INTO cross_examination_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (examination_id, decision_id, package["summary"]["explainability_id"], question, normalized, intent, _json(answer), _json(refs), SCHEMA_VERSION, VERSION, integrity_hash, created_at))
        gov.audit("CROSS_EXAMINE_DECISION", "cross_examination", examination_id, new={"decision_id": decision_id, "intent": intent, "integrity_hash": integrity_hash}, actor=actor, explanation="Deterministic evidence-backed cross-examination recorded")
    return {"ok": True, "status": "CREATED" if persist else "ANSWERED", "created": bool(persist), "examination_id": examination_id,
            "decision_id": decision_id, "intent": intent, "question": question, "answer": answer, "evidence_refs": refs,
            "integrity_hash": integrity_hash, "created_at": created_at, "future_information_allowed": False, "production_effect": "NONE"}


def compare(identifier_a: str, identifier_b: str) -> dict[str, Any]:
    a, b = dic.dashboard(identifier_a), dic.dashboard(identifier_b)
    if not a.get("ok") or not b.get("ok"):
        return {"ok": False, "status": "UNAVAILABLE", "error": "decision_not_found"}
    sa, sb = a["summary"], b["summary"]
    support_a = {str(x.get("label")) for x in a.get("supporting_evidence") or []}
    support_b = {str(x.get("label")) for x in b.get("supporting_evidence") or []}
    comparison = {
        "decision_a": sa, "decision_b": sb,
        "recommendation_changed": sa.get("recommendation") != sb.get("recommendation"),
        "confidence_delta": (sb.get("canonical_confidence") or 0) - (sa.get("canonical_confidence") or 0),
        "risk_changed": sa.get("risk_level") != sb.get("risk_level"),
        "new_supporting_evidence": sorted(support_b - support_a),
        "lost_supporting_evidence": sorted(support_a - support_b),
        "decision_quality_delta": (sb.get("decision_quality", {}).get("score") or 0) - (sa.get("decision_quality", {}).get("score") or 0),
        "governance": {"a": a.get("governance"), "b": b.get("governance")},
    }
    ih = hashlib.sha256(_json(comparison).encode()).hexdigest()
    return {"ok": True, "status": "READY", "comparison": comparison, "integrity_hash": ih, "future_information_allowed": False, "production_effect": "NONE"}


def history(identifier: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    init_db()
    params: list[Any] = []
    where = ""
    if identifier:
        package = dic.dashboard(identifier)
        if not package.get("ok"):
            return []
        where = "WHERE decision_id=?"
        params.append(package["summary"]["decision_id"])
    params.append(max(1, min(int(limit), 1000)))
    with _conn() as c:
        rows = c.execute(f"SELECT examination_id,decision_id,explainability_id,question,intent,answer_json,evidence_refs_json,integrity_hash,created_at FROM cross_examination_records {where} ORDER BY created_at DESC LIMIT ?", params).fetchall()
    out = []
    for row in rows:
        d = dict(row); d["answer"] = _load(d.pop("answer_json")); d["evidence_refs"] = _load(d.pop("evidence_refs_json")); out.append(d)
    return out


def questions() -> list[dict[str, str]]:
    return [
        {"intent": "RATIONALE", "example": "Why did APEX recommend this?"},
        {"intent": "CONFIDENCE", "example": "Why is confidence only 74?"},
        {"intent": "CONFLICT", "example": "What argued against the trade?"},
        {"intent": "RISK", "example": "Why was risk elevated?"},
        {"intent": "INVALIDATION", "example": "What would invalidate this decision?"},
        {"intent": "TIMELINE", "example": "What changed during the decision?"},
        {"intent": "GOVERNANCE", "example": "Which version produced this?"},
        {"intent": "REPLAY", "example": "Replay how this decision evolved."},
    ]


def status() -> dict[str, Any]:
    init_db()
    with _conn() as c:
        count = c.execute("SELECT COUNT(*) n FROM cross_examination_records").fetchone()["n"]
    return {"status": "READY", "schema_version": SCHEMA_VERSION, "build_version": VERSION, "examination_count": count,
            "question_routing": "DETERMINISTIC", "free_form_inference_enabled": False, "future_information_allowed": False,
            "decision_mutation_enabled": False, "confidence_mutation_enabled": False, "production_effect": "NONE"}
