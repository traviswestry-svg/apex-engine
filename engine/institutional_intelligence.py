"""engine/institutional_intelligence.py — APEX 6.5 Institutional Intelligence Layer.

THE canonical intelligence object. Every dashboard component, Story Engine,
Trade Coach, Ribbon, and Replay consumes this single object — no component
independently queries multiple engines.

Four Pillars:
  1. Market Structure  — auction, volume profile, rotation, trend
  2. Dealer            — GEX, DEX, VEX, CHEX, hedging, pinning
  3. Institutional     — sweeps, blocks, splits, options chain, story
  4. Execution         — Pine, Trade Coach, risk, replay

Inputs: outputs of all existing engines — no new API calls.
Output: single `institutional_intelligence` dict published once per scan.
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


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


# ═══════════════════════════════════════════════════════════════════════════
# PILLAR BUILDERS
# Each pillar rolls up its engines into a single scored, narrated object.
# ═══════════════════════════════════════════════════════════════════════════

def _build_market_structure_pillar(
    auction_intel:  Dict[str, Any],
    market_state:   Dict[str, Any],
    rotation:       Optional[Dict[str, Any]],
    volume_profile: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Pillar 1: Market Structure — auction + volume + rotation + trend."""
    ai_state  = (auction_intel.get("auction_state") or {})
    ai_poc    = (auction_intel.get("poc_migration") or {})
    ai_acc    = (auction_intel.get("acceptance") or {})
    ai_excess = (auction_intel.get("excess") or {})

    # Auction
    auction_state = (ai_state.get("state") or "UNKNOWN").replace("_", " ")
    auction_conf  = _sf(ai_state.get("confidence"))
    would_trade   = ai_state.get("would_trade", False)

    # POC migration
    poc_mig    = ai_poc.get("direction") or market_state.get("poc_migration") or "STABLE"
    poc_delta  = _sf(ai_poc.get("delta"))
    poc        = _sf(market_state.get("poc"))
    vah        = _sf(market_state.get("vah"))
    val_       = _sf(market_state.get("val"))
    price      = _sf(market_state.get("price"))

    # Acceptance
    acc_status = ai_acc.get("primary_status") or ""
    acc_level  = ai_acc.get("primary_level") or ""

    # Excess
    excess_detected = ai_excess.get("detected", False)
    excess_type     = (ai_excess.get("type") or "").replace("_", " ")

    # Rotation
    rot_label  = (rotation or {}).get("rotation_label", "Unknown")
    rot_type   = (rotation or {}).get("rotation_type", "BALANCED_ROTATION")
    breadth    = (rotation or {}).get("breadth_label", "UNKNOWN")
    spx_bias   = (rotation or {}).get("spx_bias", "NEUTRAL")

    # Structure score (0–100)
    score = 50.0
    if would_trade:
        score += 15
    if poc_mig in ("RISING", "FALLING"):
        score += 10
    if acc_status == "ACCEPTING":
        score += 12
    elif acc_status == "REJECTED":
        score -= 12
    if excess_detected:
        score -= 10
    if rot_type == "GROWTH_ROTATION" and spx_bias in ("BULLISH", "MODERATELY_BULLISH"):
        score += 8
    score = _clamp(score)

    # Direction from auction + POC
    if would_trade and poc_mig == "RISING" and acc_status == "ACCEPTING":
        direction = "BULLISH"
    elif would_trade and poc_mig == "FALLING" and acc_status == "ACCEPTING":
        direction = "BEARISH"
    elif "BALANCED" in auction_state.upper() or poc_mig == "STABLE":
        direction = "NEUTRAL"
    else:
        direction = "DEVELOPING"

    narrative = (
        f"Auction: {auction_state} ({auction_conf:.0f}% confidence). "
        f"POC {'migrating ' + poc_mig.lower() if poc_mig != 'STABLE' else 'stable'} at ${poc:.2f}. "
        f"Acceptance: {acc_status or 'unknown'}{' at ' + acc_level if acc_level else ''}. "
        f"Rotation: {rot_label}. Breadth: {breadth.lower()}. "
        f"{'⚠ ' + excess_type + ' detected. ' if excess_detected else ''}"
        f"{'Institutional structure supports participation.' if would_trade else 'Wait for better structure.'}"
    )

    return {
        "pillar":             "MARKET_STRUCTURE",
        "score":              round(score, 1),
        "direction":          direction,
        "auction_state":      auction_state,
        "auction_conf":       round(auction_conf, 1),
        "would_trade":        would_trade,
        "poc_migration":      poc_mig,
        "poc_delta":          round(poc_delta, 2),
        "poc":                round(poc, 2),
        "vah":                round(vah, 2),
        "val":                round(val_, 2),
        "acceptance":         acc_status,
        "excess_detected":    excess_detected,
        "excess_type":        excess_type,
        "rotation_type":      rot_type,
        "breadth":            breadth,
        "spx_bias":           spx_bias,
        "narrative":          narrative,
    }


def _build_dealer_pillar(
    dealer_positioning: Dict[str, Any],
    options_chain:      Optional[Dict[str, Any]],
    volatility:         Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Pillar 2: Dealer — GEX, DEX, VEX, CHEX, hedging, pinning."""
    d_gamma   = dealer_positioning.get("gamma") or {}
    d_delta   = dealer_positioning.get("delta") or {}
    d_charm   = dealer_positioning.get("charm") or {}
    d_vega    = dealer_positioning.get("vega") or {}
    d_hedge   = dealer_positioning.get("hedging_pressure") or {}
    d_pin     = dealer_positioning.get("pin_probability") or {}
    d_mom     = dealer_positioning.get("momentum_probability") or {}

    gamma_regime   = d_gamma.get("regime") or "NEUTRAL_GAMMA"
    delta_bias     = d_delta.get("bias") or "NEUTRAL"
    charm          = d_charm.get("charm") or "NEUTRAL"
    hedge_level    = d_hedge.get("level") or "LOW"
    pin_prob       = _sf(d_pin.get("probability"))
    mom_prob       = _sf(d_mom.get("probability"), 50.0)
    gex_score      = _sf(d_gamma.get("gex_score"))
    dealer_summary = dealer_positioning.get("dealer_summary", "")

    # Vol regime
    vol_regime     = (volatility or {}).get("regime", "NORMAL")
    dealer_vega_risk = (volatility or {}).get("dealer_vega_risk", "MEDIUM")

    # Options chain
    oc_dealer_bias = (options_chain or {}).get("dealer_bias", "NEUTRAL")
    oc_skew        = (options_chain or {}).get("skew", "NEUTRAL")

    # Dealer score
    score = 50.0
    if gamma_regime == "NEGATIVE_GAMMA":
        score += 15    # momentum amplifier
    elif gamma_regime == "POSITIVE_GAMMA":
        score -= 5     # damper
    if delta_bias == "BUYING":
        score += 10
    elif delta_bias == "SELLING":
        score -= 10
    if charm in ("POSITIVE", "NEGATIVE"):
        score += 5
    if hedge_level == "HIGH":
        score += 8
    score = _clamp(score)

    # Direction from dealer signals
    if delta_bias == "BUYING" and (charm == "POSITIVE" or gamma_regime == "NEGATIVE_GAMMA"):
        direction = "BULLISH"
    elif delta_bias == "SELLING" and (charm == "NEGATIVE" or gamma_regime == "NEGATIVE_GAMMA"):
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    narrative = (
        f"Dealer Gamma: {gamma_regime.replace('_', ' ')}. "
        f"Delta: {delta_bias} ({d_delta.get('confidence', 0):.0f}% confidence). "
        f"Charm: {charm} — {d_charm.get('charm_bias', '').replace('_', ' ').lower()}. "
        f"Vega risk: {dealer_vega_risk} (VIX {vol_regime.lower()}). "
        f"Hedging pressure: {hedge_level}. "
        f"Pin probability: {pin_prob:.0f}%. "
        f"Momentum probability: {mom_prob:.0f}%. "
        f"{dealer_summary[:120] if dealer_summary else ''}"
    )

    return {
        "pillar":          "DEALER",
        "score":           round(score, 1),
        "direction":       direction,
        "gamma_regime":    gamma_regime,
        "delta_bias":      delta_bias,
        "delta_confidence": round(_sf(d_delta.get("confidence")), 1),
        "charm":           charm,
        "hedge_level":     hedge_level,
        "pin_probability": round(pin_prob, 1),
        "momentum_probability": round(mom_prob, 1),
        "gex_score":       round(gex_score, 1),
        "vol_regime":      vol_regime,
        "dealer_vega_risk": dealer_vega_risk,
        "options_skew":    oc_skew,
        "narrative":       narrative,
    }


def _build_institutional_pillar(
    flow_intel_2:    Dict[str, Any],
    options_chain:   Optional[Dict[str, Any]],
    story:           Optional[Dict[str, Any]],
    market_state:    Dict[str, Any],
) -> Dict[str, Any]:
    """Pillar 3: Institutional Intent — flow, options chain, story."""
    conviction   = _sf(flow_intel_2.get("flow_conviction"), 50.0)
    urgency      = flow_intel_2.get("urgency") or "LOW"
    flow_intent  = flow_intel_2.get("flow_intent") or "MIXED"
    flow_bias    = flow_intel_2.get("flow_bias") or "MIXED"
    sweep_pres   = _sf(flow_intel_2.get("sweep_pressure"))
    block_conv   = _sf(flow_intel_2.get("block_conviction"))
    split_acc    = _sf(flow_intel_2.get("split_accumulation"))
    dealer_resp  = _sf(flow_intel_2.get("dealer_response"), 50.0)
    call_outs    = flow_intel_2.get("call_outs") or []

    # Options chain
    inst_read    = (options_chain or {}).get("institutional_read", "")
    oc_gamma     = (options_chain or {}).get("gamma_profile", "BALANCED")

    # Story
    exec_summary = (story or {}).get("executive_summary", "")

    # Institutional score
    score = conviction * 0.4 + sweep_pres * 0.2 + block_conv * 0.2 + split_acc * 0.1 + dealer_resp * 0.1

    if flow_bias == "BULLISH":
        direction = "BULLISH"
    elif flow_bias == "BEARISH":
        direction = "BEARISH"
    else:
        direction = "MIXED"

    narrative = (
        f"Flow conviction: {conviction:.0f}/100. "
        f"Urgency: {urgency.lower()}. "
        f"Intent: {flow_intent.lower().replace('_', ' ')}. "
        f"Sweep pressure: {sweep_pres:.0f}, block conviction: {block_conv:.0f}, split accumulation: {split_acc:.0f}. "
        f"{call_outs[0] if call_outs else ''} "
        f"{inst_read[:100] if inst_read else ''}"
    ).strip()

    return {
        "pillar":            "INSTITUTIONAL",
        "score":             round(_clamp(score), 1),
        "direction":         direction,
        "flow_bias":         flow_bias,
        "flow_conviction":   round(conviction, 1),
        "flow_intent":       flow_intent,
        "urgency":           urgency,
        "sweep_pressure":    round(sweep_pres, 1),
        "block_conviction":  round(block_conv, 1),
        "split_accumulation": round(split_acc, 1),
        "dealer_response":   round(dealer_resp, 1),
        "options_gamma":     oc_gamma,
        "executive_summary": exec_summary,
        "narrative":         narrative,
        "top_call_out":      call_outs[0] if call_outs else "",
    }


def _build_execution_pillar(
    market_state:   Dict[str, Any],
    trade_coach:    Optional[Dict[str, Any]],
    risk:           Optional[Dict[str, Any]],
    decision_state: str,
    ici:            Dict[str, Any],
    consensus:      Dict[str, Any],
) -> Dict[str, Any]:
    """Pillar 4: Execution — Pine, Trade Coach, risk."""
    pine_state    = market_state.get("pine_state") or "WAITING"
    pine_confirmed = pine_state == "CONFIRMED"
    pine_secs     = _sf(market_state.get("signal_secs"))
    is_tradeable  = market_state.get("is_tradeable", False)
    ici_score     = _sf(ici.get("ici"))

    coach_action  = (trade_coach or {}).get("action", "")
    readiness     = _sf((trade_coach or {}).get("readiness"))
    entry_zone    = (trade_coach or {}).get("entry_zone", "")
    stop          = (trade_coach or {}).get("stop")
    target1       = (trade_coach or {}).get("target1")
    target2       = (trade_coach or {}).get("target2")
    contract_hint = (trade_coach or {}).get("contract_hint", "")

    risk_ok       = (risk or {}).get("risk_approved", True)
    risk_note     = (risk or {}).get("risk_note", "")

    is_enter = decision_state.startswith("ENTER")
    is_watch = decision_state.startswith("WATCH") or decision_state == "READY"

    score = 50.0
    if pine_confirmed:
        score += 20
    if is_tradeable:
        score += 10
    if ici_score >= 70:
        score += 15
    elif ici_score >= 55:
        score += 7
    if is_enter:
        score += 20
    elif is_watch:
        score += 10
    if risk_ok:
        score += 5
    score = _clamp(score)

    narrative = (
        f"Decision: {decision_state.replace('_', ' ')}. "
        f"ICI: {ici_score:.0f}. "
        f"Pine: {'confirmed' if pine_confirmed else 'waiting'}{'( ' + str(int(pine_secs)) + 's)' if pine_confirmed and pine_secs > 0 else ''}. "
        f"Readiness: {readiness:.0f}%. "
        f"{coach_action[:100] if coach_action else ''}"
    ).strip()

    return {
        "pillar":         "EXECUTION",
        "score":          round(score, 1),
        "decision_state": decision_state,
        "is_enter":       is_enter,
        "is_watch":       is_watch,
        "pine_state":     pine_state,
        "pine_confirmed": pine_confirmed,
        "ici_score":      round(ici_score, 1),
        "readiness":      round(readiness, 1),
        "is_tradeable":   is_tradeable,
        "entry_zone":     entry_zone,
        "stop":           stop,
        "target1":        target1,
        "target2":        target2,
        "contract_hint":  contract_hint,
        "risk_ok":        risk_ok,
        "risk_note":      risk_note,
        "narrative":      narrative,
        "coach_action":   coach_action,
    }


# ═══════════════════════════════════════════════════════════════════════════
# MASTER ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════

def build_institutional_intelligence(
    *,
    # Pillar 1: Market Structure
    auction_intel:      Dict[str, Any],
    market_state:       Dict[str, Any],
    rotation:           Optional[Dict[str, Any]] = None,
    volume_profile:     Optional[Dict[str, Any]] = None,
    # Pillar 2: Dealer
    dealer_positioning: Dict[str, Any],
    options_chain:      Optional[Dict[str, Any]] = None,
    volatility:         Optional[Dict[str, Any]] = None,
    # Pillar 3: Institutional
    flow_intel_2:       Dict[str, Any],
    story:              Optional[Dict[str, Any]] = None,
    # Pillar 4: Execution
    trade_coach:        Optional[Dict[str, Any]] = None,
    risk:               Optional[Dict[str, Any]] = None,
    ici:                Dict[str, Any],
    consensus:          Dict[str, Any],
    decision_state:     str = "NO_TRADE",
    playbook:           Optional[Dict[str, Any]] = None,
    session_state:      str = "MARKET_OPEN",
) -> Dict[str, Any]:
    """Build the canonical institutional intelligence object.

    This is the SINGLE object consumed by every dashboard component.
    Built once per scan cycle, published through the data bus.
    """
    # Build four pillars
    p1 = _build_market_structure_pillar(auction_intel, market_state, rotation, volume_profile)
    p2 = _build_dealer_pillar(dealer_positioning, options_chain, volatility)
    p3 = _build_institutional_pillar(flow_intel_2, options_chain, story, market_state)
    p4 = _build_execution_pillar(market_state, trade_coach, risk, decision_state, ici, consensus)

    # ── Overall institutional score (weighted average across pillars) ──────
    weights = {"MARKET_STRUCTURE": 0.25, "DEALER": 0.25, "INSTITUTIONAL": 0.30, "EXECUTION": 0.20}
    overall = (
        p1["score"] * weights["MARKET_STRUCTURE"] +
        p2["score"] * weights["DEALER"] +
        p3["score"] * weights["INSTITUTIONAL"] +
        p4["score"] * weights["EXECUTION"]
    )
    overall = _clamp(overall)

    # ── Pillar alignment check ─────────────────────────────────────────────
    directions = [p1["direction"], p2["direction"], p3["direction"]]
    bull_count = sum(1 for d in directions if d == "BULLISH")
    bear_count = sum(1 for d in directions if d == "BEARISH")
    neut_count = sum(1 for d in directions if d in ("NEUTRAL", "MIXED", "DEVELOPING"))

    if bull_count >= 3:
        alignment = "FULL_BULL_ALIGNMENT"
        alignment_note = "All three intelligence pillars confirm bullish institutional positioning."
    elif bear_count >= 3:
        alignment = "FULL_BEAR_ALIGNMENT"
        alignment_note = "All three intelligence pillars confirm bearish institutional positioning."
    elif bull_count >= 2:
        alignment = "PARTIAL_BULL_ALIGNMENT"
        alignment_note = f"{bull_count}/3 pillars bullish — partial alignment. Wait for full confirmation."
    elif bear_count >= 2:
        alignment = "PARTIAL_BEAR_ALIGNMENT"
        alignment_note = f"{bear_count}/3 pillars bearish — partial alignment. Wait for full confirmation."
    else:
        alignment = "UNALIGNED"
        alignment_note = "Pillars are not aligned. Balanced or transitioning institutional conditions."

    # ── Primary institutional read ─────────────────────────────────────────
    is_enter   = decision_state.startswith("ENTER")
    is_watch   = decision_state.startswith("WATCH") or decision_state == "READY"
    exec_sum   = (story or {}).get("executive_summary", "")

    if session_state not in ("MARKET_OPEN",):
        primary_read = (
            f"[{session_state.replace('_', ' ')}] {exec_sum}"
        )
    elif is_enter:
        primary_read = (
            f"ALL SYSTEMS GO — {decision_state.replace('_', ' ')}. "
            f"Institutional score: {overall:.0f}/100. {alignment_note} "
            f"{exec_sum[:150] if exec_sum else ''}"
        )
    elif is_watch:
        primary_read = (
            f"WATCHING — {decision_state.replace('_', ' ')}. "
            f"Institutional score: {overall:.0f}/100. {alignment_note} "
            f"Waiting for Pine confirmation and full pillar alignment."
        )
    else:
        primary_read = (
            f"NO TRADE. Institutional score: {overall:.0f}/100. "
            f"{alignment_note} "
            f"{exec_sum[:150] if exec_sum else ''}"
        )

    # ── What institutions are doing ────────────────────────────────────────
    what_institutions = (
        f"Structure: {p1['auction_state']} — {'accepting' if p1['acceptance'] == 'ACCEPTING' else 'testing'} "
        f"{'higher' if p1['poc_migration'] == 'RISING' else 'lower' if p1['poc_migration'] == 'FALLING' else 'current'} prices. "
        f"Flow: {p3['flow_bias'].lower()} bias, {p3['urgency'].lower()} urgency. "
        f"{p3['top_call_out']}"
    )

    what_dealers = p2["narrative"][:200]

    return {
        "available":        True,
        "version":          "6.5.0",
        "session_state":    session_state,
        "overall_score":    round(overall, 1),
        "alignment":        alignment,
        "alignment_note":   alignment_note,
        "primary_read":     primary_read,
        "what_institutions": what_institutions,
        "what_dealers":     what_dealers,
        "decision_state":   decision_state,
        # Four pillars
        "pillars": {
            "market_structure": p1,
            "dealer":           p2,
            "institutional":    p3,
            "execution":        p4,
        },
        # Flat scores for ribbon
        "market_structure_score": p1["score"],
        "dealer_score":           p2["score"],
        "institutional_score":    p3["score"],
        "execution_score":        p4["score"],
        # Key reads
        "auction_state":     p1["auction_state"],
        "poc_migration":     p1["poc_migration"],
        "acceptance":        p1["acceptance"],
        "gamma_regime":      p2["gamma_regime"],
        "delta_bias":        p2["delta_bias"],
        "flow_bias":         p3["flow_bias"],
        "flow_conviction":   p3["flow_conviction"],
        "pine_confirmed":    p4["pine_confirmed"],
        "readiness":         p4["readiness"],
        # Playbook
        "playbook":          playbook,
        # Bull/bear counts for alignment indicator
        "bull_pillars":      bull_count,
        "bear_pillars":      bear_count,
    }
