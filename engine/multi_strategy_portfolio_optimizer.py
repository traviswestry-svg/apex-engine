"""APEX 18.1.2 — Multi-Strategy Portfolio Optimizer.

Advisory-only optimizer for the supported premium candidate set. It allocates a
bounded risk budget across eligible structures, prevents overlapping or
contradictory exposure, and publishes both selected and excluded candidates with
complete rationale. It never routes or authorizes an order.
"""
from __future__ import annotations

import itertools
import math
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

VERSION = "18.1.2_MULTI_STRATEGY_PORTFOLIO_OPTIMIZER"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return default if value is None else float(value)
    except (TypeError, ValueError):
        return default


def _envf(name: str, default: float) -> float:
    return _f(os.getenv(name), default)


def _envi(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _exposure(strategy: str) -> str:
    return {"BULL_PUT": "BULLISH", "BEAR_CALL": "BEARISH", "IRON_CONDOR": "NEUTRAL"}.get(strategy, "UNKNOWN")


def _pair_penalty(a: Dict[str, Any], b: Dict[str, Any]) -> Tuple[float, Optional[str]]:
    sa, sb = str(a.get("strategy")), str(b.get("strategy"))
    pair = {sa, sb}
    if "IRON_CONDOR" in pair:
        return 1.0, "Iron condor overlaps the directional credit-spread exposure."
    if pair == {"BULL_PUT", "BEAR_CALL"}:
        return 0.35, None  # bounded diversification, but economically condor-like
    if sa == sb:
        return 1.0, "Duplicate strategy-family exposure is prohibited."
    return 0.15, None


def _candidate_rows(expectancy: Dict[str, Any]) -> List[Dict[str, Any]]:
    intelligence = expectancy.get("premium_intelligence") or {}
    playbooks = expectancy.get("regime_playbook") or {}
    rows: List[Dict[str, Any]] = []
    for item in intelligence.get("rankings") or []:
        strategy = str(item.get("strategy") or "UNKNOWN")
        ev = item.get("expected_value") or {}
        pb = playbooks.get(strategy) or {}
        max_loss = _f(ev.get("max_loss"))
        expected_value = _f(ev.get("value_per_contract"))
        historical_ev = _f(pb.get("average_pnl")) if int(_f(pb.get("sample_size"))) >= 10 else 0.0
        blended_ev = expected_value if not historical_ev else 0.65 * expected_value + 0.35 * historical_ev
        rows.append({
            "strategy": strategy,
            "eligible": bool(item.get("eligible")),
            "institutional_score": _f(item.get("institutional_score")),
            "expected_value_per_contract": round(expected_value, 2),
            "historical_average_pnl": round(historical_ev, 2),
            "blended_expected_value": round(blended_ev, 2),
            "max_loss_per_contract": round(max_loss, 2),
            "probability_of_profit": ev.get("probability_of_profit"),
            "execution_confidence": _f(item.get("execution_confidence")),
            "exposure": _exposure(strategy),
            "source_rank": item.get("rank"),
            "candidate": item.get("candidate"),
        })
    return rows


def build_portfolio_optimizer(
    expectancy: Dict[str, Any], *, daily_realized_pnl: float = 0.0,
    open_risk: float = 0.0, account_size: Optional[float] = None,
    max_portfolio_risk: Optional[float] = None, max_daily_loss: Optional[float] = None,
    max_positions: Optional[int] = None, max_contracts_per_strategy: Optional[int] = None,
) -> Dict[str, Any]:
    """Construct the highest-scoring governed portfolio from eligible candidates."""
    acct = max(0.0, _f(account_size, _envf("ACCOUNT_SIZE", 0.0)))
    configured_risk = max(0.0, _f(max_portfolio_risk, _envf("APEX_PREMIUM_MAX_PORTFOLIO_RISK", 2500.0)))
    daily_cap = max(0.0, _f(max_daily_loss, _envf("TRADE_MAX_DAILY_LOSS", 2500.0)))
    position_cap = max(1, int(max_positions if max_positions is not None else _envi("APEX_PREMIUM_MAX_POSITIONS", 2)))
    contract_cap = max(1, int(max_contracts_per_strategy if max_contracts_per_strategy is not None else _envi("APEX_PREMIUM_MAX_CONTRACTS", 3)))
    account_cap = acct * 0.03 if acct > 0 else configured_risk
    remaining_daily = max(0.0, daily_cap + min(0.0, _f(daily_realized_pnl)) - max(0.0, _f(open_risk)))
    budget = min(configured_risk, account_cap, remaining_daily)

    rows = _candidate_rows(expectancy)
    eligible = [r for r in rows if r["eligible"] and r["max_loss_per_contract"] > 0 and r["blended_expected_value"] > 0]
    blockers: List[str] = []
    warnings: List[str] = []
    if budget <= 0:
        blockers.append("Portfolio risk capacity is exhausted.")
    if not eligible:
        blockers.append("No eligible positive-expectancy premium candidates are available.")

    best: Optional[Dict[str, Any]] = None
    if not blockers:
        for n in range(1, min(position_cap, len(eligible)) + 1):
            for combo in itertools.combinations(eligible, n):
                conflict = None
                correlation_penalty = 0.0
                for a, b in itertools.combinations(combo, 2):
                    penalty, reason = _pair_penalty(a, b)
                    correlation_penalty += penalty
                    if reason:
                        conflict = reason
                        break
                if conflict:
                    continue
                base_risk = sum(r["max_loss_per_contract"] for r in combo)
                if base_risk > budget:
                    continue
                quality = sum((r["institutional_score"] / 100.0) * max(0.0, r["blended_expected_value"]) for r in combo)
                score = quality * max(0.0, 1.0 - correlation_penalty)
                if best is None or score > best["objective_score"]:
                    best = {"combo": combo, "objective_score": score, "correlation_penalty": correlation_penalty}

    selected: List[Dict[str, Any]] = []
    used_risk = 0.0
    if best:
        combo = list(best["combo"])
        weights = [max(1.0, (r["institutional_score"] / 100.0) * max(1.0, r["blended_expected_value"])) for r in combo]
        weight_sum = sum(weights)
        for row, weight in sorted(zip(combo, weights), key=lambda x: x[0]["institutional_score"], reverse=True):
            allocation_budget = budget * weight / weight_sum
            contracts = min(contract_cap, max(1, math.floor(allocation_budget / row["max_loss_per_contract"])))
            while contracts > 0 and used_risk + contracts * row["max_loss_per_contract"] > budget:
                contracts -= 1
            if contracts <= 0:
                continue
            risk = contracts * row["max_loss_per_contract"]
            used_risk += risk
            selected.append({**row, "contracts": contracts, "allocated_risk": round(risk, 2),
                             "portfolio_expected_value": round(contracts * row["blended_expected_value"], 2),
                             "selection_reason": "Selected by risk-adjusted expectancy under concentration constraints."})

    selected_names = {r["strategy"] for r in selected}
    excluded = []
    for row in rows:
        if row["strategy"] in selected_names:
            continue
        reasons = []
        if not row["eligible"]:
            reasons.append("Candidate failed Premium Discipline or institutional eligibility.")
        if row["max_loss_per_contract"] <= 0:
            reasons.append("Canonical maximum loss is unavailable.")
        if row["blended_expected_value"] <= 0:
            reasons.append("Blended expected value is not positive.")
        if not reasons and selected:
            for chosen in selected:
                _, reason = _pair_penalty(row, chosen)
                if reason:
                    reasons.append(reason)
                    break
        if not reasons:
            reasons.append("Not selected by the constrained portfolio objective.")
        excluded.append({**row, "exclusion_reasons": reasons})

    total_ev = round(sum(r["portfolio_expected_value"] for r in selected), 2)
    utilization = round(100.0 * used_risk / budget, 1) if budget > 0 else 0.0
    if selected and utilization < 50:
        warnings.append("Less than half of available portfolio risk is deployable under current constraints.")

    return {
        "version": VERSION, "advisory_only": True, "execution_authority": False,
        "state": "BLOCKED" if blockers else "PORTFOLIO_READY" if selected else "NO_ALLOCATION",
        "selected_positions": selected, "excluded_candidates": excluded,
        "portfolio_summary": {
            "position_count": len(selected), "total_contracts": sum(r["contracts"] for r in selected),
            "maximum_defined_risk": round(used_risk, 2), "expected_value": total_ev,
            "risk_adjusted_expected_return": round(total_ev / used_risk, 4) if used_risk else None,
            "remaining_risk_capacity": round(max(0.0, budget - used_risk), 2),
            "risk_utilization_pct": utilization,
            "net_exposure": "BALANCED" if {r["exposure"] for r in selected} == {"BULLISH", "BEARISH"} else (selected[0]["exposure"] if len(selected) == 1 else "MIXED"),
        },
        "limits": {"portfolio_risk_budget": round(budget, 2), "configured_max_portfolio_risk": configured_risk,
                   "remaining_daily_loss_capacity": round(remaining_daily, 2), "account_risk_cap_pct": 3.0,
                   "max_positions": position_cap, "max_contracts_per_strategy": contract_cap, "account_size": acct or None},
        "blockers": blockers, "warnings": warnings,
        "governance_note": "Portfolio construction is advisory and cannot bypass Premium Discipline, dynamic sizing, confirmation gates, or broker controls.",
    }
