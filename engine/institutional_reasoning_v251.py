"""APEX 25.1 — Institutional Reasoning Engine.

Read-only explanation layer built on APEX 25.0 Decision Integrity. It ranks
available evidence, exposes contradictions, traces confidence adjustments, and
returns an auditable institutional narrative. It never submits orders or mutates
production confidence.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Mapping, Optional

from . import institutional_decision_integrity_v250 as integrity

VERSION = "25.1.0_INSTITUTIONAL_REASONING"
SCHEMA_VERSION = "apex.institutional_reasoning.v251.v1"

SOURCE_WEIGHTS = {
    "market_state": 1.00,
    "institutional_intelligence": 0.95,
    "dealer_positioning": 0.85,
    "flow": 0.80,
    "multi_timeframe": 0.75,
    "market_memory": 0.55,
    "similarity": 0.50,
    "calibration": 0.50,
}


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _direction_match(text: str, direction: str) -> int:
    value = text.upper()
    bullish = any(token in value for token in ("BULL", "CALL", "LONG", "UP", "BUY", "POSITIVE"))
    bearish = any(token in value for token in ("BEAR", "PUT", "SHORT", "DOWN", "SELL", "NEGATIVE"))
    if direction == "BULLISH":
        return 1 if bullish and not bearish else -1 if bearish and not bullish else 0
    if direction == "BEARISH":
        return 1 if bearish and not bullish else -1 if bullish and not bearish else 0
    return 0


def _source_block(root: Mapping[str, Any], source: str) -> Mapping[str, Any]:
    aliases = integrity.SOURCE_ALIASES.get(source, (source,))
    for alias in aliases:
        block = root.get(alias)
        if isinstance(block, Mapping):
            return block
    return {}


def _source_summary(source: str, block: Mapping[str, Any]) -> str:
    keys = (
        "headline", "summary", "state", "status", "bias", "direction",
        "dominant_bias", "institutional_bias", "regime", "signal", "context",
    )
    for key in keys:
        value = block.get(key)
        if value not in (None, "", [], {}):
            return f"{source.replace('_', ' ').title()}: {_text(value)}"
    for key in ("score", "confidence", "ici_score", "alignment_score", "similarity"):
        if block.get(key) is not None:
            return f"{source.replace('_', ' ').title()}: {key.replace('_', ' ')} {_number(block.get(key)):.1f}"
    return f"{source.replace('_', ' ').title()}: evidence available"


def rank_evidence(payload: Optional[Mapping[str, Any]], decision: Optional[Mapping[str, Any]] = None) -> list[dict[str, Any]]:
    root = payload if isinstance(payload, Mapping) else {}
    evaluated = decision if isinstance(decision, Mapping) else integrity.evaluate_decision(root)
    direction = _text(_mapping(evaluated.get("decision")).get("direction")).upper()
    health_items = {item.get("source"): item for item in _list(_mapping(evaluated.get("evidence_health")).get("sources")) if isinstance(item, Mapping)}
    ranked: list[dict[str, Any]] = []

    for source, base_weight in SOURCE_WEIGHTS.items():
        block = _source_block(root, source)
        health = _mapping(health_items.get(source))
        state = _text(health.get("state") or "MISSING").upper()
        summary = _source_summary(source, block)
        alignment = _direction_match(" ".join(_text(v) for v in block.values() if isinstance(v, (str, int, float))), direction)
        confidence = _number(block.get("confidence") or block.get("score") or block.get("ici_score") or block.get("alignment_score"), 50.0)
        confidence = confidence * 100 if 0 < confidence <= 1 else confidence
        confidence_factor = max(0.25, min(1.0, confidence / 100.0))
        health_factor = {"FRESH": 1.0, "STALE": 0.35, "MISSING": 0.0, "FAILED": 0.0, "NOT_CONFIGURED": 0.0}.get(state, 0.0)
        importance = base_weight * confidence_factor * health_factor
        ranked.append({
            "source": source,
            "summary": summary,
            "health": state,
            "alignment": "SUPPORTIVE" if alignment > 0 else "OPPOSING" if alignment < 0 else "NEUTRAL",
            "base_weight": round(base_weight, 3),
            "importance_score": round(importance * 100, 2),
            "age_seconds": health.get("age_seconds"),
        })

    ranked.sort(key=lambda item: (-item["importance_score"], item["source"]))
    total = sum(item["importance_score"] for item in ranked)
    for item in ranked:
        item["share_pct"] = round(item["importance_score"] / total * 100, 2) if total > 0 else 0.0
    return ranked


def build_confidence_waterfall(decision: Mapping[str, Any], ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decision_block = _mapping(decision.get("decision"))
    raw = _number(decision_block.get("raw_confidence"))
    current = raw
    steps = [{"label": "Raw model confidence", "delta": 0.0, "confidence": round(current, 2), "kind": "BASE"}]

    for item in ranked:
        if item["health"] != "FRESH":
            delta = -min(10.0, SOURCE_WEIGHTS.get(item["source"], .5) * 8.0)
            current = max(0.0, current + delta)
            steps.append({"label": f"{item['source'].replace('_', ' ').title()} {item['health'].lower()}", "delta": round(delta, 2), "confidence": round(current, 2), "kind": "DEGRADATION"})
        elif item["alignment"] == "OPPOSING":
            delta = -min(8.0, item["importance_score"] / 10.0)
            current = max(0.0, current + delta)
            steps.append({"label": f"Opposing {item['source'].replace('_', ' ')}", "delta": round(delta, 2), "confidence": round(current, 2), "kind": "CONTRADICTION"})

    final = _number(decision_block.get("integrity_adjusted_confidence"))
    if abs(current - final) > .01:
        steps.append({"label": "Decision Integrity ceiling", "delta": round(final - current, 2), "confidence": round(final, 2), "kind": "CEILING"})
    return steps


def _historical_match(root: Mapping[str, Any]) -> dict[str, Any]:
    similarity = _source_block(root, "similarity")
    match = _mapping(similarity.get("best_match") or similarity.get("top_match"))
    score = _number(match.get("similarity") or match.get("score") or similarity.get("similarity") or similarity.get("score"))
    score = score * 100 if 0 < score <= 1 else score
    return {
        "available": bool(similarity),
        "session": match.get("session") or match.get("date") or similarity.get("matched_session"),
        "similarity_pct": round(score, 2),
        "average_move_points": match.get("average_move_points") or similarity.get("average_move_points"),
        "sample_size": match.get("sample_size") or similarity.get("sample_size"),
        "outcome": match.get("outcome") or similarity.get("expected_outcome"),
    }


def _timeline(root: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates = root.get("story_timeline") or root.get("thesis_timeline")
    if not isinstance(candidates, list):
        story = _mapping(root.get("market_story") or root.get("story_engine"))
        candidates = story.get("timeline") or story.get("events") or []
    output: list[dict[str, Any]] = []
    for index, event in enumerate(_list(candidates)):
        if isinstance(event, Mapping):
            output.append({
                "time": event.get("time") or event.get("timestamp") or event.get("at"),
                "event": event.get("event") or event.get("label") or event.get("headline") or event.get("description"),
                "state": event.get("state") or event.get("type") or "OBSERVATION",
            })
        elif event:
            output.append({"time": None, "event": _text(event), "state": "OBSERVATION"})
    return [item for item in output if item.get("event")][:12]


def _trade_grade(final_confidence: float, health_state: str, supportive: int, opposing: int) -> dict[str, Any]:
    score = final_confidence + min(8, supportive * 2) - min(15, opposing * 4)
    if health_state == "DEGRADED":
        score -= 10
    elif health_state == "UNRELIABLE":
        score -= 25
    score = max(0.0, min(100.0, score))
    grade = "A" if score >= 90 else "A-" if score >= 85 else "B+" if score >= 80 else "B" if score >= 75 else "C" if score >= 65 else "D" if score >= 50 else "F"
    return {"grade": grade, "score": round(score, 2), "advisory_only": True}


def build_reasoning(payload: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    root = payload if isinstance(payload, Mapping) else {}
    decision = integrity.evaluate_decision(root)
    explain = _mapping(decision.get("explainability"))
    decision_block = _mapping(decision.get("decision"))
    health = _mapping(decision.get("evidence_health"))
    ranked = rank_evidence(root, decision)
    supportive = _list(explain.get("supporting_evidence"))
    opposing = _list(explain.get("opposing_evidence"))
    final_confidence = _number(decision_block.get("integrity_adjusted_confidence"))

    top_support = [item["summary"] for item in ranked if item["alignment"] == "SUPPORTIVE" and item["health"] == "FRESH"][:4]
    top_oppose = [item["summary"] for item in ranked if item["alignment"] == "OPPOSING" and item["health"] == "FRESH"][:4]
    thesis_parts = supportive[:3] or top_support
    contradiction_parts = opposing[:3] or top_oppose
    direction = _text(decision_block.get("direction") or "NEUTRAL")

    thesis = explain.get("thesis")
    if thesis_parts:
        thesis = f"{direction.title()} thesis: " + "; ".join(_text(x) for x in thesis_parts)
    counter = explain.get("counter_thesis")
    if contradiction_parts:
        counter = "Counter-thesis: " + "; ".join(_text(x) for x in contradiction_parts)

    return {
        "ok": True,
        "status": "READY",
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso_now(),
        "reasoning": {
            "direction": direction,
            "execution_eligibility": decision_block.get("execution_eligibility"),
            "institutional_thesis": thesis,
            "counter_thesis": counter,
            "invalidation": _list(explain.get("invalidation")),
            "evidence_rankings": ranked,
            "contradictions": contradiction_parts,
            "confidence_waterfall": build_confidence_waterfall(decision, ranked),
            "historical_match": _historical_match(root),
            "story_timeline": _timeline(root),
            "trade_grade": _trade_grade(final_confidence, _text(health.get("state")), len(supportive), len(opposing)),
            "raw_confidence": decision_block.get("raw_confidence"),
            "final_confidence": final_confidence,
            "confidence_ceiling": decision_block.get("confidence_ceiling"),
        },
        "decision_integrity": decision,
        "guardrails": {
            "read_only": True,
            "advisory_only": True,
            "automatic_order_submission": False,
            "production_confidence_mutation": False,
        },
        "production_effect": "NONE",
    }


def status() -> dict[str, Any]:
    return {
        "status": "READY",
        "engine": "INSTITUTIONAL_REASONING",
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "read_only": True,
        "advisory_only": True,
        "production_effect": "NONE",
    }
