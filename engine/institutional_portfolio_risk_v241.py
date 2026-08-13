"""APEX 24.1 - Institutional Portfolio & Risk Intelligence.

Portfolio-level (not trade-level) risk intelligence. This module is a
deterministic, read-only advisory layer. It NEVER submits, mutates, or cancels
orders, never moves stops, never resizes positions, and never bypasses kill
switches. Every output is advisory and requires human confirmation before any
action is taken elsewhere in the platform.

It is built on top of the existing APEX 16.3 ``portfolio_risk_intelligence``
engine (reused for base position normalization, net Greeks, position heat, and
breach detection) and adds the institutional portfolio layer:

  * Portfolio Greeks + Net Directional Exposure + Premium at Risk +
    Buying-Power Utilization + Open Risk + Remaining Risk Capacity.
  * Risk Budget Manager (daily / weekly / monthly / drawdown / concurrency /
    premium / directional / heat / remaining deployable capital) sourced from
    Configuration Governance environment variables - no hardcoded limits.
  * Capital Allocation Intelligence (FULL_SIZE / HALF_SIZE / REDUCED_SIZE /
    NO_NEW_RISK) - advisory sizing only.
  * Correlation Intelligence (duplicate direction / playbook / strategy family,
    call / put / premium-selling concentration).
  * Opportunity Prioritization (expected value, risk-adjusted return, capital
    efficiency, diversification benefit, institutional confidence, execution
    quality).

The engine is designed so that additional broker accounts can be aggregated in
the future: ``evaluate_portfolio`` accepts either a single-account snapshot or a
multi-account snapshot (``accounts: [...]``) and folds them into one book.
"""
from __future__ import annotations

import math
import os
from typing import Any, Mapping, Optional, Sequence

from . import portfolio_risk_intelligence as base

VERSION = "24.1.0_INSTITUTIONAL_PORTFOLIO_RISK_INTELLIGENCE"
SCHEMA_VERSION = "apex.portfolio_risk_v241.v1"

# ---------------------------------------------------------------------------
# Governed risk-budget definitions. These are the *fallback* defaults used when
# the corresponding Configuration Governance environment variable is not set.
# The variables themselves are registered in ``configuration_governance`` so the
# governance audit can see and validate them. Nothing here is silently
# hardcoded into behaviour: ``resolve_risk_budget`` always reports the source
# (``ENVIRONMENT`` vs ``GOVERNED_DEFAULT``) of every limit it returns.
# ---------------------------------------------------------------------------
BUDGET_ENV = {
    "account_equity": ("ACCOUNT_SIZE", 60000.0, float),
    "max_risk_per_trade": ("MAX_RISK_PER_TRADE", 750.0, float),
    "daily_risk_budget": ("APEX_DAILY_RISK_BUDGET", 1500.0, float),
    "weekly_risk_budget": ("APEX_WEEKLY_RISK_BUDGET", 4500.0, float),
    "monthly_drawdown_limit": ("APEX_MONTHLY_DRAWDOWN_LIMIT", 9000.0, float),
    "max_concurrent_positions": ("APEX_MAX_CONCURRENT_POSITIONS", 3, int),
    "max_premium_at_risk": ("APEX_MAX_PREMIUM_AT_RISK", 3000.0, float),
    "max_directional_bias_pct": ("APEX_MAX_DIRECTIONAL_BIAS_PCT", 60.0, float),
    "max_portfolio_heat_pct": ("APEX_MAX_PORTFOLIO_HEAT_PCT", 35.0, float),
}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(value)))


def _pct(part: float, whole: float) -> float:
    whole = float(whole)
    if whole == 0:
        return 0.0
    return round(100.0 * float(part) / whole, 2)


def resolve_risk_budget(env: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
    """Resolve institutional risk limits from Configuration Governance.

    Every limit is read from its governed environment variable; when unset, the
    governed default is used and reported as such. No limit is applied without
    an accompanying ``source`` so operators can audit provenance.
    """
    env = env if env is not None else os.environ
    limits: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for key, (var, default, caster) in BUDGET_ENV.items():
        raw = env.get(var)
        if raw is not None and str(raw).strip() != "":
            try:
                limits[key] = caster(raw)
                sources[key] = "ENVIRONMENT"
                continue
            except Exception:
                pass
        limits[key] = caster(default)
        sources[key] = "GOVERNED_DEFAULT"
    limits["variable_names"] = {k: v[0] for k, v in BUDGET_ENV.items()}
    limits["sources"] = sources
    return limits


# ---------------------------------------------------------------------------
# Snapshot folding (multi-account ready)
# ---------------------------------------------------------------------------

def _fold_accounts(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Collapse a single- or multi-account snapshot into one book.

    A multi-account snapshot supplies ``accounts: [{positions, ...}, ...]``.
    A single-account snapshot supplies ``positions``/``open_positions`` at the
    top level. Both are supported; the folded book preserves per-account counts.
    """
    accounts = snapshot.get("accounts")
    if isinstance(accounts, list) and accounts:
        positions: list[dict[str, Any]] = []
        realized = 0.0
        trades = 0
        losses = 0
        account_ids: list[str] = []
        for acct in accounts:
            if not isinstance(acct, Mapping):
                continue
            raw = acct.get("positions") or acct.get("open_positions") or []
            if isinstance(raw, Mapping):
                raw = [raw]
            positions.extend([p for p in raw if isinstance(p, Mapping)])
            realized += _num(acct.get("realized_pnl_today"))
            trades += int(_num(acct.get("trades_today")))
            losses += int(_num(acct.get("losses_today")))
            account_ids.append(str(acct.get("account_id") or "ACCOUNT"))
        equity = _num(snapshot.get("account_equity") or snapshot.get("net_liquidation"))
        if equity <= 0:
            equity = sum(_num(a.get("account_equity") or a.get("net_liquidation"))
                         for a in accounts if isinstance(a, Mapping))
        return {
            "positions": positions,
            "realized_pnl_today": realized,
            "trades_today": trades,
            "losses_today": losses,
            "account_equity": equity,
            "underlying_price": snapshot.get("underlying_price"),
            "policy": snapshot.get("policy"),
            "account_ids": account_ids,
        }
    folded = dict(snapshot)
    folded["account_ids"] = [str(snapshot.get("account_id") or "PRIMARY")]
    return folded


# ---------------------------------------------------------------------------
# Portfolio exposure
# ---------------------------------------------------------------------------

def _exposure(positions: Sequence[Mapping[str, Any]], equity: float,
              underlying_price: float, budget: Mapping[str, Any]) -> dict[str, Any]:
    """Institutional exposure block derived from normalized positions."""
    net_delta = round(sum(_num(p.get("delta")) for p in positions), 4)
    net_gamma = round(sum(_num(p.get("gamma")) for p in positions), 4)
    net_theta = round(sum(_num(p.get("theta")) for p in positions), 4)
    net_vega = round(sum(_num(p.get("vega")) for p in positions), 4)

    # Net directional exposure: dollar P&L per 1.0 move in the underlying is the
    # net delta (already scaled by qty * multiplier by the base engine). When an
    # underlying price is available we also express it as notional and as a
    # percentage of equity so it can be governed against a directional cap.
    directional_notional = round(net_delta * underlying_price, 2) if underlying_price else 0.0
    if underlying_price:
        directional_bias_pct = _pct(abs(directional_notional), equity)
    else:
        directional_bias_pct = _pct(abs(net_delta), equity)

    # Premium at risk: long-option premium is fully at risk; short premium is a
    # credit, not an outlay. Open risk is the governed max-risk sum from base.
    premium_at_risk = round(sum(p["market_value"] for p in positions
                                if str(p.get("side", "LONG")).upper() == "LONG"), 2)
    open_risk = round(sum(_num(p.get("max_risk")) for p in positions), 2)
    total_market_value = round(sum(_num(p.get("market_value")) for p in positions), 2)
    bp_utilization_pct = _pct(total_market_value, equity)

    max_heat = _num(budget.get("max_portfolio_heat_pct"), 35.0)
    heat_capital = max_heat / 100.0 * equity
    remaining_risk_capacity_pct = round(max(0.0, max_heat - _pct(open_risk, equity)), 2)
    remaining_deployable_capital = round(max(0.0, heat_capital - open_risk), 2)

    direction = "NEUTRAL"
    if net_delta > 0:
        direction = "NET_LONG"
    elif net_delta < 0:
        direction = "NET_SHORT"

    return {
        "portfolio_delta": net_delta,
        "portfolio_gamma": net_gamma,
        "portfolio_theta": net_theta,
        "portfolio_vega": net_vega,
        "net_directional_exposure": directional_notional,
        "net_direction": direction,
        "directional_bias_pct": directional_bias_pct,
        "premium_at_risk": premium_at_risk,
        "buying_power_utilization_pct": bp_utilization_pct,
        "open_risk": open_risk,
        "total_market_value": total_market_value,
        "remaining_risk_capacity_pct": remaining_risk_capacity_pct,
        "remaining_deployable_capital": remaining_deployable_capital,
    }


# ---------------------------------------------------------------------------
# Risk Budget Manager
# ---------------------------------------------------------------------------

def _budget_manager(exposure: Mapping[str, Any], daily_pnl: float,
                    open_position_count: int, budget: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate the current book against every governed risk budget."""
    max_daily = _num(budget.get("daily_risk_budget"))
    max_weekly = _num(budget.get("weekly_risk_budget"))
    max_monthly = _num(budget.get("monthly_drawdown_limit"))
    max_concurrent = int(_num(budget.get("max_concurrent_positions"), 3))
    max_premium = _num(budget.get("max_premium_at_risk"))
    max_directional = _num(budget.get("max_directional_bias_pct"))
    max_heat = _num(budget.get("max_portfolio_heat_pct"))

    daily_loss = abs(min(daily_pnl, 0.0))
    checks = [
        {"budget": "DAILY_RISK_BUDGET", "used": round(daily_loss, 2), "limit": max_daily,
         "utilization_pct": _pct(daily_loss, max_daily),
         "breached": daily_loss > max_daily > 0},
        {"budget": "MAX_CONCURRENT_POSITIONS", "used": open_position_count, "limit": max_concurrent,
         "utilization_pct": _pct(open_position_count, max_concurrent),
         "breached": open_position_count > max_concurrent},
        {"budget": "MAX_PREMIUM_AT_RISK", "used": exposure["premium_at_risk"], "limit": max_premium,
         "utilization_pct": _pct(exposure["premium_at_risk"], max_premium),
         "breached": exposure["premium_at_risk"] > max_premium > 0},
        {"budget": "MAX_DIRECTIONAL_BIAS", "used": exposure["directional_bias_pct"], "limit": max_directional,
         "utilization_pct": _pct(exposure["directional_bias_pct"], max_directional),
         "breached": exposure["directional_bias_pct"] > max_directional > 0},
        {"budget": "MAX_PORTFOLIO_HEAT", "used": _pct(exposure["open_risk"], max(1.0, max_heat)),
         "limit": max_heat,
         "utilization_pct": _pct(exposure["open_risk"] / max(1.0, exposure["open_risk"] or 1.0) * exposure["open_risk"], 1),
         "breached": exposure["remaining_risk_capacity_pct"] <= 0.0},
    ]
    # Heat utilization is cleaner expressed directly from remaining capacity.
    checks[-1]["utilization_pct"] = round(
        _clamp(100.0 - (exposure["remaining_risk_capacity_pct"] / max(0.01, max_heat)) * 100.0), 2)

    breached = [c["budget"] for c in checks if c["breached"]]
    peak_utilization = max((c["utilization_pct"] for c in checks), default=0.0)
    if breached:
        state = "BUDGET_BREACH"
    elif peak_utilization >= 75.0:
        state = "ELEVATED"
    else:
        state = "WITHIN_BUDGET"
    return {
        "state": state,
        "checks": checks,
        "breached_budgets": breached,
        "peak_utilization_pct": round(peak_utilization, 2),
        "weekly_risk_budget": max_weekly,
        "monthly_drawdown_limit": max_monthly,
        "remaining_deployable_capital": exposure["remaining_deployable_capital"],
    }


# ---------------------------------------------------------------------------
# Correlation Intelligence
# ---------------------------------------------------------------------------

def _infer_kind(position: Mapping[str, Any]) -> str:
    for key in ("option_type", "right", "type", "kind"):
        v = str(position.get(key) or "").upper()
        if v in ("C", "CALL"):
            return "CALL"
        if v in ("P", "PUT"):
            return "PUT"
    return "UNKNOWN"


def _infer_bias(position: Mapping[str, Any]) -> str:
    delta = _num(position.get("delta"))
    if delta > 0:
        return "BULLISH"
    if delta < 0:
        return "BEARISH"
    return "NEUTRAL"


def correlation_intelligence(positions: Sequence[Mapping[str, Any]],
                             *, call_put_concentration_pct: float = 70.0,
                             premium_selling_pct: float = 60.0) -> dict[str, Any]:
    """Detect portfolio-level correlation and concentration risks."""
    warnings: list[dict[str, Any]] = []
    n = len(positions)
    if n == 0:
        return {"warnings": [], "position_count": 0, "concentration": {}}

    biases: dict[str, int] = {}
    playbooks: dict[str, int] = {}
    families: dict[str, int] = {}
    call_premium = 0.0
    put_premium = 0.0
    short_premium = 0.0
    total_premium = 0.0
    for p in positions:
        biases[_infer_bias(p)] = biases.get(_infer_bias(p), 0) + 1
        pb = str(p.get("playbook_id") or p.get("playbook") or "").strip()
        if pb:
            playbooks[pb] = playbooks.get(pb, 0) + 1
        fam = str(p.get("strategy_family") or p.get("strategy") or "").strip()
        if fam:
            families[fam] = families.get(fam, 0) + 1
        mv = abs(_num(p.get("market_value")))
        if mv == 0.0:
            # Raw (un-normalized) position: derive market value defensively.
            mark = _num(p.get("mark_price") or p.get("current_price") or p.get("entry_price"))
            qty = max(0.0, _num(p.get("quantity"), 1))
            mult = max(1.0, _num(p.get("multiplier"), 100))
            mv = abs(mark * qty * mult)
        total_premium += mv
        kind = _infer_kind(p)
        if kind == "CALL":
            call_premium += mv
        elif kind == "PUT":
            put_premium += mv
        if str(p.get("side", "LONG")).upper() == "SHORT":
            short_premium += mv

    directional = {k: v for k, v in biases.items() if k in ("BULLISH", "BEARISH")}
    if directional and len(directional) == 1 and n >= 2:
        only = next(iter(directional))
        warnings.append({"code": "DUPLICATE_DIRECTIONAL_EXPOSURE", "severity": "HIGH",
                         "detail": f"All {n} directional positions are {only}."})
    for pb, count in playbooks.items():
        if count >= 2:
            warnings.append({"code": "DUPLICATE_PLAYBOOK", "severity": "MEDIUM",
                             "detail": f"{count} positions share playbook '{pb}'."})
    for fam, count in families.items():
        if count >= 2:
            warnings.append({"code": "DUPLICATE_STRATEGY_FAMILY", "severity": "MEDIUM",
                             "detail": f"{count} positions share strategy family '{fam}'."})
    call_pct = _pct(call_premium, total_premium)
    put_pct = _pct(put_premium, total_premium)
    short_pct = _pct(short_premium, total_premium)
    if call_pct >= call_put_concentration_pct:
        warnings.append({"code": "EXCESS_CALL_CONCENTRATION", "severity": "MEDIUM",
                         "detail": f"Call premium is {call_pct}% of the book."})
    if put_pct >= call_put_concentration_pct:
        warnings.append({"code": "EXCESS_PUT_CONCENTRATION", "severity": "MEDIUM",
                         "detail": f"Put premium is {put_pct}% of the book."})
    if short_pct >= premium_selling_pct:
        warnings.append({"code": "PREMIUM_SELLING_CONCENTRATION", "severity": "MEDIUM",
                         "detail": f"Short premium is {short_pct}% of the book."})
    return {
        "warnings": warnings,
        "position_count": n,
        "concentration": {"call_pct": call_pct, "put_pct": put_pct, "short_premium_pct": short_pct},
        "bias_distribution": biases,
    }


# ---------------------------------------------------------------------------
# Capital Allocation Intelligence
# ---------------------------------------------------------------------------

def capital_allocation(*, assessment: Mapping[str, Any], exposure: Mapping[str, Any],
                       budget_eval: Mapping[str, Any], signal: Optional[Mapping[str, Any]] = None,
                       budget: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Advisory position-sizing recommendation.

    Returns FULL_SIZE / HALF_SIZE / REDUCED_SIZE / NO_NEW_RISK based on Trading
    Brain confidence, forecast confidence, regime alignment, playbook quality,
    execution intelligence score, portfolio heat, existing exposure, and the
    governed risk budget. Advisory only.
    """
    signal = dict(signal or {})
    budget = dict(budget or {})
    reasons: list[str] = []

    hard_block = False
    if assessment.get("risk_state") in ("LOCKED_OUT", "BREACH"):
        hard_block = True
        reasons.append(f"Portfolio risk state is {assessment.get('risk_state')}.")
    if budget_eval.get("state") == "BUDGET_BREACH":
        hard_block = True
        reasons.append("A governed risk budget is breached: " +
                       ", ".join(budget_eval.get("breached_budgets", [])) + ".")
    if exposure.get("remaining_deployable_capital", 0.0) < _num(budget.get("max_risk_per_trade"), 0.0):
        hard_block = True
        reasons.append("Remaining deployable capital is below one trade's max risk.")

    brain = _clamp(_num(signal.get("brain_confidence"), 0.0))
    forecast = _clamp(_num(signal.get("forecast_confidence"), 0.0))
    playbook = _clamp(_num(signal.get("playbook_quality"), 0.0))
    execution = _clamp(_num(signal.get("execution_score"), 0.0))
    regime_conf = _clamp(_num(signal.get("regime_confidence"), 0.0))

    composite = round(
        0.28 * brain + 0.22 * forecast + 0.20 * playbook + 0.18 * execution + 0.12 * regime_conf, 2)
    # Scale the raw signal quality down by how much of the heat budget is used
    # and by current directional saturation.
    heat_use = _clamp(budget_eval.get("peak_utilization_pct", 0.0))
    directional_use = _clamp(exposure.get("directional_bias_pct", 0.0))
    scaled = round(composite * (1.0 - 0.5 * heat_use / 100.0) * (1.0 - 0.3 * directional_use / 100.0), 2)

    if hard_block:
        grade = "NO_NEW_RISK"
    elif scaled >= 70.0:
        grade = "FULL_SIZE"
    elif scaled >= 52.0:
        grade = "HALF_SIZE"
    elif scaled >= 34.0:
        grade = "REDUCED_SIZE"
    else:
        grade = "NO_NEW_RISK"
        reasons.append("Composite signal quality is below the reduced-size floor.")

    size_multiplier = {"FULL_SIZE": 1.0, "HALF_SIZE": 0.5, "REDUCED_SIZE": 0.25, "NO_NEW_RISK": 0.0}[grade]
    advised_max_risk = round(size_multiplier * _num(budget.get("max_risk_per_trade"), 0.0), 2)
    advised_max_risk = min(advised_max_risk, exposure.get("remaining_deployable_capital", advised_max_risk))
    return {
        "grade": grade,
        "size_multiplier": size_multiplier,
        "advised_max_risk": round(max(0.0, advised_max_risk), 2),
        "composite_signal": composite,
        "scaled_signal": scaled,
        "inputs": {"brain_confidence": brain, "forecast_confidence": forecast,
                   "playbook_quality": playbook, "execution_score": execution,
                   "regime_confidence": regime_conf, "heat_utilization_pct": heat_use,
                   "directional_bias_pct": directional_use},
        "reasons": reasons,
        "advisory_only": True,
        "broker_effect": "NONE",
    }


# ---------------------------------------------------------------------------
# Opportunity Prioritization
# ---------------------------------------------------------------------------

def prioritize_opportunities(opportunities: Sequence[Mapping[str, Any]],
                             *, current_book: Optional[Sequence[Mapping[str, Any]]] = None) -> dict[str, Any]:
    """Rank simultaneous trade opportunities.

    Each opportunity may supply: ``expected_value``, ``max_risk``,
    ``capital_required``, ``confidence`` (institutional confidence 0-100),
    ``execution_quality`` (0-100), ``direction``/``strategy_family``. Missing
    fields degrade gracefully. Diversification benefit rewards opportunities
    that differ in direction/family from the existing book.
    """
    current_book = list(current_book or [])
    book_directions = {_infer_bias(p) for p in current_book}
    book_families = {str(p.get("strategy_family") or p.get("strategy") or "").strip()
                     for p in current_book}
    ranked: list[dict[str, Any]] = []
    for opp in opportunities:
        if not isinstance(opp, Mapping):
            continue
        ev = _num(opp.get("expected_value"))
        risk = max(1.0, _num(opp.get("max_risk"), 1.0))
        capital = max(1.0, _num(opp.get("capital_required") or opp.get("max_risk"), 1.0))
        confidence = _clamp(_num(opp.get("confidence")))
        execution = _clamp(_num(opp.get("execution_quality")))
        risk_adjusted = round(ev / risk, 4)
        capital_efficiency = round(ev / capital, 4)
        direction = str(opp.get("direction") or "").upper() or _infer_bias(opp)
        family = str(opp.get("strategy_family") or opp.get("strategy") or "").strip()
        diversification = 100.0
        if direction and direction in book_directions:
            diversification -= 50.0
        if family and family in book_families:
            diversification -= 50.0
        diversification = _clamp(diversification)
        # Normalize EV-derived metrics into 0-100 bands with a bounded curve.
        ra_score = _clamp(50.0 + 50.0 * math.tanh(risk_adjusted))
        ce_score = _clamp(50.0 + 50.0 * math.tanh(capital_efficiency))
        priority = round(
            0.25 * ra_score + 0.15 * ce_score + 0.15 * diversification
            + 0.25 * confidence + 0.20 * execution, 2)
        ranked.append({
            "id": str(opp.get("id") or opp.get("opportunity_id") or opp.get("playbook_id") or "OPP"),
            "priority_score": priority,
            "components": {
                "expected_value": round(ev, 4),
                "risk_adjusted_return": risk_adjusted,
                "capital_efficiency": capital_efficiency,
                "diversification_benefit": diversification,
                "institutional_confidence": confidence,
                "execution_quality": execution,
            },
            "direction": direction or "UNKNOWN",
            "strategy_family": family or "UNKNOWN",
        })
    ranked.sort(key=lambda r: r["priority_score"], reverse=True)
    for i, r in enumerate(ranked, start=1):
        r["rank"] = i
    return {"ranked": ranked, "count": len(ranked)}


# ---------------------------------------------------------------------------
# Top-level evaluation + Mission Control builder
# ---------------------------------------------------------------------------

def evaluate_portfolio(snapshot: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Full portfolio-risk evaluation. Deterministic and advisory only."""
    snapshot = dict(snapshot or {})
    folded = _fold_accounts(snapshot)
    budget = resolve_risk_budget(snapshot.get("env"))

    assessment = base.evaluate(folded)
    positions = assessment.get("positions", [])
    equity = max(1.0, _num(folded.get("account_equity"), budget["account_equity"]))
    underlying_price = _num(folded.get("underlying_price"))

    exposure = _exposure(positions, equity, underlying_price, budget)
    budget_eval = _budget_manager(exposure, _num(assessment.get("daily_pnl")),
                                  int(assessment.get("open_position_count", 0)), budget)
    correlation = correlation_intelligence(positions)
    allocation = capital_allocation(assessment=assessment, exposure=exposure,
                                    budget_eval=budget_eval, signal=snapshot.get("signal"),
                                    budget=budget)

    states = [assessment.get("risk_state", "NORMAL"), budget_eval["state"]]
    if "LOCKED_OUT" in states or "BUDGET_BREACH" in states or "BREACH" in states:
        portfolio_state = "RESTRICTED"
    elif "ELEVATED" in states or budget_eval["peak_utilization_pct"] >= 75.0:
        portfolio_state = "ELEVATED"
    else:
        portfolio_state = "NORMAL"

    return {
        "ok": True,
        "status": "READY",
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "portfolio_state": portfolio_state,
        "account_ids": folded.get("account_ids", ["PRIMARY"]),
        "account_equity": round(equity, 2),
        "base_assessment": {
            "risk_state": assessment.get("risk_state"),
            "risk_score": assessment.get("risk_score"),
            "daily_pnl": assessment.get("daily_pnl"),
            "position_heat_pct": assessment.get("position_heat_pct"),
            "open_position_count": assessment.get("open_position_count"),
            "breaches": assessment.get("breaches"),
            "permissions": assessment.get("permissions"),
        },
        "exposure": exposure,
        "risk_budget": budget,
        "budget_manager": budget_eval,
        "correlation": correlation,
        "capital_allocation": allocation,
        "positions": positions,
        # --- Backward-compatible fields (APEX 16.3 contract). Existing consumers
        # of /api/portfolio-risk/evaluate continue to read these top-level keys.
        "risk_state": assessment.get("risk_state"),
        "risk_score": assessment.get("risk_score"),
        "lockout_recommended": assessment.get("lockout_recommended"),
        "daily_pnl": assessment.get("daily_pnl"),
        "position_heat_pct": assessment.get("position_heat_pct"),
        "open_position_count": assessment.get("open_position_count"),
        "net_greeks": assessment.get("net_greeks"),
        "total_open_risk": assessment.get("total_open_risk"),
        "breaches": assessment.get("breaches"),
        "permissions": assessment.get("permissions"),
        "advisory_only": True,
        "broker_effect": "NONE",
        "orders_changed": False,
        "broker_order_submission_enabled": False,
        "automatic_position_resizing_enabled": False,
        "production_effect": "NONE",
    }


def _extract_snapshot(last: Mapping[str, Any]) -> dict[str, Any]:
    """Best-effort extraction of a portfolio snapshot from a scan result."""
    if not isinstance(last, Mapping):
        return {}
    snap: dict[str, Any] = {}
    for key in ("accounts", "positions", "open_positions", "account_equity",
                "net_liquidation", "realized_pnl_today", "trades_today",
                "losses_today", "underlying_price", "policy", "signal", "env"):
        if key in last:
            snap[key] = last[key]
    portfolio = last.get("portfolio")
    if isinstance(portfolio, Mapping):
        for key, value in portfolio.items():
            snap.setdefault(key, value)
    return snap


def build_portfolio_intelligence(last: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Mission-Control-facing summary. Safe on empty/sparse input."""
    snapshot = _extract_snapshot(last or {})
    evaluation = evaluate_portfolio(snapshot)
    opportunities = []
    if isinstance(last, Mapping):
        raw = last.get("opportunities")
        if isinstance(raw, list):
            opportunities = raw
    ranked = prioritize_opportunities(opportunities, current_book=evaluation["positions"])
    evaluation["opportunities"] = ranked
    return evaluation


def status() -> dict[str, Any]:
    budget = resolve_risk_budget()
    # Preserve backward-compatible APEX 16.3 status fields (default_policy,
    # snapshot_count, etc.) by folding in the base engine status, then overlay
    # the richer 24.1 fields. Evolution, not replacement.
    try:
        legacy = base.status()
    except Exception:
        legacy = {}
    payload = dict(legacy)
    payload.update({
        "ok": True,
        "status": "READY",
        "engine": "INSTITUTIONAL_PORTFOLIO_RISK_INTELLIGENCE",
        "version": VERSION,
        "build_version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "supersedes": legacy.get("build_version"),
        "deterministic": True,
        "advisory_only": True,
        "multi_account_ready": True,
        "broker_order_submission_enabled": False,
        "automatic_position_resizing_enabled": False,
        "automatic_stop_modification_enabled": False,
        "production_effect": "NONE",
        "governed_variables": budget["variable_names"],
        "limit_sources": budget["sources"],
    })
    return payload
