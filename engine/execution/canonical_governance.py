"""APEX 66.4.0 — Canonical Decision Execution Governance.

Single source of truth for one rule: the institutional reasoning layer GOVERNS
new risk initiation. Opening or increasing risk requires an authoritative
canonical decision that is actionable, carries an ACTIVE institutional thesis,
agrees in direction with the proposed order, and is fresh.

The rule is ASYMMETRIC, and the asymmetry is enforced structurally by the
caller: only the risk-opening executors (single-leg / complex entry) consult
this module. Risk-reducing and protective actions (EXIT / TRIM_* /
PROTECT_PROFIT / MOVE_STOP_BE / CANCEL) never call it and are therefore never
blocked by thesis state. An INVALIDATED thesis must never trap a position — if
anything it strengthens the case for reducing risk.

This module is pure and deterministic: no I/O, and no wall clock beyond the
`now_epoch` the caller injects. That makes the governance rule trivially
testable in isolation from the broker path.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

# Explicit blocker codes so the UI and audit trail show exactly why a NEW trade
# was refused, instead of a generic failure. These are contract; do not rename
# without updating consumers.
CANONICAL_DECISION_UNAVAILABLE = "CANONICAL_DECISION_UNAVAILABLE"
CANONICAL_DECISION_NOT_ACTIONABLE = "CANONICAL_DECISION_NOT_ACTIONABLE"
THESIS_NOT_ACTIVE = "THESIS_NOT_ACTIVE"
DECISION_DIRECTION_MISMATCH = "DECISION_DIRECTION_MISMATCH"
CANONICAL_DECISION_STALE = "CANONICAL_DECISION_STALE"
CANONICAL_DECISION_NO_TRADE = "CANONICAL_DECISION_NO_TRADE"

_ACTIVE = "ACTIVE"
_DIRECTIONAL = ("BULLISH", "BEARISH")


def _side_to_direction(side: Any) -> Optional[str]:
    """Map a proposed order side to the directional call it implies.

    Returns None when the side has no directional meaning (e.g. a delta-neutral
    strategy), in which case direction agreement is not enforced.
    """
    s = str(side or "").upper().strip()
    if s in ("CALL", "C", "LONG_CALL", "BUY_CALL", "LONG", "BULLISH"):
        return "BULLISH"
    if s in ("PUT", "P", "LONG_PUT", "BUY_PUT", "SHORT", "BEARISH"):
        return "BEARISH"
    return None


def _parse_epoch(value: Any) -> Optional[float]:
    """Parse an epoch float or an ISO-8601 timestamp into epoch seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.timestamp()
    except Exception:
        return None


def governance_snapshot_from_decision(decision: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Extract the governance-relevant summary from a canonical institutional
    decision. Returns ``{"available": False}`` when no decision exists so that
    opening risk fails closed.
    """
    if not isinstance(decision, Mapping) or not decision:
        return {"available": False}
    thesis = decision.get("thesis") or decision.get("institutional_thesis") or {}
    thesis_state = (thesis.get("state") if isinstance(thesis, Mapping) else None) \
        or decision.get("thesis_state") or "UNKNOWN"
    narrative = decision.get("narrative") if isinstance(decision.get("narrative"), Mapping) else {}
    return {
        "available": True,
        "authoritative": bool(
            decision.get("authoritative_contract")
            or decision.get("decision_authority") == "institutional_decision_object"
        ),
        "actionable": bool(decision.get("actionable")),
        "action": str(decision.get("action") or decision.get("decision_state") or "NO_TRADE").upper(),
        "direction": str(decision.get("direction") or "NEUTRAL").upper(),
        "thesis_state": str(thesis_state).upper(),
        "generated_at": decision.get("timestamp") or decision.get("generated_at")
        or (narrative or {}).get("generated_at"),
    }


@dataclass
class GovernanceResult:
    allow: bool
    blockers: List[Dict[str, str]] = field(default_factory=list)
    evaluated: bool = True
    thesis_state: str = "UNKNOWN"
    decision_direction: str = "NEUTRAL"
    required_direction: Optional[str] = None
    age_seconds: Optional[float] = None

    @property
    def codes(self) -> List[str]:
        return [b["code"] for b in self.blockers]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allow": self.allow,
            "evaluated": self.evaluated,
            "blockers": self.blockers,
            "codes": self.codes,
            "thesis_state": self.thesis_state,
            "decision_direction": self.decision_direction,
            "required_direction": self.required_direction,
            "age_seconds": self.age_seconds,
            "policy": "OPEN_RISK_REQUIRES_ACTIONABLE_CANONICAL_DECISION",
        }


def evaluate_open_risk(snapshot: Optional[Mapping[str, Any]], *, proposed_side: Any,
                       now_epoch: float, max_age_seconds: float) -> GovernanceResult:
    """Governance gate for OPENING or INCREASING risk ONLY.

    Never call this for risk-reducing or protective actions; those must always
    be permitted. Returns ``allow=False`` with explicit blocker codes when the
    canonical decision does not authorize opening new risk.
    """
    snap = dict(snapshot or {})
    required = _side_to_direction(proposed_side)
    res = GovernanceResult(
        allow=True,
        thesis_state=str(snap.get("thesis_state") or "UNKNOWN").upper(),
        decision_direction=str(snap.get("direction") or "NEUTRAL").upper(),
        required_direction=required,
    )

    # No authoritative decision at all -> cannot open new risk.
    if not snap.get("available"):
        res.allow = False
        res.blockers.append({
            "code": CANONICAL_DECISION_UNAVAILABLE,
            "detail": "No authoritative canonical decision available; refusing to open new risk.",
        })
        return res
    if not snap.get("authoritative", True):
        res.allow = False
        res.blockers.append({
            "code": CANONICAL_DECISION_UNAVAILABLE,
            "detail": "Decision is not the authoritative institutional_decision_object.",
        })
        return res

    # Freshness — measured from the decision's own generated_at, enforced at the
    # irreversible placement step.
    ts = _parse_epoch(snap.get("generated_at"))
    if ts is None:
        res.allow = False
        res.blockers.append({
            "code": CANONICAL_DECISION_STALE,
            "detail": "Canonical decision has no verifiable timestamp; treated as stale for opening risk.",
        })
    else:
        age = max(0.0, float(now_epoch) - ts)
        res.age_seconds = round(age, 1)
        if age > float(max_age_seconds):
            res.allow = False
            res.blockers.append({
                "code": CANONICAL_DECISION_STALE,
                "detail": f"Canonical decision is {age:.0f}s old (> {float(max_age_seconds):.0f}s freshness budget).",
            })

    if not snap.get("actionable"):
        res.allow = False
        res.blockers.append({
            "code": CANONICAL_DECISION_NOT_ACTIONABLE,
            "detail": "Canonical decision is not actionable.",
        })

    if str(snap.get("action") or "NO_TRADE").upper() == "NO_TRADE" \
            and CANONICAL_DECISION_NOT_ACTIONABLE not in res.codes:
        # Surface NO_TRADE distinctly only when it isn't already implied by
        # NOT_ACTIONABLE, to avoid duplicate noise.
        res.allow = False
        res.blockers.append({
            "code": CANONICAL_DECISION_NO_TRADE,
            "detail": "Canonical action is NO_TRADE.",
        })

    if res.thesis_state != _ACTIVE:
        res.allow = False
        res.blockers.append({
            "code": THESIS_NOT_ACTIVE,
            "detail": f"Institutional thesis is {res.thesis_state}, not ACTIVE.",
        })

    # Direction agreement only when both the proposed side and the canonical
    # decision express a direction. A NEUTRAL canonical read is caught above by
    # NOT_ACTIONABLE / THESIS_NOT_ACTIVE, not by a mismatch.
    if required is not None and res.decision_direction in _DIRECTIONAL \
            and res.decision_direction != required:
        res.allow = False
        res.blockers.append({
            "code": DECISION_DIRECTION_MISMATCH,
            "detail": f"Proposed {str(proposed_side).upper()} implies {required}, "
                      f"but canonical direction is {res.decision_direction}.",
        })

    return res
