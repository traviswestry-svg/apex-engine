"""APEX 25.0 — Institutional Decision Integrity Engine.

Read-only, deterministic decision-governance layer. It does not create a new
market signal. It audits the evidence already produced by APEX, distinguishes
missing/stale/failed evidence from neutral evidence, applies an advisory
confidence ceiling, and returns an explainable institutional decision record.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Mapping, Optional

VERSION = "25.0.0_INSTITUTIONAL_DECISION_INTEGRITY"
SCHEMA_VERSION = "apex.decision_integrity.v250.v1"

DEFAULT_MAX_AGE_SECONDS = {
    "market_state": 90,
    "institutional_intelligence": 120,
    "flow": 120,
    "dealer_positioning": 300,
    "multi_timeframe": 600,
    "market_memory": 86400,
    "similarity": 86400,
    "calibration": 86400,
}

SOURCE_ALIASES = {
    "market_state": ("market_state",),
    "institutional_intelligence": ("institutional_intelligence",),
    "flow": ("flow_intelligence", "flow", "flow_tape"),
    "dealer_positioning": ("dealer_positioning", "dealer", "gamma"),
    "multi_timeframe": ("multi_timeframe",),
    "market_memory": ("market_memory", "memory"),
    "similarity": ("historical_similarity", "similarity"),
    "calibration": ("confidence_calibration", "calibration"),
}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso_now() -> str:
    return _now().isoformat()


def _float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _upper(value: Any) -> str:
    return str(value or "").strip().upper()


def _parse_time(value: Any) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def _first_mapping(payload: Mapping[str, Any], aliases: tuple[str, ...]) -> tuple[str, Mapping[str, Any]]:
    for alias in aliases:
        value = payload.get(alias)
        if isinstance(value, Mapping):
            return alias, value
    return aliases[0], {}


def _timestamp(block: Mapping[str, Any], root: Mapping[str, Any]) -> Optional[dt.datetime]:
    for key in ("as_of", "generated_at", "timestamp", "updated_at", "last_update", "observed_at", "created_at"):
        parsed = _parse_time(block.get(key))
        if parsed:
            return parsed
    for key in ("as_of", "generated_at", "timestamp", "updated_at", "last_scan_at"):
        parsed = _parse_time(root.get(key))
        if parsed:
            return parsed
    return None


def _block_error(block: Mapping[str, Any]) -> Optional[str]:
    for key in ("error", "error_message", "failure", "exception"):
        if block.get(key):
            return str(block.get(key))
    status = _upper(block.get("status") or block.get("state"))
    if status in {"ERROR", "FAILED", "FAIL", "UNAVAILABLE", "NOT_CONFIGURED", "DISABLED"}:
        return status
    return None


def evaluate_evidence_health(
    payload: Optional[Mapping[str, Any]],
    *,
    now: Optional[dt.datetime] = None,
    max_age_seconds: Optional[Mapping[str, int]] = None,
) -> dict[str, Any]:
    root = payload if isinstance(payload, Mapping) else {}
    current = now or _now()
    thresholds = {**DEFAULT_MAX_AGE_SECONDS, **dict(max_age_seconds or {})}
    sources: list[dict[str, Any]] = []

    for source, aliases in SOURCE_ALIASES.items():
        alias, block = _first_mapping(root, aliases)
        configured = block.get("configured")
        enabled = block.get("enabled")
        error = _block_error(block)
        observed = _timestamp(block, root)
        age = max(0.0, (current - observed).total_seconds()) if observed else None
        meaningful = bool(block) and any(v not in (None, "", [], {}) for v in block.values())

        if configured is False or enabled is False or _upper(error) in {"NOT_CONFIGURED", "DISABLED"}:
            state = "NOT_CONFIGURED"
        elif error:
            state = "FAILED"
        elif not meaningful:
            state = "MISSING"
        elif observed and age is not None and age > int(thresholds[source]):
            state = "STALE"
        else:
            state = "FRESH"

        sources.append({
            "source": source,
            "resolved_key": alias,
            "state": state,
            "age_seconds": round(age, 1) if age is not None else None,
            "max_age_seconds": int(thresholds[source]),
            "observed_at": observed.isoformat() if observed else None,
            "error": error,
            "neutral_interpretation_allowed": state == "FRESH",
        })

    counts = {state: sum(1 for item in sources if item["state"] == state)
              for state in ("FRESH", "STALE", "MISSING", "FAILED", "NOT_CONFIGURED")}
    critical = {"market_state", "institutional_intelligence"}
    critical_degraded = [s["source"] for s in sources if s["source"] in critical and s["state"] != "FRESH"]
    available = counts["FRESH"] / max(1, len(sources))
    state = "HEALTHY" if not critical_degraded and available >= .75 else "DEGRADED" if available >= .50 else "UNRELIABLE"
    return {
        "state": state,
        "fresh_ratio": round(available, 4),
        "counts": counts,
        "critical_degraded": critical_degraded,
        "sources": sources,
        "generated_at": current.isoformat(),
    }


def _raw_confidence(root: Mapping[str, Any]) -> float:
    candidates = [
        root.get("confidence"),
        root.get("decision_confidence"),
        (root.get("institutional_decision") or {}).get("confidence") if isinstance(root.get("institutional_decision"), Mapping) else None,
        (root.get("institutional_intelligence") or {}).get("ici_score") if isinstance(root.get("institutional_intelligence"), Mapping) else None,
        (root.get("institutional_intelligence") or {}).get("confidence") if isinstance(root.get("institutional_intelligence"), Mapping) else None,
    ]
    for value in candidates:
        number = _float(value, -1)
        if number >= 0:
            return max(0.0, min(100.0, number * 100 if number <= 1 else number))
    return 0.0


def _direction(root: Mapping[str, Any]) -> str:
    candidates = [
        root.get("direction"), root.get("bias"), root.get("dominant_side"),
        (root.get("institutional_decision") or {}).get("direction") if isinstance(root.get("institutional_decision"), Mapping) else None,
        (root.get("institutional_intelligence") or {}).get("institutional_bias") if isinstance(root.get("institutional_intelligence"), Mapping) else None,
        (root.get("multi_timeframe") or {}).get("dominant_bias") if isinstance(root.get("multi_timeframe"), Mapping) else None,
    ]
    for value in candidates:
        text = _upper(value)
        if any(token in text for token in ("CALL", "LONG", "BULL", "UP")):
            return "BULLISH"
        if any(token in text for token in ("PUT", "SHORT", "BEAR", "DOWN")):
            return "BEARISH"
    return "NEUTRAL"


def _collect_evidence(root: Mapping[str, Any], direction: str) -> tuple[list[str], list[str], list[str]]:
    supportive: list[str] = []
    opposing: list[str] = []
    invalidation: list[str] = []

    containers = [root]
    for key in ("institutional_intelligence", "institutional_decision", "decision_intelligence", "evidence_graph"):
        value = root.get(key)
        if isinstance(value, Mapping):
            containers.append(value)

    for block in containers:
        for key in ("evidence", "supporting_evidence", "confirmations", "reasons", "why"):
            value = block.get(key)
            if isinstance(value, list):
                supportive.extend(str(x) for x in value if x)
        for key in ("counter_evidence", "opposing_evidence", "conflicts", "risks", "missing_confirmations"):
            value = block.get(key)
            if isinstance(value, list):
                opposing.extend(str(x) for x in value if x)
        for key in ("invalidation", "invalidations", "stop_conditions"):
            value = block.get(key)
            if isinstance(value, list):
                invalidation.extend(str(x) for x in value if x)
            elif value:
                invalidation.append(str(value))
        if block.get("primary_risk"):
            opposing.append(str(block["primary_risk"]))

    mtf = root.get("multi_timeframe") if isinstance(root.get("multi_timeframe"), Mapping) else {}
    mtf_bias = _upper(mtf.get("dominant_bias") or mtf.get("bias"))
    if mtf_bias:
        aligned = ((direction == "BULLISH" and any(x in mtf_bias for x in ("BULL", "UP", "LONG"))) or
                   (direction == "BEARISH" and any(x in mtf_bias for x in ("BEAR", "DOWN", "SHORT"))))
        (supportive if aligned else opposing).append(f"Multi-timeframe bias: {mtf_bias}")

    def unique(items: list[str]) -> list[str]:
        seen: set[str] = set(); output: list[str] = []
        for item in items:
            normalized = item.strip()
            if normalized and normalized.lower() not in seen:
                seen.add(normalized.lower()); output.append(normalized)
        return output[:12]

    return unique(supportive), unique(opposing), unique(invalidation)


def _confidence_ceiling(health: Mapping[str, Any], conflict_count: int) -> tuple[float, list[str]]:
    states = {item["source"]: item["state"] for item in health.get("sources", [])}
    ceiling = 100.0
    reasons: list[str] = []
    if states.get("market_state") != "FRESH":
        ceiling = min(ceiling, 0.0); reasons.append("Live market state is not fresh")
    if states.get("institutional_intelligence") != "FRESH":
        ceiling = min(ceiling, 40.0); reasons.append("Institutional intelligence is degraded")
    degraded_optional = sum(1 for key, state in states.items() if key not in {"market_state", "institutional_intelligence"} and state != "FRESH")
    if degraded_optional:
        ceiling = min(ceiling, max(45.0, 90.0 - degraded_optional * 7.5))
        reasons.append(f"{degraded_optional} supporting evidence sources are unavailable or stale")
    if conflict_count:
        ceiling = min(ceiling, max(45.0, 85.0 - conflict_count * 5.0))
        reasons.append(f"{conflict_count} opposing/conflicting evidence items remain")
    return round(ceiling, 2), reasons


def evaluate_decision(payload: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    root = payload if isinstance(payload, Mapping) else {}
    health = evaluate_evidence_health(root)
    direction = _direction(root)
    raw = _raw_confidence(root)
    supportive, opposing, invalidation = _collect_evidence(root, direction)
    ceiling, ceiling_reasons = _confidence_ceiling(health, len(opposing))
    adjusted = min(raw, ceiling)

    if health["state"] == "UNRELIABLE" or ceiling <= 0:
        eligibility = "STAND_DOWN"
    elif direction == "NEUTRAL":
        eligibility = "NO_DIRECTION"
    elif adjusted >= 75 and len(supportive) >= 2 and len(opposing) <= 2:
        eligibility = "ELIGIBLE"
    elif adjusted >= 55:
        eligibility = "WATCH"
    else:
        eligibility = "STAND_DOWN"

    missing = [item["source"] for item in health["sources"] if item["state"] in {"MISSING", "FAILED", "STALE"}]
    thesis = (f"{direction.title()} institutional thesis with {adjusted:.1f}% integrity-adjusted confidence."
              if direction != "NEUTRAL" else "No defensible directional thesis is established.")
    counter = ("; ".join(opposing[:4]) if opposing else
               "No explicit counter-thesis was supplied; absence of opposition is not treated as confirmation.")

    return {
        "ok": True,
        "status": "READY",
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso_now(),
        "decision": {
            "direction": direction,
            "execution_eligibility": eligibility,
            "raw_confidence": round(raw, 2),
            "confidence_ceiling": ceiling,
            "integrity_adjusted_confidence": round(adjusted, 2),
            "confidence_reduced": adjusted < raw,
            "confidence_ceiling_reasons": ceiling_reasons,
        },
        "explainability": {
            "thesis": thesis,
            "counter_thesis": counter,
            "supporting_evidence": supportive,
            "opposing_evidence": opposing,
            "missing_or_degraded_evidence": missing,
            "invalidation": invalidation,
            "minimum_evidence_satisfied": len(supportive) >= 2,
        },
        "evidence_health": health,
        "guardrails": {
            "unavailable_is_neutral": False,
            "stale_is_neutral": False,
            "failed_is_neutral": False,
            "automatic_order_submission": False,
            "production_confidence_mutation": False,
            "advisory_only": True,
        },
        "production_effect": "NONE",
    }


def status() -> dict[str, Any]:
    return {
        "status": "READY",
        "engine": "INSTITUTIONAL_DECISION_INTEGRITY",
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "read_only": True,
        "advisory_only": True,
        "automatic_order_submission": False,
        "production_confidence_mutation": False,
        "production_effect": "NONE",
    }
