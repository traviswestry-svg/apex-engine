"""APEX 68.2 — Dynamic-state alert governance.

Consumes already-computed dynamic state and translates it into deterministic,
explainable alert-quality adjustments.  This module does not create directional
signals and does not mutate broker/execution state.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Mapping, Optional

from .dynamic_state import build_dynamic_state

VERSION = "68.2.0"
SCHEMA_VERSION = "apex.dynamic_state_policy.v1"


def _mapping(v: Any) -> Dict[str, Any]:
    return dict(v) if isinstance(v, Mapping) else {}


def _f(v: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _direction(v: Any) -> str:
    s = str(v or "").upper()
    if any(x in s for x in ("BULL", "CALL", "LONG", "UP")):
        return "BULLISH"
    if any(x in s for x in ("BEAR", "PUT", "SHORT", "DOWN")):
        return "BEARISH"
    return "NEUTRAL"


def _age_seconds(iso: Any, now: Optional[dt.datetime] = None) -> Optional[float]:
    if not iso:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        ref = now or dt.datetime.now(dt.timezone.utc)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=dt.timezone.utc)
        return max(0.0, (ref.astimezone(dt.timezone.utc) - parsed.astimezone(dt.timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


def evaluate_dynamic_state_policy(
    snapshot: Optional[Mapping[str, Any]], *,
    direction: Any = None,
    dynamic_state: Optional[Mapping[str, Any]] = None,
    now: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    """Return policy adjustments without inventing a trade direction.

    Hard suppression is reserved for scheduled-release windows or severely stale
    gamma context.  Other dynamic conditions increase the required decision
    margin and/or reduce conviction while remaining inspectable by the caller.
    """
    s = _mapping(snapshot)
    ds = _mapping(dynamic_state) or build_dynamic_state(s)
    resolved_direction = _direction(direction or s.get("direction") or s.get("bias"))

    warnings = []
    blockers = []
    modifiers = []
    threshold_add = 0.0
    conviction_penalty = 0.0
    consensus_penalty = 0.0
    watch_only = False
    suppress = False

    # Flow independence is primarily consumed by consensus weighting.  The policy
    # exposes the condition and only adds a small boundary buffer, avoiding a
    # second full conviction penalty for the same redundancy.
    flow = _mapping(ds.get("flow_excitation"))
    ief = _f(flow.get("independent_evidence_factor"))
    if flow.get("available") and ief is not None:
        if ief < 0.25:
            threshold_add += 3.0
            warnings.append("FLOW_EVIDENCE_HIGHLY_REDUNDANT")
            modifiers.append({"driver": "flow_independence", "value": round(ief, 3), "effect": "REQUIRE_MORE_MARGIN"})
        elif ief < 0.50:
            threshold_add += 1.5
            warnings.append("FLOW_EVIDENCE_PARTLY_REDUNDANT")
            modifiers.append({"driver": "flow_independence", "value": round(ief, 3), "effect": "REQUIRE_MORE_MARGIN"})

    residual = _mapping(ds.get("residual_pressure"))
    residual_dir = _direction(residual.get("direction"))
    if residual.get("available") and residual.get("unresolved") and residual_dir != "NEUTRAL" and resolved_direction != "NEUTRAL":
        remaining = max(0.0, min(100.0, _f(residual.get("remaining_pressure"), 0.0) or 0.0))
        if residual_dir != resolved_direction:
            p = 3.0 + min(5.0, remaining / 20.0)
            conviction_penalty += p
            threshold_add += 3.0
            warnings.append("RESIDUAL_PRESSURE_OPPOSES_DIRECTION")
            modifiers.append({"driver": "residual_pressure", "direction": residual_dir, "remaining": round(remaining, 1), "effect": "OPPOSES"})
        else:
            modifiers.append({"driver": "residual_pressure", "direction": residual_dir, "remaining": round(remaining, 1), "effect": "ALIGNED_NO_BONUS"})

    gamma_term = _mapping(ds.get("gamma_term_structure"))
    if gamma_term.get("available"):
        if gamma_term.get("term_divergence"):
            conviction_penalty += 4.0
            consensus_penalty += 3.0
            threshold_add += 2.0
            warnings.append("GAMMA_TERM_DIVERGENCE")
            modifiers.append({"driver": "gamma_term_structure", "effect": "TERM_DIVERGENCE"})
        if gamma_term.get("near_term_fragility"):
            conviction_penalty += 2.0
            threshold_add += 1.0
            warnings.append("NEAR_TERM_GAMMA_FRAGILITY")
            modifiers.append({"driver": "gamma_term_structure", "effect": "NEAR_TERM_FRAGILITY"})

    gamma = _mapping(ds.get("gamma_path"))
    source_age = _age_seconds(gamma.get("source_snapshot_at") or gamma.get("generated_at"), now=now) if gamma.get("available") else None
    if source_age is not None and source_age > 600:
        watch_only = True
        threshold_add += 5.0
        conviction_penalty += 6.0
        warnings.append("GAMMA_PATH_SEVERELY_STALE")
        modifiers.append({"driver": "gamma_path_age", "seconds": round(source_age, 1), "effect": "WATCH_ONLY"})
    elif source_age is not None and source_age > 180:
        threshold_add += 2.0
        conviction_penalty += 2.0
        warnings.append("GAMMA_PATH_AGING")
        modifiers.append({"driver": "gamma_path_age", "seconds": round(source_age, 1), "effect": "REQUIRE_MORE_MARGIN"})

    event = _mapping(ds.get("event_phase"))
    phase = str(event.get("phase") or "NORMAL").upper()
    if phase == "PRE_EVENT":
        threshold_add += 3.0
        conviction_penalty += 3.0
        warnings.append("PRE_EVENT_RISK")
        modifiers.append({"driver": "event_phase", "phase": phase, "effect": "TIGHTEN_ENTRY"})
    elif phase == "EVENT_IMMINENT":
        suppress = True
        blockers.append("EVENT_IMMINENT_NEW_ALERT_SUPPRESSION")
        modifiers.append({"driver": "event_phase", "phase": phase, "effect": "SUPPRESS_NEW_ALERT"})
    elif phase == "RELEASE":
        suppress = True
        blockers.append("EVENT_RELEASE_NEW_ALERT_SUPPRESSION")
        modifiers.append({"driver": "event_phase", "phase": phase, "effect": "SUPPRESS_NEW_ALERT"})
    elif phase == "PRICE_DISCOVERY":
        watch_only = True
        threshold_add += 8.0
        conviction_penalty += 8.0
        warnings.append("POST_EVENT_PRICE_DISCOVERY")
        modifiers.append({"driver": "event_phase", "phase": phase, "effect": "WATCH_ONLY"})
    elif phase == "POST_EVENT_NORMALIZATION":
        threshold_add += 1.0
        warnings.append("POST_EVENT_NORMALIZATION")
        modifiers.append({"driver": "event_phase", "phase": phase, "effect": "MILD_BUFFER"})

    from .calibration_activation import active_adjustments
    cal_adj = active_adjustments()
    if cal_adj.get("active"):
        threshold_add += cal_adj["threshold_adjustment_points"]

    state = "SUPPRESSED" if suppress else "WATCH_ONLY" if watch_only else "NORMAL"
    return {
        "schema_version": SCHEMA_VERSION,
        "version": VERSION,
        "state": state,
        "direction": resolved_direction,
        "threshold_adjustment_points": round(threshold_add, 1),
        "required_boundary_margin_points": round(5.0 + threshold_add, 1),
        "conviction_penalty_points": round(conviction_penalty, 1),
        "consensus_penalty_points": round(consensus_penalty, 1),
        "suppress_new_alerts": suppress,
        "watch_only": watch_only,
        "blocking_conditions": blockers,
        "warnings": warnings,
        "modifiers": modifiers,
        "calibration_activation": cal_adj,
        "provenance": {"dynamic_state_available": bool(ds.get("available")), "policy_is_directionally_non_generative": True},
    }
