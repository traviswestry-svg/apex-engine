"""APEX 43 — Institutional Intelligence Mesh.

Deterministic evidence aggregation only. This module never places orders and
never replaces an upstream engine. It converts heterogeneous engine outputs
into a transparent consensus, conflict, and confidence contract.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
import math
import time

MESH_VERSION = "43.5"

@dataclass(frozen=True)
class EvidenceNode:
    engine: str
    label: str
    direction: str
    score: float
    weight: float
    freshness: float
    reliability: float
    contribution: float
    reason: str
    available: bool = True

ENGINE_SPECS: Tuple[Tuple[str, Tuple[str, ...], float], ...] = (
    ("gamma", ("gamma", "gex", "dealer_positioning"), 1.15),
    ("auction", ("auction", "auction_state", "volume_profile"), 1.10),
    ("volume_profile", ("volume_profile", "profile"), 1.00),
    ("order_flow", ("flow", "options_flow", "order_flow"), 1.15),
    ("momentum", ("momentum", "micro_execution", "subminute"), 1.05),
    ("market_structure", ("structure", "market_structure", "market_state"), 1.10),
    ("expected_move", ("expected_move", "levels"), 0.75),
    ("cross_asset", ("cross_asset", "lead_lag", "internals"), 0.80),
)

BULL = ("CALL", "BULL", "BUY", "LONG", "UP", "POSITIVE", "RISING", "SUPPORT", "ACCEPTANCE_ABOVE")
BEAR = ("PUT", "BEAR", "SELL", "SHORT", "DOWN", "NEGATIVE", "FALLING", "RESISTANCE", "ACCEPTANCE_BELOW")


def _get(obj: Mapping[str, Any], path: str) -> Any:
    cur: Any = obj
    for part in path.split("."):
        if not isinstance(cur, Mapping) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _first(obj: Mapping[str, Any], paths: Iterable[str]) -> Any:
    for path in paths:
        value = _get(obj, path)
        if value not in (None, "", [], {}):
            return value
    return None


def _direction(value: Any) -> str:
    text = str(value or "").upper().replace("-", "_").replace(" ", "_")
    if any(token in text for token in BULL):
        return "CALL"
    if any(token in text for token in BEAR):
        return "PUT"
    return "NEUTRAL"


def _bounded(value: Any, default: float = 0.65) -> float:
    try:
        n = float(value)
        if n > 1.0:
            n /= 100.0
        return max(0.0, min(1.0, n))
    except (TypeError, ValueError):
        return default


def _freshness(payload: Mapping[str, Any], now: float) -> float:
    fresh = _first(payload, ("freshness", "data_fresh", "is_fresh"))
    if isinstance(fresh, bool):
        return 1.0 if fresh else 0.45
    ts = _first(payload, ("timestamp", "updated_at", "as_of", "generated_at"))
    try:
        age = max(0.0, now - float(ts))
        return max(0.25, math.exp(-age / 180.0))
    except (TypeError, ValueError):
        return 0.80


def _payload(snapshot: Mapping[str, Any], aliases: Tuple[str, ...]) -> Tuple[Any, str]:
    for alias in aliases:
        value = snapshot.get(alias)
        if value not in (None, "", [], {}):
            return value, alias
    return None, aliases[0]


def _node(snapshot: Mapping[str, Any], engine: str, aliases: Tuple[str, ...], weight: float, now: float) -> EvidenceNode:
    raw, source = _payload(snapshot, aliases)
    if raw is None:
        return EvidenceNode(engine, source, "NEUTRAL", 0.0, weight, 0.0, 0.0, 0.0, "No usable evidence", False)
    data = raw if isinstance(raw, Mapping) else {"value": raw}
    directional = _first(data, ("direction", "bias", "regime", "state", "signal", "action", "decision", "value"))
    direction = _direction(directional)
    score = _bounded(_first(data, ("confidence", "score", "strength", "probability", "quality")), 0.62)
    reliability = _bounded(_first(data, ("reliability", "calibration", "historical_accuracy")), 0.78)
    freshness = _freshness(data, now)
    signed = 1.0 if direction == "CALL" else -1.0 if direction == "PUT" else 0.0
    contribution = signed * score * reliability * freshness * weight
    reason = str(_first(data, ("reason", "summary", "narrative", "label", "state", "regime", "bias", "value")) or directional or "Evidence available")
    return EvidenceNode(engine, source, direction, round(score, 4), weight, round(freshness, 4), round(reliability, 4), round(contribution, 4), reason[:240], True)


def build_intelligence_mesh(snapshot: Optional[Mapping[str, Any]], now: Optional[float] = None, calibration: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    snapshot = snapshot or {}
    calibration = calibration or {}
    now = float(now if now is not None else time.time())
    disabled = {str(x) for x in calibration.get("disabled_engines", []) if x}
    custom_weights = calibration.get("weights", {}) if isinstance(calibration.get("weights"), Mapping) else {}
    specs = [(name, aliases, float(custom_weights.get(name, weight))) for name, aliases, weight in ENGINE_SPECS if name not in disabled]
    nodes = [_node(snapshot, name, aliases, weight, now) for name, aliases, weight in specs]
    disabled_nodes = [EvidenceNode(name, aliases[0], "NEUTRAL", 0.0, float(custom_weights.get(name, weight)), 0.0, 0.0, 0.0, "Disabled in temporary calibration sandbox", False) for name, aliases, weight in ENGINE_SPECS if name in disabled]
    nodes.extend(disabled_nodes)
    active = [n for n in nodes if n.available]
    directional = [n for n in active if n.direction in ("CALL", "PUT")]
    call_weight = sum(max(0.0, n.contribution) for n in directional)
    put_weight = sum(abs(min(0.0, n.contribution)) for n in directional)
    total = call_weight + put_weight
    coverage = len(active) / max(1, len(ENGINE_SPECS))
    agreement = (max(call_weight, put_weight) / total) if total else 0.0
    conflict = (min(call_weight, put_weight) / total) if total else 0.0
    net = (call_weight - put_weight) / total if total else 0.0
    pre_penalty_confidence = 100.0 * agreement * (0.55 + 0.45 * coverage)
    conflict_penalty = pre_penalty_confidence * 0.55 * conflict
    confidence = pre_penalty_confidence - conflict_penalty
    confidence = max(0.0, min(99.0, confidence))

    min_engines = max(1, int(calibration.get("min_engines", 3)))
    min_agreement = max(0.0, min(1.0, float(calibration.get("min_agreement", 0.58))))
    max_conflict = max(0.0, min(1.0, float(calibration.get("max_conflict", 0.34))))
    min_confidence = max(0.0, min(99.0, float(calibration.get("min_confidence", 58))))
    reasons: List[str] = []
    if len(active) < min_engines:
        decision = "WAIT"
        reasons.append("Insufficient engine coverage")
    elif total == 0 or agreement < min_agreement:
        decision = "WAIT"
        reasons.append("Directional consensus is below threshold")
    elif conflict > max_conflict:
        decision = "WAIT"
        reasons.append("Material cross-engine conflict")
    elif confidence < min_confidence:
        decision = "WAIT"
        reasons.append("Governed confidence threshold not met")
    else:
        decision = "CALL" if net > 0 else "PUT"
        reasons.append("Weighted institutional consensus established")

    supporting = sorted((n for n in directional if n.direction == decision), key=lambda n: abs(n.contribution), reverse=True)
    opposing = sorted((n for n in directional if n.direction != decision), key=lambda n: abs(n.contribution), reverse=True)
    if decision == "WAIT":
        supporting = sorted(directional, key=lambda n: abs(n.contribution), reverse=True)[:3]

    return {
        "ok": True,
        "version": MESH_VERSION,
        "decision": decision,
        "confidence": round(confidence, 1),
        "pre_penalty_confidence": round(pre_penalty_confidence, 1),
        "conflict_penalty": round(conflict_penalty, 1),
        "coverage": round(coverage * 100.0, 1),
        "agreement": round(agreement * 100.0, 1),
        "conflict": round(conflict * 100.0, 1),
        "net_score": round(net, 4),
        "governed": True,
        "broker_action": "NONE",
        "reasons": reasons,
        "supporting_engines": [n.engine for n in supporting[:4]],
        "opposing_engines": [n.engine for n in opposing[:4]],
        "nodes": [asdict(n) for n in nodes],
        "diagnostics": {
            "evaluated_at": now,
            "active_engines": len(active),
            "directional_engines": len(directional),
            "call_weight": round(call_weight, 4),
            "put_weight": round(put_weight, 4),
            "thresholds": {
                "min_engines": min_engines,
                "min_agreement": round(min_agreement, 4),
                "max_conflict": round(max_conflict, 4),
                "min_confidence": round(min_confidence, 1),
            },
            "temporary_calibration": bool(calibration),
            "disabled_engines": sorted(disabled),
        },
    }
