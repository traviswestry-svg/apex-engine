"""engine/execution_intelligence.py — APEX 8.0 Execution Intelligence Engine.

Answers ONE question: Is NOW the highest-probability moment to enter?

Ten modules:
  1. Institutional Pressure Acceleration — measures RATE OF CHANGE of flow
  2. Execution Countdown — WATCH → PREPARE → ARMED → ENTER stages
  3. Liquidity Absorption — large order vs. price movement ratio
  4. Buyer/Seller Exhaustion — aggression and climax detection
  5. Delta Acceleration — first + second derivative of delta flow
  6. Auction Acceptance — time/volume at price acceptance score
  7. Gamma Wall Interaction — wall hold/break/accelerate probability
  8. Execution Probability — composite 0-100
  9. Trade Timing — EARLY / GOOD / PERFECT / LATE
 10. Institutional Trigger — the go/no-go signal

Reads from institutional_intelligence — never independently queries APIs.
Updates scoring from available scan-cycle data.
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


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 1 — Institutional Pressure Acceleration
# ═══════════════════════════════════════════════════════════════════════════

def _pressure_acceleration(
    flow_history: List[float],   # net_premium time series, newest last
) -> Dict[str, Any]:
    """Measure rate of change of institutional flow — not level but velocity."""
    if len(flow_history) < 3:
        return {"score": 50, "direction": "STABLE", "acceleration": 0.0, "note": "Insufficient history."}

    # First derivative: change between points
    deltas = [flow_history[i] - flow_history[i-1] for i in range(1, len(flow_history))]
    # Second derivative: acceleration
    accel  = [deltas[i] - deltas[i-1] for i in range(1, len(deltas))]
    avg_delta = sum(deltas[-3:]) / min(3, len(deltas))
    avg_accel = sum(accel[-2:])  / min(2, len(accel)) if accel else 0.0

    # Score: accelerating in one direction = high pressure
    abs_delta = abs(avg_delta) / 1_000_000  # normalize to millions
    score = _clamp(50 + abs_delta * 2 + abs(avg_accel) / 500_000)

    if avg_delta > 0 and avg_accel >= 0:
        direction = "ACCELERATING_BULLISH"
        note = f"Call pressure increasing at ${abs_delta/1e6:.1f}M/cycle and accelerating."
    elif avg_delta > 0 and avg_accel < 0:
        direction = "DECELERATING_BULLISH"
        note = f"Call pressure still positive but momentum slowing — watch for exhaustion."
    elif avg_delta < 0 and avg_accel <= 0:
        direction = "ACCELERATING_BEARISH"
        note = f"Put pressure increasing at ${abs_delta/1e6:.1f}M/cycle and accelerating."
    elif avg_delta < 0 and avg_accel > 0:
        direction = "DECELERATING_BEARISH"
        note = f"Put pressure still negative but momentum slowing — potential reversal forming."
    else:
        direction = "STABLE"
        note = "Flow pressure stable — no acceleration signal."

    return {
        "score":        round(score, 1),
        "direction":    direction,
        "avg_delta_m":  round(avg_delta / 1_000_000, 2),
        "acceleration": round(avg_accel / 1_000_000, 3),
        "note":         note,
    }


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 2 — Execution Countdown Stages
# ═══════════════════════════════════════════════════════════════════════════

EXEC_STAGES = [
    (0,  59,  "WATCH",   "#94a3b8", "Monitoring — conditions building"),
    (60, 74,  "PREPARE", "#f59e0b", "Setup developing — prepare for entry"),
    (75, 89,  "ARMED",   "#fb923c", "High probability — execution imminent"),
    (90, 100, "ENTER",   "#22c55e", "Execute — all conditions aligned"),
]

def _exec_stage(score: float) -> Dict[str, str]:
    for lo, hi, label, color, desc in EXEC_STAGES:
        if lo <= score <= hi:
            return {"stage": label, "color": color, "description": desc, "min": lo, "max": hi}
    return {"stage": "WATCH", "color": "#94a3b8", "description": "Monitoring", "min": 0, "max": 59}


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 3 — Liquidity Absorption
# ═══════════════════════════════════════════════════════════════════════════

def _liquidity_absorption(
    net_premium: float,      # dollar flow in period
    price_change_pts: float, # price movement in that period
) -> Dict[str, Any]:
    """Detect when large orders fail to move price — institutional absorption."""
    prem_m = abs(net_premium) / 1_000_000 if net_premium else 0
    if prem_m < 50 or price_change_pts == 0:
        return {"score": 50, "signal": "NEUTRAL", "note": "Insufficient data for absorption analysis."}

    # Impact ratio: price points per million dollars of flow
    impact_ratio = abs(price_change_pts) / prem_m if prem_m > 0 else 0

    # Low impact = high absorption (institutions absorbing the order flow)
    if impact_ratio < 0.05:
        score  = 85
        signal = "HIGH_ABSORPTION"
        note   = (
            f"${prem_m:.0f}M of flow moved price only {abs(price_change_pts):.2f} pts. "
            "Institutions are absorbing flow — expect a directional release when absorption ends."
        )
    elif impact_ratio < 0.15:
        score  = 65
        signal = "MODERATE_ABSORPTION"
        note   = f"Moderate absorption — ${prem_m:.0f}M moved price {abs(price_change_pts):.2f} pts."
    else:
        score  = 40
        signal = "LOW_ABSORPTION"
        note   = f"Normal price impact — no significant absorption detected."

    # Directional context
    if net_premium > 0 and price_change_pts <= 0:
        signal = "BULLISH_ABSORPTION"
        note  += " Bullish: buying flow but price not rising — sellers being absorbed. Bullish breakout risk."
    elif net_premium < 0 and price_change_pts >= 0:
        signal = "BEARISH_ABSORPTION"
        note  += " Bearish: selling flow but price not falling — buyers being absorbed. Bearish breakdown risk."

    return {"score": round(score, 1), "signal": signal, "note": note, "impact_ratio": round(impact_ratio, 4)}


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 4 — Buyer / Seller Exhaustion
# ═══════════════════════════════════════════════════════════════════════════

def _exhaustion_detection(
    sweep_count: int,
    sweep_pct_change: float,  # % change in sweep rate vs prior period
    price_momentum: float,    # recent price rate of change
    flow_bias: str,
) -> Dict[str, Any]:
    """Detect when aggressive buyers or sellers are running out of fuel."""
    # Sweeps increasing but price momentum slowing = exhaustion
    exhaustion_score = 50.0

    if sweep_count >= 5 and sweep_pct_change < -20 and abs(price_momentum) < 0.5:
        if flow_bias == "BULLISH":
            signal = "BUYER_EXHAUSTION"
            exhaustion_score = 75
            note = (
                f"{sweep_count} call sweeps active but sweep rate slowing {sweep_pct_change:.0f}% "
                "while price momentum fades. Buyers may be running out of fuel — caution on chasing."
            )
        else:
            signal = "SELLER_EXHAUSTION"
            exhaustion_score = 75
            note = (
                f"{sweep_count} put sweeps but momentum fading. Sellers exhausting — "
                "responsive buyers may take control."
            )
    elif sweep_count >= 5 and sweep_pct_change > 20:
        signal = "AGGRESSIVE_BUYERS" if flow_bias == "BULLISH" else "AGGRESSIVE_SELLERS"
        exhaustion_score = 30
        note = f"Sweep rate accelerating {sweep_pct_change:.0f}% — aggression increasing, not exhausted."
    else:
        signal = "BALANCED"
        note = "No clear exhaustion or aggression signal."

    return {
        "score":  round(exhaustion_score, 1),
        "signal": signal,
        "note":   note,
        "sweep_count": sweep_count,
    }


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 5 — Delta Acceleration
# ═══════════════════════════════════════════════════════════════════════════

def _delta_acceleration(
    dealer_delta_score_history: List[float],  # dealer delta score time series
) -> Dict[str, Any]:
    """First + second derivative of dealer delta positioning."""
    if len(dealer_delta_score_history) < 3:
        return {"score": 50, "direction": "STABLE", "velocity": 0.0, "acceleration": 0.0}

    h = dealer_delta_score_history
    velocity = h[-1] - h[-2]
    accel    = velocity - (h[-2] - h[-3]) if len(h) >= 3 else 0.0

    if velocity > 5 and accel >= 0:
        direction = "DELTA_ACCELERATING_BULLISH"
        score     = _clamp(50 + velocity * 2 + abs(accel))
        note      = "Dealer delta bias accelerating bullish — increasing buy-side pressure."
    elif velocity > 5 and accel < 0:
        direction = "DELTA_DECELERATING_BULLISH"
        score     = 55.0
        note      = "Dealer delta bullish but decelerating — watch for reversal."
    elif velocity < -5 and accel <= 0:
        direction = "DELTA_ACCELERATING_BEARISH"
        score     = _clamp(50 - abs(velocity) * 2 - abs(accel))
        note      = "Dealer delta bias accelerating bearish — increasing sell-side pressure."
    else:
        direction = "DELTA_STABLE"
        score     = 50.0
        note      = "Dealer delta stable — no acceleration signal."

    return {
        "score":        round(score, 1),
        "direction":    direction,
        "velocity":     round(velocity, 2),
        "acceleration": round(accel, 2),
        "note":         note,
    }


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 6 — Auction Acceptance Score
# ═══════════════════════════════════════════════════════════════════════════

def _auction_acceptance(
    auction_intel: Dict[str, Any],
    market_state:  Dict[str, Any],
) -> Dict[str, Any]:
    """Score the quality of auction acceptance for execution timing."""
    ai_acc  = (auction_intel.get("acceptance") or {}) if isinstance(auction_intel, dict) else {}
    ai_poc  = (auction_intel.get("poc_migration") or {}) if isinstance(auction_intel, dict) else {}
    ai_st   = (auction_intel.get("auction_state") or {}) if isinstance(auction_intel, dict) else {}

    acc_status = ai_acc.get("primary_status") or ""
    poc_mig    = market_state.get("poc_migration") or "STABLE"
    would_trade = ai_st.get("would_trade", False)
    pva        = market_state.get("price_vs_va") or ""

    score = 50.0
    if acc_status == "ACCEPTING" and poc_mig in ("RISING", "FALLING"):
        score = 82
        note  = f"Auction accepting with POC migration confirmed — high-quality entry environment."
    elif acc_status == "ACCEPTING":
        score = 68
        note  = f"Acceptance confirmed but POC not yet migrating — wait for POC follow-through."
    elif acc_status == "REJECTED":
        score = 25
        note  = "Price was rejected at reference level — avoid entries in rejection direction."
    elif acc_status == "TESTING":
        score = 55
        note  = "Auction is testing — wait for acceptance confirmation before entering."
    else:
        score = 45
        note  = "Auction state unclear."

    if would_trade:
        score = min(score + 10, 100)
    if pva in ("ABOVE_VAH", "BELOW_VAL") and poc_mig in ("RISING", "FALLING"):
        score = min(score + 8, 100)  # breakout with POC following = higher quality

    return {"score": round(score, 1), "acceptance": acc_status, "poc_migration": poc_mig, "note": note}


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 7 — Gamma Wall Interaction
# ═══════════════════════════════════════════════════════════════════════════

def _gamma_wall_interaction(
    price:      float,
    call_wall:  float,
    put_wall:   float,
    zero_gamma: float,
    gex_score:  float,
) -> Dict[str, Any]:
    """Determine how price is interacting with dealer gamma walls."""
    if price <= 0 or call_wall <= 0 or put_wall <= 0:
        return {"score": 50, "interaction": "UNKNOWN", "note": "Gamma wall data unavailable."}

    dist_call = call_wall - price
    dist_put  = price - put_wall
    dist_flip = abs(price - zero_gamma) if zero_gamma > 0 else 999

    # Is price trapped between walls, testing a wall, or breaking through?
    if dist_call < 3 and dist_call > 0:
        interaction = "TESTING_CALL_WALL"
        score       = 45   # resistance approaching — reduce bullish score
        note        = f"Price within {dist_call:.1f} pts of Call Wall ({call_wall:.2f}). Expect resistance. Wall hold probability high in positive gamma."
    elif dist_call <= 0:
        interaction = "BREAKING_CALL_WALL"
        score       = 80 if gex_score < 40 else 55  # in neg gamma = momentum, pos gamma = may reject
        note        = f"Price has crossed Call Wall ({call_wall:.2f}). In {'negative' if gex_score < 40 else 'positive'} gamma — {'momentum expected.' if gex_score < 40 else 'watch for rejection back below wall.'}"
    elif dist_put < 3 and dist_put > 0:
        interaction = "TESTING_PUT_WALL"
        score       = 55   # support approaching — potential bounce
        note        = f"Price within {dist_put:.1f} pts of Put Wall ({put_wall:.2f}). Expect support. Responsive buyers likely active here."
    elif dist_put <= 0:
        interaction = "BREAKING_PUT_WALL"
        score       = 25 if gex_score < 40 else 50
        note        = f"Price has broken below Put Wall ({put_wall:.2f}). {'Momentum selling expected.' if gex_score < 40 else 'Watch for support at next level.'}"
    elif dist_flip < 5:
        interaction = "AT_GAMMA_FLIP"
        score       = 50
        note        = f"Price is at the gamma flip level ({zero_gamma:.2f}). Dealer behavior about to change — high uncertainty."
    else:
        interaction = "BETWEEN_WALLS"
        score       = 60
        note        = f"Price between walls. Call Wall {dist_call:.1f} pts above, Put Wall {dist_put:.1f} pts below."

    return {"score": round(score, 1), "interaction": interaction, "note": note,
            "dist_call_wall": round(dist_call, 2), "dist_put_wall": round(dist_put, 2)}


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 8 — Execution Probability (Composite)
# ═══════════════════════════════════════════════════════════════════════════

def _execution_probability(
    inst_intel_score:  float,
    flow_conviction:   float,
    auction_acc_score: float,
    pressure_accel:    float,
    absorption_score:  float,
    gamma_wall_score:  float,
    ici_score:         float,
    pine_confirmed:    bool,
    is_tradeable:      bool,
) -> float:
    """Weighted composite execution probability."""
    if not is_tradeable:
        return 0.0

    weights = {
        "inst_intel":   0.20,
        "flow_conv":    0.18,
        "auction_acc":  0.18,
        "ici":          0.15,
        "pressure":     0.12,
        "gamma_wall":   0.10,
        "absorption":   0.07,
    }

    raw = (
        inst_intel_score  * weights["inst_intel"] +
        flow_conviction   * weights["flow_conv"]  +
        auction_acc_score * weights["auction_acc"] +
        ici_score         * weights["ici"]         +
        pressure_accel    * weights["pressure"]    +
        gamma_wall_score  * weights["gamma_wall"]  +
        absorption_score  * weights["absorption"]
    )

    # Pine confirmation adds 8 pts — significant but not gate-keeping
    if pine_confirmed:
        raw = min(raw + 8, 100)

    return _clamp(raw)


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 9 — Trade Timing
# ═══════════════════════════════════════════════════════════════════════════

def _trade_timing(
    exec_prob:      float,
    minutes_open:   int,
    session_state:  str,
    poc_migration:  str,
    flow_bias:      str,
) -> Dict[str, Any]:
    """Assess whether timing is early, optimal, late, or missed."""
    if session_state not in ("MARKET_OPEN",):
        return {"timing": "NO_SESSION", "color": "#94a3b8", "note": "Market not in RTH."}

    # Early: all setups present but not confirmed
    if exec_prob < 60:
        timing = "EARLY"
        color  = "#94a3b8"
        note   = "Setup forming but not mature — patience. Let the auction confirm."
    elif exec_prob < 75:
        timing = "DEVELOPING"
        color  = "#f59e0b"
        note   = "Setup developing. Prepare entry plan. Watch for Pine trigger."
    elif exec_prob < 90:
        timing = "GOOD"
        color  = "#fb923c"
        note   = "High-quality setup. Final confirmation (Pine) may be all that's needed."
    else:
        timing = "OPTIMAL"
        color  = "#22c55e"
        note   = "Execution window open. All conditions aligned. Enter on next confirmation."

    # Time of day adjustments
    if 0 < minutes_open < 15:
        note += " Early session — wait for opening range to establish."
    elif minutes_open > 360:
        note += " Late session — tighten stops, reduce size, theta risk elevated."

    return {"timing": timing, "color": color, "note": note}


# ═══════════════════════════════════════════════════════════════════════════
# MASTER ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════

def build_execution_intelligence(
    *,
    institutional_intelligence: Dict[str, Any],
    auction_intel:              Dict[str, Any],
    dealer_positioning:         Dict[str, Any],
    flow_snapshot:              Dict[str, Any],
    market_state:               Dict[str, Any],
    # Historical data for acceleration modules (optional)
    flow_history:               Optional[List[float]] = None,
    delta_score_history:        Optional[List[float]] = None,
    session_state:              str = "MARKET_OPEN",
) -> Dict[str, Any]:
    """Build the complete Execution Intelligence object."""

    ii = institutional_intelligence if isinstance(institutional_intelligence, dict) else {}
    ms = market_state if isinstance(market_state, dict) else {}
    dp = dealer_positioning if isinstance(dealer_positioning, dict) else {}
    fs = flow_snapshot if isinstance(flow_snapshot, dict) else {}
    ai = auction_intel if isinstance(auction_intel, dict) else {}

    # Extract key values
    price          = _sf(ms.get("price"))
    gex_score      = _sf((dp.get("gamma") or {}).get("gex_score"), 50.0)
    call_wall      = _sf((dp.get("gamma") or {}).get("call_wall"))
    put_wall       = _sf((dp.get("gamma") or {}).get("put_wall"))
    zero_gamma     = _sf((dp.get("gamma") or {}).get("zero_gamma"))
    flow_bias      = str(fs.get("bias") or ms.get("flow_bias") or "MIXED")
    sweep_count    = int(_sf(fs.get("sweep_count")))
    net_prem       = _sf(fs.get("net_premium"))
    price_chg      = _sf(ms.get("price_change_pts"))
    flow_conv      = _sf(ii.get("flow_conviction"), 50.0)
    ici_score      = _sf(ii.get("ici_score"), 0.0)
    inst_score     = _sf(ii.get("overall_score"), 50.0)
    poc_mig        = str(ms.get("poc_migration") or "STABLE")
    pine_conf      = bool(ii.get("pine_confirmed"))
    is_tradeable   = ms.get("is_tradeable", session_state == "MARKET_OPEN")
    minutes_open   = int(_sf(ms.get("minutes_open")))

    # Run all modules
    m1_pressure = _pressure_acceleration(flow_history or [net_prem])
    m3_absorb   = _liquidity_absorption(net_prem, price_chg)
    m4_exhaust  = _exhaustion_detection(sweep_count, 0.0, price_chg, flow_bias)
    m5_delta    = _delta_acceleration(delta_score_history or [50.0])
    m6_auction  = _auction_acceptance(ai, ms)
    m7_wall     = _gamma_wall_interaction(price, call_wall, put_wall, zero_gamma, gex_score)

    # Module 8 — execution probability
    exec_prob = _execution_probability(
        inst_intel_score  = inst_score,
        flow_conviction   = flow_conv,
        auction_acc_score = m6_auction["score"],
        pressure_accel    = m1_pressure["score"],
        absorption_score  = m3_absorb["score"],
        gamma_wall_score  = m7_wall["score"],
        ici_score         = ici_score,
        pine_confirmed    = pine_conf,
        is_tradeable      = is_tradeable,
    )

    # Module 2 — stage
    stage_info = _exec_stage(exec_prob)

    # Module 9 — timing
    timing = _trade_timing(exec_prob, minutes_open, session_state, poc_mig, flow_bias)

    # Institutional trigger — only fires at 90+
    trigger_active = exec_prob >= 90 and is_tradeable and pine_conf
    trigger_label  = "EXECUTE" if trigger_active else stage_info["stage"]
    trigger_color  = "#22c55e" if trigger_active else stage_info["color"]

    # Why bullets (5 key reasons)
    decision_state = str(ii.get("decision_state") or "NO_TRADE")
    why_bullets = _build_why_bullets(ii, ms, dp, fs, ai, exec_prob, pine_conf)

    # Invalidation sentence
    invalidation = _build_invalidation(ii, ms, dp)

    # Narrative
    narrative = (
        f"Execution probability: {exec_prob:.0f}%. "
        f"Stage: {stage_info['stage']}. "
        f"{stage_info['description']}. "
        f"{timing['note']}"
    )

    return {
        "available":             True,
        "version":               "8.0",
        "exec_probability":      round(exec_prob, 1),
        "stage":                 stage_info["stage"],
        "stage_color":           stage_info["color"],
        "stage_description":     stage_info["description"],
        "trigger_active":        trigger_active,
        "trigger_label":         trigger_label,
        "trigger_color":         trigger_color,
        "timing":                timing["timing"],
        "timing_color":          timing["color"],
        "timing_note":           timing["note"],
        "narrative":             narrative,
        "why_bullets":           why_bullets,
        "invalidation":          invalidation,
        "decision_state":        decision_state,
        "pine_confirmed":        pine_conf,
        # Module outputs
        "pressure_acceleration": m1_pressure,
        "absorption":            m3_absorb,
        "exhaustion":            m4_exhaust,
        "delta_acceleration":    m5_delta,
        "auction_acceptance":    m6_auction,
        "gamma_wall":            m7_wall,
        # Flat scores for pyramid
        "scores": {
            "execution":         round(exec_prob, 1),
            "ici":               round(ici_score, 1),
            "flow_conviction":   round(flow_conv, 1),
            "auction_acceptance": round(m6_auction["score"], 1),
            "gamma_wall":        round(m7_wall["score"], 1),
            "pressure":          round(m1_pressure["score"], 1),
            "absorption":        round(m3_absorb["score"], 1),
        },
    }


def _build_why_bullets(
    ii:         Dict[str, Any],
    ms:         Dict[str, Any],
    dp:         Dict[str, Any],
    fs:         Dict[str, Any],
    ai:         Dict[str, Any],
    exec_prob:  float,
    pine_conf:  bool,
) -> List[Dict[str, Any]]:
    """Build 5 key WHY bullets — passing and failing conditions."""
    bullets = []

    def _bullet(label, ok, note=""):
        bullets.append({"label": label, "ok": ok, "note": note})

    # Dealer
    delta_bias = (dp.get("delta") or {}).get("bias") or ii.get("delta_bias") or "NEUTRAL"
    _bullet(
        f"Dealers {delta_bias.lower()}",
        delta_bias in ("BUYING", "SELLING"),
        (dp.get("delta") or {}).get("narrative") or ""
    )

    # POC migration
    poc_mig = ms.get("poc_migration") or "STABLE"
    _bullet(
        f"POC {poc_mig.lower()}",
        poc_mig in ("RISING", "FALLING"),
        f"Point of Control migrating {poc_mig.lower()} — {'confirms institutional acceptance' if poc_mig != 'STABLE' else 'not yet confirming direction'}"
    )

    # Flow
    flow_conv = _sf(ii.get("flow_conviction"), 50.0)
    flow_bias = str(fs.get("bias") or "MIXED")
    _bullet(
        f"Flow {flow_bias.lower()} ({flow_conv:.0f}% conviction)",
        flow_conv >= 65,
        f"{'Sufficient conviction for entry.' if flow_conv >= 65 else 'Flow conviction below threshold — wait for alignment.'}"
    )

    # Auction acceptance
    ai_acc = (ai.get("acceptance") or {}) if isinstance(ai, dict) else {}
    acc = ai_acc.get("primary_status") or ""
    _bullet(
        f"Acceptance: {acc or 'unknown'}",
        acc == "ACCEPTING",
        f"{'Price is being accepted at current levels.' if acc == 'ACCEPTING' else 'Price not yet accepted — wait for confirmation.'}"
    )

    # Pine
    _bullet(
        "Pine confirmation",
        pine_conf,
        "Pine signal confirmed — institutional + technical alignment." if pine_conf else "Pine confirmation pending — final trigger missing."
    )

    return bullets[:5]


def _build_invalidation(
    ii: Dict[str, Any],
    ms: Dict[str, Any],
    dp: Dict[str, Any],
) -> str:
    decision = str(ii.get("decision_state") or "NO_TRADE")
    poc = _sf(ms.get("poc"))
    val = _sf(ms.get("val"))
    vah = _sf(ms.get("vah"))
    poc_mig = ms.get("poc_migration") or "STABLE"

    if "CALL" in decision:
        return (
            f"Bullish thesis is invalidated if: price closes below POC (${poc:.2f}) on a confirmed bar, "
            f"POC migration stops or reverses, flow turns bearish, or dealers shift to SELLING delta. "
            f"Hard stop: below VAL (${val:.2f})."
        )
    elif "PUT" in decision:
        return (
            f"Bearish thesis is invalidated if: price reclaims POC (${poc:.2f}) with bullish flow, "
            f"POC migration reverses to rising, or dealers shift to BUYING delta. "
            f"Hard stop: above VAH (${vah:.2f})."
        )
    else:
        return (
            f"Balanced auction invalidated by: break of VAH (${vah:.2f}) with acceptance above, "
            f"or break of VAL (${val:.2f}) with acceptance below, supported by directional flow and POC following."
        )
