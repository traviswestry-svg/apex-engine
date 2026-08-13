"""engine/institutional_intelligence.py — APEX 7.0 Institutional Intelligence Layer.

THE canonical object. Every dashboard component, Story Engine, Trade Coach,
Ribbon, and Replay consumes this single object — no component independently
queries multiple engines.

Seven intelligence inputs merged into one answer:
  1. Market State (auction, volume profile, session)
  2. Market Drivers (what is moving SPX)
  3. Options Chain (OI, skew, term structure)
  4. Dealer Positioning (GEX, DEX, VEX, CHEX, hedging, pinning)
  5. Strike Magnets (pin levels, resistance, support)
  6. Institutional Flow (sweeps, blocks, splits, dark flow)
  7. Volatility (regime, path, dealer vega risk)

Output: institutional_intelligence — the complete institutional picture.
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


# ── Evidence builder ──────────────────────────────────────────────────────────

def _evidence(source: str, direction: str, strength: str, note: str) -> Dict[str, str]:
    return {"source": source, "direction": direction, "strength": strength, "note": note}


# ── Main builder ──────────────────────────────────────────────────────────────

def build_institutional_intelligence(
    *,
    # Market structure
    auction_intel:      Dict[str, Any],
    market_state:       Dict[str, Any],
    rotation:           Optional[Dict[str, Any]] = None,
    volume_profile:     Optional[Dict[str, Any]] = None,
    # Dealer
    dealer_positioning: Dict[str, Any],
    options_chain:      Optional[Dict[str, Any]] = None,
    volatility:         Optional[Dict[str, Any]] = None,
    strike_magnets:     Optional[Dict[str, Any]] = None,
    # Institutional
    flow_intel_2:       Dict[str, Any],
    market_drivers:     Optional[Dict[str, Any]] = None,
    story:              Optional[Dict[str, Any]] = None,
    # Execution
    trade_coach:        Optional[Dict[str, Any]] = None,
    risk:               Optional[Dict[str, Any]] = None,
    ici:                Dict[str, Any],
    consensus:          Dict[str, Any],
    decision_state:     str = "NO_TRADE",
    playbook:           Optional[Dict[str, Any]] = None,
    session_state:      str = "MARKET_OPEN",
) -> Dict[str, Any]:
    """Build the canonical institutional intelligence object.

    Built once per scan, consumed everywhere.
    """
    # ── Extract key values from each source ──────────────────────────────────
    price      = _sf(market_state.get("price"))
    poc        = _sf(market_state.get("poc"))
    vah        = _sf(market_state.get("vah"))
    val_       = _sf(market_state.get("val"))
    poc_mig    = str(market_state.get("poc_migration") or "STABLE")
    flow_bias  = str(market_state.get("flow_bias") or flow_intel_2.get("flow_bias") or "MIXED")
    is_trade   = market_state.get("is_tradeable", session_state == "MARKET_OPEN")

    ai_state   = (auction_intel.get("auction_state") or {}) if isinstance(auction_intel, dict) else {}
    ai_acc     = (auction_intel.get("acceptance") or {})    if isinstance(auction_intel, dict) else {}
    ai_excess  = (auction_intel.get("excess") or {})        if isinstance(auction_intel, dict) else {}

    auction_state_str = (ai_state.get("state") or "UNKNOWN").replace("_", " ")
    acceptance    = ai_acc.get("primary_status") or ""
    excess_det    = ai_excess.get("detected", False)
    would_trade   = ai_state.get("would_trade", False)
    auction_conf  = _sf(ai_state.get("confidence"))

    d_gamma   = dealer_positioning.get("gamma")   or {} if isinstance(dealer_positioning, dict) else {}
    d_delta   = dealer_positioning.get("delta")   or {} if isinstance(dealer_positioning, dict) else {}
    d_charm   = dealer_positioning.get("charm")   or {} if isinstance(dealer_positioning, dict) else {}
    d_hedge   = dealer_positioning.get("hedging_pressure") or {} if isinstance(dealer_positioning, dict) else {}
    d_pin     = dealer_positioning.get("pin_probability")  or {} if isinstance(dealer_positioning, dict) else {}
    d_mom     = dealer_positioning.get("momentum_probability") or {} if isinstance(dealer_positioning, dict) else {}
    dealer_gr = str(d_gamma.get("regime") or "NEUTRAL_GAMMA")
    dealer_db = str(d_delta.get("bias") or "NEUTRAL")
    pin_prob  = _sf(d_pin.get("probability"))
    mom_prob  = _sf(d_mom.get("probability"), 50.0)
    gex_score = _sf(d_gamma.get("gex_score"))

    fi2_conv  = _sf(flow_intel_2.get("flow_conviction") if isinstance(flow_intel_2, dict) else 0, 50.0)
    fi2_urg   = str(flow_intel_2.get("urgency") or "LOW") if isinstance(flow_intel_2, dict) else "LOW"
    fi2_intent= str(flow_intel_2.get("flow_intent") or "MIXED") if isinstance(flow_intel_2, dict) else "MIXED"
    fi2_contra= (flow_intel_2.get("contradictions") or []) if isinstance(flow_intel_2, dict) else []

    ici_score = _sf(ici.get("ici") if isinstance(ici, dict) else 0)
    pine_conf = market_state.get("pine_state") == "CONFIRMED"

    # Market drivers
    md_bias     = str((market_drivers or {}).get("market_bias") or "MIXED")
    md_lead     = str((market_drivers or {}).get("leadership_label") or "")
    md_breadth  = str((market_drivers or {}).get("breadth") or "MIXED")
    md_interp   = str((market_drivers or {}).get("story_line") or "")
    md_avail    = (market_drivers or {}).get("available", False)

    # Strike magnets
    sm_pin_risk = str((strike_magnets or {}).get("pin_risk") or "LOW")
    sm_nearest  = (strike_magnets or {}).get("nearest_magnet")
    sm_watch    = str((strike_magnets or {}).get("watch") or "")

    # Volatility
    vol_reg     = str((volatility or {}).get("regime") or "NORMAL")
    vol_path    = str((volatility or {}).get("expected_vol_path") or "STABLE")
    vix         = _sf((volatility or {}).get("vix"))

    # ── Evidence accumulation ─────────────────────────────────────────────────
    evidence: List[Dict[str, str]] = []
    bull_signals = 0
    bear_signals = 0
    neut_signals = 0

    def _add(src, direction, strength, note):
        nonlocal bull_signals, bear_signals, neut_signals
        evidence.append(_evidence(src, direction, strength, note))
        if direction == "BULLISH":
            bull_signals += {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(strength, 1)
        elif direction == "BEARISH":
            bear_signals += {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(strength, 1)
        else:
            neut_signals += 1

    # Auction evidence
    if would_trade and poc_mig == "RISING":
        _add("AUCTION", "BULLISH", "HIGH",
             f"{auction_state_str} with POC migrating higher. Institutions accepting higher prices.")
    elif would_trade and poc_mig == "FALLING":
        _add("AUCTION", "BEARISH", "HIGH",
             f"{auction_state_str} with POC migrating lower. Institutions accepting lower prices.")
    elif acceptance == "ACCEPTING" and poc_mig == "RISING":
        _add("AUCTION", "BULLISH", "MEDIUM",
             f"Price accepting above value with rising POC — bullish auction structure.")
    elif acceptance == "REJECTED":
        _add("AUCTION", "BEARISH", "MEDIUM",
             f"Price rejected at reference level — rotation back toward POC likely.")
    else:
        _add("AUCTION", "NEUTRAL", "LOW", f"{auction_state_str} — balanced auction.")

    # Flow evidence
    if flow_bias == "BULLISH" and fi2_conv >= 70:
        _add("FLOW", "BULLISH", "HIGH",
             f"Bullish flow conviction {fi2_conv:.0f}/100. {fi2_urg.lower()} urgency. {fi2_intent.replace('_', ' ').lower()}.")
    elif flow_bias == "BEARISH" and fi2_conv >= 70:
        _add("FLOW", "BEARISH", "HIGH",
             f"Bearish flow conviction {fi2_conv:.0f}/100. {fi2_urg.lower()} urgency.")
    elif flow_bias == "BULLISH":
        _add("FLOW", "BULLISH", "MEDIUM", f"Flow bias bullish, conviction {fi2_conv:.0f}/100.")
    elif flow_bias == "BEARISH":
        _add("FLOW", "BEARISH", "MEDIUM", f"Flow bias bearish, conviction {fi2_conv:.0f}/100.")
    else:
        _add("FLOW", "NEUTRAL", "LOW", "Mixed institutional flow.")

    # Dealer evidence
    if dealer_gr == "NEGATIVE_GAMMA" and dealer_db == "BUYING":
        _add("DEALER", "BULLISH", "HIGH",
             "Negative gamma forces dealers to buy strength. Delta hedging adds buy pressure.")
    elif dealer_gr == "NEGATIVE_GAMMA" and dealer_db == "SELLING":
        _add("DEALER", "BEARISH", "HIGH",
             "Negative gamma forces dealers to sell weakness. Delta hedging amplifies downside.")
    elif dealer_db == "BUYING":
        _add("DEALER", "BULLISH", "MEDIUM", "Dealer delta hedging adds structural buy pressure.")
    elif dealer_db == "SELLING":
        _add("DEALER", "BEARISH", "MEDIUM", "Dealer delta hedging adds structural sell pressure.")
    else:
        _add("DEALER", "NEUTRAL", "LOW", "Dealer positioning approximately neutral.")

    # Market drivers evidence
    if md_avail:
        if md_bias == "BULLISH":
            _add("MARKET_DRIVERS", "BULLISH", "MEDIUM",
                 f"{md_lead} leading SPX. {md_interp[:100]}")
        elif md_bias == "BEARISH":
            _add("MARKET_DRIVERS", "BEARISH", "MEDIUM",
                 f"SPX weakness driven by key constituents. {md_interp[:100]}")

    # Execution evidence
    if pine_conf:
        _add("EXECUTION", "BULLISH" if "CALL" in decision_state else "BEARISH" if "PUT" in decision_state else "NEUTRAL",
             "HIGH", "Pine signal confirmed.")
    if ici_score >= 75:
        _add("CONFIDENCE", "BULLISH" if flow_bias == "BULLISH" else "NEUTRAL", "MEDIUM",
             f"ICI {ici_score:.0f}/100 — strong institutional alignment.")

    # ── Bias determination ────────────────────────────────────────────────────
    if bull_signals > bear_signals * 1.5:
        institutional_bias  = "BULLISH"
        dealer_bias_read    = "MOMENTUM_SUPPORTIVE" if dealer_gr == "NEGATIVE_GAMMA" else "MILDLY_SUPPORTIVE"
    elif bear_signals > bull_signals * 1.5:
        institutional_bias  = "BEARISH"
        dealer_bias_read    = "MOMENTUM_SUPPORTIVE" if dealer_gr == "NEGATIVE_GAMMA" else "MILDLY_SUPPORTIVE"
    else:
        institutional_bias  = "NEUTRAL"
        dealer_bias_read    = "NEUTRAL"

    # Auction bias label
    if acceptance == "ACCEPTING" and poc_mig == "RISING":
        auction_bias = "ACCEPTANCE_HIGHER"
    elif acceptance == "ACCEPTING" and poc_mig == "FALLING":
        auction_bias = "ACCEPTANCE_LOWER"
    elif acceptance == "REJECTED":
        auction_bias = "REJECTION"
    elif "BALANCED" in auction_state_str.upper():
        auction_bias = "BALANCED"
    else:
        auction_bias = "DEVELOPING"

    # ── Overall score ─────────────────────────────────────────────────────────
    overall = _clamp(
        ici_score * 0.25 +
        fi2_conv  * 0.25 +
        mom_prob  * 0.20 +
        auction_conf * 0.15 +
        (_sf(gex_score) if gex_score else 50) * 0.15
    )

    # ── Decision recommendation ───────────────────────────────────────────────
    is_enter = decision_state.startswith("ENTER")
    is_watch = decision_state.startswith("WATCH") or decision_state == "READY"

    if not is_trade:
        decision_rec = f"[{session_state.replace('_', ' ')}] No entries while market is closed."
    elif is_enter:
        decision_rec = f"ENTER — All intelligence pillars support {decision_state.replace('_', ' ')}."
    elif is_watch:
        decision_rec = f"WATCH — {decision_state.replace('_', ' ')}. Waiting for Pine confirmation."
    elif institutional_bias != "NEUTRAL" and fi2_conv >= 60:
        decision_rec = f"DEVELOPING SETUP — {institutional_bias.lower()} institutional bias building."
    else:
        decision_rec = "NO TRADE — Intelligence is not aligned. Sit out until signals converge."

    # ── Executive summary ─────────────────────────────────────────────────────
    parts = []
    if md_avail and md_interp:
        parts.append(md_interp[:120])
    parts.append(
        f"Dealers are in {dealer_gr.replace('_', ' ')} with estimated {dealer_db.lower()} delta pressure."
    )
    parts.append(
        f"Price is {auction_state_str.lower()} — "
        f"{'institutions accepting higher prices.' if poc_mig == 'RISING' else 'institutions accepting lower prices.' if poc_mig == 'FALLING' else 'auction balanced.'}"
    )
    if fi2_urg == "HIGH":
        parts.append(f"Urgent institutional flow is {flow_bias.lower()}.")
    if fi2_contra:
        parts.append(f"⚠ Contradiction: {fi2_contra[0][:100]}")
    parts.append(f"APEX is in {decision_state.replace('_', ' ')}.")
    exec_summary = " ".join(parts)

    # ── Highest probability scenario ─────────────────────────────────────────
    playbook_primary = (playbook or {}).get("primary_scenario") if isinstance(playbook, dict) else None
    if playbook_primary and isinstance(playbook_primary, dict):
        highest_prob_scenario = playbook_primary.get("path", "")
    elif institutional_bias == "BULLISH":
        highest_prob_scenario = (
            f"Continuation higher toward {_sf(d_gamma.get('call_wall')):.0f} (Call Wall) "
            f"if POC continues migrating higher and flow remains bullish."
        )
    elif institutional_bias == "BEARISH":
        highest_prob_scenario = (
            f"Continuation lower toward {_sf(d_gamma.get('put_wall')):.0f} (Put Wall) "
            f"if POC continues migrating lower and flow remains bearish."
        )
    else:
        highest_prob_scenario = "Balanced auction — await break of VAH or VAL with acceptance."

    # ── Primary risk ──────────────────────────────────────────────────────────
    if excess_det:
        primary_risk = f"Excess detected — {(ai_excess.get('type') or '').replace('_', ' ')}. {ai_excess.get('action', '')}"
    elif sm_pin_risk == "HIGH":
        primary_risk = f"High pin risk toward {sm_nearest}. Gamma pinning may limit directional moves."
    elif vol_path == "EXPANDING":
        primary_risk = f"Volatility expanding (VIX {vix:.1f}). Widen stops — dealer vega losses may trigger forced hedging."
    elif fi2_contra:
        primary_risk = f"Flow contradiction: {fi2_contra[0][:120]}"
    else:
        primary_risk = "No elevated risk signals. Standard position sizing."

    return {
        "available":                True,
        "version":                  "7.0",
        "session_state":            session_state,
        "overall_score":            round(overall, 1),
        "institutional_bias":       institutional_bias,
        "dealer_bias":              dealer_bias_read,
        "auction_bias":             auction_bias,
        "market_driver_bias":       f"{md_lead}_LEADING" if md_lead else "UNKNOWN",
        "decision_state":           decision_state,
        "decision_recommendation":  decision_rec,
        "executive_summary":        exec_summary,
        "highest_probability_scenario": highest_prob_scenario,
        "primary_risk":             primary_risk,
        "evidence":                 evidence,
        "bull_signals":             bull_signals,
        "bear_signals":             bear_signals,
        # Key reads (flat for ribbon/dashboard access)
        "auction_state":            auction_state_str,
        "poc_migration":            poc_mig,
        "acceptance":               acceptance,
        "gamma_regime":             dealer_gr,
        "delta_bias":               dealer_db,
        "flow_bias":                flow_bias,
        "flow_conviction":          round(fi2_conv, 1),
        "flow_urgency":             fi2_urg,
        "flow_contradictions":      fi2_contra,
        "pin_probability":          round(pin_prob, 1),
        "momentum_probability":     round(mom_prob, 1),
        "pin_risk":                 sm_pin_risk,
        "nearest_magnet":           sm_nearest,
        "vol_regime":               vol_reg,
        "vol_path":                 vol_path,
        "ici_score":                round(ici_score, 1),
        "pine_confirmed":           pine_conf,
        # Market drivers
        "market_driver_bias_raw":   md_bias,
        "market_driver_leadership": md_lead,
        "market_driver_breadth":    md_breadth,
        "market_driver_story":      md_interp,
        # Strike magnets
        "strike_magnet_watch":      sm_watch,
        # Playbook passthrough
        "playbook":                 playbook,
    }
