"""APEX 11.2 Institutional Market Narrative Engine.

Deterministic, provider-agnostic composition over normalized APEX outputs.
No historical performance claims and no provider queries are permitted here.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

VERSION = "11.2.0"
SCHEMA_VERSION = "apex.institutional_narrative.v1"
REQUIRED_LIVE_DOMAINS = ("market_state", "institutional_intelligence")


def _num(value: Any) -> Optional[float]:
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def _text(value: Any, default: str = "UNKNOWN") -> str:
    value = str(value or "").strip()
    return value if value else default


def _dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _direction(value: Any) -> str:
    s = _text(value).upper().replace(" ", "_")
    if any(x in s for x in ("BULL", "CALL", "UP", "LONG", "BUY")):
        return "BULLISH"
    if any(x in s for x in ("BEAR", "PUT", "DOWN", "SHORT", "SELL")):
        return "BEARISH"
    return "NEUTRAL"


def _quality(last: Mapping[str, Any], session_state: str) -> Dict[str, Any]:
    missing = [name for name in REQUIRED_LIVE_DOMAINS if not _dict(last.get(name))]
    market = _dict(last.get("market_state"))
    stale = bool(market.get("data_stale") or last.get("data_stale"))
    price = _num(market.get("price") or last.get("price"))
    closed = session_state in {"CLOSED", "AFTER_HOURS", "WEEKEND", "HOLIDAY", "MARKET_CLOSED"}
    flags: List[str] = []
    if missing:
        flags.append("REQUIRED_NORMALIZED_OUTPUT_MISSING")
    if stale:
        flags.append("STALE_LIVE_DATA")
    if price is None and not closed:
        flags.append("LIVE_PRICE_UNAVAILABLE")
    live_ok = not closed and not missing and not stale and price is not None
    status = "CLOSED" if closed else "LIVE" if live_ok else "DEGRADED"
    return {"status": status, "live_ok": live_ok, "closed": closed, "missing_domains": missing, "flags": flags}


def build_consensus_gauge(last_result: Mapping[str, Any]) -> Dict[str, Any]:
    """Deterministic, reliability-aware agreement over normalized outputs only."""
    last = _dict(last_result); market = _dict(last.get("market_state")); ii = _dict(last.get("institutional_intelligence"))
    specs = [
      ("institutional_intelligence", ii.get("institutional_bias") or ii.get("bias"), 1.5, ii.get("freshness")),
      ("auction", _dict(last.get("auction_intelligence")).get("bias") or market.get("auction_bias"), 1.2, _dict(last.get("auction_intelligence")).get("freshness")),
      ("flow", market.get("flow_bias") or _dict(last.get("flow_intelligence_2")).get("flow_bias"), 1.2, _dict(last.get("flow_intelligence_2")).get("freshness")),
      ("dealer", _dict(_dict(last.get("dealer_positioning")).get("delta")).get("bias") or _dict(last.get("dealer_positioning")).get("bias"), 1.0, _dict(last.get("dealer_positioning")).get("freshness")),
      ("structure", _dict(last.get("confirmation")).get("bias") or _dict(last.get("structure")).get("bias"), 1.0, _dict(last.get("structure")).get("freshness")),
      ("breadth", _dict(last.get("market_drivers")).get("breadth") or _dict(last.get("breadth")).get("bias"), .8, _dict(last.get("breadth")).get("freshness")),
      ("execution", _dict(last.get("execution_intelligence")).get("approved_side") or _dict(last.get("execution_os")).get("side"), .8, _dict(last.get("execution_intelligence")).get("freshness")),
    ]
    sources=[]; stale=[]; unavailable=[]
    for name,raw,weight,fresh in specs:
        if raw in (None,""): unavailable.append(name); continue
        fs=_text(fresh,"CURRENT").upper(); is_stale=fs in {"STALE","EXPIRED","DEGRADED"}
        if is_stale: stale.append(name)
        effective=weight*(.25 if is_stale else 1.0)
        sources.append({"source":name,"direction":_direction(raw),"weight":weight,"effective_weight":effective,"freshness":fs,"reason":f"normalized {name} evidence"})
    eligible=[x for x in sources if x["effective_weight"]>0]
    bull=sum(x["effective_weight"] for x in eligible if x["direction"]=="BULLISH"); bear=sum(x["effective_weight"] for x in eligible if x["direction"]=="BEARISH"); neutral=sum(x["effective_weight"] for x in eligible if x["direction"]=="NEUTRAL")
    directional=bull+bear; total=directional+neutral
    dominant="BULLISH" if bull>bear else "BEARISH" if bear>bull else "NEUTRAL"
    agreement_count=sum(1 for x in eligible if x["direction"]==dominant) if dominant!="NEUTRAL" else 0
    eligible_count=len(eligible); pct=round(agreement_count/eligible_count*100,1) if eligible_count else 0.0
    contradiction=round(min(bull,bear)/directional*200,1) if directional else 0.0
    dissenters=[x["source"] for x in eligible if x["direction"] not in {dominant,"NEUTRAL"}]
    too_few=eligible_count<3; severity="SEVERE" if contradiction>=60 else "MATERIAL" if contradiction>=35 else "LOW"
    grade="A" if pct>=80 and contradiction<20 else "B" if pct>=65 and contradiction<35 else "C" if pct>=50 else "D"
    status="UNAVAILABLE" if not eligible_count else "DEGRADED" if too_few or stale else "AVAILABLE"
    guidance="DO_NOT_TRADE" if too_few else "REDUCE_SIZE" if severity in {"MATERIAL","SEVERE"} else "NORMAL_INFORMATIONAL_SIZE"
    explanation=("Too few reliable engines are available; consensus fails closed." if too_few else f"{agreement_count} of {eligible_count} eligible engines support {dominant.lower()}; contradiction is {severity.lower()}.")
    return {"schema_version":"apex.consensus.v2","dominant_direction":dominant,"direction":dominant,"agreement_count":agreement_count,"eligible_count":eligible_count,"agreement_percentage":pct,"score":pct,"consensus_grade":grade,"dissenters":dissenters,"opposed_sources":dissenters,"contradiction_severity":severity,"conflict_score":min(100.0,contradiction),"stale_sources":stale,"unavailable_sources":unavailable,"explanation":explanation,"policy_guidance":guidance,"institutional_divergence_warning":severity in {"MATERIAL","SEVERE"},"status":status,"source_count":eligible_count,"sources":sources,"aligned_sources":[x["source"] for x in eligible if x["direction"]==dominant]}

def build_conviction(last_result: Mapping[str, Any], consensus: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    last=_dict(last_result); consensus=_dict(consensus) or build_consensus_gauge(last); ii=_dict(last.get("institutional_intelligence"))
    confidence=_num(ii.get("confidence") or ii.get("institutional_confidence") or last.get("final_live_confidence"))
    execution=_dict(last.get("execution_intelligence") or last.get("execution_os")); position=_dict(last.get("position_quality") or last.get("position_quality_snapshot")); readiness=_dict(last.get("readiness") or last.get("morning_readiness"))
    provider=_dict(last.get("provider_health")); event=_dict(last.get("event_intelligence") or last.get("event_risk"))
    values={"confidence":confidence,"consensus":_num(consensus.get("agreement_percentage")),"execution":_num(execution.get("execution_score") or execution.get("score")),"position_quality":_num(position.get("score") or position.get("position_quality_score")),"readiness":_num(readiness.get("score") or readiness.get("readiness_score"))}
    weights={"confidence":.30,"consensus":.25,"execution":.18,"position_quality":.15,"readiness":.12}; contributors=[]; detractors=[]; available=[]
    for k,v in values.items():
        if v is not None: available.append((k,v,weights[k])); (contributors if v>=70 else detractors).append({"driver":k,"value":round(v,1),"weight":weights[k]})
    blockers=[]
    if consensus.get("status") in {"UNAVAILABLE","DEGRADED"} and consensus.get("eligible_count",0)<3: blockers.append("INSUFFICIENT_RELIABLE_ENGINES")
    if _text(execution.get("status")).upper() in {"BLOCKED","UNAVAILABLE","DO_NOT_TRADE"}: blockers.append("EXECUTION_BLOCKED")
    if _text(readiness.get("trading_mode")).upper()=="DO_NOT_TRADE": blockers.append("READINESS_DO_NOT_TRADE")
    if provider and provider.get("critical_failure"): blockers.append("CRITICAL_PROVIDER_FAILURE")
    base=sum(v*w for _,v,w in available)/sum(w for _,_,w in available) if available else 0.0
    penalty=(_num(consensus.get("conflict_score")) or 0)*.2
    if _text(event.get("risk_level") or event.get("severity"),"LOW").upper() in {"HIGH","EXTREME","CRITICAL"}: penalty+=10; detractors.append({"driver":"event_risk","value":10,"weight":"penalty"})
    score=max(0.0,min(100.0,base-penalty)); score=0.0 if blockers else score
    classification="EXTREME" if score>=95 else "VERY_HIGH" if score>=85 else "HIGH" if score>=75 else "MODERATE" if score>=55 else "LOW"
    grade="A+" if score>=95 else "A" if score>=85 else "B" if score>=75 else "C" if score>=55 else "D"
    status="UNAVAILABLE" if not available else "BLOCKED" if blockers else "AVAILABLE"
    return {"schema_version":"apex.conviction.v2","score":round(score,1),"conviction_score":round(score,1),"grade":grade,"conviction_grade":grade,"classification":classification,"band":classification,"contributors":contributors,"detractors":detractors,"explanation":"Conviction combines current confidence, agreement, execution, position quality, readiness, freshness, provider health, contradiction, and event risk without historical win-rate claims.","blocking_conditions":blockers,"fail_closed":bool(blockers) or not available,"status":status,"direction":consensus.get("dominant_direction","NEUTRAL"),"historical_calibration_applied":False}

def build_institutional_narrative(last_result: Mapping[str, Any], *, session_state: Optional[str] = None,
                                  generated_at: Optional[str] = None) -> Dict[str, Any]:
    last = _dict(last_result)
    market = _dict(last.get("market_state"))
    ii = _dict(last.get("institutional_intelligence"))
    session = _text(session_state or last.get("session") or market.get("session_state"), "UNKNOWN").upper()
    quality = _quality(last, session)
    consensus = build_consensus_gauge(last)
    conviction = build_conviction(last, consensus)
    price = _num(market.get("price") or last.get("price"))
    regime = _text(ii.get("market_regime") or market.get("regime") or last.get("regime"), "UNCONFIRMED")
    bias = consensus.get("direction", "NEUTRAL")
    risks: List[str] = []
    invalidations: List[Dict[str, Any]] = []

    for key, label in (("vah", "value-area high"), ("val", "value-area low"), ("poc", "point of control")):
        level = _num(market.get(key))
        if level is not None:
            invalidations.append({"level": level, "label": label, "condition": f"Sustained acceptance through {level:.2f} changes the active thesis."})
    if consensus.get("conflict_score", 0) >= 45:
        risks.append("Material cross-engine disagreement reduces decision quality.")
    event = _dict(last.get("event_intelligence") or last.get("event_risk"))
    if event:
        risks.append(_text(event.get("summary") or event.get("message"), "Scheduled event risk may alter volatility and direction."))
    if quality["flags"]:
        risks.extend(quality["flags"])

    primary = _text(ii.get("primary_thesis") or ii.get("highest_probability_scenario"), "")
    if not primary:
        primary = f"{bias.title()} institutional pressure in a {regime.replace('_', ' ').lower()} regime."
    alternate_dir = "BEARISH" if bias == "BULLISH" else "BULLISH" if bias == "BEARISH" else "DIRECTIONAL"
    alternate = _text(ii.get("alternate_thesis"), f"{alternate_dir.title()} alternative activates if acceptance invalidates the primary structure.")
    drivers = [s["reason"] for s in consensus.get("sources", []) if s["direction"] == bias][:5]
    next_event = _text(event.get("next_event") or event.get("name") or ii.get("next_decision_point"), "Next acceptance/rejection at the nearest institutional reference level.")

    if quality["closed"]:
        summary = f"Market closed. Last normalized state was {bias.lower()} with {conviction['band'].lower()} conviction. Live trade guidance is disabled."
    elif not quality["live_ok"]:
        summary = "Live institutional narrative unavailable because required normalized data is missing, stale, or untradeable. APEX is failing closed."
    else:
        px = f" near {price:.2f}" if price is not None else ""
        summary = f"SPX is{px} in a {regime.replace('_', ' ').lower()} regime. Institutional consensus is {bias.lower()} at {consensus['score']:.0f}/100 with {conviction['band'].lower()} conviction."

    payload = {
        "schema_version": SCHEMA_VERSION, "engine_version": VERSION, "generated_at": generated_at or _utcnow(),
        "status": quality["status"], "trade_guidance_enabled": bool(quality["live_ok"]),
        "executive_summary": summary,
        "market_state": {"session": session, "price": price, "regime": regime, "bias": bias},
        "primary_thesis": primary if quality["live_ok"] or quality["closed"] else "NO_LIVE_THESIS",
        "alternate_thesis": alternate,
        "confidence_drivers": drivers,
        "risk_drivers": risks or ["No material normalized risk driver was supplied."],
        "invalidation_conditions": invalidations,
        "next_expected_event": next_event,
        "morning_narrative": summary if session in {"PREMARKET", "PRE_MARKET", "OVERNIGHT"} else None,
        "intraday_update": summary if session in {"MARKET_OPEN", "RTH", "REGULAR"} else None,
        "consensus": consensus, "conviction": conviction,
        "data_quality": quality,
    }
    payload["snapshot_hash"] = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    return payload
