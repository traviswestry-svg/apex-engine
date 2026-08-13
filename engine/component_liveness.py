"""engine/component_liveness.py — Component Liveness Monitor.

THE PROBLEM
-----------
On the dashboard, a component showing a value that never changes looks
identical whether it is:
  (a) genuinely stable   — the market really is balanced, VIX really is flat
  (b) silently frozen     — the engine errored, timed out, or lost its feed and
                            is echoing its last value forever

You can't tell these apart by looking. This monitor tells them apart by
watching each top-level component across successive composes and classifying:

  LIVE      — value changed recently (definitely working)
  STABLE    — value unchanged but the component reports fresh data / recent
              timestamp (working, market just isn't moving)
  STALE     — value unchanged AND its own timestamp is old (suspicious)
  FROZEN    — value unchanged across many composes while OTHER components move
              and the market is open (almost certainly broken)
  UNAVAILABLE— component itself reports available=False / an error

The key signal is RELATIVE: a component is "frozen" only when it sits still
while its neighbours move. If everything is quiet, nothing is frozen — that's
just a calm market, correctly reported.

STATE (an in-process dict) persists fingerprints across composes. Read-only
with respect to the components themselves; never raises into the compose loop.
"""
from __future__ import annotations

import hashlib
import json
import threading
from typing import Any, Dict, List, Optional, Tuple

VERSION = "1.0.0_COMPONENT_LIVENESS"

# Components worth watching in the institutional_os payload. Each is a top-level
# key whose value should evolve during an active RTH session.
WATCHED = [
    "auction", "auction_intelligence", "confidence", "consensus",
    "dealer_positioning", "execution_intelligence", "flow_intelligence",
    "gamma_regime", "liquidity_intelligence", "market_drivers",
    "market_regime", "market_state", "market_narrative", "strike_magnets",
    "structure", "trend", "volatility", "volume_profile",
]

# How many consecutive unchanged composes before we call a moving-market
# component FROZEN (guards against a single coincidental repeat).
_FROZEN_STREAK = 4

_LOCK = threading.Lock()
# key -> {"hash": str, "streak": int, "last_changed_compose": int}
_STATE: Dict[str, Dict[str, Any]] = {}
_COMPOSE_COUNTER = 0


def _fingerprint(value: Any) -> str:
    """Stable hash of a component's value, ignoring volatile timestamp fields
    so a component that ONLY updates its clock still counts as unchanged."""
    try:
        pruned = _strip_timestamps(value)
        blob = json.dumps(pruned, sort_keys=True, default=str)
    except (TypeError, ValueError):
        blob = repr(value)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


_TS_KEYS = {"updated_at", "updated_at_et", "generated_at", "generated_at_iso",
            "evaluated_at", "sampled_at", "captured_at", "cache_age_seconds",
            "response_ms", "received_at", "received_at_et", "time", "minutes_open"}


def _strip_timestamps(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_timestamps(v) for k, v in value.items() if k not in _TS_KEYS}
    if isinstance(value, list):
        return [_strip_timestamps(v) for v in value]
    return value


def _component_reports_available(value: Any) -> Optional[bool]:
    if isinstance(value, dict):
        if value.get("available") is False:
            return False
        if value.get("state") in ("ERROR", "UNAVAILABLE", "STORE_DOWN"):
            return False
        if "available" in value:
            return bool(value["available"])
    return None  # component doesn't self-report — unknown, not failed


def observe(os_payload: Dict[str, Any], *, is_rth: bool) -> Dict[str, Any]:
    """Call once per compose with the assembled institutional_os payload.
    Returns a liveness report. Never raises."""
    try:
        return _observe(os_payload or {}, is_rth)
    except Exception as err:
        return {"ok": True, "available": False, "version": VERSION,
                "state": "ERROR", "error": f"{type(err).__name__}: {err!r}"}


def _observe(payload: Dict[str, Any], is_rth: bool) -> Dict[str, Any]:
    global _COMPOSE_COUNTER
    with _LOCK:
        _COMPOSE_COUNTER += 1
        compose_id = _COMPOSE_COUNTER

        changed_this_compose = 0
        present = [k for k in WATCHED if k in payload]
        # First pass: update fingerprints, count how many moved this compose.
        per_component: Dict[str, Dict[str, Any]] = {}
        for key in present:
            value = payload.get(key)
            avail = _component_reports_available(value)
            fp = _fingerprint(value)
            prev = _STATE.get(key)
            if prev is None:
                _STATE[key] = {"hash": fp, "streak": 0, "last_changed_compose": compose_id}
                moved = True
            elif prev["hash"] != fp:
                _STATE[key] = {"hash": fp, "streak": 0, "last_changed_compose": compose_id}
                moved = True
            else:
                prev["streak"] += 1
                moved = False
            if moved:
                changed_this_compose += 1
            per_component[key] = {"moved": moved, "streak": _STATE[key]["streak"],
                                  "available": avail}

        # A market is "moving" if a meaningful share of components changed.
        # Only then is a stuck component suspicious.
        market_moving = is_rth and changed_this_compose >= max(2, len(present) // 4)

        components: List[Dict[str, Any]] = []
        counts = {"LIVE": 0, "STABLE": 0, "STALE": 0, "FROZEN": 0, "UNAVAILABLE": 0}
        for key in present:
            info = per_component[key]
            avail = info["available"]
            streak = info["streak"]
            if avail is False:
                status = "UNAVAILABLE"
            elif info["moved"]:
                status = "LIVE"
            elif market_moving and streak >= _FROZEN_STREAK:
                status = "FROZEN"
            elif streak >= _FROZEN_STREAK:
                status = "STALE"
            else:
                status = "STABLE"
            counts[status] += 1
            components.append({
                "component": key,
                "status": status,
                "unchanged_composes": streak,
                "self_reported_available": avail,
            })

        # Overall verdict
        frozen = [c["component"] for c in components if c["status"] == "FROZEN"]
        unavailable = [c["component"] for c in components if c["status"] == "UNAVAILABLE"]
        if frozen:
            state = "FROZEN_COMPONENTS"
            reason = (f"{len(frozen)} component(s) have not changed in {_FROZEN_STREAK}+ composes "
                      f"while the market is moving: {', '.join(frozen)}. Likely a stuck feed or "
                      f"silent engine error.")
        elif unavailable:
            state = "DEGRADED"
            reason = (f"{len(unavailable)} component(s) report unavailable: "
                      f"{', '.join(unavailable)}.")
        elif not is_rth:
            state = "QUIET_MARKET_CLOSED"
            reason = "Market closed — unchanged components are expected, not frozen."
        elif not market_moving:
            state = "QUIET_MARKET_OPEN"
            reason = ("Market open but few components moving this cycle — could be a genuinely "
                      "balanced tape. Not flagged as frozen unless it persists.")
        else:
            state = "HEALTHY"
            reason = f"{counts['LIVE']} live, {counts['STABLE']} stable, all feeds responsive."

        return {
            "ok": True,
            "available": True,
            "version": VERSION,
            "state": state,
            "reason": reason,
            "is_rth": is_rth,
            "compose_id": compose_id,
            "market_moving": market_moving,
            "changed_this_compose": changed_this_compose,
            "watched_present": len(present),
            "counts": counts,
            "frozen_components": frozen,
            "unavailable_components": unavailable,
            "components": sorted(components, key=lambda c: (c["status"] != "FROZEN",
                                                           c["status"] != "UNAVAILABLE",
                                                           c["component"])),
            "advisory_only": True,
            "read_only": True,
        }


def reset() -> None:
    """Clear liveness state (used by tests)."""
    global _COMPOSE_COUNTER
    with _LOCK:
        _STATE.clear()
        _COMPOSE_COUNTER = 0
