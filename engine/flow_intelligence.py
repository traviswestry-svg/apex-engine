"""engine/flow_intelligence.py — APEX 7.0 Flow Intelligence 3.0.

Interprets institutional flow instead of displaying raw numbers.
Every sweep, block, and split gets a plain-English read with:
  - Intent classification (accumulation/distribution/hedge/momentum/closing)
  - Urgency score
  - Conviction level
  - What it implies for dealers and price direction
  - Contradiction detection (e.g. high blocks but mixed direction)

Consumes: flow_tape.py output, quantdata flow snapshot, dark pool data.
Produces: Flow Interpretation 3.0 object.
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
    a = abs(v)
    if a >= 1_000_000_000:
        return f"${a/1_000_000_000:.1f}B"
    if a >= 1_000_000:
        return f"${a/1_000_000:.1f}M"
    return f"${a:,.0f}"


# ── Flow type interpretations (Sprint 7.0.6 — complete set) ──────────────────

FLOW_INTERP: Dict[str, Dict[str, str]] = {
    "BUY_SWEEP": {
        "intent":       "Urgent institutional buying",
        "intent_class": "MOMENTUM",
        "conviction":   "HIGH",
        "urgency":      "HIGH",
        "is_accum":     "YES",
        "description":  "A buy sweep crosses multiple exchanges simultaneously — the institution needed fills immediately at any price. This is aggressive, directional bullish intent.",
        "dealer":       "Dealers must sell delta (short futures) to hedge short calls — creates overhead resistance but confirms institutional urgency.",
        "implication":  "Bullish momentum. Institutions are not waiting for better prices.",
    },
    "SELL_SWEEP": {
        "intent":       "Urgent institutional selling / protection",
        "intent_class": "MOMENTUM",
        "conviction":   "HIGH",
        "urgency":      "HIGH",
        "is_accum":     "NO",
        "description":  "A sell sweep crosses multiple exchanges simultaneously — urgent put buying or call selling. Directional bearish intent with no patience.",
        "dealer":       "Dealers must buy delta (long futures) to hedge short puts — creates underlying support but confirms bearish institutional conviction.",
        "implication":  "Bearish momentum. Institutions are urgently buying downside.",
    },
    "BUY_BLOCK": {
        "intent":       "Institutional accumulation",
        "intent_class": "ACCUMULATION",
        "conviction":   "HIGH",
        "urgency":      "LOW",
        "is_accum":     "YES",
        "description":  "A single large buy — high conviction, no urgency. Portfolio-level accumulation or strategic positioning. Likely early in a move.",
        "dealer":       "Large block requires significant dealer delta hedging — creates directional futures pressure proportional to the block size.",
        "implication":  "Bullish accumulation. High conviction without urgency — typically precedes sustained moves.",
    },
    "SELL_BLOCK": {
        "intent":       "Institutional distribution / protection",
        "intent_class": "DISTRIBUTION",
        "conviction":   "HIGH",
        "urgency":      "LOW",
        "is_accum":     "NO",
        "description":  "A single large put buy or call sell — strategic, not panicked. Portfolio protection or deliberate bearish positioning.",
        "dealer":       "Dealers buy futures to hedge short puts, providing underlying support despite the bearish intent.",
        "implication":  "Bearish distribution. Strategic exit or downside protection — watch for follow-through.",
    },
    "BUY_SPLIT": {
        "intent":       "Hidden institutional accumulation",
        "intent_class": "ACCUMULATION",
        "conviction":   "MEDIUM",
        "urgency":      "LOW",
        "is_accum":     "YES",
        "description":  "Call buying broken across multiple smaller orders to reduce market impact. The institution is hiding its size — true position is likely larger than visible.",
        "dealer":       "Split accumulation spreads dealer hedging across time, making the cumulative impact less visible but persistent.",
        "implication":  "Mildly bullish. Hidden accumulation — the true scale may be larger than it appears.",
    },
    "SELL_SPLIT": {
        "intent":       "Hidden institutional distribution",
        "intent_class": "DISTRIBUTION",
        "conviction":   "MEDIUM",
        "urgency":      "LOW",
        "is_accum":     "NO",
        "description":  "Put buying or call selling broken into smaller orders. Institution is hiding distribution — an early warning of institutional exit.",
        "dealer":       "Gradual dealer hedging from cumulative positions. Less visible but creates sustained directional pressure.",
        "implication":  "Mildly bearish. Watch for cumulative split patterns to identify stealth exit.",
    },
}


def interpret_tape_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Interpret a single flow tape row."""
    label   = str(row.get("tape_label") or "").upper()
    premium = _sf(row.get("premium"))
    ticker  = str(row.get("ticker") or "")
    strike  = row.get("strike")
    ctype   = str(row.get("contract_type") or "").upper()
    exp     = row.get("expiration") or ""
    interp  = FLOW_INTERP.get(label, {})
    if not interp:
        return {**row, "interpretation": None}

    prem_m = abs(premium) / 1_000_000 if premium else 0
    if prem_m >= 10:
        size_label = "MEGA"
    elif prem_m >= 2:
        size_label = "INSTITUTIONAL"
    elif prem_m >= 0.5:
        size_label = "ELEVATED"
    else:
        size_label = "SMALL"

    contract = f"{ticker} {strike}{ctype[0] if ctype else ''} {exp}" if strike else f"{ticker} {ctype}"
    read = (
        f"{interp.get('intent', '')} in {contract} ({size_label}, {_fmtM(premium)}). "
        f"{interp.get('description', '')} "
        f"{interp.get('implication', '')}"
    )

    return {
        **row,
        "interpretation": {
            "intent":       interp.get("intent"),
            "intent_class": interp.get("intent_class"),
            "conviction":   interp.get("conviction"),
            "urgency":      interp.get("urgency"),
            "is_accum":     interp.get("is_accum") == "YES",
            "dealer_note":  interp.get("dealer"),
            "implication":  interp.get("implication"),
            "size_label":   size_label,
            "read":         read,
        },
    }


def build_flow_intelligence_2(
    *,
    flow_snapshot:  Dict[str, Any],
    tape_rows:      List[Dict[str, Any]],
    tape_summary:   Dict[str, Any],
    dark_pool:      Optional[Dict[str, Any]] = None,
    dealer_delta:   Optional[Dict[str, Any]] = None,
    dealer_gamma:   Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Flow Intelligence 3.0 — aggregate interpretation with contradiction detection."""
    call_prem   = _sf(flow_snapshot.get("call_premium"))
    put_prem    = _sf(flow_snapshot.get("put_premium"))
    net_prem    = _sf(flow_snapshot.get("net_premium"))
    sweep_count = int(_sf(flow_snapshot.get("sweep_count")))
    flow_bias   = str(flow_snapshot.get("bias") or "MIXED")
    flow_score  = _sf(flow_snapshot.get("flow_score"), 50.0)
    call_ratio  = _sf(flow_snapshot.get("call_ratio_pct"), 50.0)
    order_score = _sf(flow_snapshot.get("order_flow_score"), 50.0)
    block_prem  = _sf(tape_summary.get("block_premium"))
    split_prem  = _sf(tape_summary.get("split_premium"))
    sweep_prem  = _sf(tape_summary.get("sweep_premium"))
    total_prem  = call_prem + put_prem or 1.0

    # Dark pool confirmation
    dp_score  = _sf((dark_pool or {}).get("dark_pool_score"), 50.0)
    dp_status = str((dark_pool or {}).get("dark_pool_status") or "")
    dp_avail  = dp_score != 50.0 or bool(dp_status and "NOT CONFIGURED" not in dp_status)

    # Interpret tape rows
    interpreted = [interpret_tape_row(r) for r in tape_rows[:25]]

    # Component scores
    sweep_score = min(100, sweep_count * 12 + abs(sweep_prem) / 1_000_000 * 2)
    block_score = min(100, abs(block_prem) / 1_000_000 * 3 + (20 if flow_bias != "MIXED" else 0))
    split_score = min(100, abs(split_prem) / 1_000_000 * 4)
    dp_adj_score = dp_score if dp_avail else 50.0
    dealer_r    = _sf((dealer_delta or {}).get("confidence") or (dealer_gamma or {}).get("score"), 50.0)

    conviction = (
        flow_score  * 0.30 +
        order_score * 0.25 +
        sweep_score * 0.20 +
        block_score * 0.10 +
        dp_adj_score * 0.10 +
        dealer_r    * 0.05
    )

    # Urgency
    if sweep_count >= 5 or sweep_score >= 70:
        urgency = "HIGH"
        urgency_note = f"{sweep_count} active sweeps signal urgent institutional repositioning."
    elif sweep_count >= 2 or sweep_score >= 40:
        urgency = "MEDIUM"
        urgency_note = "Multiple sweeps indicate building institutional pressure."
    else:
        urgency = "LOW"
        urgency_note = "Low sweep activity. Institutions positioning slowly or not at all."

    # Intent classification
    if call_ratio > 58 and net_prem > 0:
        flow_intent  = "BULLISH_ACCUMULATION"
        intent_note  = f"Call premium dominates at {call_ratio:.0f}%. Net flow {_fmtM(net_prem)} bullish."
    elif call_ratio < 42 and net_prem < 0:
        flow_intent  = "BEARISH_DISTRIBUTION"
        intent_note  = f"Put premium dominates at {100-call_ratio:.0f}%. Net flow {_fmtM(abs(net_prem))} bearish."
    else:
        flow_intent  = "MIXED"
        intent_note  = f"Call/put split {call_ratio:.0f}%/{100-call_ratio:.0f}% — no clear directional accumulation."

    # ── Contradiction detection (Sprint 7.0.6) ────────────────────────────────
    contradictions: List[str] = []

    # Block conviction high but flow mixed
    if block_score >= 60 and flow_bias == "MIXED":
        contradictions.append(
            "Block conviction is high but directional bias is mixed — institutions are making large trades "
            "but not aligned in direction. Expect two-way trade until one side dominates."
        )

    # Sweeps bullish but dark pool bearish (or vice versa)
    if dp_avail and sweep_count >= 3:
        if flow_bias == "BULLISH" and dp_score < 40:
            contradictions.append(
                "Surface flow is bullish (sweeps) but dark pool activity is bearish. "
                "Possible that visible buying is retail/momentum while institutions distribute quietly."
            )
        elif flow_bias == "BEARISH" and dp_score > 60:
            contradictions.append(
                "Surface flow is bearish but dark pool is bullish. "
                "Potential stealth accumulation while visible flow appears defensive."
            )

    # High urgency but mixed conviction
    if urgency == "HIGH" and block_score < 40:
        contradictions.append(
            "High sweep urgency but low block conviction — aggressive retail or momentum-driven flow "
            "rather than deliberate institutional positioning."
        )

    # Dealer response
    dealer_read = ""
    if dealer_delta:
        dealer_read = dealer_delta.get("market_impact") or dealer_delta.get("narrative") or ""
    elif dealer_gamma:
        dealer_read = dealer_gamma.get("behavior") or ""

    # Narrative
    narrative = (
        f"{intent_note} "
        f"{urgency_note} "
        f"Flow conviction: {conviction:.0f}/100. "
        f"{'Contradiction: ' + contradictions[0] if contradictions else ''}"
    ).strip()

    # Dark pool confirmation line
    dp_line = ""
    if dp_avail:
        if dp_score >= 65:
            dp_line = f"Dark pool activity is bullish ({dp_score:.0f}/100) — confirming underlying accumulation."
        elif dp_score <= 35:
            dp_line = f"Dark pool activity is bearish ({dp_score:.0f}/100) — institutional distribution continuing."
        else:
            dp_line = "Dark pool is neutral — no strong dark flow confirmation."

    # Top call-outs
    call_outs = []
    for r in interpreted[:5]:
        interp = r.get("interpretation")
        if interp and interp.get("read"):
            call_outs.append(interp["read"])

    return {
        "available":           True,
        "version":             "3.0",
        # Scores
        "flow_conviction":     round(conviction, 1),
        "sweep_pressure":      round(sweep_score, 1),
        "block_conviction":    round(block_score, 1),
        "split_accumulation":  round(split_score, 1),
        "dealer_response":     round(dealer_r, 1),
        "dark_pool_score":     round(dp_adj_score, 1),
        # Classifications
        "urgency":             urgency,
        "urgency_note":        urgency_note,
        "flow_intent":         flow_intent,
        "intent_note":         intent_note,
        "flow_bias":           flow_bias,
        "call_ratio_pct":      round(call_ratio, 1),
        "net_premium":         round(net_prem, 0),
        "call_premium":        round(call_prem, 0),
        "put_premium":         round(put_prem, 0),
        "sweep_count":         sweep_count,
        # Contradictions
        "contradictions":      contradictions,
        "has_contradiction":   len(contradictions) > 0,
        # Narrative
        "narrative":           narrative,
        "dark_pool_line":      dp_line,
        "dealer_read":         dealer_read[:150] if dealer_read else "",
        "call_outs":           call_outs[:3],
        # Interpreted tape
        "interpreted_rows":    interpreted,
        # Meter values for UI
        "sweep_pressure_label":  "BUY" if flow_bias == "BULLISH" else "SELL" if flow_bias == "BEARISH" else "MIXED",
        "sweep_urgency":         round(sweep_score, 0),
        "institutional_intent":  flow_intent,
        "interpretation":        narrative,
    }
