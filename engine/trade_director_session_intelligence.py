"""APEX Trade Director Phase 11 — Institutional Portfolio & Session Intelligence.

Pure analytics layer. It consumes the active position, Phase 6 archived outcomes,
and current Trade Director state. It performs no provider requests, broker calls,
background work, or import-time persistence.
"""
from __future__ import annotations

import os
from datetime import datetime, time
from typing import Any, Dict, Iterable, List, Optional


def _f(v: Any, d: float = 0.0) -> float:
    try: return float(v)
    except (TypeError, ValueError): return d


def _i(v: Any, d: int = 0) -> int:
    try: return int(float(v))
    except (TypeError, ValueError): return d


def _today_key(value: Any) -> str:
    s = str(value or "")
    return s[:10] if len(s) >= 10 else ""


def _outcome(trade: Dict[str, Any]) -> Dict[str, Any]:
    return dict(trade.get("outcome") or {})


def _strategy(trade: Dict[str, Any]) -> str:
    p = dict(trade.get("position") or {})
    raw = str(p.get("strategy") or p.get("setup") or p.get("tag") or "DIRECTIONAL").strip().upper()
    aliases = {
        "CALL": "DIRECTIONAL", "PUT": "DIRECTIONAL", "ORB": "OPENING_RANGE_BREAKOUT",
        "IRON_CONDOR": "IRON_CONDOR", "CREDIT_SPREAD": "CREDIT_SPREAD",
    }
    return aliases.get(raw, raw or "DIRECTIONAL")


def _session_trades(history: Iterable[Dict[str, Any]], day: str) -> List[Dict[str, Any]]:
    rows = []
    for t in history:
        stamp = t.get("closed_at") or t.get("entered_at") or t.get("updated_at")
        if _today_key(stamp) == day:
            rows.append(t)
    return rows


def _streak(pnls: List[float]) -> Dict[str, Any]:
    if not pnls: return {"type": "NONE", "count": 0}
    last_win = pnls[0] > 0
    count = 0
    for p in pnls:
        if (p > 0) == last_win and p != 0: count += 1
        else: break
    return {"type": "WIN" if last_win else "LOSS", "count": count}


def _session_mode(realized: float, max_loss: float, trades: int, max_trades: int, streak: Dict[str, Any], health: float, cutoff_passed: bool) -> Dict[str, str]:
    if cutoff_passed or trades >= max_trades or realized <= -max_loss:
        return {"mode": "STOP_TRADING", "reason": "Session cutoff, trade limit, or daily loss limit reached."}
    if realized >= max_loss * 0.75:
        return {"mode": "LOCK_PROFIT", "reason": "Protect a strong session; only exceptional setups qualify."}
    if streak.get("type") == "LOSS" and streak.get("count", 0) >= 2:
        return {"mode": "DEFENSE", "reason": "Two consecutive losses; reduce size and raise selectivity."}
    if realized < 0:
        return {"mode": "RECOVERY", "reason": "Session is negative; risk must contract, not expand."}
    if health >= 78 and trades < max_trades:
        return {"mode": "ATTACK", "reason": "Risk capacity and current trade quality support normal participation."}
    return {"mode": "OBSERVATION", "reason": "Wait for clearer alignment before deploying additional risk."}


def _size_recommendation(confidence: float, health: float, remaining_risk: float, premium: float, mode: str, max_contracts: int) -> Dict[str, Any]:
    contract_risk = max(1.0, premium * 100.0)
    capacity = max(0, min(max_contracts, int(remaining_risk // contract_risk)))
    quality = 0
    if confidence >= 85 and health >= 80: quality = 3
    elif confidence >= 72 and health >= 68: quality = 2
    elif confidence >= 60 and health >= 55: quality = 1
    mode_cap = {"ATTACK": max_contracts, "OBSERVATION": 1, "DEFENSE": 1, "RECOVERY": 1, "LOCK_PROFIT": 1, "STOP_TRADING": 0}.get(mode, 1)
    recommended = max(0, min(capacity, quality, mode_cap, max_contracts))
    return {
        "recommended_contracts": recommended,
        "capacity_contracts": capacity,
        "estimated_risk_per_contract": round(contract_risk, 2),
        "method": "QUALITY_X_REMAINING_RISK_X_SESSION_MODE",
        "note": "Sizing is advisory and assumes long-option premium at risk; broker risk preview remains authoritative.",
    }


def _strategy_scorecards(history: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for trade in history:
        out = _outcome(trade)
        if out.get("realized_pnl") is None: continue
        groups.setdefault(_strategy(trade), []).append(trade)
    cards = []
    for name, rows in groups.items():
        pnls = [_f(_outcome(t).get("realized_pnl")) for t in rows]
        wins = [p for p in pnls if p > 0]; losses = [p for p in pnls if p < 0]
        gross_win, gross_loss = sum(wins), abs(sum(losses))
        cards.append({
            "strategy": name, "trades": len(rows),
            "win_rate": round(100 * len(wins) / len(rows), 1),
            "average_pnl": round(sum(pnls) / len(pnls), 2),
            "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
            "total_pnl": round(sum(pnls), 2),
        })
    cards.sort(key=lambda x: (-x["trades"], -x["total_pnl"]))
    return cards


def build_session_intelligence(
    active_position: Optional[Dict[str, Any]],
    monitor: Optional[Dict[str, Any]],
    history: Iterable[Dict[str, Any]],
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    now = now or datetime.now()
    active_position, monitor = dict(active_position or {}), dict(monitor or {})
    history = list(history or [])
    day = now.date().isoformat()
    todays = _session_trades(history, day)
    pnls = [_f(_outcome(t).get("realized_pnl")) for t in todays if _outcome(t).get("realized_pnl") is not None]
    realized = round(sum(pnls), 2)
    unrealized = _f(monitor.get("unrealized_pnl"), 0.0) if active_position.get("active") else 0.0
    max_loss = max(1.0, _f(os.getenv("APEX_MAX_DAILY_LOSS", "1000"), 1000.0))
    max_daily_risk = max(max_loss, _f(os.getenv("APEX_MAX_DAILY_RISK", "2000"), 2000.0))
    max_trades = max(1, _i(os.getenv("APEX_MAX_DAILY_TRADES", "3"), 3))
    max_contracts = max(1, _i(os.getenv("APEX_MAX_CONTRACTS", "3"), 3))
    risk_used = min(max_daily_risk, max(0.0, -realized) + max(0.0, -unrealized))
    remaining = max(0.0, max_daily_risk - risk_used)
    streak = _streak(pnls)
    cutoff = os.getenv("APEX_SESSION_CUTOFF", "11:30")
    try:
        hh, mm = [int(x) for x in cutoff.split(":", 1)]
        cutoff_passed = now.time() >= time(hh, mm)
    except Exception:
        cutoff_passed = False
    health = _f(monitor.get("trade_health"), 50.0)
    mode = _session_mode(realized, max_loss, len(todays), max_trades, streak, health, cutoff_passed)
    premium = _f(monitor.get("option_current_price") or active_position.get("option_entry_price"), 0.0)
    sizing = _size_recommendation(_f(monitor.get("confidence")), health, remaining, premium, mode["mode"], max_contracts)
    selection = min(100, max(0, int(_f(monitor.get("confidence"), 50))))
    risk_score = int(max(0, min(100, 100 - (risk_used / max_daily_risk * 100))))
    discipline = 100 if mode["mode"] != "STOP_TRADING" else 75
    execution = 90 if not (monitor.get("execution_control") or {}).get("blockers") else 65
    overall = round(selection * .25 + risk_score * .35 + discipline * .25 + execution * .15)
    queue = []
    if active_position.get("active"):
        queue.append({"opportunity": f"{active_position.get('ticker','SPX')} {active_position.get('side','')}", "score": selection, "status": "ACTIVE"})
    return {
        "version": "PHASE_11", "as_of": now.isoformat(),
        "session": {
            "date": day, "mode": mode["mode"], "mode_reason": mode["reason"],
            "realized_pnl": realized, "unrealized_pnl": round(unrealized, 2),
            "net_pnl": round(realized + unrealized, 2), "trades_completed": len(todays),
            "max_trades": max_trades, "streak": streak, "cutoff": cutoff,
            "cutoff_passed": cutoff_passed,
        },
        "risk_budget": {
            "maximum_daily_risk": max_daily_risk, "risk_used": round(risk_used, 2),
            "remaining_risk": round(remaining, 2), "daily_loss_limit": max_loss,
            "utilization_pct": round(100 * risk_used / max_daily_risk, 1),
        },
        "dynamic_sizing": sizing,
        "institutional_scorecard": {
            "overall": overall, "trade_selection": selection, "execution": execution,
            "risk_management": risk_score, "discipline": discipline,
            "opportunity_capture": 50 if not queue else selection,
        },
        "opportunity_queue": queue,
        "strategy_performance": _strategy_scorecards(history),
        "capital_efficiency": {
            "score": round(max(0, min(100, 50 + (realized / max_daily_risk * 50)))) if max_daily_risk else 50,
            "realized_per_trade": round(realized / len(todays), 2) if todays else None,
        },
        "safety_note": "Phase 11 allocates and scores session risk only. Phase 9 and Phase 10 remain authoritative for order risk and execution.",
    }
