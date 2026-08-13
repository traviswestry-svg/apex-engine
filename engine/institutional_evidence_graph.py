"""APEX 14 Sprint 10.3: immutable Institutional Evidence Graph.

Builds an explorable graph only from Sprint 10.1 frozen decision-time records and
Sprint 10.2 preserved attribution. It never changes recommendations, confidence,
risk, execution, or production governance.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import sqlite3
import uuid
from typing import Any

from . import institutional_governance as gov
from . import decision_intelligence_core as core
from . import confidence_attribution_engine as attribution

VERSION = "14.0.10.3"
SCHEMA_VERSION = "apex.institutional_evidence_graph.v1"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _json(v: Any) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), default=str)


def _load(v: Any, default: Any = None) -> Any:
    try:
        return json.loads(v) if isinstance(v, str) else v
    except Exception:
        return {} if default is None else default


def _conn():
    c = sqlite3.connect(gov.DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init_db() -> dict[str, Any]:
    core.init_db(); attribution.init_db()
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS institutional_evidence_graphs(
          graph_id TEXT PRIMARY KEY,
          decision_id TEXT NOT NULL UNIQUE,
          explainability_id TEXT NOT NULL,
          schema_version TEXT NOT NULL,
          engine_version TEXT NOT NULL,
          node_count INTEGER NOT NULL,
          edge_count INTEGER NOT NULL,
          graph_json TEXT NOT NULL,
          limitations_json TEXT NOT NULL,
          integrity_hash TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(decision_id) REFERENCES decision_intelligence_records(decision_id)
        );
        CREATE INDEX IF NOT EXISTS idx_evidence_graph_created ON institutional_evidence_graphs(created_at);
        """)
    return {"ok": True, "status": "READY", "schema_version": SCHEMA_VERSION, "build_version": VERSION}


def _node(node_id: str, kind: str, label: str, payload: Any, *, polarity: str = "OBSERVED", source_ref: str | None = None) -> dict[str, Any]:
    return {"node_id": node_id, "kind": kind, "label": label, "polarity": polarity, "source_ref": source_ref, "payload": payload}


def _build(record: dict[str, Any]) -> dict[str, Any]:
    d = record.get("decision") or {}
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    root = f"decision:{record['decision_id']}"
    nodes.append(_node(root, "DECISION", str(d.get("action") or record.get("recommendation") or "NO_TRADE"), {
        "recommendation": record.get("recommendation"), "direction": record.get("direction"),
        "canonical_confidence": record.get("confidence"), "conviction": record.get("conviction"),
        "risk_level": record.get("risk_level"), "observed_at": record.get("observed_at")
    }, source_ref=record["decision_id"]))

    for e in sorted(record.get("evidence") or [], key=lambda x: (str(x.get("category")), str(x.get("evidence_id")))):
        nid = f"evidence:{e['evidence_id']}"
        nodes.append(_node(nid, "EVIDENCE", str(e.get("category") or "EVIDENCE"), e.get("evidence") or {}, polarity=str(e.get("polarity") or "OBSERVED"), source_ref=e["evidence_id"]))
        edges.append({"edge_id": f"edge:{nid}->{root}", "from": nid, "to": root, "relation": "SUPPORTS_DECISION" if e.get("polarity") == "SUPPORTING" else ("CONFLICTS_WITH_DECISION" if e.get("polarity") == "CONFLICTING" else "INFORMS_DECISION")})

    for c in sorted(record.get("contributions") or [], key=lambda x: str(x.get("contribution_id"))):
        nid = f"contribution:{c['contribution_id']}"
        value = float(c.get("contribution") or 0.0)
        polarity = "SUPPORTING" if value > 0 else ("CONFLICTING" if value < 0 else "NEUTRAL")
        nodes.append(_node(nid, "CONTRIBUTION", str(c.get("contributor") or "UNKNOWN"), {"contribution": value, "direction": c.get("direction"), "reliability": c.get("reliability"), "freshness": c.get("freshness"), "explanation": c.get("explanation")}, polarity=polarity, source_ref=c["contribution_id"]))
        edges.append({"edge_id": f"edge:{nid}->{root}", "from": nid, "to": root, "relation": "INCREASES_CONFIDENCE" if value > 0 else ("REDUCES_CONFIDENCE" if value < 0 else "NEUTRAL_TO_CONFIDENCE")})

    for group, relation in (("risks", "INCREASES_RISK"), ("invalidation", "INVALIDATES_IF_TRUE")):
        vals = d.get(group) or []
        if isinstance(vals, dict): vals = [vals]
        for i, value in enumerate(vals if isinstance(vals, list) else []):
            nid = f"{group}:{i}:{record['decision_id']}"
            nodes.append(_node(nid, group[:-1].upper() if group.endswith('s') else group.upper(), group.upper(), value, polarity="CONFLICTING" if group == "risks" else "BOUNDARY", source_ref=f"canonical_decision.{group}[{i}]"))
            edges.append({"edge_id": f"edge:{nid}->{root}", "from": nid, "to": root, "relation": relation})

    provenance = d.get("evidence_and_provenance") or {}
    pnid = f"provenance:{record['decision_id']}"
    nodes.append(_node(pnid, "PROVENANCE", "Decision provenance", provenance, source_ref="canonical_decision.evidence_and_provenance"))
    edges.append({"edge_id": f"edge:{pnid}->{root}", "from": pnid, "to": root, "relation": "PROVES_ORIGIN"})
    return {"root_node_id": root, "nodes": nodes, "edges": edges}


def create(identifier: str, *, actor: str = "SYSTEM") -> dict[str, Any]:
    init_db()
    record = core.get(identifier)
    if record is None:
        return {"ok": False, "status": "UNAVAILABLE", "error": "decision_not_found"}
    with _conn() as c:
        existing = c.execute("SELECT graph_id,integrity_hash FROM institutional_evidence_graphs WHERE decision_id=?", (record["decision_id"],)).fetchone()
    if existing:
        return {"ok": True, "status": "IMMUTABLE_EXISTS", "created": False, "graph_id": existing["graph_id"], "integrity_hash": existing["integrity_hash"]}
    graph = _build(record)
    gid, created = str(uuid.uuid4()), _now()
    limitations = [
        "Graph contains only frozen decision-time evidence and preserved contributors",
        "No missing causal link is inferred",
        "No future outcome or post-hoc explanation is allowed",
        "Graph construction has no production effect",
    ]
    identity = {"graph_id": gid, "decision_id": record["decision_id"], "explainability_id": record["explainability_id"], "graph": graph, "schema_version": SCHEMA_VERSION}
    ih = hashlib.sha256(_json(identity).encode()).hexdigest()
    with _conn() as c:
        c.execute("INSERT INTO institutional_evidence_graphs VALUES(?,?,?,?,?,?,?,?,?,?,?)", (gid, record["decision_id"], record["explainability_id"], SCHEMA_VERSION, VERSION, len(graph["nodes"]), len(graph["edges"]), _json(graph), _json(limitations), ih, created))
    gov.audit("CREATE_EVIDENCE_GRAPH", "institutional_evidence_graph", gid, new={"decision_id": record["decision_id"], "integrity_hash": ih}, actor=actor, explanation="Immutable graph created from frozen decision-time records")
    return {"ok": True, "status": "CREATED", "created": True, "graph_id": gid, "integrity_hash": ih, "graph": graph}


def get(identifier: str) -> dict[str, Any] | None:
    init_db(); record = core.get(identifier)
    if record is None: return None
    with _conn() as c:
        row = c.execute("SELECT * FROM institutional_evidence_graphs WHERE decision_id=?", (record["decision_id"],)).fetchone()
    if row is None: return None
    out = dict(row); out["graph"] = _load(out.pop("graph_json")); out["limitations"] = _load(out.pop("limitations_json"), [])
    return out


def explain(identifier: str) -> dict[str, Any]:
    existing = get(identifier)
    if existing: return {"ok": True, "status": "READY", **existing}
    result = create(identifier)
    if not result.get("ok"): return result
    return {"ok": True, "status": "READY", "graph_id": result["graph_id"], "integrity_hash": result["integrity_hash"], "graph": result["graph"]}


def list_graphs(limit: int = 100) -> list[dict[str, Any]]:
    init_db()
    with _conn() as c:
        rows = c.execute("SELECT graph_id,decision_id,explainability_id,node_count,edge_count,integrity_hash,created_at FROM institutional_evidence_graphs ORDER BY created_at DESC LIMIT ?", (max(1,min(int(limit),1000)),)).fetchall()
    return [dict(r) for r in rows]


def status() -> dict[str, Any]:
    init_db()
    with _conn() as c: count = c.execute("SELECT COUNT(*) n FROM institutional_evidence_graphs").fetchone()["n"]
    return {"status":"READY","schema_version":SCHEMA_VERSION,"build_version":VERSION,"graph_count":count,"post_hoc_inference_enabled":False,"future_information_allowed":False,"recommendation_mutation_enabled":False,"confidence_mutation_enabled":False,"production_effect":"NONE"}
