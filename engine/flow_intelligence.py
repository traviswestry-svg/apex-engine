"""engine/flow_intelligence.py — APEX 6.5 Flow Intelligence 2.0.

Interprets institutional flow instead of just displaying it.
Every sweep, block, and split gets a plain-English institutional read:
  conviction level, urgency, intent (accumulation/distribution), and
  what it implies for dealer positioning.

Design rules:
  - Consumes existing flow_tape.py output and quantdata flow snapshot.
  - Never duplicates API calls or flow_tape calculations.
  - Returns interpretations for both tape rows and aggregate flow.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


def _sf(v: Any, d: float = 0.0) -> float:
    try:
        f = float(v) if v is not None else d
        return d if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return d


def _fmtM(v: float) -> str:
    """Format dollar value as $X.XM or $X.XB."""
    a = abs(v)
    if a >= 1_000_000_000:
        return f"${a/1_000_000_000:.1f}B"
    if a >= 1_000_000:
        return f"${a/1_000_000:.1f}M"
    return f"${a:,.0f}"


# ── Flow type interpretation ──────────────────────────────────────────────────

FLOW_INTERPRETATIONS: Dict[str, Dict[str, str]] = {
    "BUY_SWEEP": {
        "intent":      "Urgent institutional buying",
        "conviction":  "HIGH",
        "urgency":     "HIGH",
        "accumulation": "YES",
        "description": (
            "A buy sweep crosses multiple exchanges simultaneously, "
            "indicating urgency — the institution needed to get filled immediately "
            "at any available price. This is aggressive, directional intent."
        ),
        "dealer_impact": (
            "Dealers must short calls or sell delta to hedge, "
            "creating potential short-term resistance as dealer hedging absorbs buying."
        ),
        "implication": "Bullish — institutions are urgently buying exposure. Momentum likely.",
    },
    "SELL_SWEEP": {
        "intent":      "Urgent institutional selling",
        "conviction":  "HIGH",
        "urgency":     "HIGH",
        "accumulation": "NO",
        "description": (
            "A sell sweep crosses multiple exchanges simultaneously, "
            "indicating urgency — the institution needed puts immediately. "
            "This is aggressive, directional bearish intent."
        ),
        "dealer_impact": (
            "Dealers must short puts or buy delta to hedge, "
            "creating potential short-term support as dealer hedging absorbs selling."
        ),
        "implication": "Bearish — institutions are urgently buying downside protection. Momentum likely.",
    },
    "BUY_BLOCK": {
        "intent":      "Institutional accumulation",
        "conviction":  "HIGH",
        "urgency":     "LOW",
        "accumulation": "YES",
        "description": (
            "A buy block is a single large transaction — high conviction but without urgency. "
            "The institution was willing to wait for a single fill. "
            "This is typically portfolio-level accumulation or strategic positioning."
        ),
        "dealer_impact": (
            "Dealers absorb the block on the other side. "
            "Large blocks require significant dealer delta hedging, creating directional pressure."
        ),
        "implication": "Bullish — institutional accumulation. High conviction, no rush. Likely early in a move.",
    },
    "SELL_BLOCK": {
        "intent":      "Institutional distribution",
        "conviction":  "HIGH",
        "urgency":     "LOW",
        "accumulation": "NO",
        "description": (
            "A sell block is a large single transaction — high conviction bearish positioning "
            "without urgency. Typically portfolio-level protection or strategic shorting."
        ),
        "dealer_impact": (
            "Dealers absorb the block. Large put blocks create dealer long delta hedging, "
            "providing support as dealers buy futures to hedge."
        ),
        "implication": "Bearish — institutional distribution or protection buying. Strategic move, not panic.",
    },
    "BUY_SPLIT": {
        "intent":      "Hidden institutional accumulation",
        "conviction":  "MEDIUM",
        "urgency":     "LOW",
        "accumulation": "YES",
        "description": (
            "A buy split is broken into multiple smaller orders to reduce market impact — "
            "the institution is hiding its size. This indicates significant intent "
            "but deliberate disguise. The true size is likely larger than visible."
        ),
        "dealer_impact": (
            "Splits spread dealer hedging across time, making the impact less visible "
            "but cumulative. Watch for split patterns to identify hidden accumulation."
        ),
        "implication": "Mildly bullish — hidden accumulation. Position may be larger than it appears.",
    },
    "SELL_SPLIT": {
        "intent":      "Hidden institutional distribution",
        "conviction":  "MEDIUM",
        "urgency":     "LOW",
        "accumulation": "NO",
        "description": (
            "A sell split is broken into smaller orders to reduce impact — "
            "the institution is hiding its distribution. Watch for cumulative put splits "
            "as an early warning of institutional exit."
        ),
        "dealer_impact": (
            "Gradual dealer hedging from cumulative put positions. "
            "Less visible than blocks but can create sustained downward pressure."
        ),
        "implication": "Mildly bearish — hidden distribution. Cumulative effect may exceed what's visible.",
    },
}


def interpret_tape_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Add institutional interpretation to a single flow tape row."""
    label   = str(row.get("tape_label") or "").upper()
    premium = _sf(row.get("premium"))
    side    = str(row.get("aggressor_side") or "")
    ticker  = str(row.get("ticker") or "")
    strike  = row.get("strike")
    exp     = row.get("expiration") or ""
    ctype   = str(row.get("contract_type") or "").upper()

    interp  = FLOW_INTERPRETATIONS.get(label, {})
    if not interp:
        return {**row, "interpretation": None}

    # Size context
    prem_m = abs(premium) / 1_000_000 if premium else 0
    if prem_m >= 10:
        size_label = "INSTITUTIONAL MEGA-BLOCK"
        size_note  = f"Premium of {_fmtM(premium)} is mega-institutional scale — portfolio-level positioning."
    elif prem_m >= 2:
        size_label = "LARGE INSTITUTIONAL"
        size_note  = f"Premium of {_fmtM(premium)} is clearly institutional scale."
    elif prem_m >= 0.5:
        size_label = "INSTITUTIONAL"
        size_note  = f"Premium of {_fmtM(premium)} is institutional size."
    else:
        size_label = "ELEVATED RETAIL / SMALL INST."
        size_note  = f"Premium of {_fmtM(premium)} is below typical institutional threshold."

    # Contract context
    contract_str = f"{ticker} {strike}{ctype[0] if ctype else ''} {exp}" if strike else f"{ticker} {ctype}"

    # Combined plain-English read
    institutional_read = (
        f"{interp.get('intent', '')} detected in {contract_str}. "
        f"{size_note} "
        f"{interp.get('description', '')} "
        f"{interp.get('implication', '')}"
    )

    return {
        **row,
        "interpretation": {
            "intent":           interp.get("intent"),
            "conviction":       interp.get("conviction"),
            "urgency":          interp.get("urgency"),
            "is_accumulation":  interp.get("accumulation") == "YES",
            "dealer_impact":    interp.get("dealer_impact"),
            "implication":      interp.get("implication"),
            "size_label":       size_label,
            "institutional_read": institutional_read,
        },
    }


def build_flow_intelligence_2(
    *,
    flow_snapshot:   Dict[str, Any],
    tape_rows:       List[Dict[str, Any]],
    tape_summary:    Dict[str, Any],
    dealer_delta:    Optional[Dict[str, Any]] = None,
    dealer_gamma:    Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Flow Intelligence 2.0 — aggregate interpretation of all flow signals.

    Produces:
      - Flow Conviction (0–100)
      - Flow Urgency    (LOW/MEDIUM/HIGH)
      - Accumulation vs Distribution read
      - Sweep Pressure score
      - Block Conviction score
      - Split Accumulation score
      - Dealer Response read
      - Aggregate narrative
    """
    call_prem    = _sf(flow_snapshot.get("call_premium"))
    put_prem     = _sf(flow_snapshot.get("put_premium"))
    net_prem     = _sf(flow_snapshot.get("net_premium"))
    sweep_count  = int(_sf(flow_snapshot.get("sweep_count")))
    flow_bias    = str(flow_snapshot.get("bias") or "MIXED")
    flow_score   = _sf(flow_snapshot.get("flow_score"), 50.0)
    call_ratio   = _sf(flow_snapshot.get("call_ratio_pct"), 50.0)
    order_score  = _sf(flow_snapshot.get("order_flow_score"), 50.0)
    block_prem   = _sf(tape_summary.get("block_premium"))
    split_prem   = _sf(tape_summary.get("split_premium"))
    sweep_prem   = _sf(tape_summary.get("sweep_premium"))
    total_prem   = call_prem + put_prem or 1.0

    # ── Interpret tape rows ──
    interpreted_rows = [interpret_tape_row(r) for r in tape_rows[:20]]

    # ── Component scores ──

    # Sweep Pressure (0–100): urgency of institutional positioning
    sweep_score = min(100, (sweep_count * 12) + (abs(sweep_prem) / 1_000_000 * 2))

    # Block Conviction (0–100): size and direction of block flow
    block_score = min(100, abs(block_prem) / 1_000_000 * 3 + (20 if flow_bias != "MIXED" else 0))

    # Split Accumulation (0–100): hidden positioning
    split_score = min(100, abs(split_prem) / 1_000_000 * 4)

    # Dealer Response (0–100): estimated dealer activity from flow
    dealer_resp_score = 50.0
    if dealer_delta:
        dealer_resp_score = _sf(dealer_delta.get("confidence"), 50.0)
    elif dealer_gamma:
        dealer_resp_score = _sf(dealer_gamma.get("score"), 50.0)

    # Overall Flow Conviction
    conviction_score = (
        flow_score * 0.35 +
        order_score * 0.25 +
        sweep_score * 0.20 +
        block_score * 0.10 +
        dealer_resp_score * 0.10
    )

    # ── Urgency classification ──
    if sweep_count >= 5 or sweep_score >= 70:
        urgency = "HIGH"
        urgency_note = f"{sweep_count} active sweeps indicate urgent institutional positioning."
    elif sweep_count >= 2 or sweep_score >= 40:
        urgency = "MEDIUM"
        urgency_note = "Multiple sweeps suggest building institutional momentum."
    else:
        urgency = "LOW"
        urgency_note = "Low sweep activity — institutions are positioning slowly or not at all."

    # ── Accumulation vs Distribution ──
    if call_ratio > 58 and net_prem > 0:
        flow_intent = "ACCUMULATION"
        intent_note = (
            f"Call premium dominates at {call_ratio:.0f}% of total flow. "
            f"Net premium is {_fmtM(net_prem)} bullish. "
            "Institutions are accumulating upside exposure."
        )
    elif call_ratio < 42 and net_prem < 0:
        flow_intent = "DISTRIBUTION"
        intent_note = (
            f"Put premium dominates at {100-call_ratio:.0f}% of total flow. "
            f"Net premium is {_fmtM(abs(net_prem))} bearish. "
            "Institutions are accumulating downside protection / distributing."
        )
    else:
        flow_intent = "MIXED"
        intent_note = (
            f"Call/put premium split is {call_ratio:.0f}%/{100-call_ratio:.0f}%. "
            "No clear directional accumulation or distribution. "
            "Institutions may be hedging existing positions rather than establishing new ones."
        )

    # ── Dealer response interpretation ──
    if dealer_delta:
        dealer_read = dealer_delta.get("market_impact", "")
    elif dealer_gamma:
        dealer_read = dealer_gamma.get("behavior", "")[:120]
    else:
        dealer_read = "Dealer response analysis unavailable."

    # ── Narrative ──
    narrative = (
        f"{intent_note} "
        f"{urgency_note} "
        f"Flow conviction: {conviction_score:.0f}/100. "
        f"{dealer_read}"
    )

    # ── Key call-outs (most significant individual flows) ──
    call_outs = []
    for r in interpreted_rows[:5]:
        interp = r.get("interpretation")
        if interp and interp.get("institutional_read"):
            call_outs.append(interp["institutional_read"])

    return {
        "available":        True,
        "version":          "2.0",
        # Scores
        "flow_conviction":  round(conviction_score, 1),
        "sweep_pressure":   round(sweep_score, 1),
        "block_conviction": round(block_score, 1),
        "split_accumulation": round(split_score, 1),
        "dealer_response":  round(dealer_resp_score, 1),
        # Classification
        "urgency":          urgency,
        "urgency_note":     urgency_note,
        "flow_intent":      flow_intent,
        "intent_note":      intent_note,
        "flow_bias":        flow_bias,
        "call_ratio_pct":   round(call_ratio, 1),
        "net_premium":      round(net_prem, 0),
        "call_premium":     round(call_prem, 0),
        "put_premium":      round(put_prem, 0),
        "sweep_count":      sweep_count,
        # Narrative
        "narrative":        narrative,
        "dealer_read":      dealer_read,
        "call_outs":        call_outs[:3],
        # Interpreted rows
        "interpreted_rows": interpreted_rows,
    }
