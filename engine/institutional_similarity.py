"""APEX 13.0 Sprint 4 — evidence-backed institutional similarity intelligence.

Read-only research infrastructure. It never queries providers, never fabricates outcomes,
and never allows a comparison observed after the requested as-of cutoff.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import math
import os
import sqlite3
import uuid
from typing import Any, Dict, Iterable, Mapping, Optional

from . import institutional_evidence as evidence

VERSION = "13.0.0-sprint4"
SCHEMA_VERSION = 1
FEATURE_VERSION = "apex.institutional.features.v1"
DB_PATH = os.getenv("APEX_SIMILARITY_DB", os.path.join(os.path.dirname(os.path.dirname(__file__)), "apex_similarity.db"))

FEATURE_SCHEMA: Dict[str, Dict[str, Any]] = {
    "market_state": {"type": "categorical", "weight": 1.2},
    "market_regime": {"type": "categorical", "weight": 1.3},
    "strategy": {"type": "categorical", "weight": 1.1},
    "direction": {"type": "categorical", "weight": 1.0},
    "auction_state": {"type": "categorical", "weight": 1.1},
    "value_relationship": {"type": "categorical", "weight": 1.0},
    "profile_shape": {"type": "categorical", "weight": 0.8},
    "gamma_regime": {"type": "categorical", "weight": 1.1},
    "flow_bias": {"type": "categorical", "weight": 1.0},
    "breadth_bias": {"type": "categorical", "weight": 0.7},
    "trading_mode": {"type": "categorical", "weight": 1.0},
    "consensus_grade": {"type": "categorical", "weight": 1.1},
    "conviction_grade": {"type": "categorical", "weight": 1.0},
    "liquidity_grade": {"type": "categorical", "weight": 0.9},
    "risk_state": {"type": "categorical", "weight": 1.0},
    "confidence": {"type": "numeric", "weight": 1.0, "scale": 100.0},
    "consensus_percentage": {"type": "numeric", "weight": 1.0, "scale": 100.0},
    "conviction_score": {"type": "numeric", "weight": 1.0, "scale": 100.0},
    "execution_score": {"type": "numeric", "weight": 0.9, "scale": 100.0},
    "position_quality_score": {"type": "numeric", "weight": 0.9, "scale": 100.0},
    "readiness_score": {"type": "numeric", "weight": 0.8, "scale": 100.0},
    "expected_move_utilization": {"type": "numeric", "weight": 0.7, "scale": 2.0},
}


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
        CREATE TABLE IF NOT EXISTS similarity_schema(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS institutional_feature_vectors(
          vector_id TEXT PRIMARY KEY,
          recommendation_id TEXT NOT NULL UNIQUE,
          observed_at TEXT NOT NULL,
          feature_version TEXT NOT NULL,
          feature_hash TEXT NOT NULL,
          vector_json TEXT NOT NULL,
          provenance_json TEXT NOT NULL,
          source_package_hash TEXT NOT NULL,
          created_at TEXT NOT NULL,
          immutable INTEGER NOT NULL DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS idx_isim_time ON institutional_feature_vectors(observed_at);
        CREATE INDEX IF NOT EXISTS idx_isim_hash ON institutional_feature_vectors(feature_version,feature_hash);
        CREATE TABLE IF NOT EXISTS similarity_queries(
          query_id TEXT PRIMARY KEY,
          vector_id TEXT NOT NULL,
          as_of TEXT NOT NULL,
          top_k INTEGER NOT NULL,
          query_hash TEXT NOT NULL,
          result_count INTEGER NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_isim_query_time ON similarity_queries(created_at);
        """)
        conn.execute("INSERT OR IGNORE INTO similarity_schema VALUES(?,?)", (SCHEMA_VERSION, _now()))
    return {"ok": True, "schema_version": SCHEMA_VERSION, "feature_version": FEATURE_VERSION, "db_path": DB_PATH}


def _first(mapping: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", {}, []):
            return value
    return default


def _number(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def extract_features(package: Mapping[str, Any]) -> Dict[str, Any]:
    decision = package.get("canonical_decision") or {}
    snapshots = package.get("snapshots") or {}
    narrative = snapshots.get("narrative") or decision.get("market_narrative") or {}
    consensus = snapshots.get("consensus") or decision.get("institutional_consensus") or {}
    conviction = snapshots.get("conviction") or decision.get("conviction") or {}
    execution = snapshots.get("execution") or decision.get("execution") or {}
    position = snapshots.get("position_quality") or decision.get("position_quality") or {}
    liquidity = snapshots.get("liquidity") or decision.get("liquidity") or {}
    evidence_map = decision.get("evidence") or {}
    auction = evidence_map.get("auction") or {}
    profile = evidence_map.get("volume_profile") or {}
    gamma = evidence_map.get("gamma") or evidence_map.get("dealer_positioning") or {}
    flow = evidence_map.get("flow") or evidence_map.get("flow_tape") or {}
    breadth = evidence_map.get("breadth") or {}
    readiness = evidence_map.get("readiness") or evidence_map.get("morning_readiness") or {}
    expected = evidence_map.get("expected_move") or {}

    vector = {
        "market_state": _first(decision, "market_state", default=_first(narrative, "market_state", "state", default="UNAVAILABLE")),
        "market_regime": _first(decision, "market_regime", "regime", default=_first(narrative, "regime", default="UNAVAILABLE")),
        "strategy": _first(decision, "strategy", "action", default="UNAVAILABLE"),
        "direction": _first(decision, "direction", default=_first(consensus, "dominant_direction", default="NEUTRAL")),
        "auction_state": _first(auction, "state", "auction_state", "type", default="UNAVAILABLE"),
        "value_relationship": _first(auction, "value_relationship", "location", default="UNAVAILABLE"),
        "profile_shape": _first(profile, "shape", "profile_shape", default="UNAVAILABLE"),
        "gamma_regime": _first(gamma, "regime", "gamma_regime", "state", default="UNAVAILABLE"),
        "flow_bias": _first(flow, "bias", "direction", "state", default="UNAVAILABLE"),
        "breadth_bias": _first(breadth, "bias", "direction", "state", default="UNAVAILABLE"),
        "trading_mode": _first(readiness, "trading_mode", default=_first(execution, "trading_mode", default="UNAVAILABLE")),
        "consensus_grade": _first(consensus, "consensus_grade", "grade", default="UNAVAILABLE"),
        "conviction_grade": _first(conviction, "conviction_grade", "grade", "classification", default="UNAVAILABLE"),
        "liquidity_grade": _first(liquidity, "grade", "liquidity_grade", default="UNAVAILABLE"),
        "risk_state": _first(narrative, "risk_state", default="UNAVAILABLE"),
        "confidence": _number(_first(decision, "confidence", default=None)),
        "consensus_percentage": _number(_first(consensus, "agreement_percentage", "score", default=None)),
        "conviction_score": _number(_first(conviction, "conviction_score", "score", default=None)),
        "execution_score": _number(_first(execution, "execution_score", "score", default=None)),
        "position_quality_score": _number(_first(position, "position_quality_score", "score", default=None)),
        "readiness_score": _number(_first(readiness, "score", "readiness_score", default=None)),
        "expected_move_utilization": _number(_first(expected, "utilization", "utilization_ratio", default=None)),
    }
    return {key: vector.get(key) for key in FEATURE_SCHEMA}


def create_vector(recommendation_id: str) -> Dict[str, Any]:
    init_db()
    case = evidence.get(recommendation_id)
    if not case:
        return {"ok": False, "status": "UNAVAILABLE", "error": "evidence_package_not_found"}
    if case.get("status") != "READY":
        return {"ok": False, "status": "DEGRADED", "error": "evidence_package_not_ready"}
    package = case.get("package") or {}
    observed_at = package.get("captured_at") or (package.get("canonical_decision") or {}).get("timestamp")
    if not observed_at:
        return {"ok": False, "status": "DEGRADED", "error": "observation_timestamp_missing"}
    vector = extract_features(package)
    payload = {"feature_version": FEATURE_VERSION, "features": vector}
    feature_hash = _hash(payload)
    provenance = {
        "source": "INSTITUTIONAL_EVIDENCE_PACKAGE",
        "recommendation_id": recommendation_id,
        "evidence_package_id": case.get("package_id"),
        "source_package_hash": case.get("integrity_hash"),
        "build_version": VERSION,
    }
    with _conn() as conn:
        existing = conn.execute("SELECT * FROM institutional_feature_vectors WHERE recommendation_id=?", (recommendation_id,)).fetchone()
        if existing:
            return {"ok": True, "status": "READY", "created": False, **_row(existing)}
        vector_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO institutional_feature_vectors VALUES(?,?,?,?,?,?,?,?,?,1)",
            (vector_id, recommendation_id, observed_at, FEATURE_VERSION, feature_hash, _json(vector), _json(provenance), case.get("integrity_hash") or "", _now()),
        )
    return {"ok": True, "status": "READY", "created": True, "vector_id": vector_id, "recommendation_id": recommendation_id, "observed_at": observed_at, "feature_version": FEATURE_VERSION, "feature_hash": feature_hash, "features": vector, "provenance": provenance, "immutable": True}


def _row(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "vector_id": row["vector_id"], "recommendation_id": row["recommendation_id"],
        "observed_at": row["observed_at"], "feature_version": row["feature_version"],
        "feature_hash": row["feature_hash"], "features": _load(row["vector_json"]),
        "provenance": _load(row["provenance_json"]), "source_package_hash": row["source_package_hash"],
        "created_at": row["created_at"], "immutable": bool(row["immutable"]),
    }


def get_vector(identifier: str) -> Optional[Dict[str, Any]]:
    init_db()
    with _conn() as conn:
        row = conn.execute("SELECT * FROM institutional_feature_vectors WHERE vector_id=? OR recommendation_id=?", (identifier, identifier)).fetchone()
    return _row(row) if row else None


def create_all(limit: int = 500) -> Dict[str, Any]:
    evidence.init_db()
    created = existing = unavailable = 0
    with evidence._conn() as conn:  # canonical persisted packages; no provider access
        rows = conn.execute("SELECT recommendation_id FROM evidence_packages ORDER BY created_at LIMIT ?", (max(1, min(limit, 5000)),)).fetchall()
    for row in rows:
        result = create_vector(row["recommendation_id"])
        if result.get("created"): created += 1
        elif result.get("ok"): existing += 1
        else: unavailable += 1
    return {"ok": True, "status": "COLLECTING" if not rows else "READY", "processed": len(rows), "created": created, "existing": existing, "unavailable": unavailable}


def _similarity(a: Mapping[str, Any], b: Mapping[str, Any]) -> Dict[str, Any]:
    weighted = matched = 0.0
    comparisons = 0
    factors = []
    for name, spec in FEATURE_SCHEMA.items():
        av, bv = a.get(name), b.get(name)
        if av in (None, "", "UNAVAILABLE") or bv in (None, "", "UNAVAILABLE"):
            continue
        weight = float(spec["weight"])
        comparisons += 1
        weighted += weight
        if spec["type"] == "categorical":
            contribution = weight if str(av).upper() == str(bv).upper() else 0.0
            relation = "MATCH" if contribution else "DIFFERENT"
        else:
            scale = float(spec.get("scale", 100.0))
            contribution = weight * max(0.0, 1.0 - min(abs(float(av) - float(bv)) / scale, 1.0))
            relation = "CLOSE" if contribution >= weight * 0.75 else "DIFFERENT"
        matched += contribution
        factors.append({"feature": name, "base": av, "candidate": bv, "relation": relation, "contribution": round(contribution, 6), "weight": weight})
    score = round((matched / weighted) * 100.0, 4) if weighted else 0.0
    factors.sort(key=lambda item: (-item["contribution"], item["feature"]))
    return {"similarity_score": score, "eligible_feature_count": comparisons, "top_factors": factors[:8]}


def search(identifier: str, *, top_k: int = 10, as_of: Optional[str] = None) -> Dict[str, Any]:
    init_db()
    base = get_vector(identifier)
    if not base:
        return {"status": "UNAVAILABLE", "available": False, "reason": "vector_not_found", "matches": []}
    cutoff = as_of or base["observed_at"]
    # Fail closed: caller may narrow cutoff but never move it after the source observation.
    if cutoff > base["observed_at"]:
        cutoff = base["observed_at"]
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM institutional_feature_vectors WHERE vector_id<>? AND feature_version=? AND observed_at<? ORDER BY observed_at DESC LIMIT 2000",
            (base["vector_id"], base["feature_version"], cutoff),
        ).fetchall()
    matches = []
    for row in rows:
        candidate = _row(row)
        metric = _similarity(base["features"], candidate["features"])
        matches.append({**candidate, **metric, "outcome_analytics": {"status": "INSUFFICIENT_HISTORY", "available": False}})
    matches.sort(key=lambda item: (-item["similarity_score"], item["observed_at"], item["vector_id"]))
    matches = matches[:max(1, min(int(top_k), 100))]
    query_hash = _hash({"vector_id": base["vector_id"], "as_of": cutoff, "top_k": top_k, "feature_version": base["feature_version"]})
    with _conn() as conn:
        conn.execute("INSERT INTO similarity_queries VALUES(?,?,?,?,?,?,?)", (str(uuid.uuid4()), base["vector_id"], cutoff, int(top_k), query_hash, len(matches), _now()))
    return {
        "status": "READY" if matches else "COLLECTING", "available": True,
        "vector": base, "as_of": cutoff, "look_ahead_guard": "ENFORCED",
        "matches": matches, "match_count": len(matches),
        "outcome_analytics_status": "INSUFFICIENT_HISTORY",
        "limitations": ["Similarity is descriptive research only.", "No outcome performance is reported without real eligible graded history."],
        "build_version": VERSION,
    }


def schema() -> Dict[str, Any]:
    return {"status": "READY", "feature_version": FEATURE_VERSION, "schema_version": SCHEMA_VERSION, "features": FEATURE_SCHEMA, "look_ahead_guard": "ENFORCED", "build_version": VERSION}


def status() -> Dict[str, Any]:
    init_db()
    with _conn() as conn:
        row = conn.execute("SELECT COUNT(*) n, MIN(observed_at) first_at, MAX(observed_at) last_at, COUNT(DISTINCT feature_hash) unique_n FROM institutional_feature_vectors").fetchone()
    count = int(row["n"] or 0)
    return {
        "status": "COLLECTING" if count == 0 else "READY", "vector_count": count,
        "unique_vector_count": int(row["unique_n"] or 0),
        "date_coverage": {"start": row["first_at"], "end": row["last_at"]},
        "feature_version": FEATURE_VERSION, "outcome_analytics_status": "INSUFFICIENT_HISTORY",
        "research_only": True, "automatic_trading_effect": False, "build_version": VERSION,
    }
