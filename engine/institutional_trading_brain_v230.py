"""APEX 23.0 Institutional Trading Brain.

Read-only hierarchical reasoning above the existing institutional engines.  It
never changes execution permissions or submits broker actions.  The brain
builds one point-in-time thesis, dynamically weights evidence, explains
conflicts, and exposes dormant-safe confidence calibration hooks backed by
Market Memory.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple
import math

from .institutional_decision_engine_v20 import build_institutional_decision
from .market_memory_engine_v220 import find_similar, status as memory_status

VERSION = "16.0.0_INSTITUTIONAL_TRADING_BRAIN"
SEMANTIC_VERSION = "16.0.0"
SCHEMA_VERSION = "apex.institutional_trading_brain.v1"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
        return default if math.isnan(n) or math.isinf(n) else n
    except Exception:
        return default


def _clip(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return round(max(lo, min(hi, value)), 1)


def _text(value: Any, default: str = "UNKNOWN") -> str:
    s = str(value or "").strip()
    return s if s else default


def _session(last: Mapping[str, Any]) -> str:
    raw = last.get("session") or (last.get("market_state") or {}).get("session") or "UNKNOWN"
    if isinstance(raw, Mapping):
        raw = raw.get("name") or raw.get("state") or raw.get("session")
    return _text(raw).upper()


def _time_factor(source: str, session: str) -> float:
    session = session.upper()
    if "PRE" in session or "OVERNIGHT" in session:
        return {"market_structure": 1.15, "dealer": 0.90, "flow": 0.75,
                "probability": 0.95, "adaptive_learning": 0.90}.get(source, 1.0)
    if "OPEN" in session:
        return {"market_structure": 1.10, "dealer": 1.05, "flow": 1.10,
                "probability": 0.95, "adaptive_learning": 0.95}.get(source, 1.0)
    if "MID" in session or "LUNCH" in session:
        return {"market_structure": 1.00, "dealer": 1.05, "flow": 0.95,
                "probability": 1.05, "adaptive_learning": 1.05}.get(source, 1.0)
    if "POWER" in session or "CLOSE" in session:
        return {"market_structure": 0.95, "dealer": 1.10, "flow": 1.10,
                "probability": 1.00, "adaptive_learning": 1.05}.get(source, 1.0)
    return 1.0


def _regime_factor(source: str, regime: str) -> float:
    if regime == "EXPANSION":
        return {"flow": 1.15, "market_structure": 1.10, "dealer": 1.05,
                "probability": 1.05, "adaptive_learning": 0.90}.get(source, 1.0)
    if regime == "MEAN_REVERSION":
        return {"dealer": 1.15, "market_structure": 1.10, "probability": 1.05,
                "flow": 0.90, "adaptive_learning": 1.00}.get(source, 1.0)
    return {"market_structure": 1.10, "dealer": 1.05, "probability": 1.05,
            "flow": 0.95, "adaptive_learning": 1.00}.get(source, 1.0)


def _memory_context(last: Mapping[str, Any], *, before: Optional[str] = None) -> Dict[str, Any]:
    try:
        state = memory_status()
        result = find_similar(last, limit=12, min_score=55.0, before=before)
        matches = result.get("matches") or []
        graded = [m for m in matches if m.get("outcome_status") == "GRADED" and isinstance(m.get("outcome"), Mapping)]
        directional_wins = 0
        usable = 0
        for match in graded:
            outcome = match.get("outcome") or {}
            won = outcome.get("won")
            if isinstance(won, bool):
                usable += 1
                directional_wins += int(won)
            elif outcome.get("result") in ("WIN", "LOSS"):
                usable += 1
                directional_wins += int(outcome.get("result") == "WIN")
        observed_rate = round(100.0 * directional_wins / usable, 1) if usable else None
        return {
            "available": True,
            "state": state.get("state", "UNKNOWN"),
            "learning_ready": bool(state.get("learning_ready")),
            "sessions": int(state.get("sessions") or 0),
            "graded_sessions": int(state.get("graded_sessions") or 0),
            "similar_matches": len(matches),
            "graded_similar_matches": len(graded),
            "usable_calibration_matches": usable,
            "observed_win_rate": observed_rate,
            "top_similarity": _f(matches[0].get("similarity"), 0.0) if matches else 0.0,
            "look_ahead_protected": bool(before),
            "limitations": [] if usable >= 20 else ["Calibration remains provisional until at least 20 comparable graded outcomes exist."],
        }
    except Exception as exc:
        return {"available": False, "state": "WARNING", "learning_ready": False,
                "sessions": 0, "graded_sessions": 0, "similar_matches": 0,
                "graded_similar_matches": 0, "usable_calibration_matches": 0,
                "observed_win_rate": None, "top_similarity": 0.0,
                "look_ahead_protected": bool(before), "error": type(exc).__name__,
                "limitations": ["Market Memory could not be queried; base confidence remains authoritative."]}


def _dynamic_evidence(base: Mapping[str, Any], session: str, memory: Mapping[str, Any]) -> Tuple[List[Dict[str, Any]], float, float]:
    evidence = []
    bull = bear = 0.0
    regime = _text(base.get("regime"), "BALANCE")
    memory_quality = min(1.0, _f(memory.get("usable_calibration_matches")) / 20.0)
    for item in base.get("evidence") or []:
        source = _text(item.get("source"), "unknown")
        available = bool(item.get("available"))
        base_weight = _f(item.get("weight"), 0.0)
        confidence = _clip(_f(item.get("confidence"), 0.0))
        factor = _time_factor(source, session) * _regime_factor(source, regime)
        if source == "adaptive_learning":
            factor *= 0.75 + 0.25 * memory_quality
        dynamic_weight = base_weight * factor
        contribution = confidence * dynamic_weight if available else 0.0
        direction = _text(item.get("direction"), "NEUTRAL")
        if direction == "BULLISH":
            bull += contribution
        elif direction == "BEARISH":
            bear += contribution
        evidence.append({
            "source": source,
            "available": available,
            "direction": direction,
            "confidence": confidence,
            "base_weight": round(base_weight, 4),
            "dynamic_weight": round(dynamic_weight, 4),
            "weight_adjustment": round(factor, 3),
            "contribution": round(contribution, 2),
            "reason": f"Adjusted for {regime.lower().replace('_',' ')} regime and {session.lower().replace('_',' ')} session context.",
        })
    return evidence, bull, bear


def _conflicts(evidence: List[Mapping[str, Any]], dominant: str) -> List[Dict[str, Any]]:
    out = []
    for item in evidence:
        direction = item.get("direction")
        if not item.get("available") or direction in ("NEUTRAL", dominant):
            continue
        severity = "HIGH" if _f(item.get("contribution")) >= 12 else "MEDIUM" if _f(item.get("contribution")) >= 6 else "LOW"
        out.append({
            "source": item.get("source"), "direction": direction, "severity": severity,
            "contribution": item.get("contribution"),
            "resolution": f"{dominant} remains dominant because the aggregate dynamically weighted evidence is stronger; this conflict remains an explicit risk.",
        })
    return sorted(out, key=lambda x: _f(x.get("contribution")), reverse=True)


def _timeline(last: Mapping[str, Any], base: Mapping[str, Any], dominant: str) -> List[Dict[str, Any]]:
    components = base.get("components") or {}
    structure = components.get("market_structure") or {}
    dealer = components.get("dealer") or {}
    flow = components.get("flow") or {}
    overnight = last.get("overnight_structure") or last.get("overnight") or {}
    return [
        {"phase": "OVERNIGHT_CONTEXT", "state": _text(overnight.get("state") or overnight.get("bias"), "UNAVAILABLE"),
         "interpretation": "Overnight structure establishes the opening reference frame; unavailable inputs do not invent a conclusion."},
        {"phase": "OPENING_AUCTION", "state": _text(structure.get("opening_type") or structure.get("auction_state"), "UNCLASSIFIED"),
         "interpretation": "Opening classification controls whether continuation, rejection, or balance confirmation is required."},
        {"phase": "CURRENT_STRUCTURE", "state": _text(structure.get("direction") or structure.get("state"), "UNKNOWN"),
         "interpretation": _text(base.get("narrative"), "No institutional narrative is available.")},
        {"phase": "POSITIONING_AND_FLOW", "state": f"DEALER {_text(dealer.get('bias'))} / FLOW {_text(flow.get('bias'))}",
         "interpretation": "Dealer hedging pressure and institutional flow are evaluated independently before conflict resolution."},
        {"phase": "EXPECTED_PATH", "state": dominant,
         "interpretation": "The expected path is conditional on the listed confirmation and invalidation rules, not a guaranteed forecast."},
    ]


def build_institutional_trading_brain(last: Dict[str, Any], history: Any = None, *, before: Optional[str] = None) -> Dict[str, Any]:
    last = last if isinstance(last, dict) else {}
    base = build_institutional_decision(last, history)
    session = _session(last)
    memory = _memory_context(last, before=before)
    evidence, bull, bear = _dynamic_evidence(base, session, memory)
    net = bull - bear
    dominant = "BULLISH" if net >= 8 else "BEARISH" if net <= -8 else "NEUTRAL"
    directional_total = bull + bear
    agreement = abs(net) / max(1.0, directional_total) * 100.0
    conflicts = _conflicts(evidence, dominant)

    base_conf = _f(base.get("confidence"), 0.0)
    usable = int(memory.get("usable_calibration_matches") or 0)
    observed = memory.get("observed_win_rate")
    calibration_weight = min(0.35, usable / 100.0)
    calibrated = base_conf
    if observed is not None and usable >= 5:
        calibrated = base_conf * (1.0 - calibration_weight) + _f(observed) * calibration_weight
    calibrated = _clip(calibrated - len([c for c in conflicts if c["severity"] == "HIGH"]) * 4)

    blockers = list(base.get("blocking_reasons") or [])
    if dominant == "NEUTRAL" and "NO_DIRECTIONAL_EDGE" not in blockers:
        blockers.append("NO_DIRECTIONAL_EDGE")
    if calibrated < 65 and "CALIBRATED_CONFIDENCE_BELOW_THRESHOLD" not in blockers:
        blockers.append("CALIBRATED_CONFIDENCE_BELOW_THRESHOLD")
    if any(c["severity"] == "HIGH" for c in conflicts):
        blockers.append("HIGH_SEVERITY_EVIDENCE_CONFLICT")
    execution_ready = bool(base.get("execution_eligible")) and not blockers

    scenarios = []
    for scenario in base.get("scenarios") or []:
        item = dict(scenario)
        name = _text(item.get("name"))
        item["rank"] = 1 if dominant in name else 3 if "BALANCE" in name and dominant != "NEUTRAL" else 2
        item["status"] = "PRIMARY" if item["rank"] == 1 else "ALTERNATE"
        scenarios.append(item)
    scenarios.sort(key=lambda x: (x.get("rank", 9), -_f(x.get("probability"))))

    levels = base.get("levels") or {}
    invalidations = [
        "Dominant directional evidence falls below the minimum net-weight threshold.",
        "Price accepts beyond the opposing governed structure level.",
        "A high-severity conflict persists while calibrated confidence deteriorates.",
        "Data freshness, provider health, or execution governance becomes blocking.",
    ]
    if levels:
        invalidations.append("The relevant POC, value boundary, support, or resistance acceptance condition fails.")

    supporting = [e for e in evidence if e.get("available") and e.get("direction") == dominant]
    supporting.sort(key=lambda x: _f(x.get("contribution")), reverse=True)
    primary = scenarios[0] if scenarios else {"name": "NO_SCENARIO", "probability": 0.0}
    alternate = scenarios[1] if len(scenarios) > 1 else None
    decision = "TRADE_CANDIDATE" if execution_ready else "WATCH" if base.get("decision") != "STAND_DOWN" else "STAND_DOWN"

    return {
        "ok": True, "version": VERSION, "semantic_version": SEMANTIC_VERSION,
        "schema_version": SCHEMA_VERSION, "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "ticker": _text(last.get("ticker"), "SPX"), "session": session,
        "decision": decision, "bias": dominant, "regime": base.get("regime"),
        "base_confidence": _clip(base_conf), "calibrated_confidence": calibrated,
        "headline": f"{dominant} {_text(base.get('regime'),'BALANCE').replace('_',' ')} — calibrated conviction {calibrated:.0f}/100",
        "primary_thesis": {
            "scenario": primary.get("name"), "probability": primary.get("probability"),
            "statement": f"{dominant} is the current institutional thesis because dynamically weighted evidence produces a net score of {net:.1f}.",
            "confirmation": primary.get("confirmation"), "invalidations": invalidations,
        },
        "alternate_scenario": alternate,
        "execution_readiness": {"eligible": execution_ready, "state": "READY" if execution_ready else "BLOCKED", "blocking_reasons": blockers},
        "evidence": evidence, "supporting_evidence": supporting[:5], "conflicting_evidence": conflicts,
        "evidence_summary": {"bull_score": round(bull, 2), "bear_score": round(bear, 2), "net_score": round(net, 2),
                             "agreement_score": round(agreement, 1), "coverage": base.get("evidence_coverage")},
        "scenarios": scenarios, "thesis_timeline": _timeline(last, base, dominant),
        "confidence_calibration": {
            "state": "ACTIVE" if usable >= 20 else "PROVISIONAL" if usable >= 5 else "DORMANT",
            "base_confidence": _clip(base_conf), "calibrated_confidence": calibrated,
            "calibration_weight": round(calibration_weight, 3), "observed_similar_win_rate": observed,
            "usable_similar_outcomes": usable, "minimum_recommended_outcomes": 20,
            "automatic_weight_mutation": False, "human_approval_required": True,
        },
        "memory_context": memory,
        "explainability": {
            "why_selected": [e.get("reason") for e in supporting[:3]],
            "why_alternatives_rejected": [c.get("resolution") for c in conflicts[:3]] or ["No material opposing directional evidence is currently available."],
            "limitations": list(memory.get("limitations") or []) + ["APEX produces conditional decision support, not certainty or guaranteed outcomes."],
        },
        "base_decision": base,
        "guardrails": {"read_only": True, "broker_mutation": False, "automatic_execution": False,
                       "automatic_weight_mutation": False, "human_confirmation_required": True,
                       "existing_kill_switch_authoritative": True, "does_not_change_execution_permissions": True,
                       "look_ahead_protection_supported": True},
    }
