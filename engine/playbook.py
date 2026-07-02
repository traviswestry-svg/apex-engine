"""engine/playbook.py — APEX 6.5 Institutional Playbook Engine.

Generates a morning game plan and real-time session playbook from all
existing engine outputs. Produces:
  - Session type classification
  - Dealer positioning summary
  - Primary scenario (highest probability path)
  - Alternate scenario
  - Bull case / Bear case
  - Key levels to watch
  - Invalidation conditions
  - Expected path narrative

No new data fetches. Consumes dealer_positioning, auction_intelligence,
flow_intelligence, and market_state outputs.
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


def _fmtP(v: float) -> str:
    return f"${v:,.2f}"


# ── Session type classification ───────────────────────────────────────────────

def _classify_session(
    *,
    dealer_gamma_regime: str,
    auction_state: str,
    poc_migration: str,
    flow_bias: str,
    momentum_prob: float,
    pin_prob: float,
    gex_score: float,
) -> Dict[str, str]:
    """Classify the session type from dealer + auction signals."""

    if "TREND_DAY" in auction_state or momentum_prob >= 75:
        stype = "TREND_DAY"
        desc  = "Trend day — directional momentum is favored. Ride the move, avoid counter-trend trades."
        strategy = "Follow the trend. Scale into pullbacks. Do not fade until momentum breaks."
    elif pin_prob >= 65 and dealer_gamma_regime == "POSITIVE_GAMMA":
        stype = "PINNING_DAY"
        desc  = "Pinning day — gamma gravity is pulling price toward a key strike. Expect tight range."
        strategy = "Sell premium. Fade extremes. Expect price to revert toward the pin level at close."
    elif "BALANCED" in auction_state or poc_migration == "STABLE":
        stype = "BALANCED_DAY"
        desc  = "Balanced day — auction is in equilibrium. No clear directional edge."
        strategy = "Range trade. Buy VAL, sell VAH. Wait for a break of value to initiate directional positions."
    elif "ROTATIONAL" in auction_state:
        stype = "ROTATIONAL_DAY"
        desc  = "Rotational day — price is testing both sides of value. Responsive strategies work best."
        strategy = "Fade extremes at VAH and VAL. Watch for acceptance to confirm a directional break."
    elif dealer_gamma_regime == "NEGATIVE_GAMMA":
        stype = "VOLATILE_DAY"
        desc  = "Volatile day — negative gamma is amplifying moves in both directions."
        strategy = "Momentum strategies. Wait for directional confirmation before entering. Expect larger swings."
    else:
        stype = "NEUTRAL_DAY"
        desc  = "Neutral day — mixed signals with no clear session type."
        strategy = "Wait for clarity. Reduce position size. Only take A+ setups."

    return {"type": stype, "description": desc, "strategy": strategy}


# ── Scenario builder ──────────────────────────────────────────────────────────

def _build_primary_scenario(
    *,
    flow_bias: str,
    dealer_delta_bias: str,
    poc_migration: str,
    auction_state: str,
    acceptance_status: str,
    poc: float,
    vah: float,
    val_: float,
    call_wall: float,
    put_wall: float,
    momentum_prob: float,
) -> Dict[str, Any]:
    """Build the primary (highest probability) scenario narrative."""

    is_bull = (
        flow_bias == "BULLISH" and
        dealer_delta_bias in ("BUYING", "NEUTRAL") and
        poc_migration == "RISING"
    )
    is_bear = (
        flow_bias == "BEARISH" and
        dealer_delta_bias in ("SELLING", "NEUTRAL") and
        poc_migration == "FALLING"
    )

    if is_bull:
        direction = "BULLISH"
        probability = round(min(90, 50 + momentum_prob * 0.4), 0)
        title = "Continuation Higher"
        path = (
            f"Price holds above POC ({_fmtP(poc)}) and accepts above VAH ({_fmtP(vah)}). "
            f"POC continues migrating higher, confirming institutional acceptance. "
            f"Target: Call Wall at {_fmtP(call_wall) if call_wall else 'TBD'}. "
            f"Dealers continue delta hedging with buy pressure supporting the move."
        )
        entry = f"Pullback to POC ({_fmtP(poc)}) or VAH ({_fmtP(vah)}) with Pine confirmation"
        target = _fmtP(call_wall) if call_wall else "Next HVN above"
        stop = _fmtP(val_) if val_ else "Below VAL"
    elif is_bear:
        direction = "BEARISH"
        probability = round(min(90, 50 + momentum_prob * 0.4), 0)
        title = "Continuation Lower"
        path = (
            f"Price holds below POC ({_fmtP(poc)}) and accepts below VAL ({_fmtP(val_)}). "
            f"POC continues migrating lower, confirming institutional distribution. "
            f"Target: Put Wall at {_fmtP(put_wall) if put_wall else 'TBD'}. "
            f"Dealers continue delta hedging with sell pressure amplifying the move."
        )
        entry = f"Bounce to POC ({_fmtP(poc)}) or VAL ({_fmtP(val_)}) with Pine confirmation"
        target = _fmtP(put_wall) if put_wall else "Next HVN below"
        stop = _fmtP(vah) if vah else "Above VAH"
    else:
        direction = "NEUTRAL"
        probability = 45
        title = "Balanced Rotation"
        path = (
            f"Price rotates between VAL ({_fmtP(val_)}) and VAH ({_fmtP(vah)}). "
            f"POC at {_fmtP(poc)} is the primary reference. "
            f"No directional conviction from flow or dealer positioning. "
            f"Wait for acceptance above VAH or below VAL to initiate directional trades."
        )
        entry = f"Break of VAH ({_fmtP(vah)}) or VAL ({_fmtP(val_)}) with acceptance"
        target = _fmtP(call_wall) if call_wall else "VAH"
        stop = f"Opposite side of value area"

    return {
        "direction":    direction,
        "probability":  probability,
        "title":        title,
        "path":         path,
        "entry":        entry,
        "target":       target,
        "stop":         stop,
    }


def _build_alternate_scenario(
    *,
    primary_direction: str,
    poc: float,
    vah: float,
    val_: float,
    call_wall: float,
    put_wall: float,
    pin_probability: float,
    dealer_gamma_regime: str,
) -> Dict[str, Any]:
    """Build the alternate scenario — what could invalidate the primary."""

    if primary_direction == "BULLISH":
        direction = "BEARISH"
        title = "Failed Breakout / Rotation Lower"
        probability = 100 - 65   # rough complement
        path = (
            f"Price fails to hold above POC ({_fmtP(poc)}) and rotates back into value. "
            f"VAL ({_fmtP(val_)}) becomes the next target. "
            f"A close below VAL with POC following would confirm distribution."
        )
        trigger = f"Price closes back below POC ({_fmtP(poc)}) or flow turns bearish"
    elif primary_direction == "BEARISH":
        direction = "BULLISH"
        title = "Failed Breakdown / Responsive Buying"
        probability = 100 - 65
        path = (
            f"Responsive buyers defend VAL ({_fmtP(val_)}) and push price back above POC ({_fmtP(poc)}). "
            f"A reclaim of POC with bullish flow confirms the failed breakdown. "
            f"VAH ({_fmtP(vah)}) becomes the next target."
        )
        trigger = f"Price reclaims POC ({_fmtP(poc)}) with bullish flow confirmation"
    else:
        direction = "DIRECTIONAL"
        title = "Breakout from Balance"
        probability = 40
        path = (
            f"A catalyst breaks price out of the balanced range. "
            f"Above VAH ({_fmtP(vah)}) with acceptance targets the Call Wall ({_fmtP(call_wall) if call_wall else 'above'}). "
            f"Below VAL ({_fmtP(val_)}) with acceptance targets the Put Wall ({_fmtP(put_wall) if put_wall else 'below'})."
        )
        trigger = "Break of VAH or VAL with 3+ bar acceptance and Pine confirmation"

    # Add pin scenario if relevant
    if pin_probability >= 50 and dealer_gamma_regime == "POSITIVE_GAMMA":
        path += (
            f" Note: {pin_probability:.0f}% pinning probability — price may gravitate toward the nearest "
            f"high-OI strike into close regardless of directional bias."
        )

    return {
        "direction":   direction,
        "title":       title,
        "probability": probability,
        "path":        path,
        "trigger":     trigger,
    }


# ── Main playbook builder ─────────────────────────────────────────────────────

def build_institutional_playbook(
    *,
    dealer_positioning: Dict[str, Any],
    auction_intel:      Dict[str, Any],
    flow_intel_2:       Dict[str, Any],
    market_state:       Dict[str, Any],
    overnight_plan:     Optional[Dict[str, Any]] = None,
    session_state:      str = "MARKET_OPEN",
) -> Dict[str, Any]:
    """Build the morning/session Institutional Playbook.

    Single screen. No tab digging required.
    """
    # Extract key inputs
    d_gamma  = dealer_positioning.get("gamma") or {}
    d_delta  = dealer_positioning.get("delta") or {}
    d_charm  = dealer_positioning.get("charm") or {}
    d_hedge  = dealer_positioning.get("hedging_pressure") or {}
    d_pin    = dealer_positioning.get("pin_probability") or {}
    d_mom    = dealer_positioning.get("momentum_probability") or {}

    ai_state = (auction_intel.get("auction_state") or {})
    ai_acc   = (auction_intel.get("acceptance") or {})
    ai_poc   = (auction_intel.get("poc_migration") or {})

    price        = _sf(market_state.get("price"))
    poc          = _sf(market_state.get("poc"))
    vah          = _sf(market_state.get("vah"))
    val_         = _sf(market_state.get("val"))
    vwap         = _sf(market_state.get("vwap"))
    flow_bias    = str(flow_intel_2.get("flow_bias") or "MIXED")
    poc_mig      = str(ai_poc.get("direction") or market_state.get("poc_migration") or "STABLE")
    au_state_str = str(ai_state.get("state") or "UNKNOWN")
    acc_status   = str(ai_acc.get("primary_status") or "UNKNOWN")
    dealer_gr    = str(d_gamma.get("regime") or "NEUTRAL_GAMMA")
    dealer_db    = str(d_delta.get("bias") or "NEUTRAL")
    call_wall    = _sf(d_gamma.get("call_wall"))
    put_wall     = _sf(d_gamma.get("put_wall"))
    mom_prob     = _sf(d_mom.get("probability"), 50.0)
    pin_prob     = _sf(d_pin.get("probability"), 0.0)
    conviction   = _sf(flow_intel_2.get("flow_conviction"), 50.0)

    # Session type
    session_type = _classify_session(
        dealer_gamma_regime=dealer_gr,
        auction_state=au_state_str,
        poc_migration=poc_mig,
        flow_bias=flow_bias,
        momentum_prob=mom_prob,
        pin_prob=pin_prob,
        gex_score=_sf(d_gamma.get("gex_score")),
    )

    # Primary scenario
    primary = _build_primary_scenario(
        flow_bias=flow_bias,
        dealer_delta_bias=dealer_db,
        poc_migration=poc_mig,
        auction_state=au_state_str,
        acceptance_status=acc_status,
        poc=poc, vah=vah, val_=val_,
        call_wall=call_wall, put_wall=put_wall,
        momentum_prob=mom_prob,
    )

    # Alternate scenario
    alternate = _build_alternate_scenario(
        primary_direction=primary["direction"],
        poc=poc, vah=vah, val_=val_,
        call_wall=call_wall, put_wall=put_wall,
        pin_probability=pin_prob,
        dealer_gamma_regime=dealer_gr,
    )

    # Key levels
    key_levels: List[Dict[str, Any]] = []
    if call_wall > 0: key_levels.append({"label": "Call Wall",  "price": call_wall, "role": "Resistance — dealer short delta hedging"})
    if vah > 0:       key_levels.append({"label": "VAH",        "price": vah,       "role": "Value Area High — acceptance above confirms breakout"})
    if vwap > 0:      key_levels.append({"label": "VWAP",       "price": vwap,      "role": "Intraday equilibrium — trend anchor"})
    if poc > 0:       key_levels.append({"label": "POC",        "price": poc,       "role": "Point of Control — primary institutional reference"})
    if val_ > 0:      key_levels.append({"label": "VAL",        "price": val_,      "role": "Value Area Low — acceptance below confirms breakdown"})
    if put_wall > 0:  key_levels.append({"label": "Put Wall",   "price": put_wall,  "role": "Support — dealer long delta hedging"})
    key_levels.sort(key=lambda x: x["price"], reverse=True)

    # Invalidation
    if primary["direction"] == "BULLISH":
        invalidation = (
            f"Bullish thesis fails if: price closes below POC ({_fmtP(poc)}) with POC stopping its migration, "
            f"flow turns bearish, or dealers begin selling into strength. "
            f"A close below VAL ({_fmtP(val_)}) invalidates the bullish structure entirely."
        )
    elif primary["direction"] == "BEARISH":
        invalidation = (
            f"Bearish thesis fails if: price reclaims POC ({_fmtP(poc)}) with bullish flow, "
            f"or responsive buyers defend VAL ({_fmtP(val_)}) with increasing conviction. "
            f"A close above VAH ({_fmtP(vah)}) with POC following invalidates the bearish structure."
        )
    else:
        invalidation = (
            f"Balanced auction is invalidated by a break of VAH ({_fmtP(vah)}) or VAL ({_fmtP(val_)}) "
            f"with at least 3 consecutive bars of acceptance and confirming flow."
        )

    # Next expected event
    next_event = (
        f"Watch for POC {'to continue migrating ' + poc_mig.lower() if poc_mig != 'STABLE' else 'to hold at ' + _fmtP(poc)}. "
        f"{d_charm.get('phase_note', '')} "
        f"{d_mom.get('trade_implication', '')}"
    )

    # Dealer summary for playbook header
    dealer_header = (
        f"Dealer Gamma: {dealer_gr.replace('_', ' ')} | "
        f"Dealer Delta: {dealer_db} | "
        f"Charm: {d_charm.get('charm', 'NEUTRAL')} | "
        f"Hedging: {d_hedge.get('level', 'LOW')} | "
        f"Pin Prob: {pin_prob:.0f}%"
    )

    # Overnight context
    overnight_context = ""
    if overnight_plan and overnight_plan.get("game_plan"):
        overnight_context = overnight_plan.get("executive_summary", "")

    return {
        "available":         True,
        "session_type":      session_type,
        "dealer_header":     dealer_header,
        "primary_scenario":  primary,
        "alternate_scenario": alternate,
        "key_levels":        key_levels,
        "invalidation":      invalidation,
        "next_event":        next_event,
        "overnight_context": overnight_context,
        "flow_conviction":   round(conviction, 1),
        "momentum_probability": round(mom_prob, 1),
        "pin_probability":   round(pin_prob, 1),
        "dealer_summary":    dealer_positioning.get("dealer_summary", ""),
        "session_state":     session_state,
        # Flat reads for ribbon
        "session_type_label": session_type["type"],
        "primary_direction":  primary["direction"],
        "primary_prob":       primary["probability"],
    }
