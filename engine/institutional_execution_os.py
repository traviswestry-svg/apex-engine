"""APEX 11.1 Institutional Execution OS.

History-free execution quality, fill simulation, position quality and morning
readiness helpers.  All outputs are deterministic from the current live state;
no historical win-rate or calibrated-probability claims are made.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional

VERSION = "11.1.0_INSTITUTIONAL_EXECUTION_OS"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return default if math.isnan(out) or math.isinf(out) else out
    except Exception:
        return default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _first(mapping: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


def _premium(result: Mapping[str, Any]) -> Mapping[str, Any]:
    value = result.get("premium_strategy") or result.get("premium_recommendation") or {}
    return value if isinstance(value, Mapping) else {}


def _chain(result: Mapping[str, Any], premium: Mapping[str, Any]) -> Mapping[str, Any]:
    for value in (
        premium.get("chain_quality"), result.get("chain_quality"),
        (result.get("market_state") or {}).get("chain_quality") if isinstance(result.get("market_state"), Mapping) else None,
    ):
        if isinstance(value, Mapping):
            return value
    return {}


def _legs(premium: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = premium.get("legs") or premium.get("structure_legs") or premium.get("contracts") or []
    return [x for x in raw if isinstance(x, Mapping)] if isinstance(raw, list) else []


def build_execution_snapshot(result: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    result = result or {}
    premium = _premium(result)
    chain = _chain(result, premium)
    legs = _legs(premium)

    quality_score = _num(_first(chain, "quality_score", "score", default=50), 50)
    gate = str(_first(chain, "action", "gate", "status", default="UNKNOWN")).upper()
    valid_count = int(_num(_first(chain, "valid_contract_count", "valid_count", default=len(legs)), len(legs)))

    bid = _num(_first(premium, "bid", "net_bid", "executable_bid", default=0))
    ask = _num(_first(premium, "ask", "net_ask", "executable_ask", default=0))
    mid = _num(_first(premium, "mid", "midpoint", "credit", "debit", "price", default=(bid + ask) / 2 if bid and ask else 0))
    spread = abs(ask - bid) if ask and bid else _num(_first(premium, "spread", "bid_ask_spread", default=0))
    spread_pct = spread / max(abs(mid), 0.01) * 100 if spread else 0.0

    quote_age = _num(_first(premium, "quote_age_seconds", "max_quote_age_seconds", default=_first(chain, "max_quote_age_seconds", "quote_age_seconds", default=0)))
    execution_conf = _num(_first(premium, "execution_confidence", default=_first(chain, "execution_confidence", default=0.5)), 0.5)
    if execution_conf <= 1.0:
        execution_conf *= 100

    liquidity_score = _clamp(
        quality_score * 0.55
        + _clamp(100 - spread_pct * 4) * 0.25
        + _clamp(100 - quote_age * 2) * 0.15
        + _clamp(valid_count * 12.5) * 0.05
    )
    fill_probability = _clamp(liquidity_score * 0.62 + execution_conf * 0.28 + _clamp(100 - spread_pct * 5) * 0.10)
    expected_slippage = round(max(0.0, spread * (1.0 - fill_probability / 100) + spread * 0.12), 3)
    time_to_fill = round(max(0.5, 12.0 - fill_probability * 0.105 + quote_age * 0.03), 1)

    risk = premium.get("risk") if isinstance(premium.get("risk"), Mapping) else {}
    max_loss = _num(_first(premium, "max_loss", default=_first(risk, "max_loss", default=0)))
    max_profit = _num(_first(premium, "max_profit", default=_first(risk, "max_profit", default=0)))
    rr = max_profit / max(max_loss, 0.01) if max_loss > 0 else 0.0
    risk_score = 70.0 if max_loss > 0 else 45.0
    if rr > 0:
        risk_score = _clamp(50 + min(rr, 3.0) * 15)

    market_open = bool(_first(result, "market_open", default=(result.get("market_status") or {}).get("is_open") if isinstance(result.get("market_status"), Mapping) else False))
    freshness_score = _clamp(100 - quote_age * 3) if quote_age else 60.0
    broker_ready = bool(_first(result, "broker_ready", "broker_connected", default=False))
    operational_score = 100.0 if market_open else 70.0
    if not broker_ready:
        operational_score -= 10

    execution_score = _clamp(
        liquidity_score * 0.34 + quality_score * 0.22 + freshness_score * 0.18
        + risk_score * 0.14 + operational_score * 0.12
    )
    if gate in {"SUPPRESS", "BLOCK", "FAIL"}:
        execution_score = min(execution_score, 39.0)
    if not premium:
        execution_score = min(execution_score, 25.0)

    position_score = _clamp(quality_score * 0.35 + liquidity_score * 0.30 + risk_score * 0.20 + execution_conf * 0.15)

    grade = "A" if execution_score >= 90 else "B" if execution_score >= 80 else "C" if execution_score >= 70 else "D" if execution_score >= 60 else "F"
    quality = "EXCELLENT" if execution_score >= 90 else "GOOD" if execution_score >= 80 else "ACCEPTABLE" if execution_score >= 70 else "POOR" if execution_score >= 50 else "BLOCKED"
    decision = "EXECUTABLE" if execution_score >= 80 and gate not in {"SUPPRESS", "BLOCK", "FAIL"} else "CAUTION" if execution_score >= 60 else "DO_NOT_EXECUTE"

    expected_fill = mid
    best_fill = mid + spread * 0.15 if mid else 0.0
    worst_fill = mid - spread * 0.45 if mid else 0.0

    checks = {
        "recommendation_present": bool(premium),
        "chain_gate_passed": gate not in {"SUPPRESS", "BLOCK", "FAIL"},
        "quotes_present": bool(mid or (bid and ask)),
        "quotes_fresh": quote_age <= 15 if quote_age else False,
        "liquidity_acceptable": liquidity_score >= 70,
        "risk_defined": max_loss > 0,
        "market_open": market_open,
        "broker_ready": broker_ready,
    }
    blockers = [name for name, passed in checks.items() if not passed and name in {"recommendation_present", "chain_gate_passed", "quotes_present", "liquidity_acceptable", "risk_defined"}]

    return {
        "ok": True,
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execution_score": round(execution_score, 1),
        "execution_grade": grade,
        "execution_quality": quality,
        "execution_decision": decision,
        "position_quality_score": round(position_score, 1),
        "liquidity_score": round(liquidity_score, 1),
        "fill_probability": round(fill_probability / 100, 3),
        "expected_slippage": expected_slippage,
        "estimated_time_to_fill_seconds": time_to_fill,
        "pricing": {"bid": bid, "ask": ask, "mid": round(mid, 3), "spread": round(spread, 3), "spread_pct": round(spread_pct, 2)},
        "fill_simulation": {
            "best_fill": round(best_fill, 3), "expected_fill": round(expected_fill, 3),
            "worst_fill": round(worst_fill, 3), "partial_fill_risk": "LOW" if fill_probability >= 85 else "MEDIUM" if fill_probability >= 65 else "HIGH",
        },
        "risk": {"max_profit": max_profit, "max_loss": max_loss, "reward_risk": round(rr, 2), "risk_quality_score": round(risk_score, 1)},
        "chain": {"quality_score": round(quality_score, 1), "gate": gate, "valid_contract_count": valid_count, "quote_age_seconds": quote_age},
        "checks": checks,
        "blocking_items": blockers,
        "history_free": True,
        "note": "Scores describe current execution conditions; they are not historical win probabilities.",
    }


def build_morning_readiness(*, system_checks: Mapping[str, Any], execution: Mapping[str, Any], market_open: bool = False) -> Dict[str, Any]:
    weights = {
        "application": 10, "database": 10, "data_freshness": 15, "providers": 10,
        "recommendation_ledger": 10, "execution": 10, "clock": 5,
        "version_consistency": 5, "alerts": 5, "scheduler": 10,
    }
    status_value = {"PASS": 100, "DISABLED": 70, "BLOCKED": 40, "WARN": 55, "FAIL": 0}
    weighted = 0.0
    used = 0.0
    components: Dict[str, Any] = {}
    blockers = []
    critical = {"application", "database", "data_freshness", "recommendation_ledger"}
    for name, weight in weights.items():
        item = system_checks.get(name, {}) if isinstance(system_checks, Mapping) else {}
        status = str(item.get("status", "WARN")).upper()
        points = status_value.get(status, 55)
        weighted += points * weight
        used += weight
        components[name] = {"status": status, "weight": weight, "score": points, "summary": item.get("summary")}
        if name in critical and status in {"FAIL", "BLOCKED"}:
            blockers.append(name)

    execution_score = _num(execution.get("execution_score"), 0)
    weighted += execution_score * 10
    used += 10
    components["execution_intelligence"] = {"status": execution.get("execution_decision", "UNKNOWN"), "weight": 10, "score": execution_score}

    score = round(weighted / max(used, 1), 1)
    if blockers:
        mode, status = "DO_NOT_TRADE", "NOT_READY"
    elif not market_open:
        mode, status = "ANALYSIS_ONLY", "READY_FOR_ANALYSIS" if score >= 75 else "CAUTION"
    elif score >= 90:
        mode, status = "FULLY_OPERATIONAL", "READY"
    elif score >= 75:
        mode, status = "DEGRADED", "CAUTION"
    else:
        mode, status = "DO_NOT_TRADE", "NOT_READY"
    return {
        "ok": True, "version": VERSION, "generated_at": datetime.now(timezone.utc).isoformat(),
        "score": score, "status": status, "trading_mode": mode, "market_open": market_open,
        "blocking_items": blockers, "components": components,
        "recommendation": "READY TO TRADE" if mode == "FULLY_OPERATIONAL" else "ANALYSIS ONLY" if mode == "ANALYSIS_ONLY" else "DO NOT TRADE" if mode == "DO_NOT_TRADE" else "TRADE WITH CAUTION",
    }
