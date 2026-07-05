"""engine/director/thesis.py — active hold intelligence (Part 8).

While a position is open, continuously classify whether the *original thesis* is
strengthening, intact, weakening, conflicted or invalidated. This is what turns a
static stop into an evidence-based hold. Inputs: flow, flow acceleration, auction
state, POC migration, acceptance/rejection, gamma, price vs the dynamic hold
level, and time in trade.

Output is a score-driven classification plus the specific evidence bullets that
drove it, so the directive can explain *why*.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .contracts import FlowAcceleration, HoldLevel


def _u(v: Any) -> str:
    return str(v or "").upper()


def _f(v: Any, d: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def classify_thesis(
    *,
    side: str,
    market_state: Dict[str, Any],
    institutional: Dict[str, Any],
    flow_acc: FlowAcceleration,
    hold_level: HoldLevel,
    time_in_trade_s: float = 0.0,
) -> Tuple[str, int, List[str]]:
    """Return (thesis_status, thesis_score 0..100, evidence[])."""
    side = _u(side)
    ms = market_state or {}
    ii = institutional or {}
    ev: List[str] = []
    score = 50  # neutral baseline; >65 strengthening, <35 weakening, hard-fail invalidates

    bullish = side == "CALL"
    fc = _u(flow_acc.classification)

    # ── flow acceleration (heaviest weight) ────────────────────────────────────
    if bullish:
        if fc == "BUYERS_ACCELERATING":
            score += 22; ev.append("Buyers accelerating into the position.")
        elif fc == "BUYERS_STEADY":
            score += 8; ev.append("Buyer flow steady.")
        elif fc == "BUYERS_WEAKENING":
            score -= 12; ev.append("Buyer acceleration is fading.")
        elif fc in ("SELLERS_ACCELERATING", "BEARISH_FLOW_REVERSAL"):
            score -= 28; ev.append("Sellers taking control against the CALL.")
        elif fc == "FLOW_EXHAUSTION":
            score -= 16; ev.append("Buyer flow showing exhaustion.")
    else:
        if fc == "SELLERS_ACCELERATING":
            score += 22; ev.append("Sellers accelerating into the position.")
        elif fc == "SELLERS_STEADY":
            score += 8; ev.append("Seller flow steady.")
        elif fc == "SELLERS_WEAKENING":
            score -= 12; ev.append("Seller acceleration is fading.")
        elif fc in ("BUYERS_ACCELERATING", "BULLISH_FLOW_REVERSAL"):
            score -= 28; ev.append("Buyers taking control against the PUT.")
        elif fc == "FLOW_EXHAUSTION":
            score -= 16; ev.append("Seller flow showing exhaustion.")

    # ── POC migration ──────────────────────────────────────────────────────────
    poc = _u(ii.get("poc_migration") or ms.get("poc_migration"))
    if bullish and poc == "RISING":
        score += 10; ev.append("Developing POC migrating higher.")
    elif bullish and poc == "FALLING":
        score -= 12; ev.append("Developing POC turning lower against the CALL.")
    elif not bullish and poc == "FALLING":
        score += 10; ev.append("Developing POC migrating lower.")
    elif not bullish and poc == "RISING":
        score -= 12; ev.append("Developing POC turning higher against the PUT.")

    # ── auction acceptance ──────────────────────────────────────────────────────
    acc = _u(ii.get("acceptance") or ii.get("auction_state") or ms.get("auction_state"))
    if "ACCEPT" in acc and ("HIGHER" in acc or "ABOVE" in acc):
        score += (8 if bullish else -8); ev.append("Auction accepting higher.")
    elif "ACCEPT" in acc and ("LOWER" in acc or "BELOW" in acc):
        score += (-8 if bullish else 8); ev.append("Auction accepting lower.")
    elif "REJECT" in acc:
        ev.append("Auction rejection in progress — location fragile.")
        score -= 6

    # ── price vs the dynamic hold level (structural truth) ─────────────────────
    price = _f(ms.get("price"))
    invalidated = False
    if hold_level.available and hold_level.level and price:
        if hold_level.direction == "ABOVE":
            if price < hold_level.level:
                invalidated = True
                ev.append(f"Price lost the hold level {hold_level.level} ({hold_level.source}).")
            else:
                score += 6; ev.append(f"Price holding above {hold_level.level}.")
        elif hold_level.direction == "BELOW":
            if price > hold_level.level:
                invalidated = True
                ev.append(f"Price lost the hold level {hold_level.level} ({hold_level.source}).")
            else:
                score += 6; ev.append(f"Price holding below {hold_level.level}.")

    # ── gamma regime supportiveness ────────────────────────────────────────────
    gr = _u(ii.get("gamma_regime") or ms.get("gamma_regime"))
    if gr.startswith("NEGATIVE"):
        ev.append("Negative-gamma regime — moves can extend and reverse fast.")
        score -= 3

    score = max(0, min(100, score))

    # ── classification ─────────────────────────────────────────────────────────
    # A lost hold level with confirming opposite flow is an outright invalidation.
    opp_flow = (bullish and fc in ("SELLERS_ACCELERATING", "BEARISH_FLOW_REVERSAL")) or \
               (not bullish and fc in ("BUYERS_ACCELERATING", "BULLISH_FLOW_REVERSAL"))
    if invalidated and opp_flow:
        return "THESIS_INVALIDATED", score, ev
    if invalidated:
        return "THESIS_WEAKENING", min(score, 34), ev

    # conflicted if flow and structure point opposite ways
    conflicted = (fc.startswith("BUYERS") and poc == "FALLING") or \
                 (fc.startswith("SELLERS") and poc == "RISING")
    if conflicted and 35 <= score <= 65:
        return "THESIS_CONFLICTED", score, ev

    if score >= 66:
        return "THESIS_STRENGTHENING", score, ev
    if score <= 34:
        return "THESIS_WEAKENING", score, ev
    return "THESIS_INTACT", score, ev
