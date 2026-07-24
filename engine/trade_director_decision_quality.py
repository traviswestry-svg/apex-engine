"""APEX Trade Director Phase 38 — Decision Quality & Alert Integrity.

Turns raw directional evidence into an execution-aware alert-quality assessment.
The module is deterministic, cached-input only, advisory, and fail-closed. It does
not contact providers or brokers and does not generate trade calls.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional

VERSION = "38.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _num(v: Any, default: float = 0.0) -> float:
    try:
        n = float(v)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError):
        return default


def _upper(v: Any) -> str:
    return str(v or "").strip().upper().replace(" ", "_")


def _direction(v: Any) -> str:
    t = _upper(v)
    if any(x in t for x in ("BULL", "CALL", "UP", "LONG", "BUY")):
        return "BULLISH"
    if any(x in t for x in ("BEAR", "PUT", "DOWN", "SHORT", "SELL")):
        return "BEARISH"
    return "NEUTRAL"


def _iter_flow_rows(node: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(node, Mapping):
        looks_like = any(k in node for k in ("premium", "notional", "dollar_value")) and any(
            k in node for k in ("size", "quantity", "contracts", "strike")
        )
        if looks_like:
            yield node
        for value in node.values():
            if isinstance(value, (Mapping, list, tuple)):
                yield from _iter_flow_rows(value)
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from _iter_flow_rows(item)


def build_flow_participation(snapshot: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Describe participation quality without equating contract count with conviction."""
    s = dict(snapshot or {})
    rows = list(_iter_flow_rows(s.get("flow") or s.get("flow_tape") or s.get("options_flow") or s))[:2500]
    if not rows:
        return {
            "status": "UNAVAILABLE", "event_count": 0, "classified_premium": 0.0,
            "delta_adjusted_notional": None, "small_lot_share_pct": None,
            "block_share_pct": None, "strike_concentration_pct": None,
            "opening_share_pct": None, "participant_mix": "UNKNOWN",
            "explanation": "No normalized option-flow events were available.",
        }

    total_premium = 0.0
    delta_notional = 0.0
    small_premium = 0.0
    block_premium = 0.0
    opening_premium = 0.0
    strike_premium: Dict[str, float] = defaultdict(float)
    usable = 0

    for row in rows:
        premium = _num(row.get("premium") or row.get("notional") or row.get("dollar_value"))
        size = _num(row.get("size") or row.get("quantity") or row.get("contracts"))
        if premium <= 0:
            premium = _num(row.get("price") or row.get("fill_price")) * size * 100.0
        if premium <= 0:
            continue
        usable += 1
        total_premium += premium
        delta = abs(_num(row.get("delta"), 0.0))
        if delta > 1.0:
            delta /= 100.0
        delta_notional += premium * min(1.0, delta) if delta else 0.0
        if size and size <= 10:
            small_premium += premium
        kind = _upper(row.get("type") or row.get("trade_type") or row.get("condition"))
        if "BLOCK" in kind or size >= 100:
            block_premium += premium
        effect = _upper(row.get("position_effect") or row.get("open_close") or row.get("intent"))
        if "OPEN" in effect:
            opening_premium += premium
        strike = row.get("strike")
        if strike is not None:
            strike_premium[str(strike)] += premium

    if usable == 0 or total_premium <= 0:
        return {"status": "UNAVAILABLE", "event_count": 0, "classified_premium": 0.0,
                "explanation": "Flow rows existed but none had usable premium or size."}

    top3 = sum(sorted(strike_premium.values(), reverse=True)[:3])
    small_share = small_premium / total_premium * 100.0
    block_share = block_premium / total_premium * 100.0
    concentration = top3 / total_premium * 100.0 if strike_premium else 0.0
    opening_share = opening_premium / total_premium * 100.0
    if block_share >= 35:
        mix = "BLOCK_LED"
    elif small_share >= 55:
        mix = "SMALL_LOT_LED"
    else:
        mix = "MIXED_PARTICIPATION"

    return {
        "status": "READY",
        "event_count": usable,
        "classified_premium": round(total_premium, 2),
        "delta_adjusted_notional": round(delta_notional, 2) if delta_notional else None,
        "small_lot_share_pct": round(small_share, 1),
        "block_share_pct": round(block_share, 1),
        "strike_concentration_pct": round(concentration, 1),
        "opening_share_pct": round(opening_share, 1),
        "participant_mix": mix,
        "explanation": (
            "Participation is described by premium, delta exposure, trade size, opening intent, "
            "and strike concentration; raw contracts are not treated as institutional conviction."
        ),
    }


def _policy_metrics(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    p = snapshot.get("policy_metrics") or snapshot.get("alert_metrics") or {}
    if not isinstance(p, Mapping):
        p = {}
    precision = _num(p.get("actionable_precision_pct") or p.get("precision_pct"), -1)
    slippage = _num(p.get("avg_slippage_pct") or p.get("slippage_pct"), -1)
    latency = _num(p.get("alert_latency_ms") or p.get("latency_ms"), -1)
    mae = _num(p.get("mae_pct") or p.get("max_adverse_excursion_pct"), -1)
    next_fill = _num(p.get("next_executable_return_pct") or p.get("next_fill_return_pct"), -999)
    available = any(x >= 0 for x in (precision, slippage, latency, mae)) or next_fill > -999
    return {
        "status": "READY" if available else "COLLECTING",
        "actionable_precision_pct": None if precision < 0 else round(precision, 2),
        "avg_slippage_pct": None if slippage < 0 else round(slippage, 3),
        "alert_latency_ms": None if latency < 0 else round(latency, 1),
        "mae_pct": None if mae < 0 else round(mae, 3),
        "next_executable_return_pct": None if next_fill <= -999 else round(next_fill, 3),
        "grading_rule": "Grade prediction quality separately from executable policy quality.",
    }


def build_decision_quality(snapshot: Optional[Mapping[str, Any]], prior_state: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    s = dict(snapshot or {})
    direction = _direction(s.get("direction") or s.get("bias") or s.get("consensus_label"))
    confidence = _num(s.get("confidence") or s.get("ici") or s.get("institutional_confidence"))
    execution = _num(s.get("execution_score") or (s.get("execution") or {}).get("score"))
    position_quality = _num(s.get("position_quality") or (s.get("execution") or {}).get("position_quality"))
    freshness_ok = not bool(s.get("stale")) and bool(s.get("data_fresh", True))
    market_open = bool(s.get("market_open", True))
    liquidity = _upper(s.get("option_liquidity_state") or s.get("liquidity_state") or "UNKNOWN")
    recommendation = _upper(s.get("recommendation") or s.get("decision") or "WAIT")

    entry_threshold = _num(s.get("entry_confidence_threshold"), 80.0)
    exit_threshold = _num(s.get("exit_confidence_threshold"), max(0.0, entry_threshold - 8.0))
    active = bool((prior_state or {}).get("active") or s.get("position_active") or "HOLD" in recommendation)
    applied_threshold = exit_threshold if active else entry_threshold
    boundary_margin = confidence - applied_threshold

    blockers = []
    if not market_open:
        blockers.append("MARKET_CLOSED")
    if not freshness_ok:
        blockers.append("STALE_OR_MISSING_DATA")
    if direction == "NEUTRAL":
        blockers.append("NO_DIRECTIONAL_CONSENSUS")
    if liquidity in {"POOR", "WIDE", "UNAVAILABLE", "FAILED"}:
        blockers.append("LIQUIDITY_NOT_ELIGIBLE")
    if confidence < applied_threshold:
        blockers.append("CONFIDENCE_BELOW_DECISION_BOUNDARY")
    if execution and execution < 70:
        blockers.append("EXECUTION_QUALITY_BELOW_MINIMUM")
    if position_quality and position_quality < 70:
        blockers.append("POSITION_QUALITY_BELOW_MINIMUM")

    participation = build_flow_participation(s)
    # Do not let raw-volume participation independently authorize an alert.
    if participation.get("status") == "READY":
        if participation.get("small_lot_share_pct", 0) >= 70 and participation.get("block_share_pct", 0) < 10:
            blockers.append("SMALL_LOT_DOMINATED_FLOW")
        if participation.get("strike_concentration_pct", 0) < 20:
            blockers.append("FLOW_TOO_DISPERSED")

    alert_eligible = not blockers
    if alert_eligible and boundary_margin < 5:
        alert_state = "WATCH_ONLY"
        alert_eligible = False
        blockers.append("INSUFFICIENT_BOUNDARY_MARGIN")
    elif alert_eligible:
        alert_state = "ELIGIBLE"
    else:
        alert_state = "SUPPRESSED"

    return {
        "version": VERSION,
        "generated_at": _now(),
        "status": "READY" if freshness_ok else "DEGRADED",
        "direction": direction,
        "recommendation": recommendation,
        "confidence": round(confidence, 1),
        "decision_boundary": {
            "active_state": active,
            "entry_threshold": entry_threshold,
            "exit_threshold": exit_threshold,
            "applied_threshold": applied_threshold,
            "margin_points": round(boundary_margin, 1),
            "hysteresis_points": round(entry_threshold - exit_threshold, 1),
            "next_state_requirement": (
                f"Confidence must improve by {abs(boundary_margin):.1f} points to reach the boundary."
                if boundary_margin < 0 else
                f"Confidence is {boundary_margin:.1f} points above the active boundary."
            ),
        },
        "alert_quality": {
            "state": alert_state,
            "alert_eligible": alert_eligible,
            "blocking_conditions": blockers,
            "abstention_is_valid": True,
            "explanation": (
                "Alerts are gated by executable decision quality, not directional prediction or raw volume alone."
            ),
        },
        "flow_participation": participation,
        "policy_quality": _policy_metrics(s),
        "counterfactuals": [
            {"change": "confidence", "required": round(max(0.0, applied_threshold + 5.0 - confidence), 1),
             "effect": "Would clear the minimum decision-boundary margin."},
            {"change": "data_freshness", "required": "FRESH", "effect": "Removes stale-data suppression."},
            {"change": "liquidity", "required": "NORMAL_OR_BETTER", "effect": "Removes execution-liquidity suppression."},
        ],
        "governance": {
            "advisory_only": True,
            "no_trade_call": True,
            "next_executable_price_required_for_grading": True,
            "raw_volume_not_conviction": True,
        },
    }
