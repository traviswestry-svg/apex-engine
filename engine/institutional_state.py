"""APEX 10 Sprint 7 — canonical institutional state and evidence graph.

This layer composes already-computed engine outputs. It does not fetch market data,
re-score direction, or allow historical evidence to become a live trade signal.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Optional

VERSION = "10.0.1_INSTITUTIONAL_STATE_STATUS"


def _d(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any, default: str = "UNKNOWN") -> str:
    text = str(value or default).strip()
    return text if text else default


def _num(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _node(node_id: str, label: str, *, state: str, direction: str = "NEUTRAL",
          confidence: Optional[float] = None, available: bool = True,
          evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "id": node_id,
        "label": label,
        "state": state,
        "direction": direction,
        "confidence": confidence,
        "available": bool(available),
        "evidence": deepcopy(evidence or {}),
    }


def _direction(value: Any) -> str:
    v = _text(value, "NEUTRAL").upper()
    if any(x in v for x in ("BULL", "CALL", "BUY", "HIGHER", "RISING")):
        return "BULLISH"
    if any(x in v for x in ("BEAR", "PUT", "SELL", "LOWER", "FALLING")):
        return "BEARISH"
    return "NEUTRAL"



def _is_after_hours(result: Dict[str, Any]) -> bool:
    ii = _d(result.get("institutional_intelligence"))
    session = _text(ii.get("session_state") or _d(result.get("session")).get("session_state") or result.get("session"), "UNKNOWN").upper()
    system_mode = _text(result.get("system_mode") or _d(result.get("system_mode_detail")).get("mode"), "UNKNOWN").upper()
    return session in {"AFTER_HOURS", "PRE_MARKET", "MARKET_CLOSED", "CLOSED"} or system_mode in {"OVERNIGHT", "CLOSED"}


def _evidence_alignment(nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    directional = [n for n in nodes if n.get("available") and n.get("id") not in {"confidence", "quality", "event", "liquidity", "volatility"} and n.get("direction") in {"BULLISH", "BEARISH"}]
    bullish = [n["id"] for n in directional if n.get("direction") == "BULLISH"]
    bearish = [n["id"] for n in directional if n.get("direction") == "BEARISH"]
    if bullish and bearish:
        state = "MIXED"
    elif bullish:
        state = "BULLISH_ALIGNED"
    elif bearish:
        state = "BEARISH_ALIGNED"
    else:
        state = "NEUTRAL_OR_UNMEASURABLE"
    return {"state": state, "bullish_domains": bullish, "bearish_domains": bearish, "directional_domain_count": len(directional)}


def _build_nodes(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    ms = _d(result.get("market_state"))
    ii = _d(result.get("institutional_intelligence"))
    auction = _d(result.get("auction_intelligence")) or _d(result.get("auction"))
    flow = _d(result.get("flow_intelligence_2")) or _d(result.get("flow_intelligence"))
    dealer = _d(result.get("dealer_positioning"))
    volatility = _d(result.get("volatility"))
    execution = _d(result.get("execution_intelligence")) or _d(result.get("execution"))
    event = _d(result.get("intraday_event_regime")) or _d(_d(result.get("event_intelligence")).get("intraday_event_regime"))
    attribution = _d(result.get("confidence_attribution"))
    quality = _d(result.get("chain_quality")) or _d(ms.get("chain_quality"))
    gate = _d(result.get("chain_quality_gate")) or _d(ms.get("chain_quality_gate"))

    auction_state = _text(ii.get("auction_bias") or ms.get("auction_state") or auction.get("auction_state"))
    flow_state = _text(ii.get("flow_bias") or ms.get("flow_bias") or flow.get("flow_bias"), "MIXED")
    gamma_state = _text(ii.get("gamma_regime") or _d(dealer.get("gamma")).get("regime") or ms.get("gamma_regime"))
    liquidity_state = _text(execution.get("liquidity_state") or execution.get("market_quality") or "UNKNOWN")
    event_state = _text(event.get("state") or event.get("regime"), "NORMAL_SESSION")
    confidence = _num(attribution.get("calibrated_confidence") or attribution.get("effective_confidence") or result.get("confidence"))
    quality_score = _num(quality.get("quality_score") or quality.get("score"))
    gate_action = _text(gate.get("action") or ("ALLOW" if quality.get("gate_passed") is True else "SUPPRESS" if quality.get("gate_passed") is False else "UNKNOWN"))
    after_hours = _is_after_hours(result)
    quality_state = "NO_LIVE_CHAIN" if after_hours and not quality_score else gate_action
    liquidity_display_state = "NOT_MEASURABLE_AFTER_HOURS" if after_hours and liquidity_state == "UNKNOWN" else liquidity_state

    return [
        _node("auction", "Auction", state=auction_state, direction=_direction(auction_state),
              confidence=_num(ii.get("auction_confidence")), available=auction_state != "UNKNOWN",
              evidence={"poc_migration": ms.get("poc_migration"), "acceptance": ii.get("acceptance")}),
        _node("flow", "Institutional Flow", state=flow_state, direction=_direction(flow_state),
              confidence=_num(ii.get("flow_conviction") or flow.get("flow_score")), available=bool(flow),
              evidence={"urgency": ii.get("flow_urgency"), "contradictions": ii.get("flow_contradictions") or []}),
        _node("dealer", "Dealer Positioning", state=gamma_state,
              direction=_direction(ii.get("delta_bias") or _d(dealer.get("delta")).get("bias")),
              confidence=_num(_d(dealer.get("gamma")).get("confidence")), available=bool(dealer),
              evidence={"delta_bias": ii.get("delta_bias"), "pin_probability": ii.get("pin_probability")}),
        _node("volatility", "Volatility", state=_text(ii.get("vol_regime") or volatility.get("regime"), "NORMAL"),
              direction="NEUTRAL", confidence=_num(volatility.get("confidence")), available=bool(volatility),
              evidence={"expected_path": ii.get("vol_path") or volatility.get("expected_vol_path")}),
        _node("liquidity", "Liquidity", state=liquidity_display_state, direction="NEUTRAL",
              confidence=_num(execution.get("liquidity_confidence")), available=liquidity_state != "UNKNOWN",
              evidence={"slippage": execution.get("slippage"), "spread_quality": execution.get("spread_quality"), "measurement_state": liquidity_display_state}),
        _node("event", "Event Regime", state=event_state, direction="NEUTRAL",
              confidence=_num(event.get("confidence_multiplier")), available=True,
              evidence={"event_type": event.get("event_type"), "release_time": event.get("release_time")}),
        _node("quality", "Data Quality", state=quality_state, direction="NEUTRAL", confidence=quality_score,
              available=bool(quality or gate) or after_hours, evidence={"quality_score": quality_score, "multiplier": gate.get("multiplier"), "gate_action": gate_action, "measurement_state": quality_state}),
        _node("confidence", "Decision Confidence", state="CALIBRATED" if attribution.get("calibrated_confidence") is not None else "EFFECTIVE",
              direction=_direction(ii.get("institutional_bias") or result.get("decision_state")), confidence=confidence,
              available=confidence is not None, evidence={"attribution": attribution}),
    ]


def _build_edges(nodes: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id = {n["id"]: n for n in nodes}
    edges: List[Dict[str, Any]] = []
    for source in ("auction", "flow", "dealer", "volatility", "liquidity", "event", "quality"):
        if source in by_id:
            relation = "CALIBRATES" if source in ("event", "quality") else "CONTRIBUTES_TO"
            edges.append({"source": source, "target": "confidence", "relation": relation})
    for a, b in (("auction", "flow"), ("flow", "dealer"), ("volatility", "dealer")):
        if a in by_id and b in by_id:
            da, db = by_id[a]["direction"], by_id[b]["direction"]
            relation = "AGREES_WITH" if da == db and da != "NEUTRAL" else "CONFLICTS_WITH" if da != "NEUTRAL" and db != "NEUTRAL" else "CONTEXTUALIZES"
            edges.append({"source": a, "target": b, "relation": relation})
    return edges


def _build_trace(result: Dict[str, Any], nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ii = _d(result.get("institutional_intelligence"))
    decision = _text(result.get("decision_state") or ii.get("decision_state"), "NO_TRADE")
    available = [n for n in nodes if n.get("available")]
    bull = [n["id"] for n in available if n.get("direction") == "BULLISH"]
    bear = [n["id"] for n in available if n.get("direction") == "BEARISH"]
    conflicts = sorted(set(bull) & set(bear))
    return [
        {"step": 1, "name": "INGEST", "status": "COMPLETE", "detail": f"{len(available)} evidence domains available."},
        {"step": 2, "name": "QUALITY_GATE", "status": _text(next((n["state"] for n in nodes if n["id"] == "quality"), "UNKNOWN")), "detail": "Chain-derived evidence is allowed, capped, or suppressed before orchestration."},
        {"step": 3, "name": "SYNTHESIZE", "status": "COMPLETE", "detail": f"Bullish domains: {len(bull)}; bearish domains: {len(bear)}."},
        {"step": 4, "name": "CONFLICT_CHECK", "status": "CLEAR" if not conflicts else "REVIEW", "detail": "Cross-engine disagreement remains visible and is never hidden."},
        {"step": 5, "name": "DECISION", "status": decision, "detail": _text(ii.get("decision_recommendation"), "No canonical recommendation available.")},
    ]


def _story(result: Dict[str, Any], nodes: List[Dict[str, Any]], alignment: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ii = _d(result.get("institutional_intelligence"))
    bias = _text(ii.get("institutional_bias") or result.get("decision_state"), "NEUTRAL")
    alignment = alignment or _evidence_alignment(nodes)
    parts = []
    for node_id in ("auction", "dealer", "flow", "volatility", "event", "quality"):
        node = next((n for n in nodes if n["id"] == node_id and n.get("available")), None)
        if node:
            parts.append(f"{node['label']}: {node['state'].replace('_', ' ').lower()}")
    narrative = "; ".join(parts) + "." if parts else "Institutional evidence is not yet available."
    headline = f"{bias.replace('_', ' ').title()} institutional state"
    if alignment.get("state") == "MIXED":
        headline = f"{bias.replace('_', ' ').title()} bias · mixed evidence"
    return {
        "headline": headline,
        "evidence_alignment": alignment.get("state"),
        "narrative": narrative,
        "decision_recommendation": ii.get("decision_recommendation") or result.get("recommendation") or "NO TRADE",
        "highest_probability_scenario": ii.get("highest_probability_scenario"),
        "primary_risk": ii.get("primary_risk"),
        "guardrail": "Narrative is deterministic composition of engine outputs, not generated market intent.",
    }


def build_institutional_state(*, current_result: Optional[Dict[str, Any]], ticker: str = "SPX",
                              sample_id: Optional[str] = None) -> Dict[str, Any]:
    result = _d(current_result)
    nodes = _build_nodes(result)
    edges = _build_edges(nodes)
    trace = _build_trace(result, nodes)
    alignment = _evidence_alignment(nodes)
    story = _story(result, nodes, alignment)
    ii = _d(result.get("institutional_intelligence"))
    confidence_node = next((n for n in nodes if n["id"] == "confidence"), {})
    payload = {
        "available": bool(result),
        "version": VERSION,
        "ticker": _text(ticker or result.get("ticker"), "SPX").upper(),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "sample_id": sample_id,
        "market_state": {
            "bias": _text(ii.get("institutional_bias"), "NEUTRAL"),
            "decision_state": _text(result.get("decision_state") or ii.get("decision_state"), "NO_TRADE"),
            "confidence": confidence_node.get("confidence"),
            "session_state": _text(ii.get("session_state") or _d(result.get("session")).get("session_state"), "UNKNOWN"),
            "auction": next((n["state"] for n in nodes if n["id"] == "auction"), "UNKNOWN"),
            "dealer": next((n["state"] for n in nodes if n["id"] == "dealer"), "UNKNOWN"),
            "flow": next((n["state"] for n in nodes if n["id"] == "flow"), "UNKNOWN"),
            "volatility": next((n["state"] for n in nodes if n["id"] == "volatility"), "UNKNOWN"),
            "liquidity": next((n["state"] for n in nodes if n["id"] == "liquidity"), "UNKNOWN"),
            "event": next((n["state"] for n in nodes if n["id"] == "event"), "NORMAL_SESSION"),
            "quality": next((n["state"] for n in nodes if n["id"] == "quality"), "UNKNOWN"),
            "evidence_alignment": alignment["state"],
        },
        "market_status": {
            "cash_market": "CLOSED" if _is_after_hours(result) else "OPEN_OR_TRANSITION",
            "es_futures": "TRADING_OR_LAST_KNOWN" if _is_after_hours(result) else "TRADING",
            "options_chain": "UNAVAILABLE_AFTER_HOURS" if _is_after_hours(result) else "LIVE_OR_ASSESSED",
            "flow": "PAUSED_AFTER_HOURS" if _is_after_hours(result) else "LIVE_OR_ASSESSED",
            "replay": "AVAILABLE",
            "institutional_state": "CURRENT",
            "trade_engine": "DISABLED_MARKET_CLOSED" if _is_after_hours(result) else "SESSION_GUARDED",
        },
        "evidence_alignment": alignment,
        "evidence_graph": {"nodes": nodes, "edges": edges},
        "decision_trace": trace,
        "market_story": story,
        "guardrails": {
            "read_only_composition": True,
            "recomputes_direction": False,
            "similarity_changes_decision": False,
            "learning_auto_activation": False,
            "fabricates_institutional_intent": False,
        },
    }
    payload["state_hash"] = hashlib.sha256(_canonical({k: v for k, v in payload.items() if k not in ("generated_at", "state_hash")}).encode()).hexdigest()
    return payload
