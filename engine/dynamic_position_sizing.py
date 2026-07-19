"""APEX 18.1.1 — Dynamic Position Sizing Intelligence.

Advisory-only contract sizing for premium strategies. Sizing is bounded by
per-trade risk, remaining daily loss capacity, confidence, historical sample
readiness, expectancy quality, and regime drift. It never submits an order.
"""
from __future__ import annotations

import math
import os
from typing import Any, Dict, Optional

VERSION = "18.1.1_DYNAMIC_POSITION_SIZING"


def _f(v: Any, d: float = 0.0) -> float:
    try:
        return d if v is None else float(v)
    except (TypeError, ValueError):
        return d


def _envf(name: str, default: float) -> float:
    return _f(os.getenv(name), default)


def _envi(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def build_position_sizing(expectancy: Dict[str, Any], *, daily_realized_pnl: float = 0.0,
                          open_risk: float = 0.0, account_size: Optional[float] = None,
                          max_risk_per_trade: Optional[float] = None,
                          max_daily_loss: Optional[float] = None,
                          max_contracts: Optional[int] = None) -> Dict[str, Any]:
    """Return a conservative advisory contract count and complete rationale."""
    per_trade = max(0.0, _f(max_risk_per_trade, _envf("TRADE_MAX_RISK_PER_TRADE", 1000.0)))
    daily_cap = max(0.0, _f(max_daily_loss, _envf("TRADE_MAX_DAILY_LOSS", 2500.0)))
    contract_cap = max(0, int(max_contracts if max_contracts is not None else _envi("APEX_PREMIUM_MAX_CONTRACTS", 3)))
    acct = max(0.0, _f(account_size, _envf("ACCOUNT_SIZE", 0.0)))

    ranking = expectancy.get("premium_intelligence") or {}
    recommendation = expectancy.get("recommendation") or ranking.get("recommendation") or "NO_TRADE"
    top = next((r for r in ranking.get("rankings", []) if r.get("strategy") == recommendation), None)
    ev = (top or {}).get("expected_value") or {}
    max_loss_contract = _f(ev.get("max_loss"))
    confidence = _f((expectancy.get("confidence") or {}).get("overall"))
    playbook = (expectancy.get("regime_playbook") or {}).get(recommendation) or {}
    sample = int(_f(playbook.get("sample_size")))
    avg_pnl = _f(playbook.get("average_pnl"))
    drift = playbook.get("drift") or {}

    remaining_daily = max(0.0, daily_cap + min(0.0, _f(daily_realized_pnl)) - max(0.0, _f(open_risk)))
    account_cap = acct * 0.02 if acct > 0 else per_trade
    hard_budget = min(per_trade, remaining_daily, account_cap)
    raw_cap = math.floor(hard_budget / max_loss_contract) if max_loss_contract > 0 else 0

    blockers = []
    warnings = []
    if recommendation == "NO_TRADE" or not top or not top.get("eligible"):
        blockers.append("No eligible premium recommendation is available.")
    if max_loss_contract <= 0:
        blockers.append("Canonical maximum loss per contract is unavailable.")
    if remaining_daily <= 0:
        blockers.append("Daily loss capacity is exhausted after realized P/L and open risk.")
    if confidence < 55:
        blockers.append("Institutional confidence is below the 55 sizing floor.")
    if avg_pnl < 0 and sample >= 10:
        blockers.append("Regime-specific historical expectancy is negative.")

    confidence_mult = 0.0 if confidence < 55 else 0.50 if confidence < 70 else 0.75 if confidence < 85 else 1.0
    sample_mult = 0.50 if sample < 10 else 0.75 if sample < 20 else 1.0
    expectancy_mult = 0.50 if sample == 0 else 0.60 if avg_pnl <= 0 else 0.80 if avg_pnl < max_loss_contract * 0.05 else 1.0
    drift_mult = 0.75 if drift.get("available") and drift.get("state") == "DETERIORATING" else 1.0
    if sample < 20:
        warnings.append("Historical sample is still developing; size is reduced.")
    if drift_mult < 1:
        warnings.append("Recent regime expectancy is deteriorating; size is reduced.")

    scaled = math.floor(raw_cap * confidence_mult * sample_mult * expectancy_mult * drift_mult)
    contracts = 0 if blockers else min(contract_cap, max(1 if raw_cap >= 1 else 0, scaled))
    risk = round(contracts * max_loss_contract, 2)
    risk_pct = round(100.0 * risk / acct, 3) if acct > 0 else None

    return {
        "version": VERSION, "advisory_only": True, "execution_authority": False,
        "strategy": recommendation, "recommended_contracts": contracts,
        "max_loss_per_contract": round(max_loss_contract, 2) if max_loss_contract > 0 else None,
        "recommended_max_risk": risk, "account_risk_pct": risk_pct,
        "hard_budget": round(hard_budget, 2), "remaining_daily_loss_capacity": round(remaining_daily, 2),
        "limits": {"max_risk_per_trade": per_trade, "max_daily_loss": daily_cap,
                   "max_contracts": contract_cap, "account_size": acct or None,
                   "account_risk_cap_pct": 2.0},
        "multipliers": {"confidence": confidence_mult, "sample": sample_mult,
                        "expectancy": expectancy_mult, "drift": drift_mult},
        "evidence": {"confidence": confidence, "regime_sample_size": sample,
                     "regime_average_pnl": avg_pnl, "drift_state": drift.get("state")},
        "blockers": blockers, "warnings": warnings,
        "sizing_state": "BLOCKED" if blockers else "SIZED" if contracts > 0 else "ZERO_SIZE",
        "governance_note": "Sizing is advisory and cannot bypass Premium Discipline, portfolio risk limits, confirmation gates, or broker controls.",
    }
