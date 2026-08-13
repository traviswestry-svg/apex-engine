"""APEX Liquidity Race Engine.

Estimates which opposing liquidity pool is more likely to be reached first.
Advisory only: visible resting size is treated as uncertain and can be cancelled.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

VERSION = "43.6.0"
SCHEMA_VERSION = "apex.liquidity_race.v1"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _signed_score(value: Any, *, neutral: float = 50.0) -> float:
    """Normalize either -100..100 or 0..100 input to -1..1."""
    score = _num(value, neutral)
    if -100.0 <= score < 0.0:
        return max(-1.0, score / 100.0)
    return max(-1.0, min(1.0, (score - 50.0) / 50.0))


def evaluate(snapshot: Mapping[str, Any] | None = None) -> dict[str, Any]:
    s = dict(snapshot or {})
    price = _num(s.get("current_price") or s.get("price") or s.get("spot"))
    upper = _num(s.get("upper_level") or s.get("upside_level") or s.get("call_wall"))
    lower = _num(s.get("lower_level") or s.get("downside_level") or s.get("put_wall"))
    upper_size = max(0.0, _num(s.get("upper_size") or s.get("ask_size") or s.get("call_wall_size"), 1.0))
    lower_size = max(0.0, _num(s.get("lower_size") or s.get("bid_size") or s.get("put_wall_size"), 1.0))

    valid = price > 0 and upper > price and 0 < lower < price
    if not valid:
        return {
            "ok": False,
            "status": "INSUFFICIENT_LEVELS",
            "schema_version": SCHEMA_VERSION,
            "engine_version": VERSION,
            "interpretation": "A current price plus one valid liquidity level above and below are required.",
            "advisory_only": True,
        }

    up_distance = upper - price
    down_distance = price - lower
    total_distance = up_distance + down_distance
    proximity_edge = (down_distance - up_distance) / total_distance

    # Resting size is intentionally low weight because displayed orders may cancel.
    size_total = upper_size + lower_size
    size_edge = 0.0 if size_total <= 0 else (lower_size - upper_size) / size_total

    order_flow = _signed_score(s.get("order_flow_score"))
    delta = _signed_score(s.get("delta_score") or s.get("cumulative_delta_score"))
    momentum = _signed_score(s.get("momentum_score"))
    structure = _signed_score(s.get("structure_score"))
    auction = _signed_score(s.get("auction_score"))
    liquidity_pressure = _signed_score(s.get("liquidity_pressure"))

    weighted_edge = (
        0.23 * order_flow
        + 0.17 * delta
        + 0.16 * momentum
        + 0.13 * structure
        + 0.10 * auction
        + 0.08 * liquidity_pressure
        + 0.10 * proximity_edge
        + 0.03 * size_edge
    )
    upper_probability = _clamp(50.0 + weighted_edge * 50.0, 5.0, 95.0)
    lower_probability = 100.0 - upper_probability
    edge = abs(upper_probability - lower_probability)

    if edge < 8:
        leader, state = "BALANCED", "NO_EDGE"
    elif upper_probability > lower_probability:
        leader, state = "UPPER", "UPSIDE_FAVORED"
    else:
        leader, state = "LOWER", "DOWNSIDE_FAVORED"

    confidence = _clamp(35.0 + edge * 0.75)
    drivers = [
        ("order_flow", order_flow, 0.23), ("delta", delta, 0.17),
        ("momentum", momentum, 0.16), ("structure", structure, 0.13),
        ("auction", auction, 0.10), ("liquidity_pressure", liquidity_pressure, 0.08),
        ("proximity", proximity_edge, 0.10), ("displayed_size", size_edge, 0.03),
    ]
    ranked = sorted(
        ({"factor": name, "direction": "UPPER" if value > 0 else "LOWER" if value < 0 else "NEUTRAL",
          "normalized_value": round(value, 3), "impact": round(value * weight * 100, 2)}
         for name, value, weight in drivers),
        key=lambda row: abs(row["impact"]), reverse=True,
    )

    return {
        "ok": True,
        "status": state,
        "leader": leader,
        "current_price": round(price, 2),
        "upper": {"level": round(upper, 2), "distance": round(up_distance, 2), "displayed_size": upper_size,
                  "probability_first_pct": round(upper_probability, 1)},
        "lower": {"level": round(lower, 2), "distance": round(down_distance, 2), "displayed_size": lower_size,
                  "probability_first_pct": round(lower_probability, 1)},
        "confidence": round(confidence, 1),
        "edge_pct": round(edge, 1),
        "ranked_drivers": ranked,
        "interpretation": (
            "Upper liquidity is currently more likely to be tested first."
            if leader == "UPPER" else
            "Lower liquidity is currently more likely to be tested first."
            if leader == "LOWER" else
            "The liquidity race is balanced; wait for order-flow separation."
        ),
        "warnings": [
            "Displayed orders can be cancelled or spoofed; size is deliberately low-weighted.",
            "A level being reached does not imply it will break; watch absorption and replenishment at contact.",
        ],
        "advisory_only": True,
        "schema_version": SCHEMA_VERSION,
        "engine_version": VERSION,
    }
