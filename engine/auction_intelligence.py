"""engine/auction_intelligence.py — APEX Auction Intelligence Suite.

Extends the existing Volume Profile + Auction engines with institutional
auction market theory. Never duplicates calculations from volume_profile.py
or auction.py — consumes their outputs and adds interpretation layers.

Modules:
  1. HVBO Intelligence        — High Volume Bar Overlap, value width, rotation
  2. POC Migration Engine     — velocity, acceleration, institutional narrative
  3. Auction State Classifier — Initiative/Responsive, Trend/Neutral/Rotational
  4. Excess Detection Engine  — bearish/bullish excess, exhaustion signals
  5. Acceptance/Rejection     — VAH/VAL/POC acceptance vs. rejection reads
  6. LVN/HVN Intelligence     — magnet levels, fast/slow zones, target context
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


# ── Shared helpers ────────────────────────────────────────────────────────────

def _sf(v: Any, d: float = 0.0) -> float:
    try:
        f = float(v) if v is not None else d
        return d if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return d


def _fmt(v: float, dp: int = 2) -> str:
    return f"{v:,.{dp}f}"


def _pct_of_range(level: float, lo: float, hi: float) -> float:
    """0–100: where does level sit in the lo–hi range?"""
    rng = hi - lo
    if rng <= 0:
        return 50.0
    return round((level - lo) / rng * 100.0, 1)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. HVBO INTELLIGENCE
#    Derives from the volume profile rows already computed upstream.
#    HVBO = the price range where the highest-volume bars overlap.
#    Operationally: the top-N HVN nodes define a "composite high volume area."
# ═══════════════════════════════════════════════════════════════════════════════

def build_hvbo(
    profile: Dict[str, Any],
    *,
    price: float = 0.0,
    top_n: int = 5,
) -> Dict[str, Any]:
    """High Volume Bar Overlap — the dense institutional transaction zone.

    Inputs:
        profile   — output of build_volume_profile() (has .levels and .profile)
        price     — current market price
        top_n     — how many HVN nodes define the HVBO zone

    Returns a dict with HVBO high, low, midpoint, and price-location read.
    """
    available = bool(profile.get("available"))
    if not available:
        return {"available": False, "status": "NO_PROFILE"}

    rows: List[Dict[str, Any]] = profile.get("profile") or []
    levels = profile.get("levels") or {}
    poc  = _sf(levels.get("poc"))
    vah  = _sf(levels.get("vah"))
    val_ = _sf(levels.get("val"))

    if not rows or poc <= 0:
        return {"available": False, "status": "INSUFFICIENT_DATA"}

    total = sum(_sf(r.get("activity")) for r in rows) or 1.0
    sorted_by_vol = sorted(rows, key=lambda r: _sf(r.get("activity")), reverse=True)
    top_rows = sorted_by_vol[:top_n]
    top_prices = [_sf(r.get("price")) for r in top_rows if r.get("price")]

    if not top_prices:
        return {"available": False, "status": "NO_HVN_NODES"}

    hvbo_low  = round(min(top_prices), 2)
    hvbo_high = round(max(top_prices), 2)
    hvbo_mid  = round((hvbo_low + hvbo_high) / 2.0, 2)

    # Daily value width
    value_width = round(vah - val_, 2) if vah and val_ else None

    # Developing POC vs session POC — track whether POC is still in HVBO zone
    poc_in_hvbo = hvbo_low <= poc <= hvbo_high if hvbo_low and hvbo_high else False

    # Value rotation: how much of the range is covered by value area
    session_high = _sf(max((r.get("price", 0) for r in rows), default=0))
    session_low  = _sf(min((r.get("price", 0) for r in rows if r.get("price", 0) > 0), default=0))
    session_range = session_high - session_low if session_high > session_low else 1.0
    value_rotation_pct = round((vah - val_) / session_range * 100, 1) if session_range > 0 else None

    # Price location relative to HVBO
    if price <= 0:
        location = "UNKNOWN"
        location_note = "Price not available."
    elif price > hvbo_high:
        location = "ABOVE_HVBO"
        location_note = f"Price is above the institutional transaction zone ({_fmt(hvbo_low)}–{_fmt(hvbo_high)}). Buyers are accepting higher prices."
    elif price < hvbo_low:
        location = "BELOW_HVBO"
        location_note = f"Price is below the HVBO zone ({_fmt(hvbo_low)}–{_fmt(hvbo_high)}). Sellers have pushed price outside the institution's comfort zone."
    else:
        location = "INSIDE_HVBO"
        pct = _pct_of_range(price, hvbo_low, hvbo_high)
        location_note = (
            f"Price is inside the high-volume institutional zone ({_fmt(hvbo_low)}–{_fmt(hvbo_high)}). "
            f"This is a high-probability rotation zone — expect slower auction activity."
        )

    # Value area status (richer than auction.py — includes accepting/rejecting language)
    if price > vah:
        va_status = "ACCEPTING_HIGHER" if poc_in_hvbo or price > hvbo_high else "TESTING_UPPER_VALUE"
        va_note = "Price is above Value Area High — institutions are accepting higher prices." if va_status == "ACCEPTING_HIGHER" \
                  else "Price is probing above VAH but HVBO has not shifted — this may be a test, not acceptance."
    elif price < val_:
        va_status = "ACCEPTING_LOWER" if price < hvbo_low else "TESTING_LOWER_VALUE"
        va_note = "Price is below Value Area Low — institutions are accepting lower prices." if va_status == "ACCEPTING_LOWER" \
                  else "Price is probing below VAL but has not escaped the HVBO zone — possible responsive buying setup."
    elif price >= poc:
        va_status = "INSIDE_VALUE_UPPER"
        va_note = "Price is inside value and above POC. Buyers have a mild advantage in this balanced auction."
    else:
        va_status = "INSIDE_VALUE_LOWER"
        va_note = "Price is inside value and below POC. Sellers have a mild advantage in this balanced auction."

    return {
        "available":          True,
        "hvbo_high":          hvbo_high,
        "hvbo_low":           hvbo_low,
        "hvbo_mid":           hvbo_mid,
        "hvbo_width":         round(hvbo_high - hvbo_low, 2),
        "poc_in_hvbo":        poc_in_hvbo,
        "nodes_used":         len(top_prices),
        "value_width":        value_width,
        "value_rotation_pct": value_rotation_pct,
        "session_high":       round(session_high, 2) if session_high else None,
        "session_low":        round(session_low, 2)  if session_low  else None,
        "price_location":     location,
        "location_note":      location_note,
        "va_status":          va_status,
        "va_note":            va_note,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 2. POC MIGRATION ENGINE
#    Consumes the POC history maintained across profile updates.
#    Existing auction.py gives us poc_delta and poc_migration direction.
#    This engine adds velocity, acceleration, and institutional narrative.
# ═══════════════════════════════════════════════════════════════════════════════

def build_poc_migration(
    *,
    current_poc: float,
    prior_poc: float,
    earlier_poc: Optional[float] = None,      # two updates ago, for acceleration
    current_price: float = 0.0,
    vah: float = 0.0,
    val: float = 0.0,
    minutes_elapsed: int = 0,                 # minutes since market open
) -> Dict[str, Any]:
    """Institutional POC Migration — velocity, acceleration, and narrative."""
    if current_poc <= 0 or prior_poc <= 0:
        return {
            "available": False,
            "direction": "UNKNOWN",
            "narrative": "POC migration unavailable — waiting for profile history.",
        }

    delta   = round(current_poc - prior_poc, 2)
    abs_d   = abs(delta)

    # Direction
    if abs_d < 0.5:
        direction = "FLAT"
    elif delta > 0:
        direction = "RISING"
    else:
        direction = "FALLING"

    # Velocity (points per update — proxy for speed)
    velocity = abs_d  # raw pts per update

    # Acceleration: compare current delta to prior delta
    acceleration = "UNKNOWN"
    accel_note   = ""
    if earlier_poc is not None and prior_poc > 0:
        prior_delta  = round(prior_poc - earlier_poc, 2)
        prior_abs    = abs(prior_delta)
        accel_delta  = abs_d - prior_abs
        if accel_delta > 1.0:
            acceleration = "ACCELERATING"
            accel_note   = " Migration is accelerating — institutional urgency is increasing."
        elif accel_delta < -1.0:
            acceleration = "DECELERATING"
            accel_note   = " Migration is slowing — institutional conviction may be waning."
        else:
            acceleration = "STEADY"
            accel_note   = " Migration pace is steady."

    # Migration speed label
    if velocity == 0:
        speed_label = "BALANCED"
    elif velocity < 2:
        speed_label = "SLOW"
    elif velocity < 5:
        speed_label = "MODERATE"
    else:
        speed_label = "FAST"

    # Price vs migrating POC
    poc_acceptance = ""
    if current_price > 0 and current_poc > 0:
        if direction == "RISING" and current_price > current_poc:
            poc_acceptance = "Buyers are accepting prices above the migrating POC — bullish conviction."
        elif direction == "RISING" and current_price <= current_poc:
            poc_acceptance = "POC is migrating higher but price has not yet accepted above it — wait for follow-through."
        elif direction == "FALLING" and current_price < current_poc:
            poc_acceptance = "Sellers are accepting prices below the migrating POC — bearish conviction."
        elif direction == "FALLING" and current_price >= current_poc:
            poc_acceptance = "POC is migrating lower but price has not yet accepted below it — possible responsive opportunity."
        else:
            poc_acceptance = "Price and POC are in balance."

    # Institutional narrative
    if direction == "RISING":
        base = (
            f"POC has migrated {_fmt(abs_d)} points higher to {_fmt(current_poc)}. "
            f"Institutions are accepting higher prices as fair value."
            f"{accel_note} {poc_acceptance}"
        )
        bias = "BULLISH"
    elif direction == "FALLING":
        base = (
            f"POC has migrated {_fmt(abs_d)} points lower to {_fmt(current_poc)}. "
            f"Institutions are distributing inventory and accepting lower prices as fair value."
            f"{accel_note} {poc_acceptance}"
        )
        bias = "BEARISH"
    else:
        base = (
            f"POC is flat at {_fmt(current_poc)}. "
            f"The auction is balanced — no institutional commitment to either direction. "
            f"Expect range-bound activity until a catalyst creates directional acceptance."
        )
        bias = "NEUTRAL"

    return {
        "available":    True,
        "current_poc":  round(current_poc, 2),
        "prior_poc":    round(prior_poc, 2),
        "delta":        delta,
        "direction":    direction,
        "speed":        speed_label,
        "velocity":     round(velocity, 2),
        "acceleration": acceleration,
        "bias":         bias,
        "poc_acceptance": poc_acceptance.strip(),
        "narrative":    base.strip(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 3. AUCTION STATE CLASSIFIER
#    Extends auction.py's basic state into full auction market theory:
#    Initiative vs. Responsive, Trend vs. Neutral vs. Rotational Day types.
# ═══════════════════════════════════════════════════════════════════════════════

def classify_auction_state(
    *,
    price: float,
    poc: float,
    vah: float,
    val: float,
    poc_migration: str,           # from auction.py: RISING/FALLING/STABLE
    poc_delta: float,
    flow_bias: str,               # BULLISH/BEARISH/MIXED
    gamma_regime: str,            # POSITIVE/NEGATIVE/MIXED
    session_high: float = 0.0,
    session_low:  float = 0.0,
    prev_day_poc: float = 0.0,
    prev_day_vah: float = 0.0,
    prev_day_val: float = 0.0,
    minutes_open: int = 0,
    hvbo: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Full auction state classification using market profile theory.

    Returns one of:
      INITIATIVE_BUYING     — breakout above value with acceptance, flow confirms
      INITIATIVE_SELLING    — breakdown below value with acceptance, flow confirms
      RESPONSIVE_BUYING     — bounce from VAL or prev low, flow turns positive
      RESPONSIVE_SELLING    — rejection from VAH or prev high, flow turns negative
      BALANCED_AUCTION      — price inside value, no directional commitment
      VALUE_EXPANSION_UP    — value area shifting higher across updates
      VALUE_EXPANSION_DOWN  — value area shifting lower across updates
      VALUE_COMPRESSION     — narrowing value area, coiling
      TREND_DAY_UP          — strong directional session, buyers controlling
      TREND_DAY_DOWN        — strong directional session, sellers controlling
      NEUTRAL_DAY           — balanced, rotational, inside prior range
      ROTATIONAL_DAY        — multi-directional, testing both sides
    """
    if poc <= 0 or vah <= 0 or val <= 0:
        return {
            "state": "WAITING_FOR_PROFILE",
            "confidence": 0,
            "explanation": "Waiting for session volume profile to build.",
            "participant_type": "UNKNOWN",
            "day_type": "UNKNOWN",
        }

    value_width = vah - val
    above_value  = price > vah
    below_value  = price < val
    inside_value = not above_value and not below_value
    above_poc    = price >= poc
    below_poc    = price <  poc

    flow_bull  = flow_bias == "BULLISH"
    flow_bear  = flow_bias == "BEARISH"
    flow_mixed = flow_bias == "MIXED"
    gamma_neg  = gamma_regime == "NEGATIVE"
    gamma_pos  = gamma_regime == "POSITIVE"

    hvbo_loc = (hvbo or {}).get("price_location", "UNKNOWN") if hvbo else "UNKNOWN"
    va_status = (hvbo or {}).get("va_status", "UNKNOWN") if hvbo else "UNKNOWN"

    # ── Trend Day detection ──
    # Strong directional move: price well outside value, POC migrating same direction
    strong_up   = above_value and poc_migration == "RISING" and flow_bull
    strong_down = below_value and poc_migration == "FALLING" and flow_bear

    # ── Initiative vs. Responsive ──
    # Initiative: participants extend price BEYOND prior reference levels
    # Responsive: participants fade moves BACK TO reference levels

    above_prev_vah = price > prev_day_vah if prev_day_vah > 0 else False
    below_prev_val = price < prev_day_val if prev_day_val > 0 else False

    if strong_up:
        state = "TREND_DAY_UP"
        participant = "INITIATIVE_BUYERS"
        day_type = "TREND_DAY"
        explanation = (
            f"Trend day in progress. Price is {_fmt(price - vah)} points above VAH ({_fmt(vah)}). "
            f"POC is migrating higher, confirming institutional acceptance of new prices. "
            f"Flow is bullish. {'Negative gamma amplifies this move.' if gamma_neg else ''}"
        )
        confidence = min(95, 65 + int(abs(poc_delta) * 3) + (10 if flow_bull else 0) + (10 if gamma_neg else 0))

    elif strong_down:
        state = "TREND_DAY_DOWN"
        participant = "INITIATIVE_SELLERS"
        day_type = "TREND_DAY"
        explanation = (
            f"Trend day in progress. Price is {_fmt(val - price)} points below VAL ({_fmt(val)}). "
            f"POC is migrating lower, confirming institutional distribution. "
            f"Flow is bearish. {'Negative gamma amplifies this move.' if gamma_neg else ''}"
        )
        confidence = min(95, 65 + int(abs(poc_delta) * 3) + (10 if flow_bear else 0) + (10 if gamma_neg else 0))

    elif above_value and poc_migration == "RISING" and not flow_bear:
        state = "INITIATIVE_BUYING"
        participant = "INITIATIVE_BUYERS"
        day_type = "DIRECTIONAL"
        explanation = (
            f"Initiative buying: price has broken above VAH ({_fmt(vah)}) with POC migrating higher. "
            f"Institutions are accepting these prices as fair value. "
            f"{'Flow confirms bullish institutional positioning.' if flow_bull else 'Flow is mixed — watch for confirmation.'}"
        )
        confidence = 70 + (15 if flow_bull else 0) + (5 if gamma_neg else 0)

    elif below_value and poc_migration == "FALLING" and not flow_bull:
        state = "INITIATIVE_SELLING"
        participant = "INITIATIVE_SELLERS"
        day_type = "DIRECTIONAL"
        explanation = (
            f"Initiative selling: price has broken below VAL ({_fmt(val)}) with POC migrating lower. "
            f"Institutions are distributing and accepting lower prices as fair value. "
            f"{'Flow confirms bearish positioning.' if flow_bear else 'Flow is mixed — watch for confirmation.'}"
        )
        confidence = 70 + (15 if flow_bear else 0) + (5 if gamma_neg else 0)

    elif below_value and (flow_bull or (not flow_bear and poc_migration != "FALLING")):
        state = "RESPONSIVE_BUYING"
        participant = "RESPONSIVE_BUYERS"
        day_type = "ROTATIONAL" if minutes_open > 60 else "NEUTRAL"
        explanation = (
            f"Responsive buying: price has moved below VAL ({_fmt(val)}) but flow is "
            f"{'turning bullish' if flow_bull else 'not confirming lower prices'}. "
            f"Institutions may be defending this level. Watch for VAL reclaim as entry trigger."
        )
        confidence = 55 + (20 if flow_bull else 0) + (5 if gamma_pos else 0)

    elif above_value and (flow_bear or (not flow_bull and poc_migration != "RISING")):
        state = "RESPONSIVE_SELLING"
        participant = "RESPONSIVE_SELLERS"
        day_type = "ROTATIONAL" if minutes_open > 60 else "NEUTRAL"
        explanation = (
            f"Responsive selling: price extended above VAH ({_fmt(vah)}) but flow is "
            f"{'turning bearish' if flow_bear else 'not confirming higher prices'}. "
            f"Institutions may be fading this move. Watch for VAH failure as entry trigger."
        )
        confidence = 55 + (20 if flow_bear else 0) + (5 if gamma_pos else 0)

    elif inside_value and abs(poc_delta) < 1.0:
        if value_width < 8.0:
            state = "VALUE_COMPRESSION"
            participant = "BALANCED"
            day_type = "NEUTRAL"
            explanation = (
                f"Value area is compressed to {_fmt(value_width)} points. "
                f"The auction is coiling — a breakout from this range will be fast. "
                f"Neither buyers nor sellers are committing. Wait for a break of VAH {_fmt(vah)} or VAL {_fmt(val)}."
            )
            confidence = 65
        else:
            state = "BALANCED_AUCTION"
            participant = "BALANCED"
            day_type = "NEUTRAL"
            explanation = (
                f"Balanced auction: price is inside value ({_fmt(val)}–{_fmt(vah)}) with POC flat at {_fmt(poc)}. "
                f"No initiative participants. The market is in equilibrium. "
                f"Avoid directional positions until the auction breaks out of this range."
            )
            confidence = 70

    elif inside_value and poc_migration == "RISING":
        state = "VALUE_EXPANSION_UP"
        participant = "BUYERS"
        day_type = "DIRECTIONAL"
        explanation = (
            f"Value area shifting higher: POC migrating up while price holds inside value. "
            f"Buyers are building control from the inside. A break of VAH {_fmt(vah)} would confirm initiative buying."
        )
        confidence = 60

    elif inside_value and poc_migration == "FALLING":
        state = "VALUE_EXPANSION_DOWN"
        participant = "SELLERS"
        day_type = "DIRECTIONAL"
        explanation = (
            f"Value area shifting lower: POC migrating down while price holds inside value. "
            f"Sellers are building control from the inside. A break of VAL {_fmt(val)} would confirm initiative selling."
        )
        confidence = 60

    else:
        state = "NEUTRAL_DAY"
        participant = "BALANCED"
        day_type = "NEUTRAL"
        explanation = (
            f"Neutral day: no initiative participants. Price is rotating between "
            f"VAL {_fmt(val)} and VAH {_fmt(vah)}. Best strategy is to fade the extremes."
        )
        confidence = 50

    # Would an institutional trader participate here?
    tradeable = state in (
        "INITIATIVE_BUYING", "INITIATIVE_SELLING",
        "RESPONSIVE_BUYING", "RESPONSIVE_SELLING",
        "TREND_DAY_UP", "TREND_DAY_DOWN",
    )
    participation_note = (
        "Yes — institutional participants are active and directional." if tradeable
        else "No — wait for the auction to break out of balance before entering."
    )

    return {
        "state":              state,
        "day_type":           day_type,
        "participant_type":   participant,
        "confidence":         min(95, max(0, confidence)),
        "explanation":        explanation,
        "would_trade":        tradeable,
        "participation_note": participation_note,
        "is_initiative":      "INITIATIVE" in state,
        "is_responsive":      "RESPONSIVE" in state,
        "is_trend_day":       "TREND_DAY" in state,
        "is_balanced":        "BALANCED" in state or state == "NEUTRAL_DAY",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 4. EXCESS DETECTION ENGINE
#    Detects when the auction has extended too far — exhaustion signals.
#    Derived from price vs. value, flow momentum, and POC stall.
# ═══════════════════════════════════════════════════════════════════════════════

def detect_excess(
    *,
    price: float,
    poc: float,
    vah: float,
    val: float,
    session_high: float = 0.0,
    session_low:  float = 0.0,
    poc_migration: str,
    flow_bias: str,
    flow_momentum: str,           # from flow_intelligence: INCREASING/DECREASING/STABLE
    sweep_count: int = 0,
    gamma_regime: str,
    minutes_open: int = 0,
    hvbo: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Detect auction excess — price extension without acceptance.

    Bearish Excess: new high + weakening flow + no value acceptance + POC stalls
    Bullish Excess: new low  + strengthening flow + no acceptance lower + POC stalls
    """
    if poc <= 0 or vah <= 0 or val <= 0:
        return {"detected": False, "type": "NONE", "narrative": "Waiting for profile."}

    is_new_session_high = price >= session_high * 0.999 if session_high > 0 else False
    is_new_session_low  = price <= session_low  * 1.001 if session_low  > 0 else False
    flow_weakening      = flow_momentum in ("DECREASING", "STABLE") and flow_bias in ("MIXED", "BEARISH")
    flow_strengthening  = flow_momentum in ("INCREASING",) and flow_bias in ("BULLISH",)
    poc_stalled         = poc_migration in ("STABLE", "FLAT")
    above_value         = price > vah
    below_value         = price < val

    excess_type     = "NONE"
    excess_detected = False
    confidence      = 0
    narrative       = "No excess conditions detected."
    action          = ""

    # ── Bearish Excess ──
    # Price makes new high, flow weakens, POC fails to follow
    if is_new_session_high and above_value and flow_weakening and poc_stalled:
        excess_type     = "BEARISH_EXCESS"
        excess_detected = True
        confidence      = 75 + (10 if sweep_count < 2 else 0) + (5 if gamma_regime == "POSITIVE" else 0)
        narrative = (
            f"Bearish excess detected. Price extended to a new session high ({_fmt(price)}) "
            f"above VAH ({_fmt(vah)}), but institutional flow is weakening and POC has not migrated higher. "
            f"Institutions are not accepting these prices. "
            f"{'Positive gamma will dampen further upside.' if gamma_regime == 'POSITIVE' else 'Negative gamma could accelerate a snap-back.'}"
        )
        action = (
            f"Watch for a reversal back toward VAH ({_fmt(vah)}) and POC ({_fmt(poc)}). "
            f"If price fails to reclaim the session high within 2–3 bars, a rotation lower is likely."
        )

    # ── Bullish Excess ──
    # Price makes new low, flow strengthens (responsive buyers coming in), POC fails to follow
    elif is_new_session_low and below_value and flow_strengthening and poc_stalled:
        excess_type     = "BULLISH_EXCESS"
        excess_detected = True
        confidence      = 70 + (10 if sweep_count > 3 else 0) + (5 if gamma_regime == "POSITIVE" else 0)
        narrative = (
            f"Bullish excess detected. Price extended to a new session low ({_fmt(price)}) "
            f"below VAL ({_fmt(val)}), but institutional flow is strengthening and POC has not migrated lower. "
            f"Responsive buyers are defending this level. "
            f"{'Positive gamma supports mean reversion.' if gamma_regime == 'POSITIVE' else ''}"
        )
        action = (
            f"Watch for a recovery back toward VAL ({_fmt(val)}) and POC ({_fmt(poc)}). "
            f"A reclaim of VAL within 2–3 bars confirms responsive buying."
        )

    # ── Partial excess signals ──
    elif is_new_session_high and above_value and poc_stalled and not flow_weakening:
        excess_type = "POTENTIAL_BEARISH_EXCESS"
        excess_detected = False
        confidence  = 45
        narrative   = (
            f"Price is at session high above VAH ({_fmt(vah)}) with POC stalled. "
            f"Flow has not yet confirmed weakness — monitor for a flow reversal before treating as excess."
        )
        action = "Watch flow momentum closely. A drop in call sweep count would confirm bearish excess."

    elif is_new_session_low and below_value and poc_stalled and not flow_strengthening:
        excess_type = "POTENTIAL_BULLISH_EXCESS"
        excess_detected = False
        confidence  = 45
        narrative   = (
            f"Price is at session low below VAL ({_fmt(val)}) with POC stalled. "
            f"Flow has not yet confirmed responsive buying — monitor before treating as excess."
        )
        action = "Watch flow momentum. An uptick in call sweeps would confirm bullish excess."

    return {
        "detected":    excess_detected,
        "type":        excess_type,
        "confidence":  min(95, confidence),
        "narrative":   narrative,
        "action":      action,
        "price":       round(price, 2),
        "poc":         round(poc, 2),
        "vah":         round(vah, 2),
        "val":         round(val, 2),
        "session_high": round(session_high, 2) if session_high else None,
        "session_low":  round(session_low, 2)  if session_low  else None,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 5. ACCEPTANCE / REJECTION ENGINE
#    Determines whether price is being accepted or rejected at key levels.
#    "Accepted" = price stays above/below a level for multiple bars.
#    "Rejected" = price tests and reverses quickly.
# ═══════════════════════════════════════════════════════════════════════════════

def build_acceptance_rejection(
    *,
    price: float,
    poc: float,
    vah: float,
    val: float,
    poc_migration: str,
    flow_bias: str,
    sweep_count: int = 0,
    bars_above_vah: int = 0,      # consecutive bars price has held above VAH
    bars_below_val: int = 0,      # consecutive bars price has held below VAL
    bars_above_poc: int = 0,
    bars_below_poc: int = 0,
    minutes_open:   int = 0,
) -> Dict[str, Any]:
    """Acceptance vs. Rejection at institutional reference levels."""
    if poc <= 0 or vah <= 0 or val <= 0:
        return {"available": False}

    # ── Acceptance thresholds ──
    # 3+ bars above VAH = acceptance; 1 bar = test; 0 = rejection
    ACCEPT_BARS = 3

    def _grade(bars: int) -> Tuple[str, int]:
        if bars >= ACCEPT_BARS:
            return "ACCEPTING", min(90, 50 + bars * 8)
        elif bars == 2:
            return "TESTING", 45
        elif bars == 1:
            return "PROBING", 30
        else:
            return "REJECTED", 10

    above_vah_status, above_vah_conf  = _grade(bars_above_vah)
    below_val_status, below_val_conf  = _grade(bars_below_val)
    above_poc_status, above_poc_conf  = _grade(bars_above_poc)
    below_poc_status, below_poc_conf  = _grade(bars_below_poc)

    # Current location read
    if price > vah:
        primary_level = "VAH"
        primary_status = above_vah_status
        primary_conf   = above_vah_conf
        # Enrich with flow
        if flow_bias == "BULLISH" and primary_status == "ACCEPTING":
            primary_note = (
                f"Price is accepting above VAH ({_fmt(vah)}) with bullish flow confirming. "
                f"{sweep_count} active sweeps. This is high-conviction initiative buying."
            )
        elif primary_status == "ACCEPTING":
            primary_note = (
                f"Price is holding above VAH ({_fmt(vah)}) for {bars_above_vah} bars. "
                f"Acceptance is in progress, but flow confirmation is mixed. Proceed with caution."
            )
        elif primary_status in ("PROBING", "TESTING"):
            primary_note = (
                f"Price is probing above VAH ({_fmt(vah)}) but has not yet confirmed acceptance. "
                f"Wait for {ACCEPT_BARS - bars_above_vah} more bars above VAH before treating as accepted."
            )
        else:
            primary_note = (
                f"Price rejected from VAH ({_fmt(vah)}). Institutions are not accepting higher prices. "
                f"Responsive selling opportunity above VAH."
            )

    elif price < val:
        primary_level = "VAL"
        primary_status = below_val_status
        primary_conf   = below_val_conf
        if flow_bias == "BEARISH" and primary_status == "ACCEPTING":
            primary_note = (
                f"Price is accepting below VAL ({_fmt(val)}) with bearish flow confirming. "
                f"High-conviction initiative selling."
            )
        elif primary_status == "ACCEPTING":
            primary_note = (
                f"Price is holding below VAL ({_fmt(val)}) for {bars_below_val} bars. "
                f"Acceptance lower is in progress without strong flow confirmation."
            )
        elif primary_status in ("PROBING", "TESTING"):
            primary_note = (
                f"Price is probing below VAL ({_fmt(val)}) but has not confirmed acceptance. "
                f"Responsive buyers may defend this level."
            )
        else:
            primary_note = (
                f"Price rejected from below VAL ({_fmt(val)}). Responsive buyers defended the low. "
                f"Watch for VAL reclaim as entry trigger."
            )

    elif price >= poc:
        primary_level = "POC"
        primary_status = above_poc_status
        primary_conf   = above_poc_conf
        primary_note   = (
            f"Price is {'accepting' if primary_status == 'ACCEPTING' else 'testing'} above POC ({_fmt(poc)}). "
            f"{'Buyers in control of the auction inside value.' if primary_status == 'ACCEPTING' else 'Waiting for consistent closes above POC.'}"
        )

    else:
        primary_level = "POC"
        primary_status = below_poc_status
        primary_conf   = below_poc_conf
        primary_note   = (
            f"Price is {'accepting' if primary_status == 'ACCEPTING' else 'testing'} below POC ({_fmt(poc)}). "
            f"{'Sellers in control of the auction inside value.' if primary_status == 'ACCEPTING' else 'Waiting for consistent closes below POC.'}"
        )

    return {
        "available":        True,
        "primary_level":    primary_level,
        "primary_status":   primary_status,
        "primary_confidence": primary_conf,
        "primary_note":     primary_note,
        "vah_status":       above_vah_status,
        "val_status":       below_val_status,
        "poc_upper_status": above_poc_status,
        "poc_lower_status": below_poc_status,
        "bars_above_vah":   bars_above_vah,
        "bars_below_val":   bars_below_val,
        "bars_above_poc":   bars_above_poc,
        "bars_below_poc":   bars_below_poc,
        "accept_threshold_bars": ACCEPT_BARS,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 6. LVN / HVN INTELLIGENCE
#    Explains the TRADING IMPLICATIONS of LVNs and HVNs in plain English.
#    Consumes the nodes already computed by volume_profile.py.
# ═══════════════════════════════════════════════════════════════════════════════

def build_node_intelligence(
    *,
    price: float,
    poc:   float,
    vah:   float,
    val:   float,
    hvn_list: List[float],
    lvn_list: List[float],
    call_wall:  float = 0.0,
    put_wall:   float = 0.0,
) -> Dict[str, Any]:
    """LVN/HVN trading intelligence — magnet levels, fast zones, targets."""
    if poc <= 0 or not hvn_list:
        return {"available": False}

    nodes = []

    # Classify each HVN
    for level in sorted(hvn_list):
        dist = level - price
        nodes.append({
            "level":   round(level, 2),
            "type":    "HVN",
            "dist":    round(dist, 2),
            "side":    "ABOVE" if dist > 0 else "BELOW",
            "role":    "MAGNET_SUPPORT" if dist < 0 else "MAGNET_RESISTANCE",
            "speed":   "SLOW",   # HVNs are slow auction zones — price stalls here
            "note": (
                f"HVN at {_fmt(level)} acts as a magnet — price tends to stall in high-volume zones. "
                f"{'Support: institutions transacted heavily here on the way up.' if level <= price else 'Resistance: this is a prior high-activity zone.'}"
            ),
        })

    # Classify each LVN
    for level in sorted(lvn_list):
        dist = level - price
        role = "FAST_TRAVEL_UP" if dist > 0 else "FAST_TRAVEL_DOWN"
        nodes.append({
            "level":  round(level, 2),
            "type":   "LVN",
            "dist":   round(dist, 2),
            "side":   "ABOVE" if dist > 0 else "BELOW",
            "role":   role,
            "speed":  "FAST",  # LVNs are fast — price moves quickly through low-volume zones
            "note": (
                f"LVN at {_fmt(level)}: low-volume node — price will travel through this level quickly. "
                f"{'If price breaks above {_fmt(level)}, expect a fast move to the next HVN.' if dist > 0 else 'Below this LVN, price will drop quickly until the next HVN support.'}"
            ),
        })

    nodes.sort(key=lambda n: abs(n["dist"]))

    # Nearest support and resistance
    above_nodes = [n for n in nodes if n["dist"] > 0]
    below_nodes = [n for n in nodes if n["dist"] < 0]

    nearest_resistance = above_nodes[0] if above_nodes else None
    nearest_support    = below_nodes[0] if below_nodes else None

    # Target context: next HVN above (for calls) and below (for puts)
    hvn_above = [n for n in above_nodes if n["type"] == "HVN"]
    hvn_below = [n for n in below_nodes if n["type"] == "HVN"]
    lvn_above = [n for n in above_nodes if n["type"] == "LVN"]
    lvn_below = [n for n in below_nodes if n["type"] == "LVN"]

    call_target_note = ""
    if hvn_above:
        t = hvn_above[0]
        call_target_note = (
            f"Call target: next HVN at {_fmt(t['level'])} ({_fmt(abs(t['dist']))} pts up). "
            f"Price will stall here — scale 50% at this level."
        )
        if call_wall > 0 and abs(call_wall - t["level"]) < 10:
            call_target_note += f" Call Wall ({_fmt(call_wall)}) is nearby — strong resistance."
    elif call_wall > 0:
        call_target_note = f"Call Wall at {_fmt(call_wall)} is the primary upside target."

    put_target_note = ""
    if hvn_below:
        t = hvn_below[0]
        put_target_note = (
            f"Put target: next HVN at {_fmt(t['level'])} ({_fmt(abs(t['dist']))} pts down). "
            f"Price will stall here — scale 50% at this level."
        )
        if put_wall > 0 and abs(put_wall - t["level"]) < 10:
            put_target_note += f" Put Wall ({_fmt(put_wall)}) is nearby — strong support."
    elif put_wall > 0:
        put_target_note = f"Put Wall at {_fmt(put_wall)} is the primary downside target."

    # Fast zone warning
    fast_zone_warning = ""
    if lvn_above and lvn_above[0]["dist"] < 3.0:
        fast_zone_warning = f"LVN at {_fmt(lvn_above[0]['level'])} is just {_fmt(lvn_above[0]['dist'])} pts above — price will accelerate through this zone quickly."
    elif lvn_below and abs(lvn_below[0]["dist"]) < 3.0:
        fast_zone_warning = f"LVN at {_fmt(lvn_below[0]['level'])} is just {_fmt(abs(lvn_below[0]['dist']))} pts below — if price breaks here, the move will be fast."

    return {
        "available":           True,
        "nodes":               nodes[:12],  # top 12 closest
        "nearest_resistance":  nearest_resistance,
        "nearest_support":     nearest_support,
        "call_target_note":    call_target_note,
        "put_target_note":     put_target_note,
        "fast_zone_warning":   fast_zone_warning,
        "hvn_count":           len(hvn_list),
        "lvn_count":           len(lvn_list),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATOR — build all intelligence from already-computed profile data
# ═══════════════════════════════════════════════════════════════════════════════

def build_auction_intelligence(
    *,
    current_profile: Dict[str, Any],
    prior_profile:   Optional[Dict[str, Any]],
    earlier_poc:     Optional[float],
    current_price:   float,
    flow_bias:       str = "MIXED",
    flow_momentum:   str = "STABLE",
    sweep_count:     int = 0,
    gamma_regime:    str = "MIXED",
    call_wall:       float = 0.0,
    put_wall:        float = 0.0,
    prev_day_poc:    float = 0.0,
    prev_day_vah:    float = 0.0,
    prev_day_val:    float = 0.0,
    minutes_open:    int   = 0,
    bars_above_vah:  int   = 0,
    bars_below_val:  int   = 0,
    bars_above_poc:  int   = 0,
    bars_below_poc:  int   = 0,
) -> Dict[str, Any]:
    """Single call that runs all auction intelligence engines.

    Inputs are the already-computed objects from volume_profile.py and
    auction.py — this function never fetches data.

    Returns a flat dict added to result["auction_intelligence"].
    """
    levels      = (current_profile.get("levels") or {})
    poc         = _sf(levels.get("poc"))
    vah         = _sf(levels.get("vah"))
    val_        = _sf(levels.get("val"))
    hvn_list    = levels.get("hvn") or []
    lvn_list    = levels.get("lvn") or []

    prior_levels = (prior_profile or {}).get("levels") or {}
    prior_poc    = _sf(prior_levels.get("poc"))

    if poc <= 0:
        return {
            "available": False,
            "status":    "WAITING_FOR_PROFILE",
            "message":   "Auction intelligence requires a complete volume profile.",
        }

    # All profile rows for HVBO
    profile_rows = current_profile.get("profile") or []

    # Session high/low from profile rows
    session_high = max((_sf(r.get("price")) for r in profile_rows), default=0.0)
    session_low  = min((_sf(r.get("price")) for r in profile_rows if r.get("price", 0) > 0), default=0.0)

    # 1. HVBO
    hvbo = build_hvbo(current_profile, price=current_price)

    # 2. POC Migration (extended)
    poc_mig = build_poc_migration(
        current_poc=poc, prior_poc=prior_poc, earlier_poc=earlier_poc,
        current_price=current_price, vah=vah, val=val_, minutes_elapsed=minutes_open,
    )

    # 3. Auction State (full classification)
    auction_state = classify_auction_state(
        price=current_price, poc=poc, vah=vah, val=val_,
        poc_migration=poc_mig.get("direction", "FLAT"),
        poc_delta=_sf(poc_mig.get("delta")),
        flow_bias=flow_bias, gamma_regime=gamma_regime,
        session_high=session_high, session_low=session_low,
        prev_day_poc=prev_day_poc, prev_day_vah=prev_day_vah, prev_day_val=prev_day_val,
        minutes_open=minutes_open, hvbo=hvbo,
    )

    # 4. Excess detection
    excess = detect_excess(
        price=current_price, poc=poc, vah=vah, val=val_,
        session_high=session_high, session_low=session_low,
        poc_migration=poc_mig.get("direction", "FLAT"),
        flow_bias=flow_bias, flow_momentum=flow_momentum,
        sweep_count=sweep_count, gamma_regime=gamma_regime,
        minutes_open=minutes_open, hvbo=hvbo,
    )

    # 5. Acceptance / Rejection
    acc_rej = build_acceptance_rejection(
        price=current_price, poc=poc, vah=vah, val=val_,
        poc_migration=poc_mig.get("direction", "FLAT"),
        flow_bias=flow_bias, sweep_count=sweep_count,
        bars_above_vah=bars_above_vah, bars_below_val=bars_below_val,
        bars_above_poc=bars_above_poc, bars_below_poc=bars_below_poc,
        minutes_open=minutes_open,
    )

    # 6. Node intelligence
    nodes = build_node_intelligence(
        price=current_price, poc=poc, vah=vah, val=val_,
        hvn_list=hvn_list, lvn_list=lvn_list,
        call_wall=call_wall, put_wall=put_wall,
    )

    return {
        "available":       True,
        "hvbo":            hvbo,
        "poc_migration":   poc_mig,
        "auction_state":   auction_state,
        "excess":          excess,
        "acceptance":      acc_rej,
        "nodes":           nodes,
        "session_high":    round(session_high, 2) if session_high else None,
        "session_low":     round(session_low, 2)  if session_low  else None,
    }
