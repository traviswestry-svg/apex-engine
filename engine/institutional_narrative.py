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

from .decision_reasoning_contracts import (
    build_engine_opinions, build_correlation_aware_consensus, normalize_acceptance,
    build_reasoning_evidence_graph,
)

VERSION = "66.3.2"
SCHEMA_VERSION = "apex.institutional_narrative.v2"
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


def resolve_session_state(last: Mapping[str, Any], explicit: Optional[str] = None) -> str:
    """Resolve the canonical market session from existing APEX state, then clock fallback."""
    market = _dict(last.get("market_state"))
    ii = _dict(last.get("institutional_intelligence"))
    session_obj = _dict(last.get("session"))
    market_status = _dict(last.get("market_status"))
    runtime = _dict(last.get("runtime_health"))
    candidates = [
        explicit,
        last.get("session") if isinstance(last.get("session"), str) else None,
        session_obj.get("session_state") or session_obj.get("session") or session_obj.get("state"),
        market.get("session_state") or market.get("session"),
        ii.get("session_state"),
        market_status.get("session_state") or market_status.get("session") or market_status.get("state"),
        runtime.get("session"),
    ]
    for value in candidates:
        if value not in (None, ""):
            return _text(value, "UNKNOWN").upper()
    try:
        from .live_operations import session_state as _live_session_state
        return _text(_live_session_state(), "UNKNOWN").upper()
    except Exception:
        return "UNKNOWN"


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
    closed = session_state in {"CLOSED", "AFTER_HOURS", "WEEKEND", "HOLIDAY", "MARKET_CLOSED", "OVERNIGHT"}
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
    """Canonical correlation-aware consensus over normalized EngineOpinion objects."""
    opinions = build_engine_opinions(last_result)
    return build_correlation_aware_consensus(opinions)

def build_conviction(last_result: Mapping[str, Any], consensus: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Produce raw conviction separately from any historically calibrated conviction.

    Calibration is deliberately fail-closed. Existing graded-history governance is
    consulted only for maturity; no probability is fabricated from aggregate win rate.
    """
    last=_dict(last_result); consensus=_dict(consensus) or build_consensus_gauge(last); ii=_dict(last.get("institutional_intelligence"))
    confidence=_num(ii.get("confidence") or ii.get("institutional_confidence") or last.get("final_live_confidence"))
    execution=_dict(last.get("execution_intelligence") or last.get("execution_os")); position=_dict(last.get("position_quality") or last.get("position_quality_snapshot")); readiness=_dict(last.get("readiness") or last.get("morning_readiness"))
    provider=_dict(last.get("provider_health")); event=_dict(last.get("event_intelligence") or last.get("event_risk"))
    values={"confidence":confidence,"consensus":_num(consensus.get("effective_consensus") or consensus.get("agreement_percentage")),"execution":_num(execution.get("execution_score") or execution.get("score")),"position_quality":_num(position.get("score") or position.get("position_quality_score")),"readiness":_num(readiness.get("score") or readiness.get("readiness_score"))}
    weights={"confidence":.30,"consensus":.25,"execution":.18,"position_quality":.15,"readiness":.12}; contributors=[]; detractors=[]; available=[]
    for k,v in values.items():
        if v is not None: available.append((k,v,weights[k])); (contributors if v>=70 else detractors).append({"driver":k,"value":round(v,1),"weight":weights[k]})
    blockers=[]
    if consensus.get("status") in {"UNAVAILABLE","DEGRADED"} and len(consensus.get("active_clusters") or [])<3: blockers.append("INSUFFICIENT_INDEPENDENT_EVIDENCE")
    if _text(execution.get("status")).upper() in {"BLOCKED","UNAVAILABLE","DO_NOT_TRADE"}: blockers.append("EXECUTION_BLOCKED")
    if _text(readiness.get("trading_mode")).upper()=="DO_NOT_TRADE": blockers.append("READINESS_DO_NOT_TRADE")
    if provider and provider.get("critical_failure"): blockers.append("CRITICAL_PROVIDER_FAILURE")
    base=sum(v*w for _,v,w in available)/sum(w for _,_,w in available) if available else 0.0
    penalty=(_num(consensus.get("disagreement")) or 0)*.25
    penalty+=(_num(consensus.get("redundant_evidence_score")) or 0)*.08
    if _text(event.get("risk_level") or event.get("severity"),"LOW").upper() in {"HIGH","EXTREME","CRITICAL"}: penalty+=10; detractors.append({"driver":"event_risk","value":10,"weight":"penalty"})
    raw=max(0.0,min(100.0,base-penalty)); raw=0.0 if blockers else raw
    classification="EXTREME" if raw>=95 else "VERY_HIGH" if raw>=85 else "HIGH" if raw>=75 else "MODERATE" if raw>=55 else "LOW"
    grade="A+" if raw>=95 else "A" if raw>=85 else "B" if raw>=75 else "C" if raw>=55 else "D"
    status="UNAVAILABLE" if not available else "BLOCKED" if blockers else "AVAILABLE"
    calibration_state="INSUFFICIENT_HISTORY"; calibration_samples=0; calibration_minimum=None
    try:
        from . import institutional_governance as _gov
        hist=_gov.history_report(_gov.MIN_GRADED)
        calibration_samples=int(hist.get("sample_size") or 0); calibration_minimum=int(hist.get("minimum_evidence") or _gov.MIN_GRADED)
        calibration_state=str(hist.get("status") or "INSUFFICIENT_HISTORY")
        if calibration_state=="COLLECTING": calibration_state="INSUFFICIENT_HISTORY"
        elif calibration_state=="READY_FOR_CALIBRATION": calibration_state="READY_FOR_CALIBRATION_MODEL"
    except Exception:
        calibration_state="INSUFFICIENT_HISTORY"
    return {"schema_version":"apex.conviction.v3","score":round(raw,1),"conviction_score":round(raw,1),"raw_conviction":round(raw,1),"calibrated_conviction":None,"calibration_state":calibration_state,"calibration_sample_size":calibration_samples,"calibration_minimum":calibration_minimum,"grade":grade,"conviction_grade":grade,"classification":classification,"band":classification,"contributors":contributors,"detractors":detractors,"explanation":"Raw conviction combines current evidence coverage, correlation-aware consensus, execution, position quality, readiness and risk penalties. Calibrated conviction remains null until an approved calibration model is supported by sufficient graded history.","blocking_conditions":blockers,"fail_closed":bool(blockers) or not available,"status":status,"direction":consensus.get("dominant_direction","NEUTRAL"),"historical_calibration_applied":False}

def build_institutional_narrative(last_result: Mapping[str, Any], *, session_state: Optional[str] = None,
                                  generated_at: Optional[str] = None) -> Dict[str, Any]:
    last = _dict(last_result)
    market = _dict(last.get("market_state"))
    ii = _dict(last.get("institutional_intelligence"))
    session = resolve_session_state(last, session_state)
    quality = _quality(last, session)
    opinions = build_engine_opinions(last)
    consensus = build_correlation_aware_consensus(opinions)
    acceptance = normalize_acceptance(last)
    conviction = build_conviction(last, consensus)
    reasoning_graph = build_reasoning_evidence_graph(opinions, consensus, acceptance)
    price = _num(market.get("price") or last.get("price"))
    regime = _text(ii.get("market_regime") or market.get("regime") or last.get("regime"), "UNCONFIRMED")
    bias = consensus.get("direction", "UNKNOWN")
    risks: List[str] = []
    invalidations: List[Dict[str, Any]] = []

    for key, label in (("vah", "value-area high"), ("val", "value-area low"), ("poc", "point of control")):
        level = _num(market.get(key))
        if level is not None:
            invalidations.append({"level": level, "label": label, "condition": f"Sustained acceptance through {level:.2f} changes the active thesis.", "trigger_type": "PRICE_ACCEPTANCE", "operator": "THROUGH_REFERENCE_LEVEL", "reference_price": level, "acceptance_required": True, "severity": "SOFT", "machine_evaluable": False})

    # Hard invalidation is only created from explicit existing risk/stop inputs.
    # APEX must never infer a hard stop from nearby reference levels or prose.
    recommendation = _dict(last.get("recommendation") or last.get("premium_strategy"))
    decision_levels = _dict(last.get("decision_levels") or recommendation.get("levels"))
    explicit_hard: List[Dict[str, Any]] = []
    for source_name, source in (("recommendation", recommendation), ("decision_levels", decision_levels), ("market_state", market), ("institutional_intelligence", ii)):
        for field in ("hard_invalidation", "hard_invalidation_level", "invalidation_level", "stop_price", "stop_loss", "stop"):
            raw = source.get(field)
            if isinstance(raw, Mapping):
                level = _num(raw.get("level") or raw.get("price") or raw.get("value"))
                operator = _text(raw.get("operator"), "").upper()
            else:
                level = _num(raw); operator = ""
            if level is None:
                continue
            if not operator:
                if bias == "BULLISH": operator = "AT_OR_BELOW"
                elif bias == "BEARISH": operator = "AT_OR_ABOVE"
                else: continue
            if operator not in {"LT","LTE","BELOW","AT_OR_BELOW","GT","GTE","ABOVE","AT_OR_ABOVE","CROSSES_BELOW","CROSSES_ABOVE"}:
                continue
            explicit_hard.append({
                "level": level, "label": field, "condition": f"Explicit {field} from {source_name} invalidates the thesis.",
                "trigger_type": "EXPLICIT_HARD_INVALIDATION", "operator": operator, "severity": "HARD",
                "machine_evaluable": True, "source": source_name, "source_field": field,
            })
    # De-duplicate identical explicit triggers while preserving provenance.
    seen_hard=set(); hard_invalidations=[]
    for row in explicit_hard:
        key=(row.get("operator"), round(float(row.get("level")),8))
        if key in seen_hard: continue
        seen_hard.add(key); hard_invalidations.append(row)
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
    drivers = [f"normalized {(s.get('engine_name') or s.get('source') or 'engine')} evidence" for s in consensus.get("sources", []) if s.get("direction") == bias][:5]
    next_event = _text(event.get("next_event") or event.get("name") or ii.get("next_decision_point"), "Next acceptance/rejection at the nearest institutional reference level.")

    if not quality["live_ok"] and not quality["closed"]:
        thesis_state = "UNKNOWN"
    elif consensus.get("conflicted_clusters") or consensus.get("disagreement", 0) >= 20:
        thesis_state = "CONFLICTED"
    elif bias in {"BULLISH", "BEARISH"} and conviction.get("raw_conviction", 0) >= 55:
        thesis_state = "ACTIVE"
    else:
        thesis_state = "FORMING"

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
        "engine_opinions": opinions, "acceptance": acceptance,
        "consensus": consensus, "conviction": conviction,
        "thesis": {
            "schema_version": "apex.institutional_thesis.v2",
            "state": thesis_state, "current_thesis": primary if quality["live_ok"] or quality["closed"] else "NO_LIVE_THESIS",
            "alternative_thesis": alternate, "dominant_direction": bias, "market_regime": regime,
            "supporting_engines": consensus.get("supporting_engines", []),
            "contradicting_engines": consensus.get("contradicting_engines", []),
            "abstaining_engines": consensus.get("abstaining_engines", []),
            "known_unknowns": sorted({o.get("abstain_reason") for o in opinions if o.get("abstain") and o.get("abstain_reason")}),
            "expected_next_event": next_event, "consensus": consensus.get("effective_consensus"),
            "raw_conviction": conviction.get("raw_conviction"), "calibrated_conviction": conviction.get("calibrated_conviction"),
            "hard_invalidation": hard_invalidations, "soft_invalidation": invalidations,
            "provenance": {"source": "institutional_narrative", "engine_version": VERSION},
        },
        "evidence_conflict_matrix": consensus.get("conflict_matrix", []),
        "evidence_graph": reasoning_graph,
        "data_quality": quality,
    }
    payload["snapshot_hash"] = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    return payload
