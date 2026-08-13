"""APEX 18.0.9 — Institutional Premium Intelligence.

Read-only portfolio ranking for supported 0DTE credit structures.  It evaluates
bull-put, bear-call, and iron-condor candidates under one common regime/EV model,
then publishes the best eligible structure or NO_TRADE.  It never authorizes or
submits an order.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .premium_discipline import APPROVE, evaluate_premium_eligibility
from .premium_strategy import (
    BEAR_CALL, BULL_PUT, IRON_CONDOR, _apply_chain_pricing, _build_legs,
    _credit_quality_check, _pull, _vix_regime,
)
from .premium_chain_pricing import price_structure

VERSION = "18.0.9_INSTITUTIONAL_PREMIUM_INTELLIGENCE"
SUPPORTED = (BULL_PUT, BEAR_CALL, IRON_CONDOR)


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return default if value is None else float(value)
    except (TypeError, ValueError):
        return default


def classify_premium_regime(last_result: Dict[str, Any]) -> Dict[str, Any]:
    b = _pull(last_result)
    auction = str(b.get("auction_state") or "").upper()
    gamma = str(b.get("gamma_regime") or "").upper()
    event = str(((last_result.get("events") or {}).get("event_regime") or "")).upper()
    exp = _f(b.get("expansion_probability"))
    mr = _f(b.get("mean_reversion_probability"))
    pin = _f(b.get("pin_probability"))
    direction = str(b.get("direction") or b.get("institutional_bias") or "").upper()

    if event in {"EVENT_DAY", "PRE_EVENT_COMPRESSION"}:
        name = "EVENT_RISK"
    elif exp >= 65 and "NEGATIVE" in gamma:
        name = "GAMMA_VACUUM"
    elif exp >= 60 or any(x in auction for x in ("BREAKOUT", "BREAKDOWN", "DISCOVERY", "TREND")):
        name = "TREND_EXPANSION"
    elif pin >= 65 and "POSITIVE" in gamma:
        name = "GAMMA_PIN"
    elif mr >= 60 or any(x in auction for x in ("BALANC", "ROTAT", "VALUE")):
        name = "MEAN_REVERSION"
    else:
        name = "MIXED_TRANSITION"

    return {
        "name": name,
        "direction": direction or "NEUTRAL",
        "auction_state": auction or "UNKNOWN",
        "gamma_regime": gamma or "UNKNOWN",
        "mean_reversion_probability": round(mr, 1),
        "expansion_probability": round(exp, 1),
        "pin_probability": round(pin, 1),
        "vix_regime": _vix_regime(_f(b.get("vix")), str(b.get("vol_regime") or "")),
    }


def _direction_fit(strategy: str, regime: Dict[str, Any], b: Dict[str, Any]) -> float:
    direction = str(regime.get("direction") or "").upper()
    flow = str(b.get("flow_bias") or "").upper()
    score = 50.0
    bullish = any(x in direction + " " + flow for x in ("BULL", "CALL", "UP"))
    bearish = any(x in direction + " " + flow for x in ("BEAR", "PUT", "DOWN"))
    if strategy == BULL_PUT:
        score += 35 if bullish else -30 if bearish else 0
    elif strategy == BEAR_CALL:
        score += 35 if bearish else -30 if bullish else 0
    else:
        score += 30 if regime["name"] in {"GAMMA_PIN", "MEAN_REVERSION"} else -25 if regime["name"] in {"TREND_EXPANSION", "GAMMA_VACUUM"} else 0
    return max(0.0, min(100.0, score))


def _expected_value(legs: Dict[str, Any]) -> Dict[str, Any]:
    pop = _f(legs.get("pop"))
    if pop > 1:
        pop /= 100.0
    max_profit = _f(legs.get("max_profit"))
    max_loss = _f(legs.get("max_loss"))
    if not pop or max_profit <= 0 or max_loss <= 0:
        return {"available": False, "value_per_contract": None, "normalized": 0.0}
    ev = pop * max_profit - (1.0 - pop) * max_loss
    capital = max_profit + max_loss
    normalized = 50.0 + (ev / capital * 100.0 if capital else 0.0)
    return {
        "available": True,
        "probability_of_profit": round(pop, 4),
        "max_profit": round(max_profit, 2),
        "max_loss": round(max_loss, 2),
        "value_per_contract": round(ev, 2),
        "normalized": round(max(0.0, min(100.0, normalized)), 1),
    }


def rank_premium_strategies(
    last_result: Dict[str, Any], *, chain_fetcher=None, now_et=None,
    symbol: str = "SPX", expiration: str = "", width: float = 10.0,
    threshold: Optional[float] = None, weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Rank all currently supported credit structures using common inputs."""
    if not isinstance(last_result, dict) or not last_result.get("institutional_intelligence"):
        return {"version": VERSION, "available": False, "recommendation": "NO_TRADE", "rankings": [], "reason": "Institutional intelligence is unavailable.", "execution_authority": False}

    b = _pull(last_result)
    regime = classify_premium_regime(last_result)
    rankings: List[Dict[str, Any]] = []
    for strategy in SUPPORTED:
        legs = _build_legs(strategy, b, width, now_et=now_et) if b.get("price") else {}
        pricing = price_structure(strategy=strategy, legs=legs, symbol=symbol,
                                  expiration=expiration, chain_fetcher=chain_fetcher, width=width)
        legs = _apply_chain_pricing(strategy, legs, pricing, b, width)
        candidate = {
            "available": True, "strategy": strategy, "premium_kind": "CREDIT",
            "confidence": round((_direction_fit(strategy, regime, b) + _f(b.get("overall_score"))) / 2.0, 1),
            "case": f"18.0.9_{regime['name']}", "legs": legs, "pricing": pricing,
            "tradeable": bool(legs.get("economics_available")),
            "economics_available": bool(legs.get("economics_available")),
        }
        quality_ok, quality_failures = _credit_quality_check(strategy, legs, b, last_result.get("events") or {}) if legs else (False, ["No structure legs available."])
        if not quality_ok:
            candidate["case"] += "->QUALITY_REJECT"
            candidate["tradeable"] = False
        gate = evaluate_premium_eligibility(last_result, candidate, threshold=threshold, weights=weights)
        ev = _expected_value(legs)
        direction_fit = _direction_fit(strategy, regime, b)
        execution = _f(legs.get("execution_confidence"), 0.0) * 100.0
        if not pricing.get("available"):
            execution = 0.0
        score = round(
            0.38 * _f(gate.get("score")) +
            0.27 * _f(ev.get("normalized")) +
            0.20 * direction_fit +
            0.15 * execution, 1)
        eligible = gate.get("decision") == APPROVE and quality_ok and ev.get("available")
        rankings.append({
            "rank": 0, "strategy": strategy, "eligible": bool(eligible),
            "institutional_score": score, "eligibility": gate,
            "expected_value": ev, "direction_fit": round(direction_fit, 1),
            "execution_confidence": round(execution, 1),
            "quality_ok": quality_ok, "quality_failures": quality_failures,
            "candidate": candidate,
        })

    rankings.sort(key=lambda x: (x["eligible"], x["institutional_score"]), reverse=True)
    for i, item in enumerate(rankings, 1):
        item["rank"] = i
    winner = next((r for r in rankings if r["eligible"]), None)
    return {
        "version": VERSION, "available": True, "advisory_only": True,
        "execution_authority": False, "regime": regime,
        "recommendation": winner["strategy"] if winner else "NO_TRADE",
        "recommended_score": winner["institutional_score"] if winner else 0.0,
        "recommended_candidate": winner["candidate"] if winner else None,
        "rankings": rankings,
        "unsupported_structures": ["IRON_BUTTERFLY", "BROKEN_WING_BUTTERFLY", "CALENDAR", "DIAGONAL"],
        "unsupported_note": "Multi-expiration and asymmetric structures remain excluded until canonical chain, fill, and replay support exists.",
    }
