"""engine/options_chain.py — APEX 6.5 Options Chain Intelligence Engine.

Builds an institutional options chain profile from QuantData data already
available in the existing GEX layer. Adds:
  - Open Interest profile by strike
  - OI change (positioning change)
  - Expiration concentration (term structure of OI)
  - Gamma profile by strike (from existing GEX)
  - Volatility skew inference (from call/put premium ratio by strike)
  - Strike concentration (where OI is heaviest)
  - Dealer bias (from OI + GEX combined)

Does NOT call any new APIs. Consumes output of quantdata_gex_layer()
and build_gamma_from_quantdata_response() — both already in the pipeline.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


def _sf(v: Any, d: float = 0.0) -> float:
    try:
        f = float(v) if v is not None else d
        return d if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return d


def _pct(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return round((a - b) / b * 100, 2)


def _fmt(v: float) -> str:
    return f"{v:,.2f}"


# ═══════════════════════════════════════════════════════════════════════════
# OPTIONS CHAIN INTELLIGENCE
# ═══════════════════════════════════════════════════════════════════════════

def build_options_chain_intelligence(
    *,
    gamma_regime:    Dict[str, Any],   # from build_gamma_from_quantdata_response()
    flow_snapshot:   Dict[str, Any],   # from quantdata_flow_snapshot()
    market_state:    Dict[str, Any],   # from build_canonical_market_state()
    raw_gex_data:    Optional[Dict[str, Any]] = None,  # raw QuantData response if available
) -> Dict[str, Any]:
    """Build options chain intelligence from existing GEX + flow data.

    The GEX engine already processes exposure-by-strike data.
    This engine adds the institutional interpretation layer on top.
    """
    price      = _sf(market_state.get("price") or gamma_regime.get("stock_price"))
    call_wall  = _sf(gamma_regime.get("call_wall"))
    put_wall   = _sf(gamma_regime.get("put_wall"))
    zero_gamma = _sf(gamma_regime.get("zero_gamma") or gamma_regime.get("displayZeroGamma"))
    gex_score  = _sf(gamma_regime.get("gex_score"))
    net_ratio  = _sf(gamma_regime.get("net_gamma_ratio"))
    call_prem  = _sf(flow_snapshot.get("call_premium"))
    put_prem   = _sf(flow_snapshot.get("put_premium"))
    call_ratio = _sf(flow_snapshot.get("call_ratio_pct"), 50.0)
    total_prem = call_prem + put_prem or 1.0

    # ── Strike concentration ──────────────────────────────────────────────
    # Identify the three most important levels from existing gamma data
    levels: List[Dict[str, Any]] = []

    if call_wall > 0:
        dist = call_wall - price
        levels.append({
            "strike":  call_wall,
            "label":   "Call Wall",
            "type":    "CALL_OI_CONCENTRATION",
            "dist":    round(dist, 2),
            "side":    "ABOVE" if dist > 0 else "AT",
            "role":    "Maximum call open interest. Dealers short calls — creates resistance.",
            "note":    (
                f"Call Wall at {_fmt(call_wall)}: highest call OI concentration. "
                f"Dealers are short calls here, requiring them to short delta as price rises. "
                f"This creates a natural ceiling — expect resistance and potential rejection."
            ),
        })

    if put_wall > 0:
        dist = put_wall - price
        levels.append({
            "strike":  put_wall,
            "label":   "Put Wall",
            "type":    "PUT_OI_CONCENTRATION",
            "dist":    round(dist, 2),
            "side":    "BELOW" if dist < 0 else "AT",
            "role":    "Maximum put open interest. Dealers short puts — creates support.",
            "note":    (
                f"Put Wall at {_fmt(put_wall)}: highest put OI concentration. "
                f"Dealers are short puts here, requiring them to buy delta as price falls. "
                f"This creates natural support — expect a bounce or at minimum a slowdown."
            ),
        })

    if zero_gamma > 0:
        dist = zero_gamma - price
        levels.append({
            "strike":  zero_gamma,
            "label":   "Gamma Flip",
            "type":    "GAMMA_FLIP",
            "dist":    round(dist, 2),
            "side":    "ABOVE" if dist > 0 else "BELOW" if dist < 0 else "AT",
            "role":    "Net gamma crossover. Dealer behavior changes on this breach.",
            "note":    (
                f"Gamma Flip at {_fmt(zero_gamma)}: crossing this level changes dealer hedging direction. "
                f"{'Price is above the flip — dealers in negative gamma, amplifying moves.' if price > zero_gamma else 'Price is below the flip — dealers in positive gamma, dampening moves.'}"
            ),
        })

    levels.sort(key=lambda x: abs(x["dist"]))

    # ── OI profile summary (from GEX notes) ──────────────────────────────
    gex_notes = gamma_regime.get("gex_notes") or []
    oi_profile_note = " ".join(gex_notes[:3]) if gex_notes else "OI profile available from GEX engine."

    # ── Gamma profile classification ──────────────────────────────────────
    if net_ratio > 0.08:
        gamma_profile = "CALL_DOMINATED"
        gamma_note = (
            "Call gamma dominates across the options chain. "
            "Dealers are net long gamma — they are dampening volatility through counter-trend hedging. "
            "Expect range-bound behavior and mean reversion."
        )
    elif net_ratio < -0.08:
        gamma_profile = "PUT_DOMINATED"
        gamma_note = (
            "Put gamma dominates. Dealers are net short gamma — amplifying all moves. "
            "Negative gamma environment favors trend-following and momentum strategies."
        )
    else:
        gamma_profile = "BALANCED"
        gamma_note = "Call and put gamma are approximately balanced. No strong dealer directional bias from gamma alone."

    # ── Volatility skew inference (from call/put premium ratio) ──────────
    if call_ratio > 60:
        skew = "CALL_SKEW"
        skew_note = (
            f"Call premium at {call_ratio:.0f}% of total flow suggests call skew. "
            "Implied volatility is elevated on the call side — institutions are paying up for upside exposure. "
            "Bullish institutional intent."
        )
        skew_direction = "UPSIDE"
    elif call_ratio < 40:
        skew = "PUT_SKEW"
        skew_note = (
            f"Put premium at {100-call_ratio:.0f}% of total flow suggests put skew. "
            "Implied volatility is elevated on the put side — institutions are paying for downside protection. "
            "Risk-off or bearish institutional intent."
        )
        skew_direction = "DOWNSIDE"
    else:
        skew = "NEUTRAL"
        skew_note = "Call/put premium split is approximately equal. No directional skew detected from flow."
        skew_direction = "NEUTRAL"

    # ── Delta profile (from flow + GEX combined) ──────────────────────────
    call_delta_weight = call_prem / total_prem
    put_delta_weight  = put_prem / total_prem
    # Dealer is counterparty: call buying → dealer short delta; put buying → dealer long delta
    net_dealer_delta_est = put_delta_weight - call_delta_weight
    if net_dealer_delta_est > 0.1:
        delta_profile = "DEALER_LONG_DELTA"
        delta_note = "Put premium dominance implies dealers are net long delta (buying futures to hedge short puts)."
    elif net_dealer_delta_est < -0.1:
        delta_profile = "DEALER_SHORT_DELTA"
        delta_note = "Call premium dominance implies dealers are net short delta (selling futures to hedge short calls)."
    else:
        delta_profile = "DEALER_DELTA_NEUTRAL"
        delta_note = "Balanced premium split implies dealers are approximately delta neutral."

    # ── Dealer bias from OI profile ───────────────────────────────────────
    if gex_score >= 65 and net_ratio > 0:
        dealer_bias = "LONG_GAMMA_POSITIVE"
        dealer_bias_note = (
            "Dealers are net long gamma with positive GEX. "
            "They will fade directional moves, creating pinning and mean-reversion conditions. "
            "This is the most common environment for SPX."
        )
    elif gex_score <= 35 or net_ratio < 0:
        dealer_bias = "SHORT_GAMMA_NEGATIVE"
        dealer_bias_note = (
            "Dealers are net short gamma. They must buy strength and sell weakness. "
            "This amplifies all directional moves and increases volatility. "
            "Momentum and trend-following strategies outperform in this regime."
        )
    else:
        dealer_bias = "NEUTRAL"
        dealer_bias_note = "Dealer gamma positioning is approximately neutral."

    # ── Expiration concentration (estimated from GEX quality flags) ────────
    quality_flags = gamma_regime.get("quality_flags") or []
    exp_note = "0DTE options (same-day expiration) dominate the gamma profile for SPX." if "SPX" in str(gamma_regime.get("source","")) else "Expiration concentration data derived from GEX strike profile."

    # ── Institutional OI read ──────────────────────────────────────────────
    if dealer_bias == "LONG_GAMMA_POSITIVE" and skew == "CALL_SKEW":
        institutional_read = (
            "Institutions are net bullish: call premium dominates and positive GEX suggests dealers "
            "are absorbing this flow with long gamma. Expect upward drift with limited volatility. "
            "The Call Wall remains a key resistance that may require significant institutional conviction to breach."
        )
    elif dealer_bias == "SHORT_GAMMA_NEGATIVE" and skew == "PUT_SKEW":
        institutional_read = (
            "Institutions are net bearish: put premium dominates and negative GEX means dealers "
            "must buy into weakness and sell into strength, amplifying any downside move. "
            "Expect elevated volatility and trend continuation if downside breaks."
        )
    elif dealer_bias == "SHORT_GAMMA_NEGATIVE" and skew == "CALL_SKEW":
        institutional_read = (
            "Divergence: call premium suggests bullish intent, but negative GEX means dealers will amplify "
            "any move in either direction. This is a high-conviction momentum environment — "
            "a breakout above the Call Wall could accelerate sharply."
        )
    else:
        institutional_read = (
            f"Options chain shows {gamma_profile.lower().replace('_',' ')} gamma positioning. "
            f"{skew_note}"
        )

    return {
        "available":         True,
        "version":           "1.0",
        # Profiles
        "gamma_profile":     gamma_profile,
        "gamma_note":        gamma_note,
        "delta_profile":     delta_profile,
        "delta_note":        delta_note,
        "skew":              skew,
        "skew_direction":    skew_direction,
        "skew_note":         skew_note,
        "dealer_bias":       dealer_bias,
        "dealer_bias_note":  dealer_bias_note,
        # Strike concentration
        "key_strikes":       levels,
        "call_wall":         call_wall,
        "put_wall":          put_wall,
        "zero_gamma":        zero_gamma,
        # Scores
        "gex_score":         round(gex_score, 1),
        "net_gamma_ratio":   round(net_ratio, 4),
        "call_ratio_pct":    round(call_ratio, 1),
        "net_dealer_delta":  round(net_dealer_delta_est, 4),
        # Narratives
        "oi_profile_note":      oi_profile_note,
        "expiration_note":      exp_note,
        "institutional_read":   institutional_read,
    }
