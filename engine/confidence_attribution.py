"""Explainable confidence attribution for APEX.

This module does not create directional evidence.  It explains the confidence
already produced by the institutional pipeline and applies reliability controls
only to the components that depend on those controls.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .quality_gating import gate_decision
from .learning_calibration import apply_active_calibration

VERSION = "1.0.0"


def _sf(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _signed_direction(vote: Any) -> int:
    text = str(vote or "").upper()
    if text in {"BULLISH", "LONG", "CALL"}:
        return 1
    if text in {"BEARISH", "SHORT", "PUT"}:
        return -1
    return 0


def _event_multiplier(event_regime: Optional[Dict[str, Any]]) -> Optional[float]:
    if not isinstance(event_regime, dict) or not event_regime:
        return None
    raw = event_regime.get("alert_confidence_multiplier")
    if raw is None:
        return None
    return _clamp(_sf(raw, 1.0), 0.0, 1.0)


def _flow_multiplier(flow_authenticity: Optional[Dict[str, Any]]) -> Optional[float]:
    if not isinstance(flow_authenticity, dict) or not flow_authenticity:
        return None
    raw = flow_authenticity.get("directional_confidence_multiplier")
    if raw is None:
        return None
    return _clamp(_sf(raw, 1.0), 0.0, 1.0)


def build_confidence_attribution(
    *,
    ici: Dict[str, Any],
    engine_contributions: Iterable[Dict[str, Any]],
    consensus: Optional[Dict[str, Any]] = None,
    chain_quality: Optional[Dict[str, Any]] = None,
    event_regime: Optional[Dict[str, Any]] = None,
    flow_authenticity: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a complete, auditable explanation of the confidence score.

    Reliability controls are multiplicative:
      * chain quality modifies only the gamma component;
      * flow authenticity modifies only the flow component;
      * event phase modifies the final score.

    No reliability measure contributes positive directional points.
    """
    ici = ici if isinstance(ici, dict) else {}
    components = ici.get("components") if isinstance(ici.get("components"), dict) else {}
    weights = ici.get("weights") if isinstance(ici.get("weights"), dict) else {}

    specs = [
        ("conviction", "Consensus conviction", "consensus"),
        ("freshness", "Execution freshness", "execution"),
        ("gamma_stability", "Gamma stability", "gamma"),
        ("flow_momentum", "Flow momentum", "flow"),
    ]

    component_rows: List[Dict[str, Any]] = []
    base_points = 0.0
    for key, label, dependency in specs:
        raw = components.get(key)
        weight_key = "gamma" if key == "gamma_stability" else "momentum" if key == "flow_momentum" else key
        weight = weights.get(weight_key)
        measurable = raw is not None and weight is not None
        points = _sf(raw) * _sf(weight) if measurable else None
        if points is not None:
            base_points += points
        component_rows.append({
            "key": key,
            "label": label,
            "dependency": dependency,
            "measurable": measurable,
            "raw_score": round(_sf(raw), 2) if raw is not None else None,
            "weight": round(_sf(weight), 4) if weight is not None else None,
            "base_points": round(points, 2) if points is not None else None,
            "reliability_multiplier": 1.0 if measurable else None,
            "adjusted_points": round(points, 2) if points is not None else None,
            "adjustment_reason": None,
        })

    adjustments: List[Dict[str, Any]] = []

    # Chain quality modifies only the chain-derived gamma component.
    if chain_quality is not None:
        gate = gate_decision(chain_quality)
        mult = _clamp(_sf(gate.get("multiplier"), 0.0), 0.0, 1.0)
        for row in component_rows:
            if row["key"] == "gamma_stability" and row["base_points"] is not None:
                row["reliability_multiplier"] = round(mult, 4)
                row["adjusted_points"] = round(row["base_points"] * mult, 2)
                row["adjustment_reason"] = f"Chain quality gate: {gate.get('action')}"
                adjustments.append({
                    "scope": "gamma_stability",
                    "type": "CHAIN_QUALITY",
                    "action": gate.get("action"),
                    "multiplier": round(mult, 4),
                    "point_effect": round(row["adjusted_points"] - row["base_points"], 2),
                    "reason": gate.get("reason"),
                })
                break

    # Flow authenticity modifies only the flow component.
    flow_mult = _flow_multiplier(flow_authenticity)
    if flow_mult is not None:
        for row in component_rows:
            if row["key"] == "flow_momentum" and row["base_points"] is not None:
                row["reliability_multiplier"] = round(flow_mult, 4)
                row["adjusted_points"] = round(row["base_points"] * flow_mult, 2)
                row["adjustment_reason"] = "Flow authenticity multiplier"
                adjustments.append({
                    "scope": "flow_momentum",
                    "type": "FLOW_AUTHENTICITY",
                    "action": str(flow_authenticity.get("state") or "ADJUST"),
                    "multiplier": round(flow_mult, 4),
                    "point_effect": round(row["adjusted_points"] - row["base_points"], 2),
                    "reason": flow_authenticity.get("reason"),
                })
                break

    component_adjusted_score = sum(_sf(row.get("adjusted_points")) for row in component_rows if row.get("adjusted_points") is not None)

    # Event regime is a final confidence calibration, not a directional vote.
    event_mult = _event_multiplier(event_regime)
    effective_score = component_adjusted_score
    if event_mult is not None:
        effective_score *= event_mult
        adjustments.append({
            "scope": "overall_confidence",
            "type": "EVENT_REGIME",
            "action": str(event_regime.get("state") or "EVENT_ADJUSTMENT"),
            "multiplier": round(event_mult, 4),
            "point_effect": round(effective_score - component_adjusted_score, 2),
            "reason": event_regime.get("calibration_reason") or event_regime.get("reason"),
        })

    # Engine rows expose signed contribution; they explain direction separately
    # from the non-directional ICI component score.
    signed_rows: List[Dict[str, Any]] = []
    for item in engine_contributions or []:
        if not isinstance(item, dict):
            continue
        direction = _signed_direction(item.get("vote"))
        raw_contribution = item.get("contribution")
        signed = None if raw_contribution is None else round(abs(_sf(raw_contribution)) * direction, 4)
        signed_rows.append({
            "engine": item.get("engine"),
            "label": item.get("label"),
            "vote": item.get("vote"),
            "data_available": bool(item.get("data_available")),
            "health_status": item.get("health_status"),
            "weight": item.get("weight"),
            "strength": item.get("strength"),
            "signed_contribution": signed,
            "direction": "BULLISH" if direction > 0 else "BEARISH" if direction < 0 else "NEUTRAL",
        })

    base_reported = _sf(ici.get("ici"), base_points)
    dominant = str((consensus or {}).get("consensus_direction") or "NEUTRAL").upper()
    total_penalty = round(effective_score - base_points, 2)

    learned_calibration = apply_active_calibration(_clamp(effective_score))

    return {
        "available": bool(component_rows),
        "version": VERSION,
        "base_score": round(base_reported, 1),
        "reconstructed_base_score": round(base_points, 1),
        "component_adjusted_score": round(_clamp(component_adjusted_score), 1),
        "effective_confidence": round(_clamp(effective_score), 1),
        "learned_calibration": learned_calibration,
        "calibrated_confidence": learned_calibration.get("calibrated_confidence"),
        "total_adjustment_points": total_penalty,
        "dominant_direction": dominant,
        "components": component_rows,
        "engine_directional_contributions": signed_rows,
        "adjustments": adjustments,
        "methodology": {
            "reliability_is_additive": False,
            "chain_quality_scope": "gamma_stability_only",
            "flow_authenticity_scope": "flow_momentum_only",
            "event_scope": "overall_confidence",
            "missing_values": "reported_as_unmeasurable",
            "learning_policy_is_automatic": False,
        },
    }
