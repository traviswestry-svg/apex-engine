"""
engine/decision_intelligence.py — APEX 7.5.7 Decision Intelligence.

WHAT THIS IS
------------
A READ-ONLY assembler that answers the six decision questions the top dashboard
must surface, using data the stack ALREADY computes. It recomputes nothing — it
reads the composed Data Bus plus the confluence and event outputs and formats
them into one clean panel payload.

The six questions:
  1. What is moving SPX?        -> market_driver_* (leadership/story)
  2. What are dealers doing?    -> gamma_regime / dealer_bias / pin_probability
  3. What are institutions doing?-> institutional_bias / flow / ici
  4. Trade / Watch / Avoid?     -> decision_state + confluence conviction
  5. Why?                        -> confluence evidence + institutional evidence
  6. What invalidates it?        -> range invalidation + primary_risk

Output also carries the confidence "pyramid" (layered: data -> signals ->
confluence -> decision) and an invalidation list, per the 7.5.7 spec.

Never raises into the caller.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

VERSION = "7.5.7_DECISION_INTELLIGENCE"


def _u(v: Any) -> str:
    return str(v or "").strip().upper()


def _sf(v: Any, d: float = 0.0) -> float:
    try:
        return float(v) if v is not None else d
    except (TypeError, ValueError):
        return d


def build_decision_intelligence(
    last_result: Dict[str, Any],
    confluence: Optional[Dict[str, Any]] = None,
    events: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble the six-question decision panel from already-computed outputs."""
    try:
        lr = last_result if isinstance(last_result, dict) else {}
        inst = lr.get("institutional_intelligence") or {}
        ms = lr.get("market_state") or {}
        rng = ((lr.get("range_intelligence") or {}).get("range_intelligence")
               if isinstance(lr.get("range_intelligence"), dict) else {}) or {}
        conf = confluence or {}
        ev = events or {}

        if not inst:
            return _empty("Institutional Intelligence not populated yet.")

        # Q1 — What is moving SPX?
        driver_story = inst.get("market_driver_story") or inst.get("market_driver_leadership")
        q1 = {
            "question": "What is moving SPX?",
            "answer": driver_story or "Driver data not available this cycle.",
            "bias": _u(inst.get("market_driver_bias")),
            "breadth": inst.get("market_driver_breadth"),
        }

        # Q2 — What are dealers doing?
        gr = _u(inst.get("gamma_regime"))
        pin = _sf(inst.get("pin_probability"))
        q2 = {
            "question": "What are dealers doing?",
            "answer": _dealer_answer(gr, _u(inst.get("dealer_bias")), pin,
                                     inst.get("nearest_magnet")),
            "gamma_regime": gr,
            "pin_probability": round(pin, 1) if pin else None,
        }

        # Q3 — What are institutions doing?
        q3 = {
            "question": "What are institutions doing?",
            "answer": _inst_answer(_u(inst.get("institutional_bias")),
                                   _u(inst.get("flow_bias")),
                                   _sf(inst.get("flow_conviction")),
                                   _sf(inst.get("ici_score"))),
            "institutional_bias": _u(inst.get("institutional_bias")),
            "flow_bias": _u(inst.get("flow_bias")),
            "ici_score": _sf(inst.get("ici_score")),
        }

        # Q4 — Trade / Watch / Avoid?
        verdict, verdict_reason = _verdict(inst, conf, ev)
        q4 = {
            "question": "Trade, Watch, or Avoid?",
            "answer": verdict,
            "reason": verdict_reason,
            "dominant_side": conf.get("dominant_side"),
            "conviction": conf.get("conviction"),
        }

        # Q5 — Why?
        why: List[str] = []
        dom = _u(conf.get("dominant_side"))
        if dom == "LONG":
            why = list(conf.get("long_evidence") or [])
        elif dom == "SHORT":
            why = list(conf.get("short_evidence") or [])
        if not why:
            why = list(inst.get("evidence") or [])[:5]
        q5 = {"question": "Why?", "answer": why or ["No confirming evidence assembled this cycle."]}

        # Q6 — What invalidates it?
        invalidation: List[str] = list(rng.get("invalidation") or [])
        primary_risk = inst.get("primary_risk")
        if primary_risk:
            invalidation.append(f"Primary risk: {primary_risk}")
        if dom == "LONG":
            missing = conf.get("long_missing") or []
        elif dom == "SHORT":
            missing = conf.get("short_missing") or []
        else:
            missing = []
        q6 = {
            "question": "What invalidates it?",
            "answer": invalidation or ["No explicit invalidation levels this cycle."],
            "missing_confirmations": list(missing)[:4],
        }

        # Confidence pyramid (layered provenance of the decision)
        pyramid = _confidence_pyramid(lr, inst, conf, ev)

        # Event overlay (from 7.5.4)
        intraday_event = ev.get("intraday_event_regime") or {}
        event_regime = _u(intraday_event.get("state") or ev.get("event_regime")) or "CLEAR"
        event_headline = (ev.get("headline_event") or {}).get("label") if ev.get("headline_event") else None

        return {
            "available": True,
            "version": VERSION,
            "verdict": verdict,                # TRADE | WATCH | AVOID
            "verdict_reason": verdict_reason,
            "questions": [q1, q2, q3, q4, q5, q6],
            "confidence_pyramid": pyramid,
            "confidence_attribution": lr.get("confidence_attribution") or {},
            "invalidation": q6["answer"],
            "event_regime": event_regime,
            "event_headline": event_headline,
            "headline": _headline(verdict, conf, event_regime, event_headline),
        }
    except Exception as e:
        return _empty(f"Decision intelligence recovered from error: {e}")


def _dealer_answer(gr: str, db: str, pin: float, magnet) -> str:
    parts = []
    if "NEGATIVE" in gr:
        parts.append("Dealers short gamma — they amplify moves (trend-friendly)")
    elif "POSITIVE" in gr:
        parts.append("Dealers long gamma — they dampen moves (pin/mean-revert)")
    else:
        parts.append("Gamma regime unclear")
    if pin >= 60:
        parts.append(f"pin risk elevated ({pin:.0f}%)")
    if magnet:
        parts.append(f"nearest magnet {magnet}")
    return "; ".join(parts) + "."


def _inst_answer(ib: str, fb: str, conv: float, ici: float) -> str:
    lean = ("leaning long" if "BULL" in ib else "leaning short" if "BEAR" in ib else "no clear lean")
    flow = ("bullish flow" if "BULL" in fb else "bearish flow" if "BEAR" in fb else "mixed flow")
    gate = ("conviction clears the floor" if ici >= 65 else f"conviction below floor (ICI {ici:.0f}/65)")
    return f"Institutions {lean}; {flow} (conviction {conv:.0f}); {gate}."


def _verdict(inst: Dict[str, Any], conf: Dict[str, Any], ev: Dict[str, Any]):
    """TRADE / WATCH / AVOID from existing decision_state + confluence conviction."""
    conviction = _u(conf.get("conviction"))
    dom = _u(conf.get("dominant_side"))
    decision_state = _u(inst.get("decision_state"))
    intraday_event = ev.get("intraday_event_regime") or {}
    event_regime = _u(intraday_event.get("state") or ev.get("event_regime"))

    # Event phases are calibrated separately; impulse/pre-release never inherit
    # ordinary-session conviction. Discovery remains a WATCH until confirmed.
    if event_regime in ("EVENT_PRE_RELEASE", "EVENT_IMPULSE"):
        return ("WATCH", f"{event_regime.replace('_', ' ').title()} — scheduled-event confidence is capped; wait for measurable post-release confirmation.")
    if event_regime == "EVENT_DISCOVERY":
        return ("WATCH", "Event price discovery is active — require price, flow, and liquidity confirmation before commitment.")

    # AVOID only when there is genuinely no setup: no dominant side at all.
    if dom == "NEITHER" or conviction == "NONE":
        return ("AVOID", "No confluent setup — factors are split, no side leads.")
    if conviction == "A+":
        return ("TRADE", f"A+ {dom.lower()} confluence — decisive confirmations aligned.")
    if conviction == "STRONG":
        return ("TRADE", f"Strong {dom.lower()} confluence — most confirmations aligned.")
    # A side leads with real evidence but confirmations are incomplete (WEAK/MODERATE)
    # → this is a WATCH, not an AVOID. A setup is forming; wait for the trigger.
    return ("WATCH", f"{dom.title()} setup forming but not confirmed — "
                     f"waiting on the missing confirmations before it's tradeable.")


def _confidence_pyramid(lr, inst, conf, ev) -> List[Dict[str, Any]]:
    """Layered provenance: each tier must hold for the decision to be trusted."""
    ms = lr.get("market_state") or {}
    data_ok = bool(ms.get("price"))
    signals_ok = bool(inst.get("available", True) and inst.get("institutional_bias"))
    confluence_ok = bool(conf.get("available") and _u(conf.get("dominant_side")) != "NEITHER")
    ici = _sf(inst.get("ici_score"))
    conviction_ok = ici >= 65 and _u(conf.get("conviction")) in ("STRONG", "A+")
    return [
        {"tier": "Data", "label": "Live price + structure present", "ok": data_ok},
        {"tier": "Signals", "label": "Institutional layer populated", "ok": signals_ok},
        {"tier": "Confluence", "label": "A directional setup is forming", "ok": confluence_ok},
        {"tier": "Conviction", "label": "ICI≥65 and strong confluence", "ok": conviction_ok},
    ]


def _headline(verdict, conf, event_regime, event_headline) -> str:
    dom = _u(conf.get("dominant_side"))
    side = dom.title() if dom in ("LONG", "SHORT") else ""
    base = {
        "TRADE": f"TRADE {side}".strip(),
        "WATCH": f"WATCH {side}".strip(),
        "AVOID": "STAND ASIDE",
    }.get(verdict, verdict)
    if event_regime in ("EVENT_PRE_RELEASE", "EVENT_IMPULSE", "EVENT_DISCOVERY", "POST_EVENT_NORMALIZATION", "EVENT_DAY", "OPEX_DAY") and event_headline:
        base += f"  ·  {event_headline} · {event_regime.replace('_', ' ').title()}"
    elif event_regime == "PRE_EVENT_COMPRESSION" and event_headline:
        base += f"  ·  {event_headline} tomorrow"
    return base


def _empty(note: str) -> Dict[str, Any]:
    return {
        "available": False, "version": VERSION,
        "verdict": "AVOID", "verdict_reason": note,
        "questions": [], "confidence_pyramid": [], "confidence_attribution": {}, "invalidation": [],
        "event_regime": "CLEAR", "event_headline": None,
        "headline": "STAND ASIDE", "note": note,
    }
