"""APEX 20.0 Institutional Decision Engine.

Read-only evidence fusion across the APEX 19.x intelligence suite. The engine
produces one explainable decision object and never submits, previews, or mutates
broker orders.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List
import math

from .institutional_dealer_positioning_engine import build_dealer_positioning
from .institutional_options_flow_engine import build_options_flow_intelligence
from .institutional_probability_engine import build_probability_engine
from .adaptive_learning_engine_v2 import build_adaptive_learning_v2
from .institutional_market_structure_engine import build_institutional_market_structure

VERSION = "13.0.0_INSTITUTIONAL_DECISION_ENGINE"
SEMANTIC_VERSION = "13.0.0"


def _f(v: Any, d: float = 0.0) -> float:
    try:
        n = float(v)
        return d if math.isnan(n) or math.isinf(n) else n
    except Exception:
        return d


def _clip(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return round(max(lo, min(hi, v)), 1)


def _dir(v: Any) -> str:
    s = str(v or "").upper()
    if any(x in s for x in ("BULL", "CALL", "UP", "RISING", "BUY", "ABOVE")):
        return "BULLISH"
    if any(x in s for x in ("BEAR", "PUT", "DOWN", "FALLING", "SELL", "BELOW")):
        return "BEARISH"
    return "NEUTRAL"


def _strategy(bias: str, regime: str, confidence: float, probability: Dict[str, Any]) -> Dict[str, Any]:
    trend = _f(probability.get("trend_day_probability"), 50)
    if bias == "NEUTRAL":
        name = "IRON_CONDOR_OR_STAND_DOWN" if regime == "BALANCE" else "STAND_DOWN"
        rationale = "Directional evidence is not sufficiently aligned."
    elif regime == "EXPANSION" and trend >= 60:
        name = "DIRECTIONAL_DEBIT_SPREAD"
        rationale = "Directional evidence and expansion probability favor defined-risk participation."
    elif regime == "MEAN_REVERSION":
        name = "DEFINED_RISK_CREDIT_SPREAD"
        rationale = "Positive-gamma or balance conditions favor premium-defined mean reversion."
    else:
        name = "PULLBACK_DIRECTIONAL"
        rationale = "Wait for price confirmation at a governed structure level rather than chase."
    return {"name": name, "bias": bias, "confidence": confidence, "rationale": rationale,
            "advisory_only": True, "requires_option_chain_validation": True}


def build_institutional_decision(last: Dict[str, Any], history: Any = None) -> Dict[str, Any]:
    last = last if isinstance(last, dict) else {}
    dealer = build_dealer_positioning(last)
    flow = build_options_flow_intelligence(last)
    structure = build_institutional_market_structure(last)
    probability = build_probability_engine(last, dealer, flow, structure)
    learning = build_adaptive_learning_v2(last, history)

    evidence: List[Dict[str, Any]] = []
    specs = [
        ("dealer", _dir(dealer.get("bias")), abs(_f(dealer.get("pressure_score"))), 0.22, dealer.get("available", False)),
        ("flow", _dir(flow.get("bias")), abs(_f(flow.get("net_flow_score"))), 0.22, flow.get("available", False)),
        ("market_structure", _dir(structure.get("direction")), 70.0 if structure.get("state") == "READY" else 45.0, 0.24, structure.get("state") != "DEGRADED"),
        ("probability", "BULLISH" if _f((probability.get("directional") or {}).get("bullish"), 50) >= 55 else "BEARISH" if _f((probability.get("directional") or {}).get("bearish"), 50) >= 55 else "NEUTRAL", abs(_f((probability.get("directional") or {}).get("bullish"), 50)-50)*2, 0.24, probability.get("state") != "DEGRADED"),
        ("adaptive_learning", "NEUTRAL", min(100, _f(learning.get("sample_size"))/30*100), 0.08, learning.get("sample_size", 0) > 0),
    ]
    bull = bear = coverage = 0.0
    for source, direction, confidence, weight, available in specs:
        if not available:
            evidence.append({"source": source, "available": False, "direction": "NEUTRAL", "confidence": 0.0, "weight": weight, "contribution": 0.0})
            continue
        confidence = _clip(confidence)
        contribution = confidence * weight
        coverage += weight
        if direction == "BULLISH": bull += contribution
        elif direction == "BEARISH": bear += contribution
        evidence.append({"source": source, "available": True, "direction": direction, "confidence": confidence, "weight": weight, "contribution": round(contribution, 2)})

    total_directional = bull + bear
    agreement = abs(bull-bear) / max(1.0, total_directional) * 100
    bias = "BULLISH" if bull-bear >= 8 else "BEARISH" if bear-bull >= 8 else "NEUTRAL"
    conflicts = [x["source"] for x in evidence if x["available"] and x["direction"] not in ("NEUTRAL", bias)] if bias != "NEUTRAL" else [x["source"] for x in evidence if x["available"] and x["direction"] != "NEUTRAL"]
    confidence = _clip(35 + agreement*0.45 + coverage*20 - len(conflicts)*5)

    gamma_regime = dealer.get("gamma_regime")
    day_class = (structure.get("day_type_probability") or {}).get("classification")
    regime = "EXPANSION" if gamma_regime == "NEGATIVE_GAMMA" or day_class == "TREND_FAVORED" else "MEAN_REVERSION" if gamma_regime == "POSITIVE_GAMMA" else "BALANCE"
    fresh = not (last.get("data_fresh") is False or (last.get("market_state") or {}).get("data_fresh") is False or "STALE_DATA" in probability.get("warnings", []))
    blockers = []
    if not fresh: blockers.append("STALE_DATA")
    if coverage < 0.55: blockers.append("INSUFFICIENT_EVIDENCE_COVERAGE")
    if bias == "NEUTRAL": blockers.append("NO_DIRECTIONAL_EDGE")
    if confidence < 62: blockers.append("CONFIDENCE_BELOW_THRESHOLD")
    execution_eligible = not blockers

    bull_prob = _f((probability.get("directional") or {}).get("bullish"), 50)
    scenarios = [
        {"name": "BULL_CASE", "probability": bull_prob, "confirmation": "Acceptance above governed resistance or value with persistent bullish flow."},
        {"name": "BEAR_CASE", "probability": round(100-bull_prob,1), "confirmation": "Acceptance below governed support or value with persistent bearish flow."},
        {"name": "BALANCE_CASE", "probability": _clip(100-abs(bull_prob-50)*2), "confirmation": "Repeated rejection at both sides of value and declining directional persistence."},
    ]
    headline = f"{bias} {regime.replace('_',' ')} — conviction {confidence:.0f}/100"
    narrative = (
        f"Market structure is {_dir(structure.get('direction')).lower()}, dealer positioning is {_dir(dealer.get('bias')).lower()}, "
        f"and institutional flow is {_dir(flow.get('bias')).lower()}. The probability engine assigns {bull_prob:.1f}% bullish direction. "
        f"Evidence agreement is {agreement:.1f}% with {len(conflicts)} conflicting source(s)."
    )
    decision = "TRADE_CANDIDATE" if execution_eligible else "WATCH" if fresh and coverage >= .55 else "STAND_DOWN"
    return {
        "ok": True, "version": VERSION, "semantic_version": SEMANTIC_VERSION,
        "evaluated_at": datetime.now(timezone.utc).isoformat(), "ticker": str(last.get("ticker") or "SPX"),
        "decision": decision, "bias": bias, "regime": regime, "confidence": confidence,
        "headline": headline, "narrative": narrative, "execution_eligible": execution_eligible,
        "blocking_reasons": blockers, "conflicting_sources": conflicts, "evidence_coverage": round(coverage,2),
        "agreement_score": round(agreement,1), "evidence": evidence, "scenarios": scenarios,
        "strategy": _strategy(bias, regime, confidence, probability),
        "levels": structure.get("institutional_levels") or structure.get("levels") or {},
        "components": {"dealer": dealer, "flow": flow, "market_structure": structure, "probability": probability, "adaptive_learning": learning},
        "guardrails": {"read_only": True, "broker_mutation": False, "automatic_execution": False,
                       "human_confirmation_required": True, "existing_kill_switch_authoritative": True,
                       "does_not_change_execution_permissions": True}
    }
