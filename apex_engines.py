"""
apex_engines.py — APEX 5.0 Nine-Engine Institutional Decision Support System

This module implements the nine-engine pipeline that replaces the ad-hoc scoring
model in app.py. Import this into app.py and call build_institutional_decision()
as the single entry point for the /api/institutional_os endpoint.

Pipeline order (each engine feeds the next):
  1. Market Regime Engine        → sets the operating environment
  2. Gamma Regime Engine         → classifies dealer behavior, adapts weights
  3. Institutional Flow Engine   → detects flow divergence, absorption, momentum
  4. Market Structure Engine     → VWAP, POC, value area, overnight/PDH levels
  5. Trend Engine                → price-only: EMA slope, ATR regime, compression
  6. Execution Engine            → Pine webhook confirmation
  7. Consensus Engine            → conviction-weighted votes, produces ENTER/WATCH/WAIT
  8. Risk Engine                 → entry zone, stop, targets adapted to gamma regime
  9. Story Engine                → prose narrative from all eight upstream engines

APEX 5.0 improvements over 4.5:
  - Flow cache TTL reduced to 90s, comparison window tightened to 2×TTL
  - Divergence signals expire automatically and downgrade A+→B if price moves
  - Absorption detection requires price-stalling confirmation (3-bar range check)
  - Consensus engine uses conviction-weighted votes (weight × strength per engine)
  - Institutional Confidence Index (ICI): single 0–100 primary dashboard number

Adaptive weight table:
  Gamma regime shifts which engines get the most conviction-weight.
  Negative gamma → flow and momentum dominate.
  Positive gamma → structure and mean-reversion dominate.
"""
from __future__ import annotations

import datetime as dt
import threading
import statistics
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# Flow snapshot cache (per-ticker, short TTL)
# Used by the flow divergence engine to detect momentum flips.
# ---------------------------------------------------------------------------
_FLOW_CACHE: Dict[str, Dict[str, Any]] = {}
_FLOW_CACHE_LOCK = threading.Lock()
# 90s TTL: enough gap to detect a genuine flip between polling cycles,
# but not so stale that we compare to a snapshot from a different session
# context. Comparison window = TTL × 2 (max 3 min lookback).
_FLOW_CACHE_TTL_SECONDS = 90

# ---------------------------------------------------------------------------
# Divergence signal cache (per-ticker)
# Tracks the active divergence signal with its trigger time and the price
# level at which it fired. On each subsequent call the geometric condition
# is re-evaluated — if price has moved away from the trigger level by more
# than the DIVERGENCE_DECAY_THRESHOLD, the signal downgrades from A+ → B.
# If it has been active longer than DIVERGENCE_MAX_AGE_SECONDS it expires.
# ---------------------------------------------------------------------------
_DIVERGENCE_CACHE: Dict[str, Dict[str, Any]] = {}
_DIVERGENCE_CACHE_LOCK = threading.Lock()
DIVERGENCE_MAX_AGE_SECONDS = 240   # 4 minutes: A+ divergence must resolve or expire
DIVERGENCE_DECAY_THRESHOLD = 0.003  # 0.3% away from trigger level → downgrade to B


def _now_et() -> dt.datetime:
    return dt.datetime.now(EASTERN)


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def _ema(values: List[float], period: int) -> Optional[float]:
    vals = [_safe_float(v) for v in values if v is not None]
    if len(vals) < period:
        return None
    k = 2 / (period + 1)
    e = sum(vals[:period]) / period
    for v in vals[period:]:
        e = v * k + e * (1 - k)
    return e


# ---------------------------------------------------------------------------
# Adaptive weight table
# Returns weights for each engine vote given the current gamma regime.
# Weights are used in the Consensus Engine vote-weight sum.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Base adaptive weight table (gamma-regime dimension).
# flow_intelligence replaces the old "flow" key — it now votes directly.
# Structure and Execution receive session-aware adjustment via
# get_adaptive_weights() which merges both dimensions.
# ---------------------------------------------------------------------------

ADAPTIVE_WEIGHTS: Dict[str, Dict[str, float]] = {
    "NEGATIVE_GAMMA": {
        # Negative gamma = dealer amplification; flow + trend dominate
        "market_regime":    0.08,
        "gamma_regime":     0.07,
        "flow_intelligence":0.28,  # HIGHEST — flow divergence is the primary signal
        "structure":        0.10,  # structure matters less — levels get blown through
        "trend":            0.20,  # momentum elevated
        "execution":        0.27,  # Pine confirmation still critical
    },
    "POSITIVE_GAMMA": {
        # Positive gamma = dealer dampening; structure + mean-reversion dominate
        "market_regime":    0.09,
        "gamma_regime":     0.08,
        "flow_intelligence":0.20,
        "structure":        0.26,  # structure elevated — levels hold better
        "trend":            0.12,
        "execution":        0.25,
    },
    "MIXED_GAMMA": {
        # Default balanced weights
        "market_regime":    0.09,
        "gamma_regime":     0.08,
        "flow_intelligence":0.24,
        "structure":        0.18,
        "trend":            0.15,
        "execution":        0.26,
    },
}

# ---------------------------------------------------------------------------
# Session-aware ICI weight tables.
# When the market is closed or pre-session, Execution and Structure
# cannot contribute meaningfully. Their ICI weight is redistributed
# to Conviction and Flow Momentum so the score still reflects real data.
# ---------------------------------------------------------------------------

ICI_WEIGHTS_BY_SESSION: Dict[str, Dict[str, float]] = {
    "MARKET_OPEN": {
        # Full weighting — all components meaningful
        "conviction":    0.50,
        "freshness":     0.20,  # Pine signal contribution
        "gamma":         0.15,
        "momentum":      0.15,
    },
    "PREMARKET": {
        # No Pine signal yet, no VWAP/OR — redistribute freshness weight
        "conviction":    0.55,
        "freshness":     0.05,  # Small — signal unlikely pre-market
        "gamma":         0.20,  # Gamma levels still valid
        "momentum":      0.20,  # Flow reading still useful
    },
    "AFTER_HOURS": {
        # Session closed — execution and structure are stale
        "conviction":    0.55,
        "freshness":     0.00,  # No live signal possible
        "gamma":         0.20,
        "momentum":      0.25,  # Flow premium accumulation still informative
    },
    "CLOSED": {
        "conviction":    0.55,
        "freshness":     0.00,
        "gamma":         0.20,
        "momentum":      0.25,
    },
}


def get_adaptive_weights(gamma_regime_label: str, session_state: str = "MARKET_OPEN") -> Dict[str, float]:
    """Return engine vote weights for the current gamma regime.

    When market is not open, Structure and Execution weights are halved and
    redistributed to Flow Intelligence (which has live data from QuantData
    regardless of session) so the consensus score reflects real information.
    """
    label = (gamma_regime_label or "MIXED_GAMMA").upper()
    base = None
    for key in ADAPTIVE_WEIGHTS:
        if key in label or label in key:
            base = dict(ADAPTIVE_WEIGHTS[key])
            break
    if base is None:
        base = dict(ADAPTIVE_WEIGHTS["MIXED_GAMMA"])

    if session_state not in ("MARKET_OPEN",):
        # Halve structure and execution — their session-data inputs are unavailable
        released = base["structure"] * 0.5 + base["execution"] * 0.15
        base["structure"]        = round(base["structure"] * 0.5, 3)
        base["execution"]        = round(base["execution"] * 0.85, 3)
        base["flow_intelligence"]= round(base["flow_intelligence"] + released * 0.7, 3)
        base["market_regime"]    = round(base["market_regime"] + released * 0.3, 3)
        # Re-normalize to exactly 1.0
        total = sum(base.values())
        base = {k: round(v / total, 4) for k, v in base.items()}
    return base


def get_ici_weights(session_state: str = "MARKET_OPEN") -> Dict[str, float]:
    """Return ICI component weights adjusted for session state."""
    return ICI_WEIGHTS_BY_SESSION.get(session_state, ICI_WEIGHTS_BY_SESSION["CLOSED"])


# ===========================================================================
# ENGINE 1: MARKET REGIME ENGINE
# Determines the day's operating environment.
# Inputs: SPY/QQQ trend (from app.py daily bars), VIX (Polygon snapshot),
#         breadth proxy (VOLD from Polygon), GEX score (passed in).
# Output: TREND_DAY | RANGE_DAY | HIGH_VOLATILITY | NEGATIVE_GAMMA_TREND
# ===========================================================================

def engine_market_regime(
    spy_bars: List[dict],
    qqq_bars: List[dict],
    vix_price: Optional[float],
    gex_score: float,
    breadth_score: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Classifies the current market operating environment.

    Returns regime label, volatility classification, and behavioral guidance
    that all downstream engines will receive.
    """
    notes: List[str] = []

    # ── SPY trend ──
    spy_score = 50.0
    spy_20d_return = 0.0
    if len(spy_bars) >= 60:
        spy_closes = [_safe_float(b.get("c")) for b in spy_bars]
        spy_price = spy_closes[-1]
        e21 = _ema(spy_closes, 21)
        e50 = _ema(spy_closes, 50)
        e200 = _ema(spy_closes, 200) or e50
        if all([spy_price, e21, e50, e200]):
            spy_score = 50.0
            if spy_price > e21: spy_score += 12
            else: spy_score -= 10
            if spy_price > e50: spy_score += 12
            else: spy_score -= 14
            if e50 >= e200: spy_score += 14
            else: spy_score -= 10
            spy_score = max(0.0, min(100.0, spy_score))
        if len(spy_closes) >= 22 and spy_closes[-21]:
            spy_20d_return = (spy_closes[-1] - spy_closes[-21]) / spy_closes[-21] * 100
        notes.append(f"SPY trend score {spy_score:.0f}")

    # ── QQQ trend ──
    qqq_score = 50.0
    if len(qqq_bars) >= 60:
        qqq_closes = [_safe_float(b.get("c")) for b in qqq_bars]
        qqq_price = qqq_closes[-1]
        q21 = _ema(qqq_closes, 21)
        q50 = _ema(qqq_closes, 50)
        q200 = _ema(qqq_closes, 200) or q50
        if all([qqq_price, q21, q50, q200]):
            qqq_score = 50.0
            if qqq_price > q21: qqq_score += 12
            else: qqq_score -= 10
            if qqq_price > q50: qqq_score += 12
            else: qqq_score -= 14
            if q50 >= q200: qqq_score += 14
            else: qqq_score -= 10
            qqq_score = max(0.0, min(100.0, qqq_score))
        notes.append(f"QQQ trend score {qqq_score:.0f}")

    # ── VIX regime ──
    vix = _safe_float(vix_price, 18.0)
    if vix >= 30:
        vix_regime = "EXTREME_FEAR"
        vix_score = 20.0
        notes.append(f"VIX {vix:.1f} — extreme fear / high volatility")
    elif vix >= 22:
        vix_regime = "ELEVATED"
        vix_score = 40.0
        notes.append(f"VIX {vix:.1f} — elevated volatility")
    elif vix <= 14:
        vix_regime = "COMPLACENCY"
        vix_score = 70.0
        notes.append(f"VIX {vix:.1f} — low vol / potential complacency")
    else:
        vix_regime = "NORMAL"
        vix_score = 55.0
        notes.append(f"VIX {vix:.1f} — normal range")

    # ── GEX environment ──
    if gex_score >= 65:
        gex_env = "POSITIVE_GAMMA_ENVIRONMENT"
        gex_env_label = "Dealers long gamma — dampened movement expected"
    elif gex_score <= 35:
        gex_env = "NEGATIVE_GAMMA_ENVIRONMENT"
        gex_env_label = "Dealers short gamma — amplified movement expected"
    else:
        gex_env = "MIXED_GAMMA_ENVIRONMENT"
        gex_env_label = "Mixed dealer positioning"
    notes.append(gex_env_label)

    # ── Breadth ──
    breadth = _safe_float(breadth_score, 50.0)
    if breadth >= 65:
        breadth_label = "BROAD_PARTICIPATION"
        notes.append("Broad market breadth supporting the move")
    elif breadth <= 35:
        breadth_label = "NARROW_LEADERSHIP"
        notes.append("Narrow breadth — internal weakness warning")
    else:
        breadth_label = "MIXED_BREADTH"

    # ── Composite score and regime label ──
    composite = (spy_score * 0.35 + qqq_score * 0.25 + vix_score * 0.20 +
                 gex_score * 0.12 + breadth * 0.08)

    # Classify regime
    if composite >= 72 and vix < 22:
        regime = "TREND_DAY"
        regime_description = "Trending conditions. Favor continuation setups, wider targets."
    elif composite >= 58 and vix < 22:
        regime = "RANGE_DAY"
        regime_description = "Range-bound conditions. Favor pullback entries, tighter targets."
    elif vix >= 28 or (gex_score <= 35 and vix >= 22):
        regime = "HIGH_VOLATILITY"
        regime_description = "High volatility / negative gamma. Expect larger swings. Reduce size."
    elif composite <= 40:
        regime = "DEFENSIVE"
        regime_description = "Defensive environment. Avoid call setups, prefer cash or puts."
    else:
        regime = "NEUTRAL"
        regime_description = "Neutral conditions. Wait for clearer institutional alignment."

    # Behavioral rules for downstream engines
    if regime == "TREND_DAY":
        behavioral_rules = {
            "entry_style": "BREAKOUT_CONTINUATION",
            "target_multiplier": 1.3,
            "stop_multiplier": 1.0,
            "preferred_setup": "Momentum entries on first pullback",
        }
    elif regime == "RANGE_DAY":
        behavioral_rules = {
            "entry_style": "PULLBACK_MEAN_REVERSION",
            "target_multiplier": 0.8,
            "stop_multiplier": 0.85,
            "preferred_setup": "Fade extremes near key levels",
        }
    elif regime == "HIGH_VOLATILITY":
        behavioral_rules = {
            "entry_style": "DIRECTIONAL_BREAKOUT",
            "target_multiplier": 1.5,
            "stop_multiplier": 1.3,
            "preferred_setup": "Only A+ setups, reduced size, wider targets",
        }
    else:
        behavioral_rules = {
            "entry_style": "SELECTIVE",
            "target_multiplier": 1.0,
            "stop_multiplier": 1.0,
            "preferred_setup": "Wait for cleaner conditions",
        }

    return {
        "regime": regime,
        "regime_description": regime_description,
        "composite_score": round(composite, 1),
        "spy_trend_score": round(spy_score, 1),
        "qqq_trend_score": round(qqq_score, 1),
        "vix": round(vix, 2),
        "vix_regime": vix_regime,
        "gex_environment": gex_env,
        "breadth_label": breadth_label,
        "spy_20d_return": round(spy_20d_return, 2),
        "behavioral_rules": behavioral_rules,
        "bullish": composite >= 58,
        "notes": notes,
        "engine": "MARKET_REGIME",
        "vote": "BULLISH" if composite >= 65 else "BEARISH" if composite <= 40 else "NEUTRAL",
        "vote_strength": round(abs(composite - 50) / 50, 2),
    }


# ===========================================================================
# ENGINE 2: GAMMA REGIME ENGINE
# Classifies dealer hedging behavior and adapts trade management rules.
# Goes much further than just support/resistance.
# ===========================================================================

def engine_gamma_regime(
    gex_score: float,
    call_wall: Optional[float],
    put_wall: Optional[float],
    zero_gamma: Optional[float],
    stock_price: Optional[float],
    vix: float = 18.0,
) -> Dict[str, Any]:
    """
    Classifies the gamma environment and produces behavioral rules
    that modify the Trade Planner and Story Engine.

    Positive Gamma → dealers dampen moves → mean reversion, tighter targets
    Negative Gamma → dealers amplify moves → momentum, wider targets
    """
    price = _safe_float(stock_price, 0.0)
    cw = _safe_float(call_wall, 0.0)
    pw = _safe_float(put_wall, 0.0)
    zg = _safe_float(zero_gamma, 0.0)
    notes: List[str] = []

    # Primary classification
    if gex_score >= 68:
        regime_label = "POSITIVE_GAMMA"
        regime_display = "Positive Gamma"
        expected_vol = "LOW"
        vol_description = "Dealers are long gamma — they sell strength and buy weakness, dampening moves."
        dealer_behavior = "DAMPENING"
        notes.append("Dealer hedging creates a gravitational pull toward key levels.")
    elif gex_score <= 35:
        regime_label = "NEGATIVE_GAMMA"
        regime_display = "Negative Gamma"
        expected_vol = "HIGH"
        vol_description = "Dealers are short gamma — they buy strength and sell weakness, amplifying moves."
        dealer_behavior = "AMPLIFYING"
        notes.append("Dealer hedging accelerates price moves away from key levels.")
    else:
        regime_label = "MIXED_GAMMA"
        regime_display = "Mixed Gamma"
        expected_vol = "MEDIUM"
        vol_description = "Mixed dealer positioning — no strong directional amplification or dampening."
        dealer_behavior = "NEUTRAL"
        notes.append("Mixed gamma — no strong dealer-driven bias.")

    # Distance to zero gamma (flip point)
    flip_risk = False
    dist_to_flip = None
    if price > 0 and zg > 0:
        dist_to_flip = round(abs(price - zg), 2)
        dist_pct = abs(price - zg) / price * 100
        if dist_pct <= 0.3:
            flip_risk = True
            notes.append(f"Price within {dist_to_flip} pts of zero-gamma flip at {zg} — regime may change soon.")
        else:
            notes.append(f"Zero-gamma flip at {zg} ({dist_pct:.1f}% away).")

    # Where is price relative to the gamma walls?
    level_context: List[str] = []
    near_call_wall = False
    near_put_wall = False
    if price > 0 and cw > 0:
        dist = (cw - price) / price * 100
        if dist <= 0.25:
            near_call_wall = True
            level_context.append(f"Near call wall {cw} — potential ceiling / resistance")
        elif dist <= 0.6:
            level_context.append(f"Approaching call wall {cw} ({dist:.1f}% above)")
    if price > 0 and pw > 0:
        dist = (price - pw) / price * 100
        if dist <= 0.25:
            near_put_wall = True
            level_context.append(f"Near put wall {pw} — potential floor / support")
        elif dist <= 0.6:
            level_context.append(f"Approaching put wall {pw} ({dist:.1f}% below)")

    # Trade management rules based on gamma regime
    if regime_label == "POSITIVE_GAMMA":
        trade_rules = {
            "entry_style": "Favor pullback entries toward VWAP or POC",
            "target_style": "Use tighter profit targets — dealers dampen extension",
            "stop_style": "Can use tighter stops — mean reversion works in your favor",
            "position_size": "FULL",
            "target_multiplier": 0.85,
            "stop_multiplier": 0.90,
            "expected_behavior": "Price tends to revert to key levels. Fade extremes.",
        }
    elif regime_label == "NEGATIVE_GAMMA":
        trade_rules = {
            "entry_style": "Favor breakout and continuation — momentum is your friend",
            "target_style": "Allow wider profit targets — moves extend further",
            "stop_style": "Use wider stops — momentum can spike before resolution",
            "position_size": "REDUCED",
            "target_multiplier": 1.4,
            "stop_multiplier": 1.25,
            "expected_behavior": "Price tends to accelerate through levels. Trend entries work.",
        }
    else:
        trade_rules = {
            "entry_style": "Standard entries — no strong regime edge",
            "target_style": "Standard targets",
            "stop_style": "Standard stops",
            "position_size": "FULL",
            "target_multiplier": 1.0,
            "stop_multiplier": 1.0,
            "expected_behavior": "No clear dealer-driven directional bias.",
        }

    return {
        "regime_label": regime_label,
        "regime_display": regime_display,
        "expected_volatility": expected_vol,
        "vol_description": vol_description,
        "dealer_behavior": dealer_behavior,
        "gex_score": round(gex_score, 1),
        "call_wall": cw or None,
        "put_wall": pw or None,
        "zero_gamma": zg or None,
        "near_call_wall": near_call_wall,
        "near_put_wall": near_put_wall,
        "flip_risk": flip_risk,
        "dist_to_gamma_flip": dist_to_flip,
        "level_context": level_context,
        "trade_rules": trade_rules,
        "notes": notes,
        "engine": "GAMMA_REGIME",
        # Consensus vote: gamma alone isn't directional — abstain unless at extremes
        "vote": "NEUTRAL",
        "vote_strength": 0.0,
    }


# ===========================================================================
# ENGINE 3: INSTITUTIONAL FLOW INTELLIGENCE ENGINE
# The heart of the system. Evaluates options flow as a proxy for institutional
# net delta and detects divergence, absorption, flow flips, and momentum.
# ===========================================================================

def _update_flow_cache(ticker: str, snapshot: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Stores the current flow snapshot and returns the previous one if it falls
    within the comparison window (TTL × 2, max 3 minutes).

    The previous snapshot is only returned if it is:
    - Newer than TTL seconds (meaning a genuine fresh comparison is possible)
    - Older than 0 seconds (the very first call for a ticker has no previous)

    This prevents comparing against a stale snapshot from a different session
    period, which could produce phantom flip signals.
    """
    now_ts = dt.datetime.now(dt.timezone.utc).timestamp()
    with _FLOW_CACHE_LOCK:
        prev = _FLOW_CACHE.get(ticker)
        _FLOW_CACHE[ticker] = {**snapshot, "_cached_at": now_ts}
    if prev:
        age = now_ts - _safe_float(prev.get("_cached_at"), 0)
        # Accept prev snapshot if it is within the comparison window (TTL × 2)
        # but old enough to have been from a genuinely different poll cycle (> 5s)
        if 5 < age <= _FLOW_CACHE_TTL_SECONDS * 2:
            return prev
    return None


def _record_divergence(
    ticker: str,
    divergence_type: str,
    divergence_direction: str,
    trigger_price: float,
    trigger_level: float,   # session high/low or rolling high/low that fired
) -> None:
    """Record a new divergence signal with its trigger context."""
    now_ts = dt.datetime.now(dt.timezone.utc).timestamp()
    with _DIVERGENCE_CACHE_LOCK:
        _DIVERGENCE_CACHE[ticker] = {
            "divergence_type": divergence_type,
            "divergence_direction": divergence_direction,
            "trigger_price": trigger_price,
            "trigger_level": trigger_level,
            "fired_at": now_ts,
        }


def _evaluate_divergence_persistence(
    ticker: str,
    current_price: float,
    current_flow_score: float,
    session_high: Optional[float],
    session_low: Optional[float],
) -> Optional[Dict[str, Any]]:
    """
    Re-evaluates the cached divergence signal on each call.

    Returns the (possibly downgraded) divergence dict if still active,
    or None if it has expired or been invalidated by price movement.

    Downgrade logic:
    - If price has moved more than DIVERGENCE_DECAY_THRESHOLD from the trigger
      level, A+ downgrades to B (still a caution, not a block).
    - If age > DIVERGENCE_MAX_AGE_SECONDS, signal expires completely.
    - If flow has recovered in the opposite direction (score crosses 50 back),
      the bearish signal is invalidated (and vice versa).
    """
    now_ts = dt.datetime.now(dt.timezone.utc).timestamp()
    with _DIVERGENCE_CACHE_LOCK:
        cached = _DIVERGENCE_CACHE.get(ticker)
    if not cached:
        return None

    age = now_ts - _safe_float(cached.get("fired_at"), 0)
    if age > DIVERGENCE_MAX_AGE_SECONDS:
        with _DIVERGENCE_CACHE_LOCK:
            _DIVERGENCE_CACHE.pop(ticker, None)
        return None

    direction = cached.get("divergence_direction", "")
    trigger_level = _safe_float(cached.get("trigger_level"), 0.0)
    div_type = cached.get("divergence_type", "B")

    # Check geometric persistence: is price still near the trigger level?
    geo_valid = False
    if trigger_level > 0 and current_price > 0:
        dist_from_trigger = abs(current_price - trigger_level) / current_price
        geo_valid = dist_from_trigger <= DIVERGENCE_DECAY_THRESHOLD * 3  # Allow wider range for persistence

    # Check flow persistence: has flow recovered against the signal?
    flow_invalidated = False
    if direction == "BEARISH" and current_flow_score >= 62:
        flow_invalidated = True  # Flow recovered bullish — bearish divergence invalidated
    elif direction == "BULLISH" and current_flow_score <= 38:
        flow_invalidated = True  # Flow recovered bearish — bullish divergence invalidated

    if flow_invalidated:
        with _DIVERGENCE_CACHE_LOCK:
            _DIVERGENCE_CACHE.pop(ticker, None)
        return None

    # Downgrade: A+ → B if price has moved away from level
    effective_type = div_type
    if div_type == "A_PLUS" and not geo_valid:
        effective_type = "B"

    seconds_remaining = max(0, int(DIVERGENCE_MAX_AGE_SECONDS - age))
    return {
        "divergence_type": effective_type,
        "divergence_direction": direction,
        "divergence_strength": "STRONG" if effective_type == "A_PLUS" else "EARLY_WARNING",
        "divergence_age_seconds": int(age),
        "divergence_seconds_remaining": seconds_remaining,
        "divergence_downgraded": effective_type != div_type,
        "trigger_level": trigger_level,
        "geo_valid": geo_valid,
    }


def engine_institutional_flow(
    ticker: str,
    flow_snapshot: Dict[str, Any],
    intraday_bars: List[dict],
    stock_price: Optional[float],
    call_wall: Optional[float],
    put_wall: Optional[float],
    zero_gamma: Optional[float],
    gamma_regime_label: str,
) -> Dict[str, Any]:
    """
    Institutional Flow Intelligence Engine.

    Detects:
    - Flow direction and net premium
    - Sweep aggression (count, size)
    - Block trade conviction
    - Call/Put ratio and flow momentum
    - Flow divergence vs. price (A+ and B signals)
    - Absorption at key gamma levels
    - Flow flip detection (previous snapshot comparison)

    The divergence detection is the primary new capability:
    - A+ divergence: price at/near session high + flow flips bearish
                     (or session low + flow flips bullish)
    - B divergence: price at/near 5-min rolling high/low + flow weakens
    """
    price = _safe_float(stock_price, 0.0)
    cw = _safe_float(call_wall, 0.0)
    pw = _safe_float(put_wall, 0.0)
    zg = _safe_float(zero_gamma, 0.0)
    notes: List[str] = []

    # ── Extract flow metrics ──
    flow_score = _safe_float(flow_snapshot.get("flow_score"), 50.0)
    order_score = _safe_float(flow_snapshot.get("order_flow_score"), 50.0)
    net_premium = _safe_float(flow_snapshot.get("net_premium"), 0.0)
    call_premium = _safe_float(flow_snapshot.get("call_premium"), 0.0)
    put_premium = _safe_float(flow_snapshot.get("put_premium"), 0.0)
    sweep_count = _safe_float(flow_snapshot.get("sweep_count"), 0.0)
    bias = (flow_snapshot.get("bias") or "MIXED").upper()

    # ── Flow momentum via cache comparison ──
    prev_snapshot = _update_flow_cache(ticker, flow_snapshot)
    flow_flip = False
    flow_flip_direction = None
    flow_momentum = "STABLE"
    prev_flow_score = None
    flow_delta = 0.0
    if prev_snapshot:
        prev_flow_score = _safe_float(prev_snapshot.get("flow_score"), 50.0)
        flow_delta = flow_score - prev_flow_score
        if flow_delta <= -12 and prev_flow_score >= 55:
            flow_flip = True
            flow_flip_direction = "BEARISH"
            flow_momentum = "FLIPPED_BEARISH"
            notes.append(f"Flow flipped bearish ({prev_flow_score:.0f} → {flow_score:.0f}) — aggressive selling entering.")
        elif flow_delta >= 12 and prev_flow_score <= 45:
            flow_flip = True
            flow_flip_direction = "BULLISH"
            flow_momentum = "FLIPPED_BULLISH"
            notes.append(f"Flow flipped bullish ({prev_flow_score:.0f} → {flow_score:.0f}) — aggressive buying entering.")
        elif flow_delta <= -6:
            flow_momentum = "WEAKENING_BULLISH" if flow_score > 50 else "ACCELERATING_BEARISH"
            notes.append(f"Flow weakening ({flow_delta:+.0f} points this snapshot).")
        elif flow_delta >= 6:
            flow_momentum = "STRENGTHENING_BULLISH" if flow_score > 50 else "RECOVERING_BEARISH"
            notes.append(f"Flow strengthening ({flow_delta:+.0f} points).")

    # ── Session high/low and rolling 5-min high/low from intraday bars ──
    session_high = session_low = None
    rolling_high = rolling_low = None
    if intraday_bars:
        highs = [_safe_float(b.get("h")) for b in intraday_bars if b.get("h")]
        lows = [_safe_float(b.get("l")) for b in intraday_bars if b.get("l")]
        if highs:
            session_high = max(highs)
            session_low = min(lows) if lows else None
        # Rolling high/low: last 6 bars (30 minutes on 5-min chart)
        recent_bars = intraday_bars[-6:] if len(intraday_bars) >= 6 else intraday_bars
        r_highs = [_safe_float(b.get("h")) for b in recent_bars if b.get("h")]
        r_lows = [_safe_float(b.get("l")) for b in recent_bars if b.get("l")]
        if r_highs:
            rolling_high = max(r_highs)
            rolling_low = min(r_lows) if r_lows else None

    # ── Flow Divergence Detection ──
    # Check for a persisting cached divergence first (it may have been downgraded
    # from A+ to B since it fired, or it may have expired entirely).
    persisted_divergence = _evaluate_divergence_persistence(
        ticker=ticker,
        current_price=price,
        current_flow_score=flow_score,
        session_high=session_high,
        session_low=session_low,
    )

    divergence_type = None
    divergence_direction = None
    divergence_strength = None
    divergence_description = None
    divergence_age_seconds = None
    divergence_seconds_remaining = None
    divergence_downgraded = False
    at_gamma_level = False

    if price > 0 and session_high and session_high > 0:
        dist_to_session_high_pct = (session_high - price) / price * 100
        dist_to_session_low_pct = (price - session_low) / price * 100 if session_low else None

        # Check for nearby key gamma level
        at_call_wall = cw > 0 and abs(price - cw) / price <= 0.003
        at_put_wall = pw > 0 and abs(price - pw) / price <= 0.003
        near_zero_gamma = zg > 0 and abs(price - zg) / price <= 0.002
        at_gamma_level = at_call_wall or at_put_wall or near_zero_gamma

        # A+ BEARISH divergence: price at/above session high, flow turning negative
        at_or_above_session_high = dist_to_session_high_pct <= 0.15
        if at_or_above_session_high and (
            flow_flip_direction == "BEARISH" or
            (flow_score <= 38 and prev_flow_score and prev_flow_score >= 55)
        ):
            divergence_type = "A_PLUS"
            divergence_direction = "BEARISH"
            divergence_strength = "STRONG" if at_gamma_level else "MODERATE"
            divergence_description = (
                f"A+ Bearish Divergence: price tagged session high ({session_high:.2f}) "
                f"while options flow flipped bearish (score {flow_score:.0f}). "
                f"{'At call wall / key gamma level.' if at_gamma_level else ''} "
                f"Aggressive sellers have taken control at the highs."
            )
            notes.append(f"⚠️ A+ BEARISH DIVERGENCE at session high {session_high:.2f}")
            _record_divergence(ticker, "A_PLUS", "BEARISH", price, session_high)

        # A+ BULLISH divergence: price at/below session low, flow turning positive
        elif dist_to_session_low_pct is not None and dist_to_session_low_pct <= 0.15 and (
            flow_flip_direction == "BULLISH" or
            (flow_score >= 62 and prev_flow_score and prev_flow_score <= 45)
        ):
            divergence_type = "A_PLUS"
            divergence_direction = "BULLISH"
            divergence_strength = "STRONG" if at_gamma_level else "MODERATE"
            divergence_description = (
                f"A+ Bullish Divergence: price tagged session low ({session_low:.2f}) "
                f"while options flow flipped bullish (score {flow_score:.0f}). "
                f"{'At put wall / key gamma level.' if at_gamma_level else ''} "
                f"Aggressive buyers have absorbed the selling at the lows."
            )
            notes.append(f"⚠️ A+ BULLISH DIVERGENCE at session low {session_low:.2f}")
            _record_divergence(ticker, "A_PLUS", "BULLISH", price, session_low)

    # If no fresh divergence fired, check whether a prior one is still persisting
    if divergence_type is None and persisted_divergence:
        divergence_type = persisted_divergence["divergence_type"]
        divergence_direction = persisted_divergence["divergence_direction"]
        divergence_strength = persisted_divergence["divergence_strength"]
        divergence_age_seconds = persisted_divergence["divergence_age_seconds"]
        divergence_seconds_remaining = persisted_divergence["divergence_seconds_remaining"]
        divergence_downgraded = persisted_divergence["divergence_downgraded"]
        trigger_level = persisted_divergence.get("trigger_level", 0.0)
        status_note = "downgraded A+→B" if divergence_downgraded else f"{divergence_age_seconds}s old"
        divergence_description = (
            f"{'A+' if divergence_type == 'A_PLUS' else 'B'} {divergence_direction} Divergence persisting "
            f"({status_note}, {divergence_seconds_remaining}s remaining). "
            f"Flow has not recovered — signal still active."
        )
        if divergence_type == "A_PLUS":
            notes.append(f"⚠️ PERSISTING A+ {divergence_direction} DIVERGENCE ({divergence_age_seconds}s old)")
        else:
            notes.append(f"Persisting B divergence ({divergence_direction}, {divergence_age_seconds}s old)")

    # B divergences: rolling high/low with flow weakening (not full flip)
    # Only fire if no A+ or persisted divergence is already active
    if divergence_type is None and rolling_high and price > 0:
        at_rolling_high = abs(price - rolling_high) / price <= 0.002
        at_rolling_low = rolling_low and abs(price - rolling_low) / price <= 0.002

        if at_rolling_high and flow_momentum in ("WEAKENING_BULLISH", "FLIPPED_BEARISH") and flow_score <= 48:
            divergence_type = "B"
            divergence_direction = "BEARISH"
            divergence_strength = "EARLY_WARNING"
            divergence_description = (
                f"B Bearish Divergence (early warning): price at 30-min rolling high ({rolling_high:.2f}), "
                f"flow weakening to {flow_score:.0f}. Not yet a full reversal signal — treat as caution."
            )
            notes.append(f"Early warning: flow weakening at 30-min rolling high {rolling_high:.2f}")
            _record_divergence(ticker, "B", "BEARISH", price, rolling_high)

        elif at_rolling_low and flow_momentum in ("STRENGTHENING_BULLISH", "FLIPPED_BULLISH", "RECOVERING_BEARISH") and flow_score >= 52:
            divergence_type = "B"
            divergence_direction = "BULLISH"
            divergence_strength = "EARLY_WARNING"
            divergence_description = (
                f"B Bullish Divergence (early warning): price at 30-min rolling low ({rolling_low:.2f}), "
                f"flow recovering to {flow_score:.0f}. Early absorption signal."
            )
            notes.append(f"Early warning: flow recovering at 30-min rolling low {rolling_low:.2f}")
            _record_divergence(ticker, "B", "BULLISH", price, rolling_low)

    # ── Absorption detection (Fix 3: price-stalling confirmation) ──
    # Absorption requires THREE conditions to all be true simultaneously:
    # 1. Price is at a key gamma level (call wall, put wall, or zero-gamma)
    # 2. Options flow opposes the price direction (net premium against the wall)
    # 3. Sweep count elevated (institutional urgency defending the level)
    # 4. NEW: Price is stalling — last 3 bars' range < 40% of session avg range
    absorption = False
    absorption_description = None
    price_stalling = False

    # Compute price-stall condition from intraday bars
    if intraday_bars and len(intraday_bars) >= 4:
        recent_3 = intraday_bars[-3:]
        all_bars = intraday_bars
        def _bar_range(b: dict) -> float:
            return _safe_float(b.get("h"), 0.0) - _safe_float(b.get("l"), 0.0)
        recent_ranges = [_bar_range(b) for b in recent_3 if _bar_range(b) > 0]
        all_ranges = [_bar_range(b) for b in all_bars if _bar_range(b) > 0]
        if recent_ranges and all_ranges:
            avg_recent = sum(recent_ranges) / len(recent_ranges)
            avg_session = sum(all_ranges) / len(all_ranges)
            if avg_session > 0:
                price_stalling = avg_recent / avg_session <= 0.40
                if price_stalling:
                    notes.append(f"Price stalling: recent bar range {avg_recent:.2f} is {avg_recent/avg_session:.0%} of session avg {avg_session:.2f}.")

    if at_gamma_level and sweep_count >= 3 and price_stalling:
        if at_call_wall and net_premium < 0:
            absorption = True
            absorption_description = (
                f"Absorption confirmed at call wall {cw:.2f}: "
                f"institutions selling into {int(sweep_count)} sweeps at the ceiling "
                f"while price stalls. High probability rejection zone."
            )
            notes.append(f"Absorption CONFIRMED at call wall {cw:.2f} (price stalling + sweep pressure)")
        elif at_put_wall and net_premium > 0:
            absorption = True
            absorption_description = (
                f"Absorption confirmed at put wall {pw:.2f}: "
                f"institutions buying into selling pressure at the floor "
                f"while price stalls. High probability support zone."
            )
            notes.append(f"Absorption CONFIRMED at put wall {pw:.2f} (price stalling + institutional defense)")
    elif at_gamma_level and sweep_count >= 3 and not price_stalling:
        # Conditions partially met but stall not confirmed yet — note it
        notes.append(f"Partial absorption setup at gamma level — price not yet stalling.")

    # ── Sweep aggression classification ──
    if sweep_count >= 12:
        sweep_aggression = "VERY_HIGH"
    elif sweep_count >= 6:
        sweep_aggression = "HIGH"
    elif sweep_count >= 3:
        sweep_aggression = "MODERATE"
    elif sweep_count >= 1:
        sweep_aggression = "LOW"
    else:
        sweep_aggression = "NONE"

    # ── Block trade conviction ──
    large_premium = _safe_float(flow_snapshot.get("large_trade_premium"), 0.0)
    if large_premium >= 5_000_000:
        block_conviction = "HIGH"
    elif large_premium >= 1_000_000:
        block_conviction = "MODERATE"
    else:
        block_conviction = "LOW"

    # ── Composite flow intelligence score ──
    # Starts at the base flow score, adjustments for divergence, momentum, absorption
    intelligence_score = flow_score
    gate_override = None  # Can override the flow decision gate

    if divergence_type == "A_PLUS" and divergence_direction == "BEARISH":
        intelligence_score = min(25.0, intelligence_score)   # Force bearish
        gate_override = "BLOCKED_BEARISH_DIVERGENCE"
        notes.append("A+ bearish divergence → flow gate forced CAUTION/BLOCKED for calls")
    elif divergence_type == "A_PLUS" and divergence_direction == "BULLISH":
        intelligence_score = max(75.0, intelligence_score)   # Force bullish
        gate_override = "BLOCKED_BULLISH_DIVERGENCE"
        notes.append("A+ bullish divergence → flow gate forced CAUTION/BLOCKED for puts")
    elif divergence_type == "B" and divergence_direction == "BEARISH":
        intelligence_score = max(0.0, intelligence_score - 15)
        gate_override = "CAUTION_BEARISH_DIVERGENCE"
    elif divergence_type == "B" and divergence_direction == "BULLISH":
        intelligence_score = min(100.0, intelligence_score + 15)
        gate_override = "CAUTION_BULLISH_DIVERGENCE"

    if absorption:
        # Absorption at level shifts score toward the defense side
        if absorption_description and "selling" in absorption_description:
            intelligence_score = min(30.0, intelligence_score)
        else:
            intelligence_score = max(70.0, intelligence_score)

    # Flow momentum adjustment (smaller than divergence)
    if flow_momentum == "FLIPPED_BEARISH":
        intelligence_score = max(0.0, intelligence_score - 8)
    elif flow_momentum == "FLIPPED_BULLISH":
        intelligence_score = min(100.0, intelligence_score + 8)

    intelligence_score = round(max(0.0, min(100.0, intelligence_score)), 1)

    # ── Recommendation ──
    if intelligence_score >= 70:
        flow_recommendation = "WATCH_CALLS"
        vote = "BULLISH"
    elif intelligence_score <= 30:
        flow_recommendation = "WATCH_PUTS"
        vote = "BEARISH"
    else:
        flow_recommendation = "NEUTRAL"
        vote = "NEUTRAL"

    # A+ divergences are directional regardless of base score
    if divergence_type == "A_PLUS":
        flow_recommendation = f"WATCH_{'PUTS' if divergence_direction == 'BEARISH' else 'CALLS'}"
        vote = divergence_direction

    return {
        "intelligence_score": intelligence_score,
        "flow_score": round(flow_score, 1),
        "order_flow_score": round(order_score, 1),
        "net_premium": net_premium,
        "call_premium": call_premium,
        "put_premium": put_premium,
        "stock_price": round(price, 2) if price else None,
        "call_wall": cw or None,
        "put_wall": pw or None,
        "zero_gamma": zg or None,
        "gamma_regime": gamma_regime_label,
        "bias": bias,
        "sweep_count": int(sweep_count),
        "sweep_aggression": sweep_aggression,
        "block_conviction": block_conviction,
        "large_trade_premium": large_premium,
        # Flow momentum / flip
        "flow_flip": flow_flip,
        "flow_flip_direction": flow_flip_direction,
        "flow_momentum": flow_momentum,
        "flow_delta": round(flow_delta, 1),
        "prev_flow_score": round(prev_flow_score, 1) if prev_flow_score is not None else None,
        # Divergence (includes persistence/expiry tracking from cache)
        "divergence_type": divergence_type,
        "divergence_direction": divergence_direction,
        "divergence_strength": divergence_strength,
        "divergence_description": divergence_description,
        "divergence_age_seconds": divergence_age_seconds,
        "divergence_seconds_remaining": divergence_seconds_remaining,
        "divergence_downgraded": divergence_downgraded,
        "at_gamma_level": at_gamma_level,
        # Absorption (now requires price-stalling confirmation)
        "absorption": absorption,
        "absorption_description": absorption_description,
        "price_stalling": price_stalling,
        # Session levels used
        "session_high": round(session_high, 2) if session_high else None,
        "session_low": round(session_low, 2) if session_low else None,
        "rolling_high": round(rolling_high, 2) if rolling_high else None,
        "rolling_low": round(rolling_low, 2) if rolling_low else None,
        # Gate override
        "gate_override": gate_override,
        "flow_recommendation": flow_recommendation,
        "notes": notes,
        "engine": "INSTITUTIONAL_FLOW",
        "vote": vote,
        "vote_strength": round(abs(intelligence_score - 50) / 50, 2),
    }


# ===========================================================================
# ENGINE 4: MARKET STRUCTURE ENGINE
# VWAP, Session POC, Value Area, Overnight POC, Previous Day levels,
# Opening Range, Initial Balance — computed from intraday bars.
# ===========================================================================

def _compute_volume_profile(bars: List[dict], price_resolution: float = 0.5) -> Dict[float, float]:
    """
    Compute a simple volume-at-price profile from bar data.
    Uses bar midpoint as the representative price for each bar's volume.
    price_resolution buckets prices to the nearest 0.5 (or custom step).
    """
    profile: Dict[float, float] = {}
    for b in bars:
        h = _safe_float(b.get("h"))
        l = _safe_float(b.get("l"))
        v = _safe_float(b.get("v"))
        if h <= 0 or l <= 0 or v <= 0:
            continue
        mid = (h + l) / 2
        # Bucket to nearest price_resolution increment
        bucketed = round(round(mid / price_resolution) * price_resolution, 4)
        profile[bucketed] = profile.get(bucketed, 0.0) + v
    return profile


def _compute_poc_vah_val(profile: Dict[float, float]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Returns (POC, VAH, VAL) from a volume profile dict.
    POC = price level with the most volume.
    Value Area = levels containing ~70% of total volume centered on POC.
    """
    if not profile:
        return None, None, None
    total_volume = sum(profile.values())
    poc_price = max(profile.items(), key=lambda kv: kv[1])[0]
    # Value area: expand outward from POC until we cover 70% of volume
    target = total_volume * 0.70
    sorted_levels = sorted(profile.keys())
    poc_idx = sorted_levels.index(poc_price) if poc_price in sorted_levels else len(sorted_levels) // 2
    included_volume = profile.get(poc_price, 0.0)
    lo_idx = poc_idx
    hi_idx = poc_idx
    while included_volume < target and (lo_idx > 0 or hi_idx < len(sorted_levels) - 1):
        lo_vol = profile.get(sorted_levels[lo_idx - 1], 0.0) if lo_idx > 0 else 0.0
        hi_vol = profile.get(sorted_levels[hi_idx + 1], 0.0) if hi_idx < len(sorted_levels) - 1 else 0.0
        if lo_vol >= hi_vol and lo_idx > 0:
            lo_idx -= 1
            included_volume += lo_vol
        elif hi_idx < len(sorted_levels) - 1:
            hi_idx += 1
            included_volume += hi_vol
        else:
            break
    vah = sorted_levels[hi_idx]
    val = sorted_levels[lo_idx]
    return poc_price, vah, val


def engine_market_structure(
    intraday_bars: List[dict],
    daily_bars: List[dict],
    overnight_bars: Optional[List[dict]] = None,
) -> Dict[str, Any]:
    """
    Market Structure Engine.

    Computes from real bar data:
    - VWAP (current session)
    - Session POC, Value Area High/Low
    - Overnight POC
    - Previous Day High/Low/Close
    - Opening Range High/Low (first 30 minutes)
    - Initial Balance (first hour)
    - Current price position relative to all above

    All levels are used by the Story Engine and Risk Engine.
    """
    notes: List[str] = []
    now = _now_et()

    # ── VWAP (current session) ──
    vwap = None
    session_open_time = now.replace(hour=9, minute=30, second=0, microsecond=0)
    session_bars = [b for b in intraday_bars if b.get("t") and
                    dt.datetime.fromtimestamp(_safe_float(b["t"]) / 1000, tz=dt.timezone.utc)
                    .astimezone(EASTERN) >= session_open_time]
    if session_bars:
        cum_pv = 0.0
        cum_v = 0.0
        for b in session_bars:
            tp = (_safe_float(b.get("h")) + _safe_float(b.get("l")) + _safe_float(b.get("c"))) / 3
            v = _safe_float(b.get("v"))
            cum_pv += tp * v
            cum_v += v
        if cum_v > 0:
            vwap = round(cum_pv / cum_v, 2)
            notes.append(f"Session VWAP: {vwap}")

    # ── Session POC and Value Area ──
    session_poc = session_vah = session_val = None
    if session_bars:
        profile = _compute_volume_profile(session_bars)
        session_poc, session_vah, session_val = _compute_poc_vah_val(profile)
        if session_poc:
            session_poc = round(session_poc, 2)
            session_vah = round(session_vah, 2) if session_vah else None
            session_val = round(session_val, 2) if session_val else None
            notes.append(f"Session POC: {session_poc}, VAH: {session_vah}, VAL: {session_val}")

    # ── Opening Range (first 30 minutes: 9:30–10:00) ──
    or_high = or_low = None
    or_cutoff = now.replace(hour=10, minute=0, second=0, microsecond=0)
    or_bars = [b for b in session_bars if b.get("t") and
               dt.datetime.fromtimestamp(_safe_float(b["t"]) / 1000, tz=dt.timezone.utc)
               .astimezone(EASTERN) < or_cutoff]
    if or_bars:
        or_high = round(max(_safe_float(b.get("h")) for b in or_bars), 2)
        or_low = round(min(_safe_float(b.get("l")) for b in or_bars), 2)
        notes.append(f"Opening Range: {or_low} – {or_high}")

    # ── Initial Balance (first 60 minutes: 9:30–10:30) ──
    ib_high = ib_low = None
    ib_cutoff = now.replace(hour=10, minute=30, second=0, microsecond=0)
    ib_bars = [b for b in session_bars if b.get("t") and
               dt.datetime.fromtimestamp(_safe_float(b["t"]) / 1000, tz=dt.timezone.utc)
               .astimezone(EASTERN) < ib_cutoff]
    if ib_bars:
        ib_high = round(max(_safe_float(b.get("h")) for b in ib_bars), 2)
        ib_low = round(min(_safe_float(b.get("l")) for b in ib_bars), 2)
        notes.append(f"Initial Balance: {ib_low} – {ib_high}")

    # ── Previous Day High/Low/Close ──
    prev_high = prev_low = prev_close = None
    if len(daily_bars) >= 2:
        prev_bar = daily_bars[-2]
        prev_high = round(_safe_float(prev_bar.get("h")), 2)
        prev_low = round(_safe_float(prev_bar.get("l")), 2)
        prev_close = round(_safe_float(prev_bar.get("c")), 2)
        notes.append(f"Prev Day: H {prev_high} L {prev_low} C {prev_close}")

    # ── Overnight POC (if bars provided) ──
    overnight_poc = None
    if overnight_bars:
        on_profile = _compute_volume_profile(overnight_bars)
        on_poc, _, _ = _compute_poc_vah_val(on_profile)
        overnight_poc = round(on_poc, 2) if on_poc else None
        if overnight_poc:
            notes.append(f"Overnight POC: {overnight_poc}")

    # ── Session high/low for divergence engine ──
    session_high_val = None
    session_low_val = None
    if session_bars:
        h_vals = [_safe_float(b.get("h")) for b in session_bars if b.get("h")]
        l_vals = [_safe_float(b.get("l")) for b in session_bars if b.get("l")]
        if h_vals:
            session_high_val = round(max(h_vals), 2)
            session_low_val = round(min(l_vals), 2) if l_vals else None

    # ── Current price and its structural position ──
    current_price = None
    if session_bars:
        last_bar = session_bars[-1]
        current_price = round(_safe_float(last_bar.get("c")), 2)

    structure_position: List[str] = []
    structure_vote_score = 50.0  # 0–100, >50 = bullish structure

    if current_price and vwap:
        if current_price > vwap:
            structure_position.append(f"Above VWAP ({vwap})")
            structure_vote_score += 12
        else:
            structure_position.append(f"Below VWAP ({vwap})")
            structure_vote_score -= 10

    if current_price and session_poc:
        if current_price > session_poc:
            structure_position.append(f"Above Session POC ({session_poc})")
            structure_vote_score += 10
        elif current_price < session_poc:
            structure_position.append(f"Below Session POC ({session_poc}) — potential weakness")
            structure_vote_score -= 8

    if current_price and session_vah and session_val:
        if current_price > session_vah:
            structure_position.append(f"Above Value Area High ({session_vah}) — extended")
            structure_vote_score += 5
        elif current_price < session_val:
            structure_position.append(f"Below Value Area Low ({session_val}) — weakness")
            structure_vote_score -= 10

    if current_price and prev_high and prev_low:
        if current_price > prev_high:
            structure_position.append(f"Above Previous Day High ({prev_high}) — bullish breakout")
            structure_vote_score += 8
        elif current_price < prev_low:
            structure_position.append(f"Below Previous Day Low ({prev_low}) — bearish")
            structure_vote_score -= 8

    structure_vote_score = round(max(0.0, min(100.0, structure_vote_score)), 1)

    # data_available = True only when we have live session data to score from.
    # When False, the consensus engine redistributes this engine's weight
    # to engines that do have live data rather than counting a neutral 50.0.
    session_data_available = bool(session_bars and current_price)
    prev_data_available = bool(prev_close is not None)
    data_available = session_data_available  # live session required for a real vote

    # If no session bars, vote NEUTRAL but flag as unavailable so consensus skips it
    final_vote = "BULLISH" if structure_vote_score >= 62 else "BEARISH" if structure_vote_score <= 38 else "NEUTRAL"
    final_strength = round(abs(structure_vote_score - 50) / 50, 2) if session_data_available else 0.0

    return {
        "vwap": vwap,
        "session_poc": session_poc,
        "session_vah": session_vah,
        "session_val": session_val,
        "opening_range_high": or_high,
        "opening_range_low": or_low,
        "initial_balance_high": ib_high,
        "initial_balance_low": ib_low,
        "prev_day_high": prev_high,
        "prev_day_low": prev_low,
        "prev_day_close": prev_close,
        "overnight_poc": overnight_poc,
        "session_high": session_high_val,
        "session_low": session_low_val,
        "current_price": current_price,
        "structure_position": structure_position,
        "structure_score": structure_vote_score,
        "notes": notes,
        "engine": "MARKET_STRUCTURE",
        "data_available": data_available,
        "prev_data_available": prev_data_available,
        "session_bars_count": len(session_bars),
        "vote": final_vote if data_available else "NEUTRAL",
        "vote_strength": final_strength,
    }


# ===========================================================================
# ENGINE 5: TREND ENGINE
# Price-only analysis: EMA structure, ATR regime, compression/expansion.
# ===========================================================================

def engine_trend(
    ticker: str,
    daily_bars: List[dict],
    intraday_bars: List[dict],
) -> Dict[str, Any]:
    """
    Trend Engine — evaluates price structure alone (no flow, no gamma).

    Detects:
    - EMA slope and alignment (8/21/50/200)
    - ATR regime (expanding/contracting)
    - Price compression (low ATR relative to average)
    - Price expansion (breakout from compression)
    - Relative volume (momentum confirmation)
    """
    notes: List[str] = []

    if len(daily_bars) < 60:
        return {
            "trend_score": 50.0, "trend_direction": "NEUTRAL", "atr": None,
            "atr_regime": "UNKNOWN", "compression": False, "expansion": False,
            "ema8": None, "ema21": None, "ema50": None, "ema200": None,
            "rsi14": None, "rel_volume": None, "price": None,
            "notes": ["Insufficient daily bars for trend analysis."],
            "engine": "TREND", "vote": "NEUTRAL", "vote_strength": 0.0,
        }

    closes = [_safe_float(b.get("c")) for b in daily_bars]
    highs = [_safe_float(b.get("h")) for b in daily_bars]
    lows = [_safe_float(b.get("l")) for b in daily_bars]
    volumes = [_safe_float(b.get("v")) for b in daily_bars]
    price = closes[-1]

    # EMAs
    e8 = _ema(closes, 8)
    e21 = _ema(closes, 21)
    e50 = _ema(closes, 50)
    e200 = _ema(closes, 200) or e50

    # ATR (14-period)
    trs = []
    for i in range(1, len(daily_bars)):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = round(sum(trs[-14:]) / 14, 2) if len(trs) >= 14 else None
    atr_avg = round(sum(trs[-50:]) / 50, 2) if len(trs) >= 50 else atr

    # ATR regime
    compression = expansion = False
    atr_regime = "NORMAL"
    if atr and atr_avg:
        ratio = atr / atr_avg
        if ratio <= 0.65:
            compression = True
            atr_regime = "COMPRESSED"
            notes.append(f"ATR compression ({ratio:.2f}× average) — potential breakout building.")
        elif ratio >= 1.5:
            expansion = True
            atr_regime = "EXPANDING"
            notes.append(f"ATR expansion ({ratio:.2f}× average) — breakout momentum active.")

    # RSI
    rsi_val = None
    if len(closes) > 14:
        gains, losses = [], []
        for i in range(1, len(closes)):
            d = closes[i] - closes[i - 1]
            gains.append(max(d, 0))
            losses.append(abs(min(d, 0)))
        ag = sum(gains[-14:]) / 14
        al = sum(losses[-14:]) / 14
        rsi_val = round(100 - 100 / (1 + ag / al), 1) if al > 0 else 100.0

    # Relative volume
    rvol = None
    if len(volumes) >= 21:
        avg_vol = sum(volumes[-21:-1]) / 20
        rvol = round(volumes[-1] / avg_vol, 2) if avg_vol > 0 else 1.0

    # EMA alignment
    bullish_stack = bool(e8 and e21 and e50 and price and price > e8 > e21 > e50)
    bearish_stack = bool(e8 and e21 and e50 and price and price < e8 < e21 < e50)
    if bullish_stack: notes.append("Full EMA stack bullish (price > EMA8 > 21 > 50)")
    if bearish_stack: notes.append("Full EMA stack bearish (price < EMA8 < 21 < 50)")

    # EMA slope (3-period rate of change on EMA21)
    e21_prev = _ema(closes[:-3], 21)
    ema21_slope = "RISING" if (e21 and e21_prev and e21 > e21_prev) else "FALLING" if (e21 and e21_prev and e21 < e21_prev) else "FLAT"

    # Intraday trend confirmation
    intraday_confirms = False
    if intraday_bars and len(intraday_bars) >= 8:
        ic = [_safe_float(b.get("c")) for b in intraday_bars]
        ie8 = _ema(ic, 8)
        ie21 = _ema(ic, 21)
        if ie8 and ie21:
            if bullish_stack and ic[-1] > ie8 > ie21:
                intraday_confirms = True
                notes.append("Intraday EMA structure confirms daily bull trend")
            elif bearish_stack and ic[-1] < ie8 < ie21:
                intraday_confirms = True
                notes.append("Intraday EMA structure confirms daily bear trend")

    # Score
    trend_score = 50.0
    if bullish_stack:
        trend_score += 18
    elif bearish_stack:
        trend_score -= 18
    if ema21_slope == "RISING" and price > (e21 or 0): trend_score += 8
    elif ema21_slope == "FALLING" and price < (e21 or 9e9): trend_score -= 8
    if rsi_val:
        if 45 <= rsi_val <= 68 and bullish_stack: trend_score += 7
        elif 32 <= rsi_val <= 55 and bearish_stack: trend_score += 7
    if rvol and rvol >= 1.2: trend_score += 5
    if intraday_confirms: trend_score += 7
    if compression: trend_score -= 4  # Compression is neutral — potential for either direction

    trend_score = round(max(0.0, min(100.0, trend_score)), 1)

    # Five-state direction with lean bands:
    #   BULLISH       >= 65  — full EMA stack, RSI confirming, volume
    #   BULLISH_LEAN  55–64  — price above key EMAs but not full stack
    #   NEUTRAL       45–54  — mixed signals
    #   BEARISH_LEAN  35–44  — price below key EMAs but not confirmed reversal
    #   BEARISH        < 35  — full bearish stack confirmed
    if trend_score >= 65:
        direction = "BULLISH"
        vote = "BULLISH"
        vote_strength = round((trend_score - 65) / 35, 2)
    elif trend_score >= 55:
        direction = "BULLISH_LEAN"
        vote = "BULLISH"          # Votes bullish but with lower strength
        vote_strength = round((trend_score - 55) / 35 * 0.6, 2)
        notes.append(f"Bullish lean ({trend_score:.0f}/100) — partial alignment, not full stack.")
    elif trend_score >= 45:
        direction = "NEUTRAL"
        vote = "NEUTRAL"
        vote_strength = 0.0
    elif trend_score >= 35:
        direction = "BEARISH_LEAN"
        vote = "BEARISH"          # Votes bearish but with lower strength
        vote_strength = round((45 - trend_score) / 35 * 0.6, 2)
        notes.append(f"Bearish lean ({trend_score:.0f}/100) — partial weakness, not confirmed reversal.")
    else:
        direction = "BEARISH"
        vote = "BEARISH"
        vote_strength = round((40 - trend_score) / 40, 2)

    vote_strength = round(min(1.0, max(0.0, vote_strength)), 2)

    return {
        "trend_score": trend_score,
        "trend_direction": direction,
        "ema8": round(e8, 2) if e8 else None,
        "ema21": round(e21, 2) if e21 else None,
        "ema50": round(e50, 2) if e50 else None,
        "ema200": round(e200, 2) if e200 else None,
        "ema21_slope": ema21_slope,
        "price": round(price, 2),
        "atr": atr,
        "atr_regime": atr_regime,
        "compression": compression,
        "expansion": expansion,
        "rsi14": rsi_val,
        "rel_volume": rvol,
        "bullish_stack": bullish_stack,
        "bearish_stack": bearish_stack,
        "intraday_confirms": intraday_confirms,
        "notes": notes,
        "engine": "TREND",
        "vote": vote,
        "vote_strength": vote_strength,
        "data_available": True,
    }


# ===========================================================================
# ENGINE 6: EXECUTION ENGINE (Pine Confirmation)
# Evaluates the last Pine webhook signal. Unchanged from 3.5.1 in logic,
# but now returns a structured vote for the Consensus Engine.
# ===========================================================================

def engine_execution(
    signal: Optional[Dict[str, Any]],
    approved_side: str,
    session_is_tradeable: bool,
    signal_ttl_seconds: int = 360,
) -> Dict[str, Any]:
    """
    Execution Engine — evaluates the last Pine webhook trigger.

    Returns a vote (BULLISH / BEARISH / NEUTRAL / WAITING) and
    whether the trigger is fresh, matching, and within session hours.
    """
    if not signal:
        return {
            "has_signal": False, "signal_fresh": False, "signal_side": None,
            "signal_score": None, "signal_age_seconds": None,
            "signal_seconds_remaining": 0, "signal_matches_flow": False,
            "execution_state": "WAITING_FOR_PINE",
            "notes": ["No Pine trigger received yet."],
            "engine": "EXECUTION", "vote": "NEUTRAL", "vote_strength": 0.0,
        }

    sig_side = (signal.get("signal") or signal.get("side") or "NONE").upper()
    sig_score = _safe_float(signal.get("score"), 0.0)
    received_at = signal.get("received_at", "")
    age_seconds = 0
    try:
        ts = dt.datetime.fromisoformat(received_at)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        age_seconds = max(0, int((dt.datetime.now(dt.timezone.utc) - ts).total_seconds()))
    except Exception:
        pass

    fresh = age_seconds <= signal_ttl_seconds
    seconds_remaining = max(0, signal_ttl_seconds - age_seconds)
    matches_flow = fresh and sig_side == approved_side and sig_side in ("CALL", "PUT")
    within_session = session_is_tradeable

    if not fresh:
        state = "SIGNAL_EXPIRED"
    elif not within_session:
        state = "OUTSIDE_MARKET_HOURS"
    elif matches_flow:
        state = f"CONFIRMED_{sig_side}"
    elif sig_side in ("CALL", "PUT") and sig_side != approved_side:
        state = "SIGNAL_REJECTED_FLOW_MISMATCH"
    else:
        state = "SIGNAL_RECEIVED_FLOW_UNCLEAR"

    notes = []
    if fresh and matches_flow:
        notes.append(f"Pine confirmed {sig_side} with {seconds_remaining}s remaining (score {sig_score:g}).")
    elif fresh and not matches_flow and sig_side in ("CALL", "PUT"):
        notes.append(f"Pine fired {sig_side} but flow approves {approved_side} — signal rejected.")
    elif not fresh and signal:
        notes.append("Last Pine signal has expired. Waiting for fresh trigger.")

    # Vote: only BULLISH/BEARISH if fresh + matches flow + within session
    if state.startswith("CONFIRMED_"):
        vote = "BULLISH" if sig_side == "CALL" else "BEARISH"
        vote_strength = min(1.0, sig_score / 100) if sig_score > 0 else 0.7
    else:
        vote = "NEUTRAL"
        vote_strength = 0.0

    return {
        "has_signal": True,
        "signal_fresh": fresh,
        "signal_side": sig_side,
        "signal_score": sig_score,
        "signal_age_seconds": age_seconds,
        "signal_seconds_remaining": seconds_remaining,
        "signal_matches_flow": matches_flow,
        "execution_state": state,
        "notes": notes,
        "engine": "EXECUTION",
        "vote": vote,
        "vote_strength": round(vote_strength, 2),
    }


# ===========================================================================
# ENGINE 7: CONSENSUS ENGINE
# Tallies engine votes with adaptive weights.
# Produces ENTER / WATCH / WAIT / NO_TRADE output with clear reasoning.
# ===========================================================================

def engine_consensus(
    market_regime: Dict[str, Any],
    gamma_regime: Dict[str, Any],
    flow: Dict[str, Any],
    structure: Dict[str, Any],
    trend: Dict[str, Any],
    execution: Dict[str, Any],
    gamma_regime_label: str,
    target_side: Optional[str] = None,  # If set, score only for this side
    session_state: str = "MARKET_OPEN",
) -> Dict[str, Any]:
    """
    Institutional Consensus Engine — APEX 6.2 conviction-weighted version.

    Flow Intelligence is now a first-class voting engine (highest weight in
    NEGATIVE_GAMMA regimes). Engines with unavailable session data
    (Structure, Execution) have their weights redistributed automatically
    via get_adaptive_weights(session_state).

    Conviction score bands (0–100):
      ≥ 75  → ENTER
      55–74 → WATCH
      35–54 → WAIT
      < 35  → NO_TRADE
    """
    weights = get_adaptive_weights(gamma_regime_label, session_state=session_state)

    # flow_intelligence is now a first-class voter; data_available gates skip
    engines = {
        "market_regime":    market_regime,
        "gamma_regime":     gamma_regime,
        "flow_intelligence":flow,
        "structure":        structure,
        "trend":            trend,
        "execution":        execution,
    }

    # Build vote table — weighted_bull/bear accumulate weight × strength per engine.
    # Engines that declare data_available=False are skipped; their weight is
    # redistributed proportionally across the remaining engines so the total
    # always sums to 1.0.
    vote_table: List[Dict[str, Any]] = []
    weighted_bull = 0.0
    weighted_bear = 0.0
    total_weight = 0.0
    skipped_weight = 0.0

    for name, engine_data in engines.items():
        data_available = engine_data.get("data_available", True)
        if not data_available:
            skipped_weight += weights.get(name, 0.0)

    for name, engine_data in engines.items():
        data_available = engine_data.get("data_available", True)
        weight = weights.get(name, 0.0)
        engine_label = engine_data.get("engine", name.replace("_", " ").title())

        if not data_available:
            vote_table.append({
                "engine": engine_label,
                "vote": "UNAVAILABLE",
                "strength": 0.0,
                "weight": 0.0,
                "conviction_contribution": 0.0,
                "emoji": "⏳",
                "skipped": True,
            })
            continue

        # Boost weight of active engines to absorb skipped weight
        active_base = 1.0 - skipped_weight
        effective_weight = (weight / active_base * 1.0) if active_base > 0 else weight

        vote = (engine_data.get("vote") or "NEUTRAL").upper()
        strength = _safe_float(engine_data.get("vote_strength"), 0.0)

        # Conviction contribution = effective_weight × strength
        conviction_contribution = effective_weight * strength

        if vote == "BULLISH":
            weighted_bull += conviction_contribution
            vote_emoji = "✅"
        elif vote == "BEARISH":
            weighted_bear += conviction_contribution
            vote_emoji = "❌"
        else:
            vote_emoji = "—"
            conviction_contribution = 0.0

        total_weight += effective_weight
        vote_table.append({
            "engine": engine_label,
            "vote": vote,
            "strength": round(strength, 2),
            "weight": round(effective_weight, 3),
            "conviction_contribution": round(conviction_contribution, 3),
            "emoji": vote_emoji,
            "skipped": False,
        })

    # Normalize to 0–100 conviction scores
    # Max possible weighted_bull = sum of all weights × 1.0 = total_weight
    if total_weight > 0:
        bull_conviction = round(weighted_bull / total_weight * 100, 1)
        bear_conviction = round(weighted_bear / total_weight * 100, 1)
    else:
        bull_conviction = bear_conviction = 0.0

    # Simple vote counts for the "N of 6 agree" display (unchanged from 4.5)
    n_bull = sum(1 for v in vote_table if v["vote"] == "BULLISH")
    n_bear = sum(1 for v in vote_table if v["vote"] == "BEARISH")
    n_neutral = sum(1 for v in vote_table if v["vote"] == "NEUTRAL")
    n_total = len(vote_table)

    # Determine leading direction by conviction score
    if bull_conviction > bear_conviction:
        leading_direction = "BULLISH"
        leading_conviction = bull_conviction
    elif bear_conviction > bull_conviction:
        leading_direction = "BEARISH"
        leading_conviction = bear_conviction
    else:
        leading_direction = "NEUTRAL"
        leading_conviction = 0.0

    # Gate override from flow divergence (bypasses conviction thresholds)
    gate_override = flow.get("gate_override")

    # ── Recommendation via conviction bands ──
    if gate_override and "BEARISH" in gate_override:
        consensus_direction = "BEARISH"
        if "BLOCKED" in gate_override:
            recommendation = "NO_TRADE_DIVERGENCE"
            consensus_label = "BLOCKED — A+ Bearish Divergence"
            action = "Do not enter calls. A+ bearish divergence detected at session high."
        else:
            recommendation = "CAUTION"
            consensus_label = "CAUTION — Bearish Divergence Warning"
            action = "Reduce size. Bearish divergence — wait for cleaner structure."

    elif gate_override and "BULLISH" in gate_override:
        consensus_direction = "BULLISH"
        if "BLOCKED" in gate_override:
            recommendation = "NO_TRADE_DIVERGENCE"
            consensus_label = "BLOCKED — A+ Bullish Divergence"
            action = "Do not enter puts. A+ bullish divergence detected at session low."
        else:
            recommendation = "CAUTION"
            consensus_label = "CAUTION — Bullish Divergence Warning"
            action = "Reduce size. Bullish divergence — potential reversal building."

    elif leading_conviction >= 75:
        consensus_direction = leading_direction
        side = "CALL" if leading_direction == "BULLISH" else "PUT"
        recommendation = f"ENTER_{side}"
        consensus_label = (
            f"ENTER {side} — {n_bull if leading_direction == 'BULLISH' else n_bear} of {n_total} agree "
            f"({leading_conviction:.0f}% conviction)"
        )
        action = f"Strong conviction for {side.lower()}s ({leading_conviction:.0f}/100). Enter if Pine confirms."

    elif leading_conviction >= 55:
        consensus_direction = leading_direction
        side = "CALLS" if leading_direction == "BULLISH" else "PUTS"
        recommendation = f"WATCH_{side.rstrip('S')}"
        consensus_label = (
            f"WATCH {side} — {n_bull if leading_direction == 'BULLISH' else n_bear} of {n_total} agree "
            f"({leading_conviction:.0f}% conviction)"
        )
        action = f"Good conviction for {side.lower()} ({leading_conviction:.0f}/100). Wait for execution confirmation."

    elif leading_conviction >= 35:
        consensus_direction = leading_direction
        recommendation = "WAIT"
        consensus_label = (
            f"WAIT — Low conviction ({leading_conviction:.0f}/100), "
            f"{n_bull} bull / {n_bear} bear / {n_neutral} neutral"
        )
        action = "Insufficient conviction. Sit out until engines align more strongly."

    else:
        consensus_direction = "NEUTRAL"
        recommendation = "NO_TRADE"
        consensus_label = f"NO TRADE — No conviction ({bull_conviction:.0f}% bull / {bear_conviction:.0f}% bear)"
        action = "No institutional conviction. Do not trade."

    # Override to ENTER_NOW if execution engine confirmed + conviction already at WATCH+
    if (execution.get("execution_state", "").startswith("CONFIRMED_") and
            recommendation in ("WATCH_CALL", "WATCH_PUT", "ENTER_CALL", "ENTER_PUT")):
        side = execution.get("signal_side", "")
        if (side == "CALL" and consensus_direction == "BULLISH") or (side == "PUT" and consensus_direction == "BEARISH"):
            recommendation = f"ENTER_{side}_NOW"
            consensus_label = consensus_label.replace("WATCH", "ENTER")
            action = f"Pine confirmed {side}. All conditions met — ENTER NOW."

    return {
        "recommendation": recommendation,
        "consensus_label": consensus_label,
        "action": action,
        "consensus_direction": consensus_direction,
        "vote_table": vote_table,
        # Conviction scores (0–100, the primary decision metric in 5.0)
        "bull_conviction": bull_conviction,
        "bear_conviction": bear_conviction,
        "leading_conviction": round(leading_conviction, 1),
        # Simple vote counts (for the "N of 6 agree" display)
        "n_bullish": n_bull,
        "n_bearish": n_bear,
        "n_neutral": n_neutral,
        "n_engines": n_total,
        # Legacy fields kept for backward compatibility
        "bull_score": bull_conviction,
        "bear_score": bear_conviction,
        "gate_override": gate_override,
        "gamma_regime_label": gamma_regime_label,
        "weights_used": gamma_regime_label,
        "engine": "CONSENSUS",
    }


# ===========================================================================
# ENGINE 8: RISK ENGINE
# Entry zone, stop, targets — adapted to gamma regime behavioral rules.
# ===========================================================================

def engine_risk(
    ticker: str,
    consensus: Dict[str, Any],
    structure: Dict[str, Any],
    gamma_regime: Dict[str, Any],
    market_regime: Dict[str, Any],
    flow: Dict[str, Any],
    signal: Optional[Dict[str, Any]] = None,
    default_risk_points: float = 6.0,
    target1_r_mult: float = 1.2,
    target2_r_mult: float = 2.0,
    strike_step_spx: int = 5,
    strike_step_etf: int = 1,
    signal_ttl_seconds: int = 360,
) -> Dict[str, Any]:
    """
    Risk Engine — produces entry zone, stop, and targets.

    Adjusts everything based on:
    - Gamma regime (positive = tighter targets/stops, negative = wider)
    - Market regime (high vol = reduced size, trend = wider targets)
    - Structure levels (VWAP, POC, walls as stop/target anchors)
    """
    direction = consensus.get("consensus_direction") or "NEUTRAL"
    approved_side = "CALL" if direction == "BULLISH" else "PUT" if direction == "BEARISH" else "NONE"

    # Derive price from structure, flow, or signal
    price = 0.0
    for src in [structure, flow, signal or {}]:
        for key in ("current_price", "stock_price", "underlying_price", "close", "zero_gamma"):
            v = _safe_float(src.get(key) if isinstance(src, dict) else 0.0, 0.0)
            if v > 0:
                price = v
                break
        if price > 0:
            break

    if price <= 0:
        return {
            "approved_side": approved_side, "price": None,
            "entry_zone": None, "stop": None, "target1": None, "target2": None,
            "contract_hint": "Waiting for price data", "error": "No price available",
            "engine": "RISK",
        }

    # Adapt risk points and multipliers by gamma regime
    trade_rules = gamma_regime.get("trade_rules", {})
    t_mult = _safe_float(trade_rules.get("target_multiplier"), 1.0)
    s_mult = _safe_float(trade_rules.get("stop_multiplier"), 1.0)

    # Further adapt by market regime
    beh = market_regime.get("behavioral_rules", {})
    t_mult *= _safe_float(beh.get("target_multiplier"), 1.0)
    s_mult *= _safe_float(beh.get("stop_multiplier"), 1.0)

    # SPX vs ETF risk adjustment
    is_spx = "SPX" in ticker.upper()
    risk_pts = default_risk_points if is_spx else max(0.5, default_risk_points / 10.0)

    # Use zero-gamma as a natural stop reference if nearby
    zg = _safe_float(flow.get("zero_gamma") if isinstance(flow, dict) else 0.0, 0.0)
    if zg > 0 and price > 0:
        zg_dist = abs(price - zg)
        risk_pts = max(risk_pts, min(zg_dist * 0.55, risk_pts * 1.8))

    # Apply multipliers
    eff_risk = risk_pts * s_mult
    eff_t1_dist = risk_pts * target1_r_mult * t_mult
    eff_t2_dist = risk_pts * target2_r_mult * t_mult

    # Compute directional levels
    if approved_side == "CALL":
        entry_low = price - risk_pts * 0.18
        entry_high = price + risk_pts * 0.18
        stop = price - eff_risk
        target1 = price + eff_t1_dist
        target2 = price + eff_t2_dist
        # Anchor stop to structure if available
        vwap = _safe_float(structure.get("vwap") if isinstance(structure, dict) else 0.0, 0.0)
        poc = _safe_float(structure.get("session_poc") if isinstance(structure, dict) else 0.0, 0.0)
        if poc > 0 and poc < price and poc > stop:
            stop = poc - risk_pts * 0.15  # Stop just below POC
        elif vwap > 0 and vwap < price and vwap > stop:
            stop = vwap - risk_pts * 0.20
    elif approved_side == "PUT":
        entry_low = price - risk_pts * 0.18
        entry_high = price + risk_pts * 0.18
        stop = price + eff_risk
        target1 = price - eff_t1_dist
        target2 = price - eff_t2_dist
        vwap = _safe_float(structure.get("vwap") if isinstance(structure, dict) else 0.0, 0.0)
        poc = _safe_float(structure.get("session_poc") if isinstance(structure, dict) else 0.0, 0.0)
        if poc > 0 and poc > price and poc < stop:
            stop = poc + risk_pts * 0.15
        elif vwap > 0 and vwap > price and vwap < stop:
            stop = vwap + risk_pts * 0.20
    else:
        return {
            "approved_side": "NONE", "price": round(price, 2),
            "entry_zone": None, "stop": None, "target1": None, "target2": None,
            "contract_hint": "No directional consensus", "rr_to_t1": None, "rr_to_t2": None,
            "engine": "RISK",
        }

    # Round to reasonable precision
    r = lambda x: round(x, 2)

    # Strike selection
    step = strike_step_spx if is_spx else strike_step_etf
    if approved_side == "CALL":
        strike = float(((int(price // step) + 1) * step))
    else:
        strike = float((int(price // step) * step))
    suffix = "C" if approved_side == "CALL" else "P"
    contract_hint = f"{ticker} 0DTE {int(strike) if strike.is_integer() else strike:g}{suffix}"

    # R:R
    rr_t1 = round(eff_t1_dist / eff_risk, 2) if eff_risk > 0 else None
    rr_t2 = round(eff_t2_dist / eff_risk, 2) if eff_risk > 0 else None

    # Exit rules (gamma-regime adapted)
    gamma_label = gamma_regime.get("regime_label", "MIXED_GAMMA")
    if gamma_label == "NEGATIVE_GAMMA":
        exit_rules = [
            "Allow wider runners — negative gamma amplifies momentum.",
            f"Take first partials at Target 1 ({r(target1)}).",
            "Hold runner to Target 2 while flow/trend stay aligned.",
            "Exit immediately if flow flips or A+ divergence appears.",
        ]
    else:
        exit_rules = [
            f"Take partials into Target 1 ({r(target1)}) — mean reversion more likely.",
            "Move stop to breakeven after Target 1 reached.",
            "Exit if price returns to VWAP or Session POC.",
            "Do not hold through reversal in positive gamma environment.",
        ]

    # Signal countdown
    seconds_remaining = 0
    if signal:
        try:
            ts = dt.datetime.fromisoformat(signal.get("received_at", ""))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=dt.timezone.utc)
            age = int((dt.datetime.now(dt.timezone.utc) - ts).total_seconds())
            seconds_remaining = max(0, signal_ttl_seconds - age)
        except Exception:
            pass

    return {
        "approved_side": approved_side,
        "price": r(price),
        "entry_zone": f"{r(entry_low)} – {r(entry_high)}",
        "entry_low": r(entry_low),
        "entry_high": r(entry_high),
        "stop": r(stop),
        "target1": r(target1),
        "target2": r(target2),
        "rr_to_t1": rr_t1,
        "rr_to_t2": rr_t2,
        "risk_points": round(eff_risk, 2),
        "target1_distance": round(eff_t1_dist, 2),
        "target2_distance": round(eff_t2_dist, 2),
        "contract_hint": contract_hint,
        "recommended_strike": strike,
        "exit_rules": exit_rules,
        "gamma_adjustments": {
            "target_multiplier": round(t_mult, 2),
            "stop_multiplier": round(s_mult, 2),
        },
        "signal_seconds_remaining": seconds_remaining,
        "walls": {
            "call_wall": flow.get("call_wall") if isinstance(flow, dict) else None,
            "put_wall": flow.get("put_wall") if isinstance(flow, dict) else None,
            "zero_gamma": flow.get("zero_gamma") if isinstance(flow, dict) else None,
        },
        "engine": "RISK",
    }


# ===========================================================================
# ENGINE 9: STORY ENGINE
# Full prose narrative from all eight upstream engines.
# This is the feature that makes APEX an institutional decision support
# system rather than a signal generator.
# ===========================================================================

def engine_story(
    ticker: str,
    market_regime: Dict[str, Any],
    gamma_regime: Dict[str, Any],
    flow: Dict[str, Any],
    structure: Dict[str, Any],
    trend: Dict[str, Any],
    execution: Dict[str, Any],
    consensus: Dict[str, Any],
    risk: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Story Engine — synthesizes all eight engines into:
    1. A timestamped chapter timeline (for dashboard display)
    2. A full prose narrative paragraph (the institutional narrative)
    3. A one-sentence executive summary

    The prose is written from the perspective of an institutional trader
    explaining to a junior trader what is happening and why.
    """
    now = _now_et()
    chapters: List[Dict[str, Any]] = []
    prose_lines: List[str] = []

    # ── Chapter 1: Market operating environment ──
    regime = market_regime.get("regime", "NEUTRAL")
    regime_desc = market_regime.get("regime_description", "")
    vix = market_regime.get("vix", 18.0)
    regime_color = ("#0ca30c" if regime in ("TREND_DAY", "RISK_ON") else
                    "#e34948" if regime in ("HIGH_VOLATILITY", "DEFENSIVE") else "#2a78d6")
    chapters.append({
        "time": now.strftime("%H:%M"),
        "chapter": "Market regime",
        "text": f"{regime.replace('_', ' ')}: {regime_desc} VIX at {vix:.1f}.",
        "color": regime_color,
        "significance": 1.0,
    })
    prose_lines.append(f"The market is operating in a {regime.replace('_', ' ').lower()} environment. {regime_desc}")

    # ── Chapter 2: Gamma regime and dealer behavior ──
    g_label = gamma_regime.get("regime_display", "Mixed Gamma")
    g_vol = gamma_regime.get("expected_volatility", "MEDIUM")
    g_desc = gamma_regime.get("vol_description", "")
    g_color = "#2a78d6" if "POSITIVE" in gamma_regime.get("regime_label", "") else "#e34948" if "NEGATIVE" in gamma_regime.get("regime_label", "") else "#fab219"
    flip_risk = gamma_regime.get("flip_risk", False)
    g_text = f"{g_label}: {g_desc}"
    if flip_risk:
        g_text += f" Price is near the zero-gamma flip point — regime may shift."
    chapters.append({
        "time": now.strftime("%H:%M"),
        "chapter": "Gamma regime",
        "text": g_text,
        "color": g_color,
        "significance": 1.5,
    })
    prose_lines.append(g_text)

    # ── Chapter 3: Institutional flow narrative ──
    bias = flow.get("bias", "MIXED")
    net_premium = _safe_float(flow.get("net_premium"), 0.0)
    flow_momentum = flow.get("flow_momentum", "STABLE")
    sweep_count = _safe_float(flow.get("sweep_count"), 0)
    intelligence_score = _safe_float(flow.get("intelligence_score"), 50.0)
    sweep_aggression = flow.get("sweep_aggression", "NONE")
    flow_flip = flow.get("flow_flip", False)

    # Build flow prose
    if abs(net_premium) > 1_000_000:
        prem_str = f"+${net_premium/1e6:.1f}M net premium" if net_premium > 0 else f"-${abs(net_premium)/1e6:.1f}M net premium"
        flow_prose = f"Institutions are {'accumulating' if net_premium > 0 else 'distributing'} aggressively on {ticker} ({prem_str})."
    elif abs(net_premium) > 0:
        flow_prose = f"Options flow bias is {bias.lower()} on {ticker}."
    else:
        flow_prose = f"Options flow is mixed or unavailable for {ticker}."

    if sweep_aggression in ("HIGH", "VERY_HIGH"):
        flow_prose += f" {int(sweep_count)} sweeps detected — institutional urgency is {sweep_aggression.lower().replace('_', ' ')}."
    if flow_flip:
        flip_dir = flow.get("flow_flip_direction", "")
        flow_prose += f" Flow just flipped {flip_dir.lower()} — a significant momentum shift."

    flow_color = "#0ca30c" if bias == "BULLISH" else "#e34948" if bias == "BEARISH" else "#fab219"
    chapters.append({
        "time": now.strftime("%H:%M"),
        "chapter": "Institutional flow",
        "text": flow_prose,
        "color": flow_color,
        "significance": 2.5,
    })
    prose_lines.append(flow_prose)

    # ── Chapter 4: Flow divergence (if detected) ──
    divergence_type = flow.get("divergence_type")
    divergence_desc = flow.get("divergence_description")
    absorption = flow.get("absorption", False)
    absorption_desc = flow.get("absorption_description")

    if divergence_type and divergence_desc:
        div_color = "#e34948" if flow.get("divergence_direction") == "BEARISH" else "#0ca30c"
        strength = flow.get("divergence_strength", "")
        div_label = f"{'A+' if divergence_type == 'A_PLUS' else 'B'} divergence — {'strong signal' if strength == 'STRONG' else 'early warning'}"
        chapters.append({
            "time": now.strftime("%H:%M"),
            "chapter": div_label,
            "text": divergence_desc,
            "color": div_color,
            "significance": 3.5 if divergence_type == "A_PLUS" else 2.0,
        })
        prose_lines.append(divergence_desc)

    if absorption and absorption_desc:
        chapters.append({
            "time": now.strftime("%H:%M"),
            "chapter": "Absorption",
            "text": absorption_desc,
            "color": "#fab219",
            "significance": 3.0,
        })
        prose_lines.append(absorption_desc)

    # ── Chapter 5: Market structure ──
    vwap = structure.get("vwap")
    poc = structure.get("session_poc")
    struct_pos = structure.get("structure_position", [])
    price = structure.get("current_price")
    if struct_pos:
        struct_text = f"Price ({price}) is " + "; ".join(struct_pos[:3]) + "."
        chapters.append({
            "time": now.strftime("%H:%M"),
            "chapter": "Market structure",
            "text": struct_text,
            "color": "#2a78d6",
            "significance": 2.0,
        })
        prose_lines.append(struct_text)

    # ── Chapter 6: Trend ──
    trend_dir = trend.get("trend_direction", "NEUTRAL")
    trend_score = trend.get("trend_score", 50.0)
    atr_regime = trend.get("atr_regime", "NORMAL")
    ema21_slope = trend.get("ema21_slope", "FLAT")
    trend_text = f"Daily trend is {trend_dir.lower()} (score {trend_score:.0f}/100). EMA21 is {ema21_slope.lower()}."
    if atr_regime == "COMPRESSED":
        trend_text += " ATR is compressed — a breakout may be building."
    elif atr_regime == "EXPANDING":
        trend_text += " ATR is expanding — momentum is active."
    trend_color = "#0ca30c" if trend_dir == "BULLISH" else "#e34948" if trend_dir == "BEARISH" else "#fab219"
    chapters.append({
        "time": now.strftime("%H:%M"),
        "chapter": "Trend",
        "text": trend_text,
        "color": trend_color,
        "significance": 1.8,
    })
    prose_lines.append(trend_text)

    # ── Chapter 7: Pine execution ──
    exec_state = execution.get("execution_state", "WAITING_FOR_PINE")
    exec_notes = execution.get("notes", [])
    pine_text = exec_notes[0] if exec_notes else f"Pine state: {exec_state.replace('_', ' ')}."
    pine_color = ("#0ca30c" if "CONFIRMED" in exec_state else
                  "#e34948" if "REJECTED" in exec_state else "#fab219")
    chapters.append({
        "time": now.strftime("%H:%M"),
        "chapter": "Pine execution",
        "text": pine_text,
        "color": pine_color,
        "significance": 3.0,
    })
    prose_lines.append(pine_text)

    # ── Chapter 8: Consensus verdict ──
    n_bull = consensus.get("n_bullish", 0)
    n_bear = consensus.get("n_bearish", 0)
    n_total = consensus.get("n_engines", 6)
    recommendation = consensus.get("recommendation", "NO_TRADE")
    consensus_action = consensus.get("action", "")
    consensus_label = consensus.get("consensus_label", "")

    verdict_text = f"{consensus_label}. {consensus_action}"
    verdict_color = ("#0ca30c" if "ENTER" in recommendation and "NO_TRADE" not in recommendation
                     else "#e34948" if "NO_TRADE" in recommendation or "BLOCKED" in recommendation
                     else "#fab219")
    chapters.append({
        "time": now.strftime("%H:%M"),
        "chapter": "Institutional verdict",
        "text": verdict_text,
        "color": verdict_color,
        "significance": 4.0,
    })
    prose_lines.append(verdict_text)

    # ── Sort chapters by significance (narrative builds toward verdict) ──
    chapters.sort(key=lambda c: c["significance"])

    # ── Full prose narrative ──
    full_narrative = " ".join(prose_lines)

    # ── Executive summary (one sentence) ──
    contract = risk.get("contract_hint", "")
    if "ENTER" in recommendation and contract:
        executive_summary = (
            f"{consensus_label} — {contract} setup active: "
            f"entry {risk.get('entry_zone')}, stop {risk.get('stop')}, "
            f"targets {risk.get('target1')} / {risk.get('target2')}."
        )
    elif divergence_type == "A_PLUS":
        executive_summary = (
            f"A+ {flow.get('divergence_direction', '')} divergence detected at "
            f"{'session high' if 'BEARISH' in str(flow.get('divergence_direction')) else 'session low'} — "
            f"{consensus.get('action', 'Do not trade against this signal.')}."
        )
    elif "WATCH" in recommendation:
        side = "CALLS" if "CALL" in recommendation else "PUTS"
        executive_summary = (
            f"{n_bull if 'CALL' in recommendation else n_bear} of {n_total} engines favor {side.lower()} — "
            f"wait for Pine confirmation before entry."
        )
    else:
        executive_summary = (
            f"No institutional consensus ({n_bull} bull / {n_bear} bear / "
            f"{consensus.get('n_neutral', 0)} neutral). Sit out until alignment improves."
        )

    return {
        "ticker": ticker,
        "chapters": chapters,
        "full_narrative": full_narrative,
        "executive_summary": executive_summary,
        "chapter_count": len(chapters),
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S ET"),
        "generated_at_iso": dt.datetime.now(dt.timezone.utc).isoformat(),
        "engine": "STORY",
    }


# ===========================================================================
# INSTITUTIONAL CONFIDENCE INDEX (ICI)
# APEX 5.0 — the single primary number on the dashboard.
# Synthesizes consensus conviction, signal freshness, gamma regime stability,
# and flow momentum into one 0–100 score that decays in real time.
# ===========================================================================

def compute_institutional_confidence_index(
    consensus: Dict[str, Any],
    execution: Dict[str, Any],
    gamma_regime: Dict[str, Any],
    flow: Dict[str, Any],
    signal_ttl_seconds: int = 360,
    session_state: str = "MARKET_OPEN",
) -> Dict[str, Any]:
    """
    Institutional Confidence Index (ICI) — APEX 5.0.

    Component weights:
      50% — Consensus conviction score (bull or bear, whichever leads)
      20% — Signal freshness and TTL remaining
      15% — Gamma regime stability (positive gamma = more stable = higher score)
      15% — Flow momentum quality

    The raw ICI decays in real time between refreshes using an exponential
    curve tied to signal age, so the number reflects the current moment
    rather than the last snapshot.

    Color bands:
      ≥ 75 → GREEN  (high confidence — conditions for entry)
      50–74 → AMBER  (moderate — watch, wait for confirmation)
      < 50  → RED    (low — sit out)
    """
    # ── Component 1: Consensus conviction (50%) ──
    leading_conviction = _safe_float(consensus.get("leading_conviction"), 0.0)
    # Normalize from 0–100 conviction scale
    conviction_component = leading_conviction  # already 0–100

    # ── Component 2: Signal freshness (20%) ──
    sig_seconds_remaining = _safe_float(execution.get("signal_seconds_remaining"), 0.0)
    signal_fresh = execution.get("signal_fresh", False)
    signal_matches = execution.get("signal_matches_flow", False)
    if signal_fresh and signal_matches and sig_seconds_remaining > 0:
        freshness_pct = sig_seconds_remaining / max(signal_ttl_seconds, 1)
        # Peak freshness: 100 when just fired, decays to 0 at expiry
        # Non-linear: 1 - (elapsed_ratio ^ 0.6), same curve as confidence_decay
        elapsed_ratio = 1.0 - freshness_pct
        freshness_component = max(0.0, (1.0 - elapsed_ratio ** 0.6)) * 100
    elif signal_fresh and not signal_matches:
        freshness_component = 20.0  # Signal present but opposing — reduce
    else:
        freshness_component = 0.0   # No signal or expired — contributes nothing

    # ── Component 3: Gamma regime stability (15%) ──
    gamma_label = gamma_regime.get("regime_label", "MIXED_GAMMA")
    gex_score = _safe_float(gamma_regime.get("gex_score"), 50.0)
    flip_risk = gamma_regime.get("flip_risk", False)
    if gamma_label == "POSITIVE_GAMMA" and not flip_risk:
        gamma_component = 80.0  # Stable positive gamma — lower vol, more predictable
    elif gamma_label == "NEGATIVE_GAMMA" and not flip_risk:
        gamma_component = 55.0  # Negative gamma — higher vol, but tradeable with conviction
    elif flip_risk:
        gamma_component = 25.0  # Near flip point — regime unstable
    else:
        gamma_component = 50.0  # Mixed — neutral contribution

    # ── Component 4: Flow momentum quality (15%) ──
    flow_momentum = flow.get("flow_momentum", "STABLE")
    intelligence_score = _safe_float(flow.get("intelligence_score"), 50.0)
    flow_flip = flow.get("flow_flip", False)
    divergence_type = flow.get("divergence_type")
    absorption = flow.get("absorption", False)

    if divergence_type == "A_PLUS":
        # A+ divergence is high-quality information regardless of direction
        momentum_component = 90.0
    elif absorption:
        momentum_component = 80.0  # Confirmed absorption = high quality setup
    elif flow_momentum in ("FLIPPED_BULLISH", "FLIPPED_BEARISH"):
        momentum_component = 75.0  # Fresh flip = strong momentum signal
    elif flow_momentum in ("STRENGTHENING_BULLISH", "ACCELERATING_BEARISH"):
        momentum_component = 65.0
    elif flow_momentum == "STABLE" and abs(intelligence_score - 50) >= 20:
        momentum_component = 55.0  # Stable but directional
    elif flow_momentum in ("WEAKENING_BULLISH", "RECOVERING_BEARISH"):
        momentum_component = 30.0  # Flow weakening = lower quality
    else:
        momentum_component = 45.0  # Mixed

    # ── Composite ICI — session-aware weights ──
    ici_w = get_ici_weights(session_state)
    raw_ici = (
        conviction_component * ici_w["conviction"] +
        freshness_component  * ici_w["freshness"] +
        gamma_component      * ici_w["gamma"] +
        momentum_component   * ici_w["momentum"]
    )
    ici = round(max(0.0, min(100.0, raw_ici)), 1)

    # ── Color band and status ──
    if ici >= 75:
        ici_color = "GREEN"
        ici_label = "HIGH"
        ici_status = _build_ici_status(consensus, execution, flow, "high")
    elif ici >= 50:
        ici_color = "AMBER"
        ici_label = "MODERATE"
        ici_status = _build_ici_status(consensus, execution, flow, "moderate")
    else:
        ici_color = "RED"
        ici_label = "LOW"
        ici_status = _build_ici_status(consensus, execution, flow, "low")

    return {
        "ici": ici,
        "ici_color": ici_color,
        "ici_label": ici_label,
        "ici_status": ici_status,
        "components": {
            "conviction": round(conviction_component, 1),
            "freshness": round(freshness_component, 1),
            "gamma_stability": round(gamma_component, 1),
            "flow_momentum": round(momentum_component, 1),
        },
        "weights": ici_w,
        "session_state": session_state,
    }


def _build_ici_status(
    consensus: Dict[str, Any],
    execution: Dict[str, Any],
    flow: Dict[str, Any],
    level: str,
) -> str:
    """Builds the one-line ICI status description."""
    n_bull = consensus.get("n_bullish", 0)
    n_bear = consensus.get("n_bearish", 0)
    n_total = consensus.get("n_engines", 6)
    direction = consensus.get("consensus_direction", "NEUTRAL")
    leading = consensus.get("leading_conviction", 0.0)
    pine_state = execution.get("execution_state", "WAITING_FOR_PINE")
    divergence = flow.get("divergence_type")
    absorption = flow.get("absorption", False)

    align_count = n_bull if direction == "BULLISH" else n_bear
    side_word = "calls" if direction == "BULLISH" else "puts" if direction == "BEARISH" else "no side"

    if level == "high":
        pine_note = "Pine confirmed." if "CONFIRMED" in pine_state else "Awaiting Pine trigger."
        return (
            f"Institutional conviction strong — {align_count} of {n_total} engines aligned for {side_word} "
            f"({leading:.0f}% conviction). {pine_note}"
        )
    elif level == "moderate":
        if divergence:
            return f"{divergence.replace('_', '+')} divergence active — monitor carefully before entry."
        if absorption:
            return f"Absorption setup forming at key level — {align_count} of {n_total} engines support {side_word}."
        return (
            f"Partial alignment for {side_word} ({align_count} of {n_total} engines, "
            f"{leading:.0f}% conviction). Wait for stronger confirmation."
        )
    else:
        return (
            f"Low institutional conviction ({leading:.0f}/100). "
            f"Sit out until more engines align."
        )




# ===========================================================================
# APEX 5.1 DECISION STATE / RIBBON / TRADE COACH LAYER
# Production dashboard contract for Institutional OS.
# This layer does not invent data; it normalizes outputs already produced by
# the nine engines into the fields the live dashboard needs.
# ===========================================================================

VALID_DECISION_STATES = {
    "PREPARING", "WATCH_CALLS", "WATCH_PUTS", "READY", "ENTER_CALL", "ENTER_PUT",
    "HOLD", "SCALE_OUT", "EXIT", "NO_TRADE",
}


def _grade_from_confidence(value: float) -> str:
    v = _safe_float(value, 0.0)
    if v >= 92: return "A+"
    if v >= 85: return "A"
    if v >= 78: return "B+"
    if v >= 70: return "B"
    if v >= 60: return "C"
    return "D"


def _readiness_from_state(state: str, confidence: float, execution: Dict[str, Any]) -> str:
    if state in ("ENTER_CALL", "ENTER_PUT"):
        return "EXECUTION_READY"
    if state == "READY":
        return "READY_WAITING_FOR_TRIGGER"
    if state in ("WATCH_CALLS", "WATCH_PUTS"):
        return "WATCHING_FOR_CONFIRMATION"
    if state in ("HOLD", "SCALE_OUT", "EXIT"):
        return "POSITION_MANAGEMENT"
    if confidence < 50:
        return "NOT_READY"
    if execution.get("execution_state") == "OUTSIDE_MARKET_HOURS":
        return "SESSION_NOT_TRADEABLE"
    return "PREPARING"


def derive_decision_state(consensus: Dict[str, Any], execution: Dict[str, Any], risk: Dict[str, Any], ici: Dict[str, Any]) -> str:
    recommendation = str(consensus.get("recommendation") or "").upper()
    direction = str(consensus.get("consensus_direction") or "NEUTRAL").upper()
    confidence = _safe_float(ici.get("ici"), 0.0)
    exec_state = str(execution.get("execution_state") or "").upper()

    if "NO_TRADE" in recommendation or "DIVERGENCE" in recommendation or direction == "NEUTRAL":
        return "NO_TRADE"
    if exec_state == "SIGNAL_REJECTED_FLOW_MISMATCH":
        return "NO_TRADE"
    if exec_state.startswith("CONFIRMED_CALL") and direction == "BULLISH" and confidence >= 70:
        return "ENTER_CALL"
    if exec_state.startswith("CONFIRMED_PUT") and direction == "BEARISH" and confidence >= 70:
        return "ENTER_PUT"
    if recommendation == "ENTER_CALL" and confidence >= 72:
        return "READY"
    if recommendation == "ENTER_PUT" and confidence >= 72:
        return "READY"
    if direction == "BULLISH" and confidence >= 50:
        return "WATCH_CALLS"
    if direction == "BEARISH" and confidence >= 50:
        return "WATCH_PUTS"
    return "PREPARING"


def build_engine_contributions(*, market_regime: Dict[str, Any], gamma_regime: Dict[str, Any], flow: Dict[str, Any], structure: Dict[str, Any], trend: Dict[str, Any], execution: Dict[str, Any], consensus: Dict[str, Any], ici: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build engine contribution rows for the Engine Matrix panel.

    Each row includes:
    - vote, weight, strength, conviction_contribution from the consensus vote_table
    - data_available flag (False = engine was skipped this cycle)
    - health_status: OK / WAITING / SKIPPED / NO_SIGNAL
    - ici_component: how much this engine contributed to the ICI score
    """
    now_str = _now_et().strftime("%H:%M:%S ET")
    # consensus vote_table uses engine label strings — map by matching
    vote_by_label = {}
    for v in consensus.get("vote_table", []):
        if isinstance(v, dict):
            lbl = str(v.get("engine", "")).upper().replace(" ", "_")
            vote_by_label[lbl] = v

    def _find_vote(search_keys: List[str]) -> Dict:
        for k in search_keys:
            if k in vote_by_label:
                return vote_by_label[k]
        return {}

    sources = [
        {
            "label": "Market Regime",
            "engine_key": "market_regime",
            "search_keys": ["MARKET_REGIME", "MARKET REGIME"],
            "score": market_regime.get("composite_score"),
            "status": market_regime.get("regime"),
            "notes": market_regime.get("notes", []),
            "data_available": True,
            "ici_comp_key": "conviction",
        },
        {
            "label": "Gamma Regime",
            "engine_key": "gamma_regime",
            "search_keys": ["GAMMA_REGIME", "GAMMA REGIME"],
            "score": gamma_regime.get("gex_score"),
            "status": gamma_regime.get("regime_display"),
            "notes": gamma_regime.get("notes", []),
            "data_available": True,
            "ici_comp_key": "gamma_stability",
        },
        {
            "label": "Flow Intelligence",
            "engine_key": "flow_intelligence",
            "search_keys": ["INSTITUTIONAL_FLOW", "FLOW_INTELLIGENCE", "FLOW INTELLIGENCE", "FLOW"],
            "score": flow.get("intelligence_score"),
            "status": flow.get("flow_momentum"),
            "notes": flow.get("notes", []),
            "data_available": flow.get("data_available", True),
            "ici_comp_key": "flow_momentum",
        },
        {
            "label": "Structure",
            "engine_key": "structure",
            "search_keys": ["MARKET_STRUCTURE", "STRUCTURE"],
            "score": structure.get("structure_score"),
            "status": "Live" if structure.get("data_available") else "Pre-session",
            "notes": structure.get("notes", []),
            "data_available": structure.get("data_available", False),
            "ici_comp_key": "conviction",
        },
        {
            "label": "Trend",
            "engine_key": "trend",
            "search_keys": ["TREND"],
            "score": trend.get("trend_score"),
            "status": trend.get("trend_direction"),
            "notes": trend.get("notes", []),
            "data_available": trend.get("data_available", True),
            "ici_comp_key": "conviction",
        },
        {
            "label": "Execution",
            "engine_key": "execution",
            "search_keys": ["EXECUTION"],
            "score": execution.get("signal_score"),
            "status": execution.get("execution_state"),
            "notes": execution.get("notes", []),
            "data_available": execution.get("has_signal", False) or execution.get("execution_state", "") not in ("WAITING_FOR_PINE", ""),
            "ici_comp_key": "freshness",
        },
    ]

    out: List[Dict[str, Any]] = []
    components = ici.get("components", {}) if isinstance(ici, dict) else {}

    for src in sources:
        vote_row = _find_vote(src["search_keys"])
        data_av = src["data_available"]

        # Health status label
        if vote_row.get("skipped"):
            health = "SKIPPED"
        elif not data_av:
            health = "WAITING"
        elif src["engine_key"] == "execution" and src["status"] == "WAITING_FOR_PINE":
            health = "NO_SIGNAL"
        else:
            health = "OK"

        out.append({
            "engine": src["engine_key"],
            "label": src["label"],
            "score": round(_safe_float(src["score"], 0.0), 1) if src["score"] is not None else None,
            "status": src["status"],
            "vote": vote_row.get("vote"),
            "weight": vote_row.get("weight"),
            "strength": vote_row.get("strength"),
            "contribution": vote_row.get("conviction_contribution"),
            "ici_component": components.get(src["ici_comp_key"]),
            "notes": list(src["notes"] or [])[:3],
            "data_available": data_av,
            "health_status": health,
            "sampled_at": now_str,
        })
    return out


def build_status_ribbon(*, ticker: str, flow_snapshot: Dict[str, Any], gamma_regime: Dict[str, Any], flow: Dict[str, Any], structure: Dict[str, Any], ici: Dict[str, Any], decision_state: str) -> Dict[str, Any]:
    price = None
    for src in (flow_snapshot, structure, flow):
        if isinstance(src, dict):
            price = src.get("stock_price") or src.get("current_price") or src.get("price") or price
    call_premium = _safe_float(flow_snapshot.get("call_premium"), 0.0)
    put_premium = _safe_float(flow_snapshot.get("put_premium"), 0.0)
    net_flow = _safe_float(flow_snapshot.get("net_premium"), call_premium - put_premium)
    if net_flow == 0 and (call_premium or put_premium):
        net_flow = call_premium - put_premium
    return {
        "ticker": ticker,
        "spx_price": round(_safe_float(price), 2) if price is not None else None,
        "call_flow": round(call_premium, 0),
        "put_flow": round(put_premium, 0),
        "net_flow": round(net_flow, 0),
        "flow_momentum": flow.get("flow_momentum"),
        "gamma_regime": gamma_regime.get("regime_display") or gamma_regime.get("regime_label"),
        "call_wall": gamma_regime.get("call_wall"),
        "put_wall": gamma_regime.get("put_wall"),
        "zero_gamma": gamma_regime.get("zero_gamma"),
        "vwap": structure.get("vwap"),
        "poc": structure.get("session_poc") or structure.get("poc"),
        "institutional_confidence": ici.get("ici"),
        "grade": _grade_from_confidence(_safe_float(ici.get("ici"), 0.0)),
        "decision": decision_state,
        "updated_at_et": _now_et().strftime("%H:%M:%S ET"),
    }


def build_trade_coach(*, decision_state: str, consensus: Dict[str, Any], execution: Dict[str, Any], risk: Dict[str, Any], gamma_regime: Dict[str, Any], flow: Dict[str, Any], structure: Dict[str, Any], ici: Dict[str, Any]) -> Dict[str, Any]:
    confidence = _safe_float(ici.get("ici"), 0.0)
    side = risk.get("approved_side") or ("CALL" if consensus.get("consensus_direction") == "BULLISH" else "PUT" if consensus.get("consensus_direction") == "BEARISH" else "NONE")
    blockers: List[str] = []
    if execution.get("execution_state") in ("WAITING_FOR_PINE", "SIGNAL_EXPIRED"):
        blockers.append("Fresh Pine confirmation missing")
    if flow.get("divergence_type") == "A_PLUS":
        blockers.append(f"A+ {flow.get('divergence_direction')} flow divergence active")
    if gamma_regime.get("flip_risk"):
        blockers.append("Price is near zero-gamma flip; regime can change fast")
    if confidence < 50:
        blockers.append("Institutional Confidence below 50")

    if decision_state in ("ENTER_CALL", "ENTER_PUT"):
        action = f"Enter {side.lower()} only within the planned zone; manage from the stop and targets."
    elif decision_state == "READY":
        action = f"Setup is ready for {side.lower()}s. Wait for fresh Pine confirmation before entering."
    elif decision_state in ("WATCH_CALLS", "WATCH_PUTS"):
        action = f"Watch {side.lower()}s, but do not front-run confirmation."
    elif decision_state == "NO_TRADE":
        action = "No trade. Wait for flow, structure, gamma, and execution to align."
    else:
        action = "Prepare only. Let the engines build cleaner alignment."

    return {
        "state": decision_state,
        "action": action,
        "approved_side": side,
        "contract_hint": risk.get("contract_hint"),
        "entry_zone": risk.get("entry_zone"),
        "stop": risk.get("stop"),
        "target1": risk.get("target1"),
        "target2": risk.get("target2"),
        "gamma_management": gamma_regime.get("trade_rules", {}).get("expected_behavior"),
        "blockers": blockers,
        "next_confirmation": "Fresh Pine trigger matching institutional side" if execution.get("execution_state") != f"CONFIRMED_{side}" and side in ("CALL", "PUT") else "Manage active decision from risk plan",
    }


def build_story_timeline(story: Dict[str, Any]) -> List[Dict[str, Any]]:
    timeline: List[Dict[str, Any]] = []
    for idx, chapter in enumerate(story.get("chapters", []) if isinstance(story, dict) else [], start=1):
        if not isinstance(chapter, dict):
            continue
        timeline.append({
            "step": idx,
            "title": chapter.get("title") or chapter.get("chapter") or f"Step {idx}",
            "text": chapter.get("text") or chapter.get("narrative") or chapter.get("summary") or "",
        })
    if not timeline and story.get("executive_summary"):
        timeline.append({"step": 1, "title": "Institutional Story", "text": story.get("executive_summary")})
    return timeline


# ===========================================================================
# MASTER PIPELINE FUNCTION
# Runs all nine engines in order and returns the full institutional OS state.
# Called by app.py's /api/institutional_os endpoint.
# ===========================================================================

def build_institutional_decision(
    ticker: str,
    # Data inputs (fetched by app.py before calling this function)
    flow_snapshot: Dict[str, Any],
    spy_bars: List[dict],
    qqq_bars: List[dict],
    daily_bars: List[dict],          # bars for the primary ticker
    intraday_bars: List[dict],       # 5-min bars for the primary ticker
    signal: Optional[Dict[str, Any]] = None,
    vix_price: Optional[float] = None,
    breadth_score: Optional[float] = None,
    overnight_bars: Optional[List[dict]] = None,
    # Config passthroughs
    default_risk_points: float = 6.0,
    target1_r_mult: float = 1.2,
    target2_r_mult: float = 2.0,
    strike_step_spx: int = 5,
    strike_step_etf: int = 1,
    signal_ttl_seconds: int = 360,
    session_is_tradeable: bool = True,
) -> Dict[str, Any]:
    """
    Master pipeline: runs all nine engines and returns the full
    APEX Institutional OS state dict.

    Pipeline order:
      1. Gamma Regime (needed early — sets adaptive weights for consensus)
      2. Market Regime (uses GEX from gamma regime)
      3. Institutional Flow Intelligence (uses GEX levels + intraday bars)
      4. Market Structure (uses intraday + daily bars)
      5. Trend (uses daily + intraday bars)
      6. Execution (Pine signal evaluation)
      7. Consensus (adaptive weights from gamma regime)
      8. Risk (uses consensus direction + gamma rules)
      9. Story (all eight engines → narrative)
    """

    # ── Pre-extract reusable values from flow snapshot ──
    gex_score = _safe_float(flow_snapshot.get("gex_score"), 50.0)
    call_wall = flow_snapshot.get("call_wall")
    put_wall = flow_snapshot.get("put_wall")
    zero_gamma = flow_snapshot.get("zero_gamma")
    stock_price = flow_snapshot.get("stock_price")
    vix = _safe_float(vix_price, 18.0)

    # ── Engine 2 (Gamma) — runs first to establish adaptive weights ──
    gamma_regime = engine_gamma_regime(
        gex_score=gex_score,
        call_wall=call_wall,
        put_wall=put_wall,
        zero_gamma=zero_gamma,
        stock_price=stock_price,
        vix=vix,
    )
    gamma_label = gamma_regime.get("regime_label", "MIXED_GAMMA")

    # ── Engine 1 (Market Regime) ──
    market_regime = engine_market_regime(
        spy_bars=spy_bars,
        qqq_bars=qqq_bars,
        vix_price=vix,
        gex_score=gex_score,
        breadth_score=breadth_score,
    )

    # ── Engine 3 (Institutional Flow Intelligence) ──
    flow_intelligence = engine_institutional_flow(
        ticker=ticker,
        flow_snapshot=flow_snapshot,
        intraday_bars=intraday_bars,
        stock_price=stock_price,
        call_wall=call_wall,
        put_wall=put_wall,
        zero_gamma=zero_gamma,
        gamma_regime_label=gamma_label,
    )

    # ── Engine 4 (Market Structure) ──
    structure = engine_market_structure(
        intraday_bars=intraday_bars,
        daily_bars=daily_bars,
        overnight_bars=overnight_bars,
    )

    # ── Engine 5 (Trend) ──
    trend = engine_trend(
        ticker=ticker,
        daily_bars=daily_bars,
        intraday_bars=intraday_bars,
    )

    # ── Engine 6 (Execution / Pine) ──
    # Use flow intelligence's approved direction for gate checking
    approved_side = flow_snapshot.get("approved_side") or "NONE"
    execution = engine_execution(
        signal=signal,
        approved_side=approved_side,
        session_is_tradeable=session_is_tradeable,
        signal_ttl_seconds=signal_ttl_seconds,
    )

    # ── Engine 7 (Consensus) ──
    # Derive session_state string for adaptive weighting
    _now = _now_et()
    _market_open_start = _now.replace(hour=9, minute=30, second=0, microsecond=0)
    _market_close = _now.replace(hour=16, minute=0, second=0, microsecond=0)
    _premarket_start = _now.replace(hour=4, minute=0, second=0, microsecond=0)
    if _market_open_start <= _now < _market_close and _now.weekday() < 5:
        _session_state = "MARKET_OPEN"
    elif _premarket_start <= _now < _market_open_start and _now.weekday() < 5:
        _session_state = "PREMARKET"
    elif _market_close <= _now and _now.weekday() < 5:
        _session_state = "AFTER_HOURS"
    else:
        _session_state = "CLOSED"

    consensus = engine_consensus(
        market_regime=market_regime,
        gamma_regime=gamma_regime,
        flow=flow_intelligence,
        structure=structure,
        trend=trend,
        execution=execution,
        gamma_regime_label=gamma_label,
        session_state=_session_state,
    )

    # ── Engine 8 (Risk) ──
    risk = engine_risk(
        ticker=ticker,
        consensus=consensus,
        structure=structure,
        gamma_regime=gamma_regime,
        market_regime=market_regime,
        flow=flow_intelligence,
        signal=signal,
        default_risk_points=default_risk_points,
        target1_r_mult=target1_r_mult,
        target2_r_mult=target2_r_mult,
        strike_step_spx=strike_step_spx,
        strike_step_etf=strike_step_etf,
        signal_ttl_seconds=signal_ttl_seconds,
    )

    # ── Engine 9 (Story) ──
    story = engine_story(
        ticker=ticker,
        market_regime=market_regime,
        gamma_regime=gamma_regime,
        flow=flow_intelligence,
        structure=structure,
        trend=trend,
        execution=execution,
        consensus=consensus,
        risk=risk,
    )

    # ── Institutional Confidence Index (APEX 6.2) ──
    ici = compute_institutional_confidence_index(
        consensus=consensus,
        execution=execution,
        gamma_regime=gamma_regime,
        flow=flow_intelligence,
        signal_ttl_seconds=signal_ttl_seconds,
        session_state=_session_state,
    )

    decision_state = derive_decision_state(consensus, execution, risk, ici)
    confidence_value = _safe_float(ici.get("ici"), 0.0)
    grade = _grade_from_confidence(confidence_value)
    readiness = _readiness_from_state(decision_state, confidence_value, execution)
    engine_contributions = build_engine_contributions(
        market_regime=market_regime,
        gamma_regime=gamma_regime,
        flow=flow_intelligence,
        structure=structure,
        trend=trend,
        execution=execution,
        consensus=consensus,
        ici=ici,
    )
    ribbon = build_status_ribbon(
        ticker=ticker,
        flow_snapshot=flow_snapshot,
        gamma_regime=gamma_regime,
        flow=flow_intelligence,
        structure=structure,
        ici=ici,
        decision_state=decision_state,
    )
    trade_coach = build_trade_coach(
        decision_state=decision_state,
        consensus=consensus,
        execution=execution,
        risk=risk,
        gamma_regime=gamma_regime,
        flow=flow_intelligence,
        structure=structure,
        ici=ici,
    )
    story_timeline = build_story_timeline(story)

    return {
        "version": "6.2.0_FLOW_VOTE_ENGINE",
        "ticker": ticker,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "updated_at_et": _now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
        # All nine engine outputs
        "market_regime": market_regime,
        "gamma_regime": gamma_regime,
        "flow_intelligence": flow_intelligence,
        "structure": structure,
        "trend": trend,
        "execution": execution,
        "consensus": consensus,
        "risk": risk,
        "story": story,
        # Institutional Confidence Index — the primary dashboard number
        "ici": ici,
        "confidence": confidence_value,
        "confidence_pct": confidence_value,
        "grade": grade,
        "readiness": readiness,
        "decision_state": decision_state,
        "decision": {
            "state": decision_state,
            "confidence": confidence_value,
            "grade": grade,
            "readiness": readiness,
            "approved_side": risk.get("approved_side"),
            "recommendation": consensus.get("recommendation"),
            "action": consensus.get("action"),
        },
        "engine_contributions": engine_contributions,
        "ribbon": ribbon,
        "trade_coach": trade_coach,
        "story_timeline": story_timeline,
        # Top-level convenience fields for the dashboard
        "recommendation": consensus.get("recommendation"),
        "consensus_label": consensus.get("consensus_label"),
        "executive_summary": story.get("executive_summary"),
        "approved_side": consensus.get("consensus_direction"),
        "n_engines_agree": max(consensus.get("n_bullish", 0), consensus.get("n_bearish", 0)),
        "n_engines_total": consensus.get("n_engines", 6),
        "leading_conviction": consensus.get("leading_conviction", 0.0),
        "gamma_regime_label": gamma_label,
        "divergence_type": flow_intelligence.get("divergence_type"),
        "divergence_direction": flow_intelligence.get("divergence_direction"),
        "divergence_seconds_remaining": flow_intelligence.get("divergence_seconds_remaining"),
    }
