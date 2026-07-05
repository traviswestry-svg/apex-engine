"""engine/director/conflict.py — disagreement & veto logic (Part 12).

Counting bullish vs bearish engines is not enough — you have to detect *conflict*.
Flow bullish while gamma bearish, POC falling while price above VWAP, etc. This
module classifies overall alignment and decides what trade type is permitted:

    STRONG_ALIGNMENT -> CONVICTION permitted
    MIXED            -> SCALP only
    CONFLICT         -> SCALP only if execution confirms
    VETO             -> no new entry at all

Hard vetoes (stale data, market closed, extreme gamma flip risk against side)
override everything. This reads only already-computed engine fields.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .contracts import ConflictReport


def _u(v: Any) -> str:
    return str(v or "").upper()


def _f(v: Any, d: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _dir(bias: str) -> int:
    """+1 bullish, -1 bearish, 0 neutral from a bias string."""
    b = _u(bias)
    if any(w in b for w in ("BULL", "ACCUM", "RISING", "ACCEPTING_HIGHER", "LONG", "CALL")):
        return 1
    if any(w in b for w in ("BEAR", "DISTRIB", "FALLING", "ACCEPTING_LOWER", "SHORT", "PUT")):
        return -1
    return 0


def build_conflict_report(
    *,
    market_state: Dict[str, Any],
    institutional: Dict[str, Any],
    auction: Dict[str, Any],
    dealer: Dict[str, Any],
    flow_class: str = "",
    side_hint: str = "",
    data_stale: bool = False,
    market_open: bool = True,
) -> ConflictReport:
    ms = market_state or {}
    ii = institutional or {}
    rep = ConflictReport()

    # ── directional reads from each independent engine ─────────────────────────
    reads: Dict[str, int] = {}
    reads["flow"] = _dir(ii.get("flow_bias") or ms.get("flow_bias"))
    reads["gamma"] = 1 if _u(ii.get("gamma_regime") or ms.get("gamma_regime")).startswith("POSITIVE") \
        else (-1 if _u(ii.get("gamma_regime") or ms.get("gamma_regime")).startswith("NEGATIVE") else 0)
    reads["poc"] = _dir(ii.get("poc_migration") or ms.get("poc_migration"))
    reads["auction"] = _dir(ii.get("auction_bias") or (auction or {}).get("acceptance") or ms.get("auction_state"))
    reads["dealer"] = _dir(ii.get("dealer_bias"))
    reads["driver"] = _dir(ii.get("market_driver_bias"))

    # price vs VWAP as an independent structural read
    price, vwap = _f(ms.get("price")), _f(ms.get("vwap"))
    reads["price_vwap"] = 1 if (price and vwap and price > vwap) else (-1 if (price and vwap and price < vwap) else 0)

    # flow acceleration reinforces/contradicts the flow read
    fc = _u(flow_class)
    if "BUYERS_ACCEL" in fc or fc == "BULLISH_FLOW_REVERSAL":
        reads["flow_accel"] = 1
    elif "SELLERS_ACCEL" in fc or fc == "BEARISH_FLOW_REVERSAL":
        reads["flow_accel"] = -1
    else:
        reads["flow_accel"] = 0

    bull = sum(1 for v in reads.values() if v > 0)
    bear = sum(1 for v in reads.values() if v < 0)
    rep.bull_signals, rep.bear_signals = bull, bear

    # ── conflicts: named pairwise disagreements that matter for 0DTE ──────────
    def _conflict(a: str, b: str, label: str):
        if reads.get(a) and reads.get(b) and reads[a] == -reads[b]:
            rep.conflicts.append(label)

    _conflict("flow", "gamma", "Flow and dealer gamma disagree")
    _conflict("flow", "poc", "Flow direction opposes POC migration")
    _conflict("poc", "price_vwap", "POC migration opposes price/VWAP location")
    _conflict("auction", "flow", "Auction acceptance opposes flow")
    _conflict("flow_accel", "flow", "Flow acceleration is fading against the flow bias")

    # agreements worth stating
    for k, v in reads.items():
        if v > 0:
            rep.agreements.append(f"{k} bullish")
        elif v < 0:
            rep.agreements.append(f"{k} bearish")

    # ── hard vetoes ───────────────────────────────────────────────────────────
    if not market_open:
        rep.hard_veto = True
        rep.veto_reasons.append("Market is not in a tradeable session.")
    if data_stale:
        rep.hard_veto = True
        rep.veto_reasons.append("Institutional data is stale — cannot approve a new entry.")

    # gamma flip risk against the intended side
    flip_risk = _u(ms.get("flip_risk"))
    if side_hint and flip_risk in ("HIGH", "ELEVATED"):
        rep.veto_reasons.append("Elevated gamma-flip risk near price.")
        rep.conflicts.append("Gamma flip risk elevated")

    # ── alignment classification ──────────────────────────────────────────────
    net = bull - bear
    n_conflict = len(rep.conflicts)

    if rep.hard_veto:
        rep.alignment, rep.permitted_type = "VETO", "NONE"
    elif n_conflict == 0 and abs(net) >= 4:
        rep.alignment, rep.permitted_type = "STRONG_ALIGNMENT", "CONVICTION"
    elif n_conflict >= 2:
        rep.alignment, rep.permitted_type = "CONFLICT", "SCALP"
    elif abs(net) >= 2:
        rep.alignment, rep.permitted_type = "MIXED", "SCALP"
    else:
        rep.alignment, rep.permitted_type = "MIXED", "SCALP"

    if rep.alignment == "STRONG_ALIGNMENT":
        rep.summary = f"Strong institutional alignment ({bull} bullish / {bear} bearish, no conflicts)."
    elif rep.alignment == "VETO":
        rep.summary = "Hard veto active — no new entries. " + " ".join(rep.veto_reasons)
    elif rep.alignment == "CONFLICT":
        rep.summary = "Institutional conflict detected — scalp only if execution confirms."
    else:
        rep.summary = f"Mixed institutional picture ({bull} bullish / {bear} bearish) — scalp only."

    return rep
