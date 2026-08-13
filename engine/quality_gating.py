"""Quality-gated analytics for chain-dependent APEX outputs.

Quality is never an additive signal.  It multiplies, caps, or suppresses only
analytics that depend on the option chain.  The policy is intentionally pure so
all engines can use the same semantics and tests can audit them.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, Optional

POLICY_VERSION = "10.0.0_QUALITY_GATE"

CHAIN_DERIVED_FIELDS = (
    "call_wall", "put_wall", "zero_gamma", "active_gamma_flip",
    "raw_zero_gamma", "gex_score", "gamma_regime", "flip_risk",
    "flip_proximity", "expected_move", "dealer_exposure", "dex_score",
)


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def quality_multiplier(quality: Optional[Dict[str, Any]]) -> float:
    """Return a conservative [0,1] multiplier from quality and measurability.

    A failed gate does not automatically mean zero information: LIMITED quality
    can be used for display with a severe cap, while unavailable/low-confidence
    assessments suppress chain-dependent analytics entirely.
    """
    if not isinstance(quality, dict):
        return 0.0
    score = max(0.0, min(100.0, _num(quality.get("score")))) / 100.0
    confidence = max(0.0, min(100.0, _num(quality.get("score_confidence_pct")))) / 100.0
    assessment = str(quality.get("assessment_confidence") or "NONE").upper()
    if assessment in {"NONE", "LOW"} or confidence < 0.75:
        return 0.0
    raw = score * confidence
    if quality.get("gate_passed"):
        return round(raw, 4)
    # Failed gates may be shown diagnostically but cannot contribute strongly.
    return round(min(raw, 0.35), 4)


def gate_decision(quality: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    m = quality_multiplier(quality)
    passed = bool(isinstance(quality, dict) and quality.get("gate_passed"))
    if m <= 0:
        action = "SUPPRESS"
        reason = "chain quality absent or assessment confidence too low"
    elif not passed:
        action = "CAP"
        reason = "chain quality gate failed; diagnostics only"
    else:
        action = "ALLOW"
        reason = "chain quality gate passed"
    return {"policy_version": POLICY_VERSION, "action": action,
            "multiplier": m, "gate_passed": passed, "reason": reason}


def apply_quality_gate(payload: Optional[Dict[str, Any]], quality: Optional[Dict[str, Any]],
                       *, dependent_fields: Iterable[str] = CHAIN_DERIVED_FIELDS,
                       confidence_fields: Iterable[str] = ("confidence", "score")) -> Dict[str, Any]:
    """Return a copy with chain-dependent fields suppressed/capped consistently."""
    out = deepcopy(payload) if isinstance(payload, dict) else {}
    decision = gate_decision(quality)
    m = decision["multiplier"]
    if decision["action"] == "SUPPRESS":
        for key in dependent_fields:
            if key in out:
                out[key] = None
    for key in confidence_fields:
        if key in out and isinstance(out.get(key), (int, float)):
            out[f"{key}_raw"] = out[key]
            out[key] = round(float(out[key]) * m, 2)
    out["chain_quality"] = quality
    out["quality_gate"] = decision
    out["chain_dependent_reliable"] = decision["action"] == "ALLOW"
    return out
