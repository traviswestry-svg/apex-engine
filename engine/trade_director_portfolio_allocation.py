"""APEX Trade Director Phase 29 — Institutional Portfolio & Capital Allocation Intelligence.

Advisory-only portfolio supervision for aggregate exposure, capital budgeting,
concentration, correlation, strategy allocation, and candidate sizing. This module
never submits orders, mutates broker state, or overrides hard risk controls.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

VERSION = "PHASE_29"


def _m(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _position_rows(context: Mapping[str, Any]) -> List[Dict[str, Any]]:
    raw = context.get("portfolio_positions") or context.get("positions") or []
    if isinstance(raw, Mapping):
        raw = list(raw.values())
    rows: List[Dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        p = dict(_m(item))
        qty = abs(_f(p.get("quantity") or p.get("qty")))
        price = _f(p.get("mark") or p.get("current_price") or p.get("option_current_price") or p.get("entry_price"))
        multiplier = _f(p.get("multiplier"), 100.0)
        notional = abs(_f(p.get("notional"), qty * price * multiplier))
        risk = abs(_f(p.get("max_risk") or p.get("risk_dollars"), notional))
        rows.append({
            "trade_id": str(p.get("trade_id") or p.get("id") or ""),
            "symbol": str(p.get("symbol") or p.get("ticker") or "UNKNOWN").upper(),
            "strategy": str(p.get("strategy") or p.get("setup") or "UNCLASSIFIED").upper(),
            "direction": str(p.get("direction") or p.get("side") or "NEUTRAL").upper(),
            "quantity": qty,
            "notional": round(notional, 2),
            "risk_dollars": round(risk, 2),
            "delta_dollars": round(_f(p.get("delta_dollars") or p.get("delta_exposure")), 2),
            "gamma_dollars": round(_f(p.get("gamma_dollars") or p.get("gamma_exposure")), 2),
            "vega_dollars": round(_f(p.get("vega_dollars") or p.get("vega_exposure")), 2),
            "theta_dollars": round(_f(p.get("theta_dollars") or p.get("theta_exposure")), 2),
            "confidence": round(_f(p.get("confidence")), 2),
        })
    return rows


def _candidate(context: Mapping[str, Any]) -> Dict[str, Any]:
    lifecycle = _m(context.get("trade_lifecycle"))
    decision = _m(context.get("institutional_decision_engine"))
    strategy = _m(context.get("strategy_orchestration"))
    options = _m(context.get("options_intelligence"))
    contract = _m(options.get("best_candidate") or options.get("selected_contract"))
    proposed_risk = _f(context.get("proposed_risk_dollars") or lifecycle.get("planned_risk_dollars") or decision.get("risk_dollars"))
    return {
        "symbol": str(context.get("symbol") or _m(context.get("position")).get("symbol") or "SPX").upper(),
        "strategy": str(strategy.get("selected_strategy") or strategy.get("strategy") or decision.get("strategy") or "UNCLASSIFIED").upper(),
        "direction": str(decision.get("direction") or decision.get("decision") or contract.get("side") or "NEUTRAL").upper(),
        "confidence": round(_f(decision.get("confidence") or strategy.get("confidence")), 2),
        "requested_risk_dollars": round(max(0.0, proposed_risk), 2),
    }


def build_portfolio_allocation(context: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    ctx = dict(context or {})
    positions = _position_rows(ctx)
    candidate = _candidate(ctx)
    capital = max(0.0, _f(ctx.get("account_equity") or ctx.get("capital_base") or 60000.0))
    daily_loss_limit = max(0.0, _f(ctx.get("daily_loss_limit") or ctx.get("max_daily_loss") or 1000.0))
    per_trade_limit = max(0.0, _f(ctx.get("per_trade_risk_limit") or ctx.get("max_risk_per_trade") or 2000.0))
    portfolio_risk_limit = max(0.0, _f(ctx.get("portfolio_risk_limit") or capital * 0.05))

    total_notional = sum(p["notional"] for p in positions)
    total_risk = sum(p["risk_dollars"] for p in positions)
    gross_delta = sum(p["delta_dollars"] for p in positions)
    gross_gamma = sum(p["gamma_dollars"] for p in positions)
    gross_vega = sum(p["vega_dollars"] for p in positions)
    gross_theta = sum(p["theta_dollars"] for p in positions)

    by_symbol: Dict[str, float] = {}
    by_strategy: Dict[str, float] = {}
    by_direction: Dict[str, float] = {}
    for p in positions:
        by_symbol[p["symbol"]] = by_symbol.get(p["symbol"], 0.0) + p["risk_dollars"]
        by_strategy[p["strategy"]] = by_strategy.get(p["strategy"], 0.0) + p["risk_dollars"]
        by_direction[p["direction"]] = by_direction.get(p["direction"], 0.0) + p["risk_dollars"]

    largest_symbol_risk = max(by_symbol.values(), default=0.0)
    largest_strategy_risk = max(by_strategy.values(), default=0.0)
    concentration_pct = (largest_symbol_risk / total_risk * 100.0) if total_risk else 0.0
    strategy_concentration_pct = (largest_strategy_risk / total_risk * 100.0) if total_risk else 0.0

    remaining_portfolio = max(0.0, portfolio_risk_limit - total_risk)
    remaining_daily = max(0.0, daily_loss_limit - abs(_f(ctx.get("realized_daily_loss") or ctx.get("daily_pnl_negative"))))
    requested = candidate["requested_risk_dollars"] or min(per_trade_limit, remaining_portfolio, remaining_daily)

    confidence_factor = _clip(candidate["confidence"] / 100.0 if candidate["confidence"] else 0.5, 0.25, 1.0)
    concentration_factor = 0.5 if concentration_pct >= 65 else 0.75 if concentration_pct >= 45 else 1.0
    direction_risk = by_direction.get(candidate["direction"], 0.0)
    direction_pct = direction_risk / total_risk * 100.0 if total_risk else 0.0
    correlation_factor = 0.5 if direction_pct >= 70 else 0.75 if direction_pct >= 50 else 1.0
    recommended = min(requested, per_trade_limit, remaining_portfolio, remaining_daily)
    recommended *= confidence_factor * concentration_factor * correlation_factor
    recommended = round(max(0.0, recommended), 2)

    blockers: List[str] = []
    warnings: List[str] = []
    if remaining_portfolio <= 0:
        blockers.append("PORTFOLIO_RISK_BUDGET_EXHAUSTED")
    if remaining_daily <= 0:
        blockers.append("DAILY_LOSS_BUDGET_EXHAUSTED")
    if concentration_pct >= 75:
        blockers.append("SYMBOL_CONCENTRATION_LIMIT")
    elif concentration_pct >= 50:
        warnings.append("ELEVATED_SYMBOL_CONCENTRATION")
    if strategy_concentration_pct >= 75:
        warnings.append("ELEVATED_STRATEGY_CONCENTRATION")
    if direction_pct >= 75:
        warnings.append("DIRECTIONAL_CORRELATION_CLUSTER")
    if candidate["confidence"] and candidate["confidence"] < 60:
        warnings.append("LOW_CONFIDENCE_ALLOCATION_REDUCTION")

    state = "BLOCKED" if blockers else "CONSTRAINED" if warnings or recommended < requested else "ALLOCATABLE"
    utilization = total_risk / portfolio_risk_limit * 100.0 if portfolio_risk_limit else 0.0
    allocation_score = 100.0
    allocation_score -= min(40.0, utilization * 0.4)
    allocation_score -= max(0.0, concentration_pct - 35.0) * 0.5
    allocation_score -= max(0.0, direction_pct - 50.0) * 0.4
    allocation_score = round(_clip(allocation_score, 0.0, 100.0), 1)

    return {
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "allocation_state": state,
        "allocation_score": allocation_score,
        "capital_base": round(capital, 2),
        "portfolio_summary": {
            "open_positions": len(positions),
            "total_notional": round(total_notional, 2),
            "total_risk_dollars": round(total_risk, 2),
            "portfolio_risk_limit": round(portfolio_risk_limit, 2),
            "risk_utilization_pct": round(utilization, 2),
            "remaining_portfolio_risk": round(remaining_portfolio, 2),
            "remaining_daily_loss_budget": round(remaining_daily, 2),
        },
        "aggregate_greeks": {
            "delta_dollars": round(gross_delta, 2),
            "gamma_dollars": round(gross_gamma, 2),
            "vega_dollars": round(gross_vega, 2),
            "theta_dollars": round(gross_theta, 2),
        },
        "concentration": {
            "symbol_risk": {k: round(v, 2) for k, v in sorted(by_symbol.items(), key=lambda x: x[1], reverse=True)},
            "strategy_risk": {k: round(v, 2) for k, v in sorted(by_strategy.items(), key=lambda x: x[1], reverse=True)},
            "direction_risk": {k: round(v, 2) for k, v in sorted(by_direction.items(), key=lambda x: x[1], reverse=True)},
            "largest_symbol_pct": round(concentration_pct, 2),
            "largest_strategy_pct": round(strategy_concentration_pct, 2),
            "candidate_direction_pct": round(direction_pct, 2),
        },
        "candidate_allocation": {
            **candidate,
            "per_trade_limit": round(per_trade_limit, 2),
            "recommended_risk_dollars": recommended,
            "allocation_factor": round((recommended / requested) if requested else 0.0, 3),
            "requires_phase20_authorization": True,
        },
        "blockers": blockers,
        "warnings": warnings,
        "positions": positions,
        "controls": {
            "advisory_only": True,
            "broker_access": False,
            "order_submission": False,
            "risk_override": False,
            "phase20_authorization_required": True,
            "hard_limits_may_only_reduce_allocation": True,
        },
        "safety_note": "Phase 29 may reduce or block suggested capital allocation, but cannot increase hard risk limits, authorize a trade, or interact with a broker.",
    }


def build_portfolio_stress_test(context: Optional[Mapping[str, Any]] = None, shocks: Optional[Iterable[float]] = None) -> Dict[str, Any]:
    allocation = build_portfolio_allocation(context)
    greeks = allocation["aggregate_greeks"]
    scenarios = []
    for move_pct in list(shocks or [-2.0, -1.0, -0.5, 0.5, 1.0, 2.0]):
        move = float(move_pct)
        estimated = greeks["delta_dollars"] * (move / 100.0) + 0.5 * greeks["gamma_dollars"] * (move / 100.0) ** 2
        scenarios.append({"underlying_move_pct": move, "estimated_pnl": round(estimated, 2)})
    worst = min((s["estimated_pnl"] for s in scenarios), default=0.0)
    return {"version": VERSION, "stress_state": "BREACH" if abs(worst) > allocation["portfolio_summary"]["remaining_daily_loss_budget"] else "WITHIN_BUDGET", "worst_estimated_pnl": worst, "scenarios": scenarios, "controls": allocation["controls"]}
