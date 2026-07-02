"""engine/dealer_positioning.py — APEX 6.5 Dealer Positioning Engine.

Seven-phase dealer intelligence engine. Derives dealer behavior from existing
gamma, flow, auction, and volume profile data — no new API calls.

Phases:
  1. Dealer Gamma (DEX proxy) — consumes gamma.py output
  2. Dealer Delta (DEX)       — inferred from flow + net premium + OI
  3. Dealer Charm (CHEX)      — time-decay drift estimation
  4. Dealer Vega (VEX)        — volatility sensitivity
  5. Hedging Pressure         — directional hedging demand
  6. Pinning Probability      — expiration gravity
  7. Momentum Probability     — trend continuation probability

Design rules:
  - Never duplicates gamma calculations. Imports from gamma.py.
  - Never fetches data. Consumes existing engine outputs.
  - All outputs are plain-English readable.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


# ── helpers ──────────────────────────────────────────────────────────────────

def _sf(v: Any, d: float = 0.0) -> float:
    try:
        f = float(v) if v is not None else d
        return d if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return d


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _pct_dist(price: float, level: float) -> Optional[float]:
    if price <= 0 or level <= 0:
        return None
    return round(abs(price - level) / price * 100, 3)


def _pts_dist(price: float, level: float) -> Optional[float]:
    if price <= 0 or level <= 0:
        return None
    return round(abs(price - level), 2)


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 1 — DEALER GAMMA
# Reuses all calculations from gamma.py. Translates into dealer language.
# ═══════════════════════════════════════════════════════════════════════════

def build_dealer_gamma(gamma_regime: Dict[str, Any], price: float = 0.0) -> Dict[str, Any]:
    """Phase 1: Dealer Gamma — translate existing GEX output into dealer behavior.

    Input: output of build_gamma_from_quantdata_response() (from gamma.py)
    """
    gex_score   = _sf(gamma_regime.get("gex_score"))
    zero_gamma  = _sf(gamma_regime.get("zero_gamma") or gamma_regime.get("displayZeroGamma"))
    call_wall   = _sf(gamma_regime.get("call_wall"))
    put_wall    = _sf(gamma_regime.get("put_wall"))
    net_ratio   = _sf(gamma_regime.get("net_gamma_ratio"))
    regime_lbl  = str(gamma_regime.get("regime_label") or gamma_regime.get("gex_status") or "")

    dist_to_flip = _pts_dist(price, zero_gamma)
    pct_to_flip  = _pct_dist(price, zero_gamma)

    # Classify dealer gamma regime
    if net_ratio > 0.05 or gex_score >= 65:
        regime = "POSITIVE_GAMMA"
        score  = min(100, 50 + int(gex_score * 0.5))
        behavior = (
            "Dealers are long gamma — they sell into strength and buy into weakness. "
            "This suppresses volatility and creates mean-reversion conditions. "
            "Fading extreme moves is favored over chasing breakouts."
        )
        expected_vol    = "SUPPRESSED"
        dealer_response = "COUNTER_TREND"
    elif net_ratio < -0.05 or gex_score <= 35:
        regime = "NEGATIVE_GAMMA"
        score  = max(0, 50 - int((50 - gex_score) * 0.5))
        behavior = (
            "Dealers are short gamma — they must buy strength and sell weakness to hedge. "
            "This amplifies moves in both directions. "
            "Trend following and momentum strategies are favored."
        )
        expected_vol    = "ELEVATED"
        dealer_response = "PRO_TREND"
    else:
        regime = "NEUTRAL_GAMMA"
        score  = 50
        behavior = (
            "Dealers are near-neutral gamma. Hedging flows are balanced. "
            "No strong directional amplification expected from dealer activity."
        )
        expected_vol    = "NORMAL"
        dealer_response = "NEUTRAL"

    # Distance to gamma flip context
    flip_note = ""
    if dist_to_flip is not None:
        if dist_to_flip < 5:
            flip_note = (
                f"Price is within {dist_to_flip:.1f} points of the gamma flip level ({zero_gamma:.2f}). "
                f"A breach would trigger a regime change — expect volatility to spike rapidly."
            )
        elif dist_to_flip < 15:
            flip_note = (
                f"Price is {dist_to_flip:.1f} points from the gamma flip ({zero_gamma:.2f}). "
                f"A move through this level changes dealer hedging direction."
            )
        else:
            flip_note = (
                f"Gamma flip at {zero_gamma:.2f} is {dist_to_flip:.1f} points away. "
                f"Dealers remain committed to current hedging regime."
            )

    # Wall context
    call_dist = _pts_dist(price, call_wall)
    put_dist  = _pts_dist(price, put_wall)
    wall_note = ""
    if call_wall > 0 and put_wall > 0 and price > 0:
        if price >= call_wall * 0.999:
            wall_note = (
                f"Price is at or above the Call Wall ({call_wall:.2f}). "
                f"Dealer call delta hedging creates strong resistance — short-term exhaustion risk."
            )
        elif call_dist and call_dist < 10:
            wall_note = (
                f"Price is approaching the Call Wall ({call_wall:.2f}) — {call_dist:.1f} points away. "
                f"Dealers will increase short delta hedging as price rises toward this level."
            )
        elif put_dist and put_dist < 10:
            wall_note = (
                f"Price is approaching the Put Wall ({put_wall:.2f}) — {put_dist:.1f} points away. "
                f"Dealers will increase long delta hedging as price falls toward this level."
            )

    return {
        "regime":              regime,
        "score":               round(score, 1),
        "gex_score":           round(gex_score, 1),
        "call_wall":           call_wall,
        "put_wall":            put_wall,
        "zero_gamma":          zero_gamma,
        "distance_to_flip_pts": dist_to_flip,
        "distance_to_flip_pct": pct_to_flip,
        "expected_volatility": expected_vol,
        "dealer_response":     dealer_response,
        "behavior":            behavior,
        "flip_note":           flip_note,
        "wall_note":           wall_note,
        "net_gamma_ratio":     round(net_ratio, 4),
    }


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 2 — DEALER DELTA (DEX)
# Estimated from call/put premium balance, sweep direction, and net flow.
# ═══════════════════════════════════════════════════════════════════════════

def build_dealer_delta(
    *,
    call_premium: float,
    put_premium: float,
    net_premium: float,
    sweep_count: int,
    flow_bias: str,
    call_ratio_pct: Optional[float],
    dealer_gamma_regime: str,
    price: float = 0.0,
) -> Dict[str, Any]:
    """Phase 2: Dealer Delta (DEX approximation).

    Dealers are the counterparty to institutional options flow.
    When institutions BUY calls → dealers SELL calls → dealers SELL delta (futures).
    When institutions BUY puts  → dealers SELL puts  → dealers BUY delta (futures).

    This estimation logic inverts the institutional flow direction.
    """
    call_prem = _sf(call_premium)
    put_prem  = _sf(put_premium)
    net_prem  = _sf(net_premium)
    ratio     = _sf(call_ratio_pct, 50.0)
    total     = call_prem + put_prem or 1.0

    # Dealer is counterparty — flip the flow direction
    # High call buying → dealers short calls → dealers need to SHORT delta (sell futures)
    # High put buying  → dealers short puts  → dealers need to LONG delta (buy futures)
    dealer_call_delta = -(call_prem / total)   # negative: dealers short calls, short delta
    dealer_put_delta  = +(put_prem  / total)   # positive: dealers short puts, long delta
    net_dealer_delta  = dealer_call_delta + dealer_put_delta

    # Score: positive = dealers net buying futures, negative = dealers net selling
    raw_score = net_dealer_delta * 100

    # Modulate by gamma regime: in negative gamma dealers amplify
    if dealer_gamma_regime == "NEGATIVE_GAMMA":
        raw_score *= 1.35
    elif dealer_gamma_regime == "POSITIVE_GAMMA":
        raw_score *= 0.75

    # Sweep direction adds urgency signal
    if flow_bias == "BULLISH" and sweep_count > 0:
        raw_score -= min(15, sweep_count * 3)   # heavy call sweeps → dealers more short delta
    elif flow_bias == "BEARISH" and sweep_count > 0:
        raw_score += min(15, sweep_count * 3)   # heavy put sweeps → dealers more long delta

    # Classify
    if raw_score > 8:
        bias       = "BUYING"
        confidence = _clamp(50 + abs(raw_score) * 0.8)
        narrative  = (
            "Dealers are estimated to be net buying delta (futures) to hedge short put exposure. "
            "Put premium dominates the flow, requiring dealers to accumulate long futures as a hedge. "
            "This creates a structural bid underneath the market."
        )
        market_impact = "SUPPORTIVE — dealer delta hedging creates underlying buy pressure."
    elif raw_score < -8:
        bias       = "SELLING"
        confidence = _clamp(50 + abs(raw_score) * 0.8)
        narrative  = (
            "Dealers are estimated to be net selling delta (futures) to hedge short call exposure. "
            "Call premium dominates the flow, requiring dealers to distribute long futures as a hedge. "
            "This creates a structural drag above the market."
        )
        market_impact = "RESISTIVE — dealer delta hedging creates overhead sell pressure."
    else:
        bias       = "NEUTRAL"
        confidence = 40.0
        narrative  = (
            "Dealer delta hedging flows are approximately balanced. "
            "Call and put exposure are near-equal, requiring minimal directional futures hedging. "
            "No structural dealer bias currently."
        )
        market_impact = "NEUTRAL — no significant dealer delta hedging pressure."

    return {
        "bias":          bias,
        "score":         round(raw_score, 1),
        "confidence":    round(confidence, 1),
        "call_premium":  round(call_prem, 0),
        "put_premium":   round(put_prem, 0),
        "net_premium":   round(net_prem, 0),
        "call_ratio_pct": round(ratio, 1),
        "net_dealer_delta": round(net_dealer_delta, 4),
        "narrative":     narrative,
        "market_impact": market_impact,
    }


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 3 — DEALER CHARM (CHEX)
# Charm = dDelta/dTime. As options age, delta changes even if price is flat.
# For short-dated options (0DTE/1DTE), charm is the dominant intraday Greek.
# ═══════════════════════════════════════════════════════════════════════════

def build_dealer_charm(
    *,
    dte: float,                         # days to expiration (0.0 for 0DTE)
    dealer_delta_bias: str,
    net_premium: float,
    call_ratio_pct: Optional[float],
    minutes_open: int = 0,              # minutes since market open
) -> Dict[str, Any]:
    """Phase 3: Dealer Charm (CHEX) — time-decay drift estimation.

    For 0DTE: charm is strongest in the first 2 hours and after 2 PM ET.
    Charm causes delta to decay toward 0 for OTM options,
    which requires dealers to unwind their delta hedges over the course of the day.
    """
    ratio   = _sf(call_ratio_pct, 50.0)
    net_p   = _sf(net_premium)
    is_0dte = dte <= 0.25

    # Charm direction: determined by which side dealers are short
    # Dealers short calls → as charm decays call delta, dealers unwind short delta (buy futures)
    # Dealers short puts  → as charm decays put delta, dealers unwind long delta (sell futures)
    if ratio > 55 and net_p > 0:
        # Call-dominated: dealer charm unwind = progressive buying pressure through day
        charm      = "POSITIVE"
        charm_bias = "UPWARD_DRIFT"
        drift_note = (
            "Call-dominated flow creates positive charm dynamics. "
            "As the session progresses, dealer call hedges will decay, "
            "requiring dealers to progressively buy back short delta. "
            "This creates upward drift bias, especially into the afternoon."
        )
    elif ratio < 45 and net_p < 0:
        # Put-dominated: dealer charm unwind = progressive selling pressure
        charm      = "NEGATIVE"
        charm_bias = "DOWNWARD_DRIFT"
        drift_note = (
            "Put-dominated flow creates negative charm dynamics. "
            "As the session progresses, dealer put hedges will decay, "
            "requiring dealers to progressively sell long delta. "
            "This creates downward drift bias through the afternoon."
        )
    else:
        charm      = "NEUTRAL"
        charm_bias = "NO_DRIFT"
        drift_note = (
            "Balanced call/put flow produces approximately neutral charm effects. "
            "No significant time-decay-driven dealer unwinding expected today."
        )

    # Session-time drift expectation
    if minutes_open < 60:
        time_phase = "MORNING"
        phase_note = "Morning session: charm effects are building. Directional moves are most reliable when confirmed by flow."
    elif minutes_open < 210:
        time_phase = "MIDDAY"
        phase_note = "Midday session: charm is accelerating. Drift bias increases as time decay intensifies."
    else:
        time_phase = "AFTERNOON"
        phase_note = (
            "Afternoon session: charm is strongest. "
            f"{'Upward' if charm == 'POSITIVE' else 'Downward' if charm == 'NEGATIVE' else 'Neutral'} "
            "drift pressure from dealer unwinds is at maximum. "
            "0DTE positions lose delta rapidly — expect acceleration into close."
        )

    # 0DTE specific note
    dte_note = (
        "0DTE session: charm effects dominate all other Greeks after 1:00 PM ET. "
        "Delta decays rapidly toward zero for OTM strikes — dealer unwind flows can drive sharp directional moves."
    ) if is_0dte else f"{dte:.1f} DTE: charm is present but less dominant than on 0DTE."

    return {
        "charm":         charm,
        "charm_bias":    charm_bias,
        "dte":           round(dte, 2),
        "is_0dte":       is_0dte,
        "time_phase":    time_phase,
        "minutes_open":  minutes_open,
        "drift_note":    drift_note,
        "phase_note":    phase_note,
        "dte_note":      dte_note,
        "call_ratio_pct": round(ratio, 1),
    }


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 4 — DEALER VEGA (VEX)
# Vega = sensitivity to implied volatility changes.
# Dealers short options are always short vega — they lose when vol rises.
# ═══════════════════════════════════════════════════════════════════════════

def build_dealer_vega(
    *,
    vix: float,
    gex_score: float,
    total_premium: float,
    call_ratio_pct: Optional[float],
    flow_momentum: str = "STABLE",
) -> Dict[str, Any]:
    """Phase 4: Dealer Vega (VEX) — volatility sensitivity estimate."""
    ratio  = _sf(call_ratio_pct, 50.0)
    vix_v  = _sf(vix)

    # Dealers are always net short vega (they sell options to institutions)
    # Higher total premium = more net short vega exposure

    # VIX environment
    if vix_v >= 20:
        vix_env   = "HIGH_VOL"
        vol_crush = "EXPECTED" if flow_momentum in ("DECREASING", "STABLE") else "UNLIKELY"
        vega_note = (
            f"Elevated VIX ({vix_v:.1f}) means dealers carry significant short vega exposure. "
            "Any further volatility spike creates accelerating dealer losses and potential forced hedging."
        )
    elif vix_v >= 15:
        vix_env   = "MODERATE_VOL"
        vol_crush = "NEUTRAL"
        vega_note = (
            f"Moderate VIX ({vix_v:.1f}). Dealer vega exposure is manageable. "
            "No extreme volatility-driven hedging expected."
        )
    else:
        vix_env   = "LOW_VOL"
        vol_crush = "LIKELY" if flow_momentum in ("DECREASING",) else "POSSIBLE"
        vega_note = (
            f"Low VIX ({vix_v:.1f}) environment. Dealers collect premium efficiently. "
            "Low volatility favors dealer positioning — premium sellers have the edge."
        )

    # Vega level from premium size and GEX
    prem_m = total_premium / 1_000_000 if total_premium else 0
    if prem_m > 2_000 or gex_score >= 70:
        vega = "HIGH"
        vega_score = 80
        expansion_risk = "ELEVATED — large premium exposure means dealer losses accelerate on vol spikes"
    elif prem_m > 500 or gex_score >= 50:
        vega = "MEDIUM"
        vega_score = 55
        expansion_risk = "MODERATE — typical 0DTE dealer exposure"
    else:
        vega = "LOW"
        vega_score = 30
        expansion_risk = "LOW — limited premium exposure"

    return {
        "vega":              vega,
        "vega_score":        vega_score,
        "vix":               round(vix_v, 2),
        "vix_environment":   vix_env,
        "vol_crush_likely":  vol_crush,
        "expansion_risk":    expansion_risk,
        "vega_note":         vega_note,
        "total_premium_m":   round(prem_m, 1),
    }


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 5 — DEALER HEDGING PRESSURE
# Combines gamma, delta, and flow to estimate hedging demand.
# ═══════════════════════════════════════════════════════════════════════════

def build_hedging_pressure(
    *,
    dealer_gamma_regime: str,
    dealer_delta_bias: str,
    dealer_delta_confidence: float,
    sweep_count: int,
    net_premium: float,
    price_vs_zero_gamma: Optional[str] = None,  # "ABOVE" / "BELOW" / "AT"
) -> Dict[str, Any]:
    """Phase 5: Dealer Hedging Pressure — directional urgency of dealer flows."""
    net_p = _sf(net_premium)
    score = 0

    # Gamma regime contribution
    if dealer_gamma_regime == "NEGATIVE_GAMMA":
        score += 35    # negative gamma = forced, amplified hedging
    elif dealer_gamma_regime == "POSITIVE_GAMMA":
        score += 10    # positive gamma = smooth, dampened hedging

    # Delta bias contribution
    if dealer_delta_bias in ("BUYING", "SELLING"):
        score += dealer_delta_confidence * 0.3

    # Sweep urgency
    score += min(25, sweep_count * 5)

    # Premium size
    prem_abs = abs(net_p)
    if prem_abs > 1_000_000_000:
        score += 20
    elif prem_abs > 500_000_000:
        score += 12
    elif prem_abs > 100_000_000:
        score += 6

    score = _clamp(score)

    if score >= 70:
        level     = "HIGH"
        narrative = (
            "Dealer hedging pressure is high. "
            f"{'Negative gamma is forcing dealers to amplify price moves. ' if dealer_gamma_regime == 'NEGATIVE_GAMMA' else ''}"
            f"{'Heavy sweep activity indicates urgent institutional positioning requiring immediate dealer response. ' if sweep_count >= 3 else ''}"
            "Expect accelerated price movement as dealer hedging flows add to directional pressure."
        )
    elif score >= 40:
        level     = "MEDIUM"
        narrative = (
            "Dealer hedging pressure is moderate. "
            "Dealers are actively adjusting positions but without extreme urgency. "
            "Price movement may be dampened or amplified depending on gamma regime."
        )
    elif score >= 15:
        level     = "LOW"
        narrative = (
            "Dealer hedging pressure is low. "
            "Minimal forced hedging activity expected. "
            "Dealers are managing positions smoothly."
        )
    else:
        level     = "NONE"
        narrative = (
            "Dealer hedging pressure is negligible. "
            "Low premium activity and balanced flow mean dealers require minimal repositioning."
        )

    # Direction of hedging pressure
    if dealer_delta_bias == "BUYING":
        direction = "UPWARD"
        direction_note = "Dealer hedging is adding buy-side pressure to the market."
    elif dealer_delta_bias == "SELLING":
        direction = "DOWNWARD"
        direction_note = "Dealer hedging is adding sell-side pressure to the market."
    else:
        direction = "NEUTRAL"
        direction_note = "Dealer hedging is balanced — no directional pressure."

    return {
        "level":          level,
        "score":          round(score, 1),
        "direction":      direction,
        "direction_note": direction_note,
        "narrative":      narrative,
        "sweep_count":    sweep_count,
    }


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 6 — PINNING PROBABILITY
# Gravity toward high-OI strikes as expiration approaches.
# ═══════════════════════════════════════════════════════════════════════════

def build_pin_probability(
    *,
    price: float,
    call_wall: float,
    put_wall: float,
    zero_gamma: float,
    gex_score: float,
    dte: float,
    minutes_open: int = 0,
) -> Dict[str, Any]:
    """Phase 6: Pinning Probability — likelihood of expiration price gravity."""
    dist_call = _pts_dist(price, call_wall)
    dist_put  = _pts_dist(price, put_wall)
    dist_flip = _pts_dist(price, zero_gamma)

    # Base pin probability from gamma score and proximity
    base = gex_score * 0.5   # positive gamma = higher pin probability

    # DTE contribution: pin is strongest near expiration
    if dte <= 0.25:
        dte_boost = 30
    elif dte <= 1:
        dte_boost = 15
    elif dte <= 5:
        dte_boost = 8
    else:
        dte_boost = 0

    # Time of day: pin strengthens in afternoon
    if minutes_open >= 300:      # after 2:30 PM ET
        time_boost = 20
    elif minutes_open >= 180:    # after 12:30 PM ET
        time_boost = 10
    else:
        time_boost = 0

    # Proximity boost: if price is between the walls and near zero gamma
    proximity_boost = 0
    if dist_call and dist_put and dist_call < 20 and dist_put < 20:
        proximity_boost = 15
    if dist_flip and dist_flip < 5:
        proximity_boost += 10

    probability = _clamp(base + dte_boost + time_boost + proximity_boost)

    if probability >= 70:
        level   = "HIGH"
        summary = (
            f"High pinning probability ({probability:.0f}%). "
            f"Price is trapped between Call Wall ({call_wall:.2f}) and Put Wall ({put_wall:.2f}) "
            f"with strong gamma gravity from the {dte:.2f} DTE options expiration. "
            "Expect range-bound price action with snap-backs to key strikes."
        )
    elif probability >= 40:
        level   = "MEDIUM"
        summary = (
            f"Moderate pinning probability ({probability:.0f}%). "
            "Some gravitational pull toward the nearest high-OI strike. "
            "A directional catalyst could overcome gamma pinning."
        )
    else:
        level   = "LOW"
        summary = (
            f"Low pinning probability ({probability:.0f}%). "
            "Gamma exposure is insufficient to create meaningful strike gravity. "
            "Price is free to trade directionally."
        )

    # Which level is price most likely to pin toward?
    pin_target = None
    if dist_call and dist_put:
        if dist_call < dist_put:
            pin_target = call_wall
            pin_note = f"Nearest pin magnet: Call Wall at {call_wall:.2f}"
        else:
            pin_target = put_wall
            pin_note = f"Nearest pin magnet: Put Wall at {put_wall:.2f}"
    else:
        pin_note = "Pin target undetermined."

    return {
        "probability":     round(probability, 1),
        "level":           level,
        "dte":             round(dte, 2),
        "call_wall":       call_wall,
        "put_wall":        put_wall,
        "zero_gamma":      zero_gamma,
        "dist_call_wall":  dist_call,
        "dist_put_wall":   dist_put,
        "dist_zero_gamma": dist_flip,
        "pin_target":      pin_target,
        "pin_note":        pin_note,
        "summary":         summary,
    }


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 7 — MOMENTUM PROBABILITY
# Likelihood of trend continuation based on all dealer signals.
# ═══════════════════════════════════════════════════════════════════════════

def build_momentum_probability(
    *,
    dealer_gamma_regime: str,
    dealer_delta_bias: str,
    dealer_delta_confidence: float,
    dealer_charm: str,
    hedging_pressure_level: str,
    poc_migration: str,
    flow_bias: str,
    auction_state: str,
    gex_score: float,
) -> Dict[str, Any]:
    """Phase 7: Momentum Probability — trend continuation likelihood.

    Combines all seven dealer signals into a single probability.
    """
    score = 50.0   # neutral baseline

    # Gamma contribution: negative gamma amplifies momentum
    if dealer_gamma_regime == "NEGATIVE_GAMMA":
        score += 15
    elif dealer_gamma_regime == "POSITIVE_GAMMA":
        score -= 10   # positive gamma suppresses momentum

    # Delta contribution
    if dealer_delta_bias in ("BUYING", "SELLING"):
        score += dealer_delta_confidence * 0.2
    
    # Charm adds directional drift
    if dealer_charm in ("POSITIVE", "NEGATIVE"):
        score += 8

    # Hedging pressure amplifies
    if hedging_pressure_level == "HIGH":
        score += 12
    elif hedging_pressure_level == "MEDIUM":
        score += 6

    # POC migration = institutional acceptance = momentum confirmed
    if poc_migration in ("RISING", "FALLING"):
        score += 10

    # Flow confirmation
    if flow_bias in ("BULLISH", "BEARISH"):
        score += 8

    # Auction state
    if "INITIATIVE" in auction_state or "TREND_DAY" in auction_state:
        score += 10
    elif "BALANCED" in auction_state or "NEUTRAL" in auction_state:
        score -= 10

    probability = _clamp(score)

    if probability >= 75:
        level   = "HIGH"
        summary = (
            f"High momentum probability ({probability:.0f}%). "
            f"{'Negative gamma forces dealers to amplify the move. ' if dealer_gamma_regime == 'NEGATIVE_GAMMA' else ''}"
            f"{'POC migration confirms institutional acceptance of the trend. ' if poc_migration in ('RISING','FALLING') else ''}"
            "Trend continuation is the highest probability outcome."
        )
        trade_implication = "Momentum and trend-following strategies are favored. Avoid fading."
    elif probability >= 55:
        level   = "MODERATE"
        summary = (
            f"Moderate momentum probability ({probability:.0f}%). "
            "Some trend continuation potential but not confirmed by all signals. "
            "Wait for additional confirmation before committing directionally."
        )
        trade_implication = "Cautious trend participation. Require Pine confirmation before entry."
    else:
        level   = "LOW"
        summary = (
            f"Low momentum probability ({probability:.0f}%). "
            "Dealer positioning and auction state do not support trend continuation. "
            f"{'Positive gamma will suppress volatility and create range-bound conditions. ' if dealer_gamma_regime == 'POSITIVE_GAMMA' else ''}"
            "Mean reversion and range strategies are favored."
        )
        trade_implication = "Fade extremes, avoid chasing. Wait for balanced auction to resolve."

    return {
        "probability":      round(probability, 1),
        "level":            level,
        "summary":          summary,
        "trade_implication": trade_implication,
        "gamma_regime":     dealer_gamma_regime,
        "delta_bias":       dealer_delta_bias,
        "poc_migration":    poc_migration,
        "flow_bias":        flow_bias,
        "auction_state":    auction_state,
    }


# ═══════════════════════════════════════════════════════════════════════════
# ORCHESTRATOR — builds all seven phases in one call
# ═══════════════════════════════════════════════════════════════════════════

def build_dealer_positioning(
    *,
    gamma_regime:    Dict[str, Any],
    flow_snapshot:   Dict[str, Any],
    auction_state:   Dict[str, Any],
    market_state:    Dict[str, Any],
    dte:             float = 0.0,
) -> Dict[str, Any]:
    """Orchestrate all 7 phases. Single call — consumes existing engine outputs."""

    price         = _sf(market_state.get("price") or flow_snapshot.get("stock_price"))
    call_prem     = _sf(flow_snapshot.get("call_premium"))
    put_prem      = _sf(flow_snapshot.get("put_premium"))
    net_prem      = _sf(flow_snapshot.get("net_premium") or (call_prem - put_prem))
    sweep_count   = int(_sf(flow_snapshot.get("sweep_count")))
    flow_bias     = str(flow_snapshot.get("bias") or market_state.get("flow_bias") or "MIXED")
    call_ratio    = _sf(flow_snapshot.get("call_ratio_pct"), 50.0) or None
    vix           = _sf(flow_snapshot.get("vix") or market_state.get("vix"))
    flow_momentum = str(flow_snapshot.get("flow_momentum") or "STABLE")
    poc_migration = str(market_state.get("poc_migration") or auction_state.get("poc_migration") or "STABLE")
    minutes_open  = int(_sf(market_state.get("minutes_open")))
    gex_score     = _sf(gamma_regime.get("gex_score"))
    call_wall     = _sf(gamma_regime.get("call_wall"))
    put_wall      = _sf(gamma_regime.get("put_wall"))
    zero_gamma    = _sf(gamma_regime.get("zero_gamma"))
    au_state_name = str(auction_state.get("state") or auction_state.get("auction_state") or "UNKNOWN")
    total_prem    = call_prem + put_prem

    # Phase 1 — Dealer Gamma
    d_gamma = build_dealer_gamma(gamma_regime, price=price)

    # Phase 2 — Dealer Delta
    d_delta = build_dealer_delta(
        call_premium=call_prem, put_premium=put_prem, net_premium=net_prem,
        sweep_count=sweep_count, flow_bias=flow_bias, call_ratio_pct=call_ratio,
        dealer_gamma_regime=d_gamma["regime"], price=price,
    )

    # Phase 3 — Dealer Charm
    d_charm = build_dealer_charm(
        dte=dte, dealer_delta_bias=d_delta["bias"], net_premium=net_prem,
        call_ratio_pct=call_ratio, minutes_open=minutes_open,
    )

    # Phase 4 — Dealer Vega
    d_vega = build_dealer_vega(
        vix=vix, gex_score=gex_score, total_premium=total_prem,
        call_ratio_pct=call_ratio, flow_momentum=flow_momentum,
    )

    # Phase 5 — Hedging Pressure
    d_hedge = build_hedging_pressure(
        dealer_gamma_regime=d_gamma["regime"], dealer_delta_bias=d_delta["bias"],
        dealer_delta_confidence=d_delta["confidence"], sweep_count=sweep_count,
        net_premium=net_prem,
    )

    # Phase 6 — Pin Probability
    d_pin = build_pin_probability(
        price=price, call_wall=call_wall, put_wall=put_wall, zero_gamma=zero_gamma,
        gex_score=gex_score, dte=dte, minutes_open=minutes_open,
    )

    # Phase 7 — Momentum Probability
    d_momentum = build_momentum_probability(
        dealer_gamma_regime=d_gamma["regime"], dealer_delta_bias=d_delta["bias"],
        dealer_delta_confidence=d_delta["confidence"], dealer_charm=d_charm["charm"],
        hedging_pressure_level=d_hedge["level"], poc_migration=poc_migration,
        flow_bias=flow_bias, auction_state=au_state_name, gex_score=gex_score,
    )

    # ── Plain-English dealer summary for Story Engine 4.0 ──
    dealer_summary = (
        f"Dealers are in {d_gamma['regime'].replace('_', ' ')} "
        f"with estimated {d_delta['bias'].lower()} delta pressure. "
        f"{d_charm['drift_note']} "
        f"{d_hedge['narrative']} "
        f"Momentum probability: {d_momentum['probability']:.0f}%."
    )

    return {
        "available":          True,
        "gamma":              d_gamma,
        "delta":              d_delta,
        "charm":              d_charm,
        "vega":               d_vega,
        "hedging_pressure":   d_hedge,
        "pin_probability":    d_pin,
        "momentum_probability": d_momentum,
        # Flat fields for quick access from ribbon/dashboard
        "dealer_regime":        d_gamma["regime"],
        "dealer_delta":         d_delta["bias"],
        "dealer_delta_score":   d_delta["score"],
        "hedging_pressure":     d_hedge["level"],
        "pin_probability_pct":  d_pin["probability"],
        "momentum_probability_pct": d_momentum["probability"],
        "dealer_summary":       dealer_summary,
        "dte":                  round(dte, 2),
        "price":                round(price, 2),
    }
