"""APEX Trade Director Phase 7 — Adaptive Trade Management Intelligence.

Derives conservative, explainable management guidance from Phase 6's user-confirmed
trade archive. This module performs no import-time I/O, starts no workers, requests
no market data, and never sends broker orders.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional

_ACTION_RANK = {
    "HOLD": 0,
    "PROTECT_PROFIT": 1,
    "TAKE_PARTIAL": 2,
    "TRIM_25": 2,
    "TRIM_50": 2,
    "EXIT_OR_REDUCE": 3,
    "EXIT": 3,
}


def _f(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _median(values: Iterable[float]) -> Optional[float]:
    data = sorted(float(v) for v in values)
    if not data:
        return None
    n = len(data)
    mid = n // 2
    return data[mid] if n % 2 else (data[mid - 1] + data[mid]) / 2.0


def _session_bucket(entered_at: Any) -> str:
    text = str(entered_at or "")
    # Handles both ISO strings and the application's display timestamps.
    hour = minute = None
    try:
        time_part = text.split("T", 1)[1] if "T" in text else text.split(" ")[-2]
        hour, minute = [int(x) for x in time_part[:5].split(":")]
    except Exception:
        return "UNKNOWN"
    mins = hour * 60 + minute
    # Stored timestamps may be UTC. These buckets are descriptive, not execution rules.
    if mins < 10 * 60:
        return "OPENING"
    if mins < 11 * 60 + 30:
        return "MORNING"
    if mins < 13 * 60 + 30:
        return "MIDDAY"
    return "LATE_SESSION"


def build_adaptive_profile(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a transparent profile from archived, user-confirmed outcomes."""
    confirmed = [t for t in trades if isinstance(t.get("outcome"), dict)]
    scored = [t for t in confirmed if isinstance(t.get("scoring"), dict)]
    wins: List[Dict[str, Any]] = []
    losses: List[Dict[str, Any]] = []
    followed_yes = followed_no = 0
    pnl_values: List[float] = []
    action_scores: Dict[str, List[float]] = defaultdict(list)
    health_by_result: Dict[str, List[float]] = defaultdict(list)
    segment_stats: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))

    for trade in confirmed:
        outcome = trade.get("outcome") or {}
        pnl = _f(outcome.get("realized_pnl"))
        if pnl is not None:
            pnl_values.append(pnl)
            (wins if pnl > 0 else losses).append(trade)
        followed = outcome.get("followed_apex")
        if followed is True:
            followed_yes += 1
        elif followed is False:
            followed_no += 1

        result_key = "WIN" if (pnl is not None and pnl > 0) else "LOSS" if pnl is not None else "UNKNOWN"
        side = str(trade.get("side") or "UNKNOWN").upper()
        session = _session_bucket(trade.get("entered_at"))
        if pnl is not None:
            segment_stats[f"SIDE:{side}"]["pnl"].append(pnl)
            segment_stats[f"SESSION:{session}"]["pnl"].append(pnl)

        scoring = trade.get("scoring") or {}
        for event in scoring.get("events") or []:
            action = str(event.get("recommendation") or "UNKNOWN").upper()
            score = _f(event.get("score"))
            health = _f(event.get("trade_health"))
            if score is not None:
                action_scores[action].append(score)
            if health is not None and result_key != "UNKNOWN":
                health_by_result[result_key].append(health)

    n = len(confirmed)
    overall_win_rate = round((len(wins) / len(pnl_values)) * 100.0, 1) if pnl_values else None
    hold_scores = action_scores.get("HOLD", [])
    defensive_scores = [v for a, vals in action_scores.items() if _ACTION_RANK.get(a, 1) >= 1 for v in vals]
    median_win_health = _median(health_by_result.get("WIN", []))
    median_loss_health = _median(health_by_result.get("LOSS", []))

    # Thresholds are bounded tightly around the system defaults. They are advisory
    # until the archive reaches the minimum sample requirement.
    protect_threshold = 65.0
    trim_threshold = 75.0
    hold_threshold = 85.0
    if n >= 30:
        if median_loss_health is not None:
            protect_threshold = max(58.0, min(72.0, median_loss_health + 4.0))
        if median_win_health is not None:
            hold_threshold = max(82.0, min(92.0, median_win_health))
        trim_threshold = max(protect_threshold + 7.0, min(82.0, (protect_threshold + hold_threshold) / 2.0))

    action_rows = []
    for action, values in action_scores.items():
        action_rows.append({
            "action": action,
            "samples": len(values),
            "average_score": round(sum(values) / len(values), 1),
            "median_score": round(_median(values) or 0.0, 1),
        })
    action_rows.sort(key=lambda x: (-x["samples"], x["action"]))

    segments = []
    for key, values in segment_stats.items():
        pnls = values.get("pnl", [])
        if not pnls:
            continue
        segments.append({
            "segment": key,
            "samples": len(pnls),
            "win_rate": round(sum(1 for x in pnls if x > 0) / len(pnls) * 100.0, 1),
            "average_pnl": round(sum(pnls) / len(pnls), 2),
        })
    segments.sort(key=lambda x: (-x["samples"], x["segment"]))

    status = "OBSERVING" if n < 10 else "LEARNING" if n < 30 else "ADAPTIVE_READY" if n < 100 else "ESTABLISHED"
    mode = "SHADOW" if n < 30 else "ASSISTIVE"
    confidence_cap = 70 if n < 30 else 82 if n < 100 else 90

    return {
        "version": "PHASE_7",
        "status": status,
        "mode": mode,
        "confirmed_trades": n,
        "scored_trades": len(scored),
        "win_rate": overall_win_rate,
        "average_realized_pnl": round(sum(pnl_values) / len(pnl_values), 2) if pnl_values else None,
        "followed_apex": {"yes": followed_yes, "no": followed_no, "recorded": followed_yes + followed_no},
        "thresholds": {
            "exit_below": round(protect_threshold - 15.0, 1),
            "protect_below": round(protect_threshold, 1),
            "trim_below": round(trim_threshold, 1),
            "hold_confidently_at": round(hold_threshold, 1),
        },
        "calibration": {
            "hold_average_score": round(sum(hold_scores) / len(hold_scores), 1) if hold_scores else None,
            "defensive_average_score": round(sum(defensive_scores) / len(defensive_scores), 1) if defensive_scores else None,
            "median_health_on_wins": round(median_win_health, 1) if median_win_health is not None else None,
            "median_health_on_losses": round(median_loss_health, 1) if median_loss_health is not None else None,
            "confidence_cap": confidence_cap,
        },
        "by_action": action_rows,
        "segments": segments[:8],
        "minimum_sample_note": "Adaptive thresholds remain in shadow mode until 30 user-confirmed outcomes are available." if n < 30 else "Adaptive guidance is active but remains advisory and cannot send or modify broker orders.",
    }


def adaptive_guidance(base_recommendation: str, trade_health: Any, confidence: Any, profile: Dict[str, Any]) -> Dict[str, Any]:
    """Return explainable adaptive guidance; never makes a position less defensive."""
    base = str(base_recommendation or "HOLD").upper()
    health = _f(trade_health, 50.0) or 50.0
    base_conf = _f(confidence, 50.0) or 50.0
    thresholds = profile.get("thresholds") or {}
    suggested = base
    reason = "The learned profile agrees with the current Trade Director posture."

    if health < float(thresholds.get("exit_below", 50)):
        learned = "EXIT"
        reason = "Trade Health is below the personalized exit-risk threshold."
    elif health < float(thresholds.get("protect_below", 65)):
        learned = "PROTECT_PROFIT"
        reason = "Trade Health is below the personalized capital-protection threshold."
    elif health < float(thresholds.get("trim_below", 75)):
        learned = "TRIM_50"
        reason = "Trade Health is below the personalized trim threshold."
    else:
        learned = "HOLD"
        reason = "Trade Health remains above the learned defensive thresholds."

    if _ACTION_RANK.get(learned, 0) > _ACTION_RANK.get(base, 0):
        suggested = learned
    else:
        suggested = base

    active = profile.get("mode") == "ASSISTIVE"
    return {
        "version": "PHASE_7",
        "mode": profile.get("mode", "SHADOW"),
        "active": active,
        "base_recommendation": base,
        "adaptive_recommendation": suggested,
        "learned_posture": learned,
        "health": round(health, 1),
        "confidence": min(round(base_conf, 1), float((profile.get("calibration") or {}).get("confidence_cap", 70))),
        "reason": reason,
        "would_change_action": suggested != base,
        "applied_to_live_recommendation": False,
        "safety_note": "Phase 7 operates as an advisory second opinion. It never weakens a defensive recommendation and does not send broker orders.",
    }
