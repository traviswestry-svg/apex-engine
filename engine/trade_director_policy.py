"""APEX Trade Director Phase 8 — Real-Time Management Policy Engine.

Transforms existing Trade Director evidence into a stable, confirmation-gated
management policy. It performs no import-time I/O, starts no workers, requests no
market data, and never sends or modifies broker orders.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

_ACTION_RANK = {
    "HOLD": 0, "PROTECT_PROFIT": 1, "MOVE_STOP_BE": 1,
    "TAKE_PARTIAL": 2, "TRIM_25": 2, "TRIM_50": 2, "TRIM_75": 2,
    "EXIT_OR_REDUCE": 3, "EXIT": 3,
}


def _f(v: Any, default: float = 0.0) -> float:
    try: return float(v)
    except (TypeError, ValueError): return default


def _normalize(action: Any) -> str:
    a=str(action or "HOLD").upper().strip()
    if a == "EXIT_OR_REDUCE": return "EXIT"
    if a == "TAKE_PARTIAL": return "TRIM_50"
    return a if a in _ACTION_RANK else "HOLD"


def _more_defensive(a: str, b: str) -> str:
    return a if _ACTION_RANK.get(a, 0) >= _ACTION_RANK.get(b, 0) else b


def _regime(health: Dict[str, Any], position_intelligence: Dict[str, Any]) -> Dict[str, Any]:
    ep=(position_intelligence or {}).get("exit_probability") or {}
    mtf=(position_intelligence or {}).get("multi_timeframe_alignment") or {}
    cont=_f(ep.get("continuation_probability"), 50)
    reversal=_f(ep.get("reversal_probability"), 100-cont)
    align=_f(mtf.get("score"), 50)
    trend=str((health or {}).get("trend") or "STABLE").upper()
    available=int(mtf.get("available") or 0)
    if available < 2:
        name="DATA_LIMITED"; posture="Require stronger confirmation before changing posture."
    elif reversal >= 68 or trend == "DETERIORATING" and align < 45:
        name="EXHAUSTION_RISK"; posture="Prioritize capital protection and fast confirmation."
    elif align >= 72 and cont >= 65 and trend != "DETERIORATING":
        name="TREND_CONTINUATION"; posture="Allow the winner room while structure remains intact."
    elif align <= 38:
        name="CONFLICTED"; posture="Reduce exposure to conflicting timeframe evidence."
    else:
        name="BALANCED_AUCTION"; posture="Use measured trims and structural stops instead of conviction holding."
    return {"name":name,"posture":posture,"alignment":round(align,1),"continuation":round(cont,1),"reversal":round(reversal,1),"data_points":available}


def build_management_policy(base_recommendation: Any, confidence: Any, health_engine: Dict[str, Any],
                            position_intelligence: Dict[str, Any], adaptive_guidance: Optional[Dict[str, Any]]=None,
                            prior_state: Optional[Dict[str, Any]]=None) -> Dict[str, Any]:
    """Return a stable advisory action and the next small in-position state."""
    prior_state=dict(prior_state or {})
    base=_normalize(base_recommendation)
    learned=_normalize((adaptive_guidance or {}).get("adaptive_recommendation") or base)
    candidate=_more_defensive(base, learned)
    health=_f((health_engine or {}).get("score"), 50)
    conf=_f(confidence, 50)
    regime=_regime(health_engine, position_intelligence)
    ep=(position_intelligence or {}).get("exit_probability") or {}
    reversal=_f(ep.get("reversal_probability"), regime["reversal"])
    mtf=(position_intelligence or {}).get("multi_timeframe_alignment") or {}
    opposing=int(mtf.get("opposing") or 0)

    # Independent safety guards. These only escalate protection.
    guards=[]
    if health < 42:
        candidate=_more_defensive(candidate,"EXIT"); guards.append("Trade Health is below 42.")
    elif health < 58:
        candidate=_more_defensive(candidate,"PROTECT_PROFIT"); guards.append("Trade Health is below 58.")
    if reversal >= 72:
        candidate=_more_defensive(candidate,"EXIT"); guards.append("Reversal probability is at least 72%.")
    elif reversal >= 58:
        candidate=_more_defensive(candidate,"TRIM_50"); guards.append("Reversal probability is elevated.")
    if opposing >= 3:
        candidate=_more_defensive(candidate,"TRIM_50"); guards.append("Three or more cached timeframes oppose the trade.")

    previous=_normalize(prior_state.get("policy_action") or base)
    pending=_normalize(prior_state.get("pending_action") or candidate)
    streak=int(prior_state.get("confirmation_streak") or 0)
    # Escalations apply immediately. De-escalations require three consecutive cycles.
    if _ACTION_RANK.get(candidate,0) >= _ACTION_RANK.get(previous,0):
        final=candidate; pending=candidate; streak=1
        stability="ESCALATION_CONFIRMED" if candidate != previous else "STABLE"
    else:
        if pending == candidate: streak += 1
        else: pending=candidate; streak=1
        if streak >= 3 and conf >= 70:
            final=candidate; stability="DE_ESCALATION_CONFIRMED"
        else:
            final=previous; stability="DE_ESCALATION_HELD"

    if final == "EXIT" and (health < 42 or reversal >= 72):
        gate="IMMEDIATE_PROTECTION"
    elif _ACTION_RANK.get(final,0) >= 2:
        gate="USER_CONFIRMATION_REQUIRED"
    elif final == "PROTECT_PROFIT":
        gate="PREPARE_ACTION"
    else:
        gate="MONITOR"

    evidence=[]
    evidence.extend(guards)
    evidence.append(f"Regime: {regime['name'].replace('_',' ').title()}.")
    evidence.append(f"Trade Health {round(health,1)}/100; continuation {regime['continuation']}%; reversal {round(reversal,1)}%.")
    if learned != base:
        evidence.append(f"Adaptive profile proposed {learned.replace('_',' ')} versus base {base.replace('_',' ')}.")
    if stability == "DE_ESCALATION_HELD":
        evidence.append(f"Less-defensive action held until 3 confirmations ({streak}/3).")

    next_state={"policy_action":final,"pending_action":pending,"confirmation_streak":streak,"regime":regime["name"]}
    return {
        "version":"PHASE_8", "policy_action":final, "candidate_action":candidate,
        "base_recommendation":base, "adaptive_recommendation":learned,
        "confidence":round(conf,1), "trade_health":round(health,1),
        "regime":regime, "confirmation_gate":gate, "stability_state":stability,
        "confirmation_streak":streak, "evidence":evidence[:6], "state":next_state,
        "requires_user_action":gate in {"USER_CONFIRMATION_REQUIRED","IMMEDIATE_PROTECTION"},
        "execution_enabled":False,
        "safety_note":"Phase 8 stabilizes and audits advisory management decisions. It never sends or modifies broker orders.",
    }
