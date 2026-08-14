"""engine/dynamic_state.py — APEX Dynamic State surface.

Read-only aggregator that pulls the three 66.4 dynamic-state signals out of the
already-composed Data Bus into one normalized block the dashboard renders:

  1. Flow Excitation        — is current flow a genuine surge or one repeated
                              burst?  (independent_evidence_factor / redundancy)
  2. Residual Pressure       — did an absorbed/contained move leave unresolved
                              pressure that can re-fire?
  3. Gamma Path              — the SPATIAL gamma map: where price is drawn next,
                              upside/downside destinations, not a single scalar.

It recomputes nothing; every value is read straight from the engines that
already produced it, so the surface always agrees with the pipeline.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple


def _get(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, Mapping) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _first(obj: Mapping[str, Any], paths: Tuple[str, ...]) -> Any:
    for p in paths:
        v = _get(obj, p)
        if v not in (None, "", [], {}):
            return v
    return None


def _f(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# Candidate bus locations for each signal (robust to exact composition keys).
_FLOW_PATHS = (
    "institutional_options_flow", "options_flow_engine", "options_flow", "flow",
)
_GAMMA_PATHS = (
    "dealer_positioning.gamma_path", "gamma.gamma_path", "gamma_path",
    "dealer_positioning.gamma.gamma_path",
)
_RESIDUAL_PATHS = (
    "execution_intelligence.residual_pressure_memory", "residual_pressure_memory",
)


def _flow_excitation(lr: Mapping[str, Any]) -> Dict[str, Any]:
    block = None
    for p in _FLOW_PATHS:
        cand = _get(lr, p)
        if isinstance(cand, Mapping):
            block = cand
            break
    fe = (block or {}).get("flow_excitation") if isinstance(block, Mapping) else None
    if not isinstance(fe, Mapping):
        fe = block if isinstance(block, Mapping) and "excitation_ratio" in block else None
    if not isinstance(fe, Mapping):
        return {"available": False, "state": "NO_FLOW",
                "independent_evidence_factor": None, "redundancy_factor": None,
                "excitation_ratio": None, "burst_count": None}
    ief = _f(fe.get("independent_evidence_factor"))
    if ief is None and isinstance(block, Mapping):
        ief = _f(block.get("independent_evidence_factor"))
    return {
        "available": bool(fe.get("available", True)),
        "state": str(fe.get("state") or "NORMAL"),
        "excitation_ratio": _f(fe.get("excitation_ratio")),
        "burst_count": _f(fe.get("burst_count")),
        "event_count": _f(fe.get("event_count")),
        "independent_evidence_factor": ief,
        "redundancy_factor": _f(fe.get("redundancy_factor")),
        "same_burst_probability": _f(fe.get("same_burst_probability")),
    }


def _residual_pressure(lr: Mapping[str, Any], scanner_state: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    rp = None
    for p in _RESIDUAL_PATHS:
        cand = _get(lr, p)
        if isinstance(cand, Mapping):
            rp = cand
            break
    if rp is None and isinstance(scanner_state, Mapping):
        cand = scanner_state.get("residual_pressure_memory")
        if isinstance(cand, Mapping):
            rp = cand
    if not isinstance(rp, Mapping):
        return {"available": False, "state": "NONE", "direction": None,
                "remaining_pressure": None, "unresolved": False}
    return {
        "available": True,
        "state": str(rp.get("state") or "NONE"),
        "direction": str(rp.get("direction") or "UNKNOWN"),
        "remaining_pressure": _f(rp.get("remaining_pressure")),
        "initial_pressure": _f(rp.get("initial_pressure")),
        "origin_level": rp.get("origin_level"),
        "absorption_signal": rp.get("absorption_signal"),
        "unresolved": bool(rp.get("unresolved")),
    }


def _gamma_path(lr: Mapping[str, Any]) -> Dict[str, Any]:
    gp = None
    for p in _GAMMA_PATHS:
        cand = _get(lr, p)
        if isinstance(cand, Mapping):
            gp = cand
            break
    if not isinstance(gp, Mapping) or not gp.get("available", False):
        return {"available": False, "current_regime": "UNKNOWN",
                "upside_destination": None, "downside_destination": None, "path_levels": []}

    def _dest(d: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(d, Mapping):
            return None
        return {"price": _f(d.get("price")), "label": d.get("label") or d.get("type"),
                "distance": _f(d.get("distance"))}

    levels = gp.get("path_levels") if isinstance(gp.get("path_levels"), list) else []
    return {
        "available": True,
        "current_regime": str(gp.get("current_regime") or gp.get("regime") or "UNKNOWN"),
        "active_flip": _f(gp.get("active_flip") or gp.get("flip")),
        "upside_destination": _dest(gp.get("upside_destination")),
        "downside_destination": _dest(gp.get("downside_destination")),
        "path_levels": [
            {"price": _f(l.get("price") or l.get("strike")),
             "net": _f(l.get("net")), "label": l.get("label") or l.get("type")}
            for l in levels if isinstance(l, Mapping)
        ][:12],
    }


def build_dynamic_state(last_result: Optional[Mapping[str, Any]],
                        scanner_state: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Assemble the three dynamic-state signals into one dashboard block."""
    lr = last_result if isinstance(last_result, Mapping) else {}
    flow = _flow_excitation(lr)
    residual = _residual_pressure(lr, scanner_state)
    gamma = _gamma_path(lr)
    available = any(x.get("available") for x in (flow, residual, gamma))

    # One-line read of what the three signals collectively imply (neutral).
    notes = []
    ief = flow.get("independent_evidence_factor")
    if flow.get("available") and ief is not None and ief < 0.5:
        notes.append("flow is largely one repeated burst — evidence discounted")
    elif flow.get("available") and flow.get("state") in ("HIGH_EXCITATION", "ELEVATED_EXCITATION"):
        notes.append(f"{str(flow['state']).replace('_', ' ').lower()}")
    if residual.get("unresolved"):
        notes.append(f"unresolved {str(residual.get('direction') or '').lower()} pressure at {residual.get('origin_level')}")
    if gamma.get("available") and gamma.get("current_regime") not in ("UNKNOWN", None):
        notes.append(f"gamma {str(gamma['current_regime']).replace('_', ' ').lower()}")

    return {
        "available": available,
        "flow_excitation": flow,
        "residual_pressure": residual,
        "gamma_path": gamma,
        "summary": " · ".join(notes) if notes else None,
    }
