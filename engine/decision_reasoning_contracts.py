"""APEX 66.3.0 decision-reasoning normalization contracts.

This module does not create a second decision engine. It normalizes existing APEX
primitive-engine outputs into shared contracts consumed by the authoritative
institutional decision object and narrative/consensus composition path.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Dict, List, Mapping, Optional

VERSION = "66.3.0"
ENGINE_OPINION_SCHEMA = "apex.engine_opinion.v1"
ACCEPTANCE_SCHEMA = "apex.acceptance_result.v1"
CONSENSUS_SCHEMA = "apex.correlation_aware_consensus.v1"

DIRECTIONS = {"BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN", "ABSTAIN"}
ACCEPTANCE_STATES = {
    "ACCEPTED", "WEAK_ACCEPTANCE", "TEMPORARY_ACCEPTANCE", "FAILED_ACCEPTANCE",
    "REJECTED", "BALANCED", "INITIATIVE_BUYING", "INITIATIVE_SELLING",
    "UNKNOWN", "ABSTAIN",
}

# Transparent configured clusters. These are architecture priors, not learned
# correlations. Historical correlation measurement can replace the penalty later.
CORRELATION_CLUSTERS = {
    "institutional_intelligence": "STRUCTURE_AUCTION",
    "auction": "STRUCTURE_AUCTION",
    "structure": "STRUCTURE_AUCTION",
    "flow": "FLOW_LIQUIDITY",
    "liquidity": "FLOW_LIQUIDITY",
    "dealer": "DEALER_POSITIONING",
    "breadth": "INTERNALS_BREADTH",
    "execution": "EXECUTION_READINESS",
    "narrative_event": "NARRATIVE_EVENT",
}
KNOWN_CLUSTERS = tuple(sorted(set(CORRELATION_CLUSTERS.values())))


def _dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def _text(value: Any, default: str = "") -> str:
    out = str(value or "").strip()
    return out if out else default


def _direction(value: Any, *, missing: bool = False) -> str:
    if missing or value is None or str(value).strip() == "":
        return "ABSTAIN"
    s = str(value).strip().upper().replace(" ", "_")
    if s in DIRECTIONS:
        return s
    if s in {"N/A", "NA", "UNAVAILABLE", "NO_DATA", "MISSING"}:
        return "ABSTAIN"
    if "UNKNOWN" in s or "UNCONFIRMED" in s:
        return "UNKNOWN"
    if any(x in s for x in ("BULL", "CALL", "UP", "LONG", "BUY", "POSITIVE")):
        return "BULLISH"
    if any(x in s for x in ("BEAR", "PUT", "DOWN", "SHORT", "SELL", "NEGATIVE")):
        return "BEARISH"
    if any(x in s for x in ("NEUTRAL", "BALANCED", "MIXED", "FLAT", "ROTATION")):
        return "NEUTRAL"
    return "UNKNOWN"


def _freshness_state(value: Any) -> str:
    s = _text(value, "CURRENT").upper()
    if s in {"STALE", "EXPIRED"}:
        return "STALE"
    if s in {"DEGRADED", "DELAYED"}:
        return "DEGRADED"
    if s in {"UNAVAILABLE", "MISSING", "NO_DATA"}:
        return "UNAVAILABLE"
    return "CURRENT"


def make_engine_opinion(
    *, engine_name: str, raw_direction: Any, reliability: float,
    correlation_cluster: Optional[str] = None, confidence: Any = None,
    strength: Any = None, freshness: Any = None, evidence: Any = None,
    missing_data: Optional[List[str]] = None, warnings: Optional[List[str]] = None,
    provenance: Optional[Mapping[str, Any]] = None, engine_version: Optional[str] = None,
    timestamp: Optional[str] = None, abstain_reason: Optional[str] = None,
) -> Dict[str, Any]:
    missing = list(missing_data or [])
    direction = _direction(raw_direction, missing=bool(missing and raw_direction in (None, "")))
    abstain = direction == "ABSTAIN"
    fs = _freshness_state(freshness)
    rel = max(0.0, min(1.0, _num(reliability, 0.0) or 0.0))
    conf = _num(confidence)
    if conf is not None and conf > 1.0:
        conf /= 100.0
    conf = None if conf is None else max(0.0, min(1.0, conf))
    st = _num(strength)
    if st is not None and st > 1.0:
        st /= 100.0
    st = (conf if st is None else max(0.0, min(1.0, st)))
    if st is None:
        st = 1.0 if direction in {"BULLISH", "BEARISH"} else 0.5 if direction == "NEUTRAL" else 0.0
    return {
        "schema_version": ENGINE_OPINION_SCHEMA,
        "engine_name": engine_name,
        "engine_version": engine_version or "UNSPECIFIED",
        "timestamp": timestamp or dt.datetime.now(dt.timezone.utc).isoformat(),
        "direction": direction,
        "strength": round(st, 4),
        "confidence": None if conf is None else round(conf, 4),
        "freshness": _text(freshness, "CURRENT"),
        "freshness_state": fs,
        "reliability": round(rel, 4),
        "correlation_cluster": correlation_cluster or CORRELATION_CLUSTERS.get(engine_name, "OTHER"),
        "abstain": abstain,
        "abstain_reason": abstain_reason or ("MISSING_REQUIRED_DATA" if abstain and missing else "NO_DIRECTIONAL_OPINION" if abstain else None),
        "evidence": evidence if evidence not in (None, "") else {},
        "missing_data": missing,
        "warnings": list(warnings or []),
        "provenance": dict(provenance or {}),
    }


def build_engine_opinions(last_result: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Normalize existing APEX outputs; never invent missing engine evidence."""
    last = _dict(last_result)
    market = _dict(last.get("market_state"))
    ii = _dict(last.get("institutional_intelligence"))
    auction = _dict(last.get("auction_intelligence"))
    flow = _dict(last.get("flow_intelligence_2") or last.get("flow_intelligence"))
    dealer = _dict(last.get("dealer_positioning"))
    structure = _dict(last.get("institutional_market_structure") or last.get("market_structure") or last.get("structure"))
    confirmation = _dict(last.get("confirmation"))
    breadth = _dict(last.get("breadth"))
    drivers = _dict(last.get("market_drivers"))
    execution = _dict(last.get("execution_intelligence") or last.get("execution_os"))
    liquidity = _dict(last.get("liquidity_intelligence"))

    specs = [
        ("institutional_intelligence", ii.get("institutional_bias") or ii.get("bias"), 0.90, ii.get("confidence") or ii.get("institutional_confidence"), ii.get("freshness"), ii, "institutional_intelligence"),
        ("auction", auction.get("bias") or market.get("auction_bias"), 0.78, auction.get("confidence"), auction.get("freshness"), auction, "auction_intelligence"),
        ("structure", structure.get("direction") or structure.get("bias") or confirmation.get("bias"), 0.78, structure.get("confidence"), structure.get("freshness"), structure or confirmation, "institutional_market_structure/confirmation"),
        ("flow", market.get("flow_bias") or flow.get("flow_bias") or flow.get("direction"), 0.80, flow.get("confidence") or flow.get("conviction"), flow.get("freshness"), flow, "flow_intelligence"),
        ("liquidity", liquidity.get("direction") or liquidity.get("bias") or liquidity.get("pressure_direction"), 0.72, liquidity.get("confidence") or liquidity.get("score"), liquidity.get("freshness"), liquidity, "liquidity_intelligence"),
        ("dealer", _dict(dealer.get("delta")).get("bias") or dealer.get("bias") or dealer.get("direction"), 0.72, dealer.get("confidence"), dealer.get("freshness"), dealer, "dealer_positioning"),
        ("breadth", drivers.get("breadth") or breadth.get("bias") or breadth.get("direction"), 0.62, breadth.get("confidence") or drivers.get("breadth_score"), breadth.get("freshness"), breadth or {"breadth": drivers.get("breadth")}, "breadth/market_drivers"),
        ("execution", execution.get("approved_side") or execution.get("side"), 0.60, execution.get("execution_score") or execution.get("score"), execution.get("freshness"), execution, "execution_intelligence"),
    ]
    out: List[Dict[str, Any]] = []
    for name, raw, rel, conf, fresh, evidence, origin in specs:
        missing = [] if raw not in (None, "") else [f"{origin}.direction"]
        out.append(make_engine_opinion(
            engine_name=name, raw_direction=raw, reliability=rel,
            correlation_cluster=CORRELATION_CLUSTERS.get(name), confidence=conf,
            freshness=fresh, evidence=evidence, missing_data=missing,
            provenance={"origin": origin, "normalizer_version": VERSION},
        ))
    return out


def normalize_acceptance(last_result: Mapping[str, Any]) -> Dict[str, Any]:
    """Select and normalize existing acceptance evidence without re-detecting it."""
    last = _dict(last_result)
    auction = _dict(last.get("auction_intelligence"))
    auction_acc = _dict(auction.get("acceptance"))
    structure = _dict(last.get("institutional_market_structure") or last.get("market_structure"))
    structure_acc = _dict(structure.get("acceptance_rejection"))
    ii = _dict(last.get("institutional_intelligence"))

    raw = (
        structure_acc.get("state") or auction_acc.get("primary_status") or
        auction_acc.get("state") or ii.get("acceptance")
    )
    direction = structure_acc.get("direction") or auction_acc.get("direction") or auction.get("bias")
    if raw in (None, ""):
        state = "ABSTAIN"
    else:
        s = str(raw).upper().replace(" ", "_")
        if "INITIATIVE_BUY" in s: state = "INITIATIVE_BUYING"
        elif "INITIATIVE_SELL" in s: state = "INITIATIVE_SELLING"
        elif "FAILED" in s: state = "FAILED_ACCEPTANCE"
        elif "REJECT" in s: state = "REJECTED"
        elif "TEMP" in s or "TEST" in s or "PROBE" in s: state = "TEMPORARY_ACCEPTANCE"
        elif "WEAK" in s: state = "WEAK_ACCEPTANCE"
        elif "ACCEPT" in s: state = "ACCEPTED"
        elif "BALANC" in s or "ROTAT" in s: state = "BALANCED"
        elif "UNKNOWN" in s or "UNCONFIRMED" in s: state = "UNKNOWN"
        else: state = "UNKNOWN"
    return {
        "schema_version": ACCEPTANCE_SCHEMA,
        "normalizer_version": VERSION,
        "state": state,
        "direction": _direction(direction) if state != "ABSTAIN" else "ABSTAIN",
        "freshness_state": _freshness_state(auction_acc.get("freshness") or structure.get("freshness")),
        "source": "institutional_market_structure.acceptance_rejection" if structure_acc else "auction_intelligence.acceptance" if auction_acc else "institutional_intelligence.acceptance" if ii.get("acceptance") else None,
        "raw_state": raw,
        "evidence": {"market_structure": structure_acc, "auction": auction_acc, "institutional_intelligence_acceptance": ii.get("acceptance")},
        "missing_data": [] if raw not in (None, "") else ["normalized_acceptance_source"],
        "abstain": state == "ABSTAIN",
    }


def build_correlation_aware_consensus(opinions: List[Mapping[str, Any]]) -> Dict[str, Any]:
    """Decorrelate configured clusters using transparent diminishing-return penalties."""
    ops = [dict(x) for x in opinions]
    supporting: Dict[str, List[str]] = {"BULLISH": [], "BEARISH": []}
    contradicting: List[str] = []
    abstaining = [o["engine_name"] for o in ops if o.get("direction") == "ABSTAIN"]
    stale = [o["engine_name"] for o in ops if o.get("freshness_state") in {"STALE", "DEGRADED"}]
    unavailable = [o["engine_name"] for o in ops if o.get("freshness_state") == "UNAVAILABLE"]
    eligible = [o for o in ops if o.get("direction") not in {"ABSTAIN", "UNKNOWN"} and o.get("freshness_state") != "UNAVAILABLE"]

    def weight(o: Mapping[str, Any]) -> float:
        freshness_factor = 0.25 if o.get("freshness_state") == "STALE" else 0.60 if o.get("freshness_state") == "DEGRADED" else 1.0
        strength = _num(o.get("strength"), 0.0) or 0.0
        return max(0.0, (_num(o.get("reliability"), 0.0) or 0.0) * strength * freshness_factor)

    raw = {"BULLISH": 0.0, "BEARISH": 0.0, "NEUTRAL": 0.0}
    by_cluster: Dict[str, List[tuple[Dict[str, Any], float]]] = {}
    for o in eligible:
        d = o.get("direction")
        w = weight(o)
        if d in raw: raw[d] += w
        by_cluster.setdefault(str(o.get("correlation_cluster") or "OTHER"), []).append((o, w))

    effective = {"BULLISH": 0.0, "BEARISH": 0.0, "NEUTRAL": 0.0}
    cluster_detail: Dict[str, Any] = {}
    raw_total = 0.0; effective_total = 0.0
    active_clusters: List[str] = []; conflicted_clusters: List[str] = []
    for cluster, rows in sorted(by_cluster.items()):
        rows = sorted(rows, key=lambda x: x[1], reverse=True)
        raw_cluster = sum(w for _, w in rows)
        raw_total += raw_cluster
        # First engine receives full weight; each additional engine in the same
        # cluster receives 35% of its configured evidence weight.
        eff_rows = []
        for i, (o, w) in enumerate(rows):
            ew = w if i == 0 else w * 0.35
            effective_total += ew
            d = o.get("direction")
            if d in effective: effective[d] += ew
            eff_rows.append({"engine": o.get("engine_name"), "direction": d, "raw_weight": round(w, 4), "effective_weight": round(ew, 4)})
        directions = {o.get("direction") for o, _ in rows if o.get("direction") in {"BULLISH", "BEARISH"}}
        if rows: active_clusters.append(cluster)
        if len(directions) > 1: conflicted_clusters.append(cluster)
        cluster_detail[cluster] = {"members": eff_rows, "raw_weight": round(raw_cluster, 4), "effective_weight": round(sum(x["effective_weight"] for x in eff_rows), 4), "configured_secondary_factor": 0.35}

    bull, bear, neutral = effective["BULLISH"], effective["BEARISH"], effective["NEUTRAL"]
    directional = bull + bear
    dominant = "BULLISH" if bull > bear else "BEARISH" if bear > bull else "NEUTRAL"
    dominant_weight = max(bull, bear)
    opposing_weight = min(bull, bear)
    effective_consensus = 0.0 if directional <= 0 else dominant_weight / directional * 100.0
    disagreement = 0.0 if directional <= 0 else opposing_weight / directional * 100.0
    correlation_penalty = max(0.0, raw_total - effective_total)
    independent_score = 0.0 if not KNOWN_CLUSTERS else len(active_clusters) / len(KNOWN_CLUSTERS) * 100.0
    coverage = independent_score
    redundant_score = 0.0 if raw_total <= 0 else correlation_penalty / raw_total * 100.0

    for o in eligible:
        if o.get("direction") == dominant and dominant != "NEUTRAL": supporting[dominant].append(o["engine_name"])
        elif o.get("direction") in {"BULLISH", "BEARISH"} and o.get("direction") != dominant: contradicting.append(o["engine_name"])

    status = "UNAVAILABLE" if not eligible else "DEGRADED" if len(active_clusters) < 3 else "AVAILABLE"
    grade = "A" if effective_consensus >= 80 and disagreement < 20 and len(active_clusters) >= 4 else "B" if effective_consensus >= 68 and len(active_clusters) >= 3 else "C" if effective_consensus >= 55 else "D"
    conflict_matrix = []
    directional_ops = [o for o in eligible if o.get("direction") in {"BULLISH", "BEARISH", "NEUTRAL"}]
    for i, left in enumerate(directional_ops):
        for right in directional_ops[i+1:]:
            ld, rd = left.get("direction"), right.get("direction")
            relation = "AGREEMENT" if ld == rd else "NEUTRAL_RELATION" if "NEUTRAL" in {ld, rd} else "CONTRADICTION"
            conflict_matrix.append({"left": left.get("engine_name"), "right": right.get("engine_name"), "left_cluster": left.get("correlation_cluster"), "right_cluster": right.get("correlation_cluster"), "relation": relation, "same_cluster": left.get("correlation_cluster") == right.get("correlation_cluster")})

    return {
        "schema_version": CONSENSUS_SCHEMA,
        "normalizer_version": VERSION,
        "dominant_direction": dominant,
        "direction": dominant,
        "raw_directional_evidence": {k: round(v, 4) for k, v in raw.items()},
        "effective_directional_evidence": {k: round(v, 4) for k, v in effective.items()},
        "effective_consensus": round(effective_consensus, 1),
        "independent_evidence_score": round(independent_score, 1),
        "redundant_evidence_score": round(redundant_score, 1),
        "correlation_penalty": round(correlation_penalty, 4),
        "disagreement": round(disagreement, 1),
        "evidence_coverage": round(coverage, 1),
        "supporting_engines": supporting.get(dominant, []) if dominant in supporting else [],
        "contradicting_engines": contradicting,
        "abstaining_engines": abstaining,
        "stale_engines": stale,
        "unavailable_engines": unavailable,
        "active_clusters": active_clusters,
        "conflicted_clusters": conflicted_clusters,
        "clusters": cluster_detail,
        "conflict_matrix": conflict_matrix,
        "consensus_grade": grade,
        "status": status,
        "configured_decorrelation": True,
        "historical_correlation_statistics_applied": False,
        "provenance": {"method": "configured_cluster_diminishing_returns", "secondary_cluster_factor": 0.35},
        # compatibility fields used by existing dashboards/consumers
        "score": round(effective_consensus, 1),
        "agreement_percentage": round(effective_consensus, 1),
        "eligible_count": len(eligible),
        "agreement_count": len(supporting.get(dominant, [])) if dominant in supporting else 0,
        "dissenters": contradicting,
        "opposed_sources": contradicting,
        "stale_sources": stale,
        "unavailable_sources": unavailable,
        "source_count": len(eligible),
        "sources": ops,
        "aligned_sources": supporting.get(dominant, []) if dominant in supporting else [],
        "conflict_score": round(disagreement * 2.0, 1) if disagreement <= 50 else 100.0,
        "contradiction_severity": "SEVERE" if disagreement >= 35 else "MATERIAL" if disagreement >= 20 else "LOW",
        "institutional_divergence_warning": disagreement >= 20,
        "policy_guidance": "DO_NOT_TRADE" if len(active_clusters) < 3 else "REDUCE_SIZE" if disagreement >= 20 else "NORMAL_INFORMATIONAL_SIZE",
        "explanation": f"{len(active_clusters)} independent evidence clusters produced {effective_consensus:.1f}% effective directional consensus after configured correlation penalties.",
    }


def build_reasoning_evidence_graph(opinions: List[Mapping[str, Any]], consensus: Mapping[str, Any], acceptance: Mapping[str, Any]) -> Dict[str, Any]:
    """Build an in-memory decision-time evidence graph without causal invention."""
    dominant = str(consensus.get("dominant_direction") or "NEUTRAL")
    nodes: List[Dict[str, Any]] = [{
        "node_id": "consensus", "kind": "CONSENSUS", "state": dominant,
        "payload": {"effective_consensus": consensus.get("effective_consensus"), "status": consensus.get("status")},
    }]
    edges: List[Dict[str, Any]] = []
    for opinion in opinions:
        name = str(opinion.get("engine_name") or "UNKNOWN")
        direction = str(opinion.get("direction") or "UNKNOWN")
        freshness = str(opinion.get("freshness_state") or "UNKNOWN")
        if direction == "ABSTAIN": relation = "ABSTAINS"
        elif direction == "UNKNOWN": relation = "UNKNOWN_EVIDENCE"
        elif freshness == "UNAVAILABLE": relation = "UNAVAILABLE_EVIDENCE"
        elif freshness in {"STALE", "DEGRADED"}: relation = "STALE_EVIDENCE"
        elif direction == "NEUTRAL": relation = "NEUTRAL_EVIDENCE"
        elif direction == dominant: relation = "SUPPORTS"
        else: relation = "CONTRADICTS"
        node_id = f"engine:{name}"
        nodes.append({"node_id": node_id, "kind": "ENGINE_OPINION", "state": direction, "payload": dict(opinion)})
        edges.append({"from": node_id, "to": "consensus", "relation": relation, "same_cluster_redundancy_possible": True})
    nodes.append({"node_id": "acceptance", "kind": "ACCEPTANCE", "state": acceptance.get("state"), "payload": dict(acceptance)})
    edges.append({"from": "acceptance", "to": "consensus", "relation": "INFORMS_STRUCTURE" if not acceptance.get("abstain") else "ABSTAINS"})
    return {
        "schema_version": "apex.reasoning_evidence_graph.v1", "version": VERSION,
        "nodes": nodes, "edges": edges,
        "guardrails": {"causal_inference": False, "future_information": False, "post_hoc_evidence": False},
    }
