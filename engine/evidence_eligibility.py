"""APEX 69.6.0 — pre-consensus evidence eligibility.

Separates evidence validity from eligibility to influence consensus.  This layer
is deterministic, non-direction-generative, and has no execution authority.
"""
from __future__ import annotations
from typing import Any, Dict, Mapping, Optional

VERSION = "69.6.0"
SCHEMA_VERSION = "apex.evidence_eligibility.v1"
STATES = {"FULL", "DISCOUNTED", "CONTEXT_ONLY", "WATCH_ONLY", "INELIGIBLE"}


def _m(v: Any) -> Dict[str, Any]:
    return dict(v) if isinstance(v, Mapping) else {}


def _f(v: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def evaluate_evidence_eligibility(engine_name: str, opinion: Mapping[str, Any],
                                  dynamic_state: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Return the strongest applicable eligibility state and weight factor."""
    op, ds = _m(opinion), _m(dynamic_state)
    reasons = []
    state, factor = "FULL", 1.0
    freshness = str(op.get("freshness_state") or op.get("freshness") or "CURRENT").upper()
    direction = str(op.get("direction") or "UNKNOWN").upper()

    if freshness == "UNAVAILABLE" or direction in {"ABSTAIN", "UNKNOWN"}:
        state, factor = "INELIGIBLE", 0.0
        reasons.append("UNAVAILABLE_OR_NON_OPINION")
    elif freshness == "STALE":
        state, factor = "CONTEXT_ONLY", 0.0
        reasons.append("STALE_EVIDENCE")
    elif freshness == "DEGRADED":
        # Freshness already scales the consensus weight; eligibility records the
        # downgrade without applying the same penalty a second time.
        state, factor = "DISCOUNTED", 1.0
        reasons.append("DEGRADED_EVIDENCE")

    event = _m(ds.get("event_phase"))
    phase = str(event.get("phase") or "NORMAL").upper()
    if phase in {"EVENT_IMMINENT", "RELEASE"} and state != "INELIGIBLE":
        state, factor = "WATCH_ONLY", 0.0
        reasons.append("EVENT_RELEASE_BOUNDARY")

    name = str(engine_name or op.get("engine_name") or "").lower()
    if name == "flow" and state not in {"INELIGIBLE", "WATCH_ONLY", "CONTEXT_ONLY"}:
        fe = _m(ds.get("flow_excitation"))
        independence = _f(fe.get("independent_evidence_factor"), _f(op.get("independence_factor"), 1.0))
        if independence is not None and independence < 0.999:
            state = "DISCOUNTED"
            # The EngineOpinion independence_factor is the canonical numerical
            # discount. Keep eligibility factor neutral to avoid double counting.
            reasons.append("CONTINUING_FLOW_BURST")

    if name == "dealer" and state not in {"INELIGIBLE", "WATCH_ONLY"}:
        gc = _m(ds.get("gamma_context"))
        durability = str(gc.get("structure_durability") or "UNKNOWN").upper()
        capacity = str(gc.get("capacity_state") or "UNKNOWN").upper()
        if durability == "LOW":
            state, factor = "CONTEXT_ONLY", 0.0
            reasons.append("LOW_GAMMA_STRUCTURE_DURABILITY")
        elif capacity == "WEAK" and state == "FULL":
            state, factor = "DISCOUNTED", min(factor, 0.60)
            reasons.append("WEAK_GAMMA_STABILIZATION_CAPACITY")

    return {
        "schema_version": SCHEMA_VERSION,
        "version": VERSION,
        "state": state,
        "weight_factor": round(max(0.0, min(1.0, factor)), 4),
        "reasons": reasons,
        "consensus_eligible": state in {"FULL", "DISCOUNTED"} and factor > 0,
        "context_visible": state != "INELIGIBLE",
        "execution_authority": False,
        "discount_delegated_to_existing_factor": bool(name == "flow" and "CONTINUING_FLOW_BURST" in reasons),
    }


def summarize_evidence_eligibility(opinions: Any) -> Dict[str, Any]:
    rows = [dict(x) for x in (opinions or []) if isinstance(x, Mapping)]
    counts = {k: 0 for k in ("FULL", "DISCOUNTED", "CONTEXT_ONLY", "WATCH_ONLY", "INELIGIBLE")}
    effective = 0.0
    details = []
    for row in rows:
        e = _m(row.get("evidence_eligibility"))
        state = str(e.get("state") or row.get("eligibility_state") or "FULL").upper()
        if state not in counts:
            state = "FULL"
        counts[state] += 1
        base_independence = max(0.0, min(1.0, _f(row.get("independence_factor"), 1.0) or 0.0))
        ef = max(0.0, min(1.0, _f(e.get("weight_factor"), _f(row.get("eligibility_weight_factor"), 1.0)) or 0.0))
        if state in {"FULL", "DISCOUNTED"}:
            effective += base_independence * ef
        details.append({"engine": row.get("engine_name"), "state": state,
                        "weight_factor": round(ef, 3), "independence_factor": round(base_independence, 3),
                        "reasons": list(e.get("reasons") or [])})
    return {"schema_version": SCHEMA_VERSION, "version": VERSION, "available": bool(rows),
            "raw_evidence_count": len(rows), "effective_independent_evidence": round(effective, 2),
            "counts": counts, "engines": details, "execution_authority": False}
