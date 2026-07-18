"""APEX 14 Sprint 10.4: unified Decision Intelligence Center.

Read-only composition layer over immutable Sprint 10.1-10.3 artifacts. It does not
recompute confidence, change recommendations, or use future outcomes.
"""
from __future__ import annotations
from typing import Any

from . import decision_intelligence_core as core
from . import confidence_attribution_engine as attribution
from . import institutional_evidence_graph as graphs

VERSION = "14.0.10.4"
SCHEMA_VERSION = "apex.decision_intelligence_center.v1"


def _items(value: Any) -> list[Any]:
    if value is None: return []
    if isinstance(value, list): return value
    return [value]


def _quality(record: dict[str, Any], attr: dict[str, Any] | None, graph: dict[str, Any] | None) -> dict[str, Any]:
    decision = record.get("decision") or {}
    evidence = record.get("evidence") or []
    timeline = record.get("timeline") or []
    provenance = decision.get("evidence_and_provenance") or {}
    checks = {
        "evidence_completeness": min(100, 40 + min(len(evidence), 6) * 10),
        "data_quality": 100 if provenance else 60,
        "confidence_transparency": 100 if attr else 50,
        "conflict_visibility": 100 if attr and "negative" in (attr.get("totals") or {}) else 60,
        "risk_assessment": 100 if decision.get("risk_level") or record.get("risk_level") else 60,
        "timeline_coverage": min(100, 60 + min(len(timeline), 4) * 10),
        "graph_integrity": 100 if graph and graph.get("integrity_hash") else 50,
        "governance_compliance": 100 if record.get("integrity_hash") and record.get("explainability_id") else 50,
    }
    score = round(sum(checks.values()) / len(checks))
    return {"score": score, "grade": "A" if score >= 90 else ("B" if score >= 80 else ("C" if score >= 70 else "D")), "components": checks,
            "method": "Deterministic completeness and governance score; independent of trade outcome"}


def _split_evidence(record: dict[str, Any], attr: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    supporting=[]; conflicting=[]
    for e in record.get("evidence") or []:
        item={"label":e.get("category") or "EVIDENCE","detail":e.get("evidence") or {},"source_ref":e.get("evidence_id")}
        (supporting if e.get("polarity") == "SUPPORTING" else conflicting if e.get("polarity") == "CONFLICTING" else supporting).append(item)
    if attr:
        for d in attr.get("ranked_contributors") or []:
            item={"label":d.get("contributor") or "UNKNOWN","contribution":d.get("contribution"),"explanation":d.get("explanation")}
            (supporting if float(d.get("contribution") or 0) >= 0 else conflicting).append(item)
    return supporting, conflicting


def dashboard(identifier: str) -> dict[str, Any]:
    record = core.get(identifier)
    if record is None: return {"ok":False,"status":"UNAVAILABLE","error":"decision_not_found"}
    attr = attribution.explain(identifier)
    attr_data = attr if attr.get("ok") else None
    graph = graphs.explain(identifier)
    graph_data = graph if graph.get("ok") else None
    supporting, conflicting = _split_evidence(record, attr_data)
    decision = record.get("decision") or {}
    risk_items = _items(decision.get("risks"))
    invalidation = _items(decision.get("invalidation"))
    quality = _quality(record, attr_data, graph_data)
    summary = {
        "decision_id": record.get("decision_id"), "explainability_id": record.get("explainability_id"),
        "recommendation_id": record.get("recommendation_id"), "recommendation": record.get("recommendation"),
        "direction": record.get("direction"), "canonical_confidence": record.get("confidence"),
        "conviction": record.get("conviction"), "risk_level": record.get("risk_level"),
        "observed_at": record.get("observed_at"), "decision_quality": quality,
    }
    return {"ok":True,"status":"READY","schema_version":SCHEMA_VERSION,"build_version":VERSION,
            "summary":summary,"confidence":attr_data,"evidence_graph":graph_data,
            "supporting_evidence":supporting,"conflicting_evidence":conflicting,
            "risk":{"level":record.get("risk_level"),"drivers":risk_items},
            "invalidation":invalidation,"timeline":record.get("timeline") or [],
            "governance":{"decision_integrity_hash":record.get("integrity_hash"),"graph_integrity_hash":(graph_data or {}).get("integrity_hash"),
                          "schema_versions":{"center":SCHEMA_VERSION,"decision":record.get("schema_version"),"graph":(graph_data or {}).get("schema_version")},
                          "future_information_allowed":False,"production_effect":"NONE"},
            "limitations":["Read-only composition of immutable artifacts","No future outcomes in live review","Decision Quality Score does not use trade outcome","No recommendation or confidence mutation"]}


def summary(identifier: str) -> dict[str, Any]:
    out=dashboard(identifier)
    return out if not out.get("ok") else {"ok":True,"status":"READY","summary":out["summary"],"governance":out["governance"]}


def status() -> dict[str, Any]:
    return {"status":"READY","schema_version":SCHEMA_VERSION,"build_version":VERSION,
            "decision_mutation_enabled":False,"confidence_mutation_enabled":False,
            "future_information_allowed":False,"production_effect":"NONE"}
