"""APEX 69.10.4 Multi-Horizon Transition Context.

Read-only composition of already-produced transition observations.  This module
creates no directional signal and has no decision/execution authority.  It keeps
1m/5m/15m/30m gamma-transition measurements separate, reports disagreement and
acceleration, and surfaces optional current flow-surprise / ES tick-momentum
context without pretending those feeds share identical time horizons.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

VERSION = "69.10.4"
SCHEMA_VERSION = "apex.multi_horizon_transition_context.v1"
HORIZONS = (1, 5, 15, 30)


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
        return x
    except (TypeError, ValueError):
        return None


def _state(ratio: Optional[float], threshold: float = 0.05) -> str:
    if ratio is None:
        return "UNAVAILABLE"
    if ratio >= threshold:
        return "UP"
    if ratio <= -threshold:
        return "DOWN"
    return "FLAT"


def _mapping(v: Any) -> Mapping[str, Any]:
    return v if isinstance(v, Mapping) else {}


def build_multi_horizon_transition_context(
    *, gamma_transition: Optional[Mapping[str, Any]] = None,
    flow_surprise: Optional[Mapping[str, Any]] = None,
    tick_momentum: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    gt = _mapping(gamma_transition)
    horizons: Dict[str, Dict[str, Any]] = {}
    valid_states = []
    valid_ratios = []
    for h in HORIZONS:
        ratio = _f(gt.get(f"net_gex_transition_ratio_{h}m"))
        delta = _f(gt.get(f"net_gex_change_{h}m"))
        state = _state(ratio)
        horizons[f"{h}m"] = {
            "gamma_transition_ratio": ratio,
            "net_gex_change": delta,
            "state": state,
            "rate_per_minute": None if ratio is None else round(ratio / h, 6),
        }
        if state != "UNAVAILABLE":
            valid_states.append(state)
        if ratio is not None:
            valid_ratios.append(ratio)

    directional = {s for s in valid_states if s in {"UP", "DOWN"}}
    disagreement = len(directional) > 1
    if not valid_states:
        alignment = "UNAVAILABLE"
    elif disagreement:
        alignment = "DIVERGENT"
    elif directional == {"UP"}:
        alignment = "ALIGNED_UP"
    elif directional == {"DOWN"}:
        alignment = "ALIGNED_DOWN"
    else:
        alignment = "FLAT_OR_MIXED"

    r1 = _f(gt.get("net_gex_transition_ratio_1m"))
    r15 = _f(gt.get("net_gex_transition_ratio_15m"))
    acceleration = None
    if r1 is not None and r15 is not None:
        acceleration = round(r1 - (r15 / 15.0), 6)

    # Confidence describes context completeness/alignment, not probability of a trade outcome.
    coverage = len(valid_ratios) / len(HORIZONS)
    context_confidence = round(coverage * (0.7 if disagreement else 1.0), 3)

    fs = _mapping(flow_surprise)
    flow = {
        "available": str(fs.get("status") or "").upper() == "AVAILABLE",
        "state": fs.get("flow_surprise_state"),
        "relative_premium_activity": _f(fs.get("relative_premium_activity")),
        "premium_percentile": _f(fs.get("premium_percentile")),
        "relative_contract_activity": _f(fs.get("relative_contract_activity")),
        "volume_percentile": _f(fs.get("volume_percentile")),
        "current_snapshot_only": True,
    }

    tm = _mapping(tick_momentum)
    align = _mapping(tm.get("alignment"))
    tick = {
        "available": bool(tm),
        "instrument": tm.get("instrument"),
        "alignment_state": align.get("state"),
        "alignment_score": _f(align.get("score")),
        "disagreement": align.get("disagreement"),
        "transaction_horizons": {
            str(k): {"state": _mapping(v).get("state"), "raw": _f(_mapping(v).get("raw"))}
            for k, v in _mapping(tm.get("horizons")).items()
        },
        "note": "Transaction-count horizons are preserved separately; they are not relabelled as clock-time horizons.",
    }

    return {
        "available": bool(valid_ratios or flow["available"] or tick["available"]),
        "schema_version": SCHEMA_VERSION,
        "version": VERSION,
        "horizons": horizons,
        "transition_alignment": alignment,
        "transition_acceleration": acceleration,
        "multi_horizon_disagreement": disagreement,
        "context_confidence": context_confidence,
        "flow_surprise": flow,
        "tick_momentum": tick,
        "behavioral_authority": False,
        "decision_authority": "NONE",
        "execution_authority": False,
        "automatic_calibration_activation": False,
        "production_effect": "NONE",
    }
