"""APEX Trade Director Phase 36 — Precision Entry & Momentum Lifecycle.

Advisory-only lifecycle logic for the user's fast SPX option-premium momentum trades.
Entry quality is evaluated separately from directional confidence. After a manually
confirmed fill, premium expansion and adverse movement are measured from the actual
option entry price. The engine never places, modifies, or closes broker orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

DEFAULT_PROFIT_EXPANSION = 2.00
DEFAULT_ADVERSE_EXIT = 2.50
MIN_ADVERSE_EXIT = 2.00
MAX_ADVERSE_EXIT = 3.00


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def compute_entry_quality(evidence: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Return a transparent entry-quality prior, independent of broad conviction.

    This is intentionally heuristic until Phase 31/32 collect enough graded entries.
    Missing inputs reduce coverage rather than being treated as neutral evidence.
    """
    e = dict(evidence or {})
    fields = {
        "level_precision": e.get("level_precision_score"),
        "momentum": e.get("momentum_score"),
        "liquidity": e.get("liquidity_score"),
        "spread": e.get("spread_quality_score"),
        "timing": e.get("timing_score"),
        "invalidation": e.get("invalidation_clarity_score"),
    }
    supplied = {k: _clamp(_num(v), 0, 100) for k, v in fields.items() if v not in (None, "")}
    coverage = round(100.0 * len(supplied) / len(fields), 1)
    weights = {
        "level_precision": 0.27,
        "momentum": 0.23,
        "liquidity": 0.15,
        "spread": 0.12,
        "timing": 0.13,
        "invalidation": 0.10,
    }
    if not supplied:
        return {
            "entry_quality_score": None,
            "entry_quality_grade": "INSUFFICIENT_DATA",
            "coverage_pct": 0.0,
            "entry_gate": "WAIT",
            "reasons": ["Entry-quality evidence is unavailable; APEX will not invent a precision-entry score."],
        }
    denominator = sum(weights[k] for k in supplied)
    score = round(sum(supplied[k] * weights[k] for k in supplied) / denominator, 1)
    if coverage < 50:
        grade, gate = "INSUFFICIENT_DATA", "WAIT"
    elif score >= 90:
        grade, gate = "A+", "ENTRY_ELIGIBLE"
    elif score >= 82:
        grade, gate = "A", "ENTRY_ELIGIBLE"
    elif score >= 74:
        grade, gate = "B+", "ENTRY_SELECTIVE"
    elif score >= 65:
        grade, gate = "B", "ENTRY_SELECTIVE"
    else:
        grade, gate = "C_OR_LOWER", "WAIT"
    reasons = []
    if supplied.get("level_precision", 100) < 70:
        reasons.append("Entry is not sufficiently close to a defined structural level.")
    if supplied.get("momentum", 100) < 70:
        reasons.append("Immediate momentum confirmation is weak.")
    if supplied.get("spread", 100) < 65:
        reasons.append("Option spread quality may impair a fast premium scalp.")
    if supplied.get("invalidation", 100) < 70:
        reasons.append("The invalidation point is not sufficiently clear.")
    if not reasons:
        reasons.append("Entry evidence is aligned for the selected function, subject to manual confirmation.")
    return {
        "entry_quality_score": score,
        "entry_quality_grade": grade,
        "coverage_pct": coverage,
        "entry_gate": gate,
        "components": supplied,
        "reasons": reasons,
        "empirical_status": "PRIOR_PENDING_CALIBRATION",
    }


def build_momentum_lifecycle(*, position: Optional[Mapping[str, Any]] = None,
                             current_premium: Optional[float] = None,
                             profit_expansion_target: float = DEFAULT_PROFIT_EXPANSION,
                             adverse_exit_threshold: float = DEFAULT_ADVERSE_EXIT,
                             momentum_state: str = "UNKNOWN",
                             entry_quality: Optional[Mapping[str, Any]] = None,
                             now: Optional[datetime] = None) -> Dict[str, Any]:
    p = dict(position or {})
    entry = _num(p.get("option_entry_price"))
    current = _num(current_premium if current_premium is not None else p.get("option_current_price"))
    profit_target = max(0.01, _num(profit_expansion_target, DEFAULT_PROFIT_EXPANSION))
    adverse = _clamp(_num(adverse_exit_threshold, DEFAULT_ADVERSE_EXIT), MIN_ADVERSE_EXIT, MAX_ADVERSE_EXIT)
    trade_function = str(p.get("trade_function") or "MOMENTUM_BURST").upper()
    status = str(p.get("status") or "UNKNOWN").upper()
    ts = now or datetime.now(timezone.utc)

    base = {
        "version": "PHASE_36",
        "advisory_only": True,
        "confirmation_gated": True,
        "broker_action": "NONE",
        "evaluated_at": ts.isoformat(),
        "trade_function": trade_function,
        "entry_quality": dict(entry_quality or p.get("entry_quality") or {}),
        "entry_premium": entry or None,
        "current_premium": current or None,
        "profit_expansion_target": profit_target,
        "adverse_exit_threshold": adverse,
        "profit_trigger_premium": round(entry + profit_target, 2) if entry else None,
        "adverse_trigger_premium": round(max(0.01, entry - adverse), 2) if entry else None,
        "momentum_state": str(momentum_state or "UNKNOWN").upper(),
    }
    if status != "OPEN":
        return {**base, "lifecycle_state": "INACTIVE", "recommendation": "OBSERVE",
                "premium_change": None, "reason": "No open manually confirmed position is available."}
    if entry <= 0:
        return {**base, "lifecycle_state": "AWAITING_ENTRY_PREMIUM", "recommendation": "SYNC_ENTRY",
                "premium_change": None, "reason": "The actual option fill premium is required before lifecycle management can begin."}
    if current <= 0:
        return {**base, "lifecycle_state": "AWAITING_LIVE_PREMIUM", "recommendation": "SYNC_PREMIUM",
                "premium_change": None, "reason": "Enter the current option premium to evaluate the trade."}

    change = round(current - entry, 2)
    if change <= -adverse:
        state, recommendation = "ENTRY_THESIS_FAILED", "EXIT_NOW"
        reason = f"Premium is ${abs(change):.2f} below entry, beyond the governed ${adverse:.2f} adverse threshold."
    elif change >= profit_target:
        state, recommendation = "EXPANSION_OBJECTIVE_REACHED", "TAKE_PROFIT"
        reason = f"Premium expanded ${change:.2f} from entry and reached the ${profit_target:.2f} momentum objective."
    elif change < 0:
        state, recommendation = "DEFENDING_ENTRY", "PROTECT"
        reason = f"Premium is ${abs(change):.2f} below entry; the precision-entry thesis is under pressure."
    elif str(momentum_state).upper() in {"ACCELERATING", "EXPANDING", "STRONG"}:
        state, recommendation = "MOMENTUM_EXPANDING", "HOLD"
        reason = "Premium is favorable and institutional momentum remains active."
    elif change > 0:
        state, recommendation = "PROFIT_NOT_YET_CONFIRMED", "PROTECT_PROFIT"
        reason = "Premium is favorable but has not reached the expansion objective; protect against reversal."
    else:
        state, recommendation = "ENTRY_TEST", "HOLD_TIGHT"
        reason = "Premium remains near entry; require immediate confirmation or exit on thesis failure."
    return {
        **base,
        "lifecycle_state": state,
        "recommendation": recommendation,
        "premium_change": change,
        "premium_change_dollars_per_contract": round(change * 100.0, 2),
        "reason": reason,
        "primary_rule": "ENTRY_FIRST",
        "time_rule": "SECONDARY_TO_PREMIUM_AND_STRUCTURE",
        "execution_note": "Recommendation only. APEX does not place or close the broker order.",
    }
