"""Flow authenticity controls derived from the July 2026 SPX 0DTE research brief.

This module distinguishes observable print structure from inferred directional intent.
Clock-synchronised, complex activity is labelled as scheduled/automated until future
market observations confirm persistence. It never fabricates institutional intent.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

FLOW_AUTHENTICITY_VERSION = "9.4.0_FLOW_AUTHENTICITY"
_CLOCK_WINDOW_S = int(os.getenv("FLOW_CLOCK_SYNC_WINDOW_S", "20"))
_COMPLEX_RATIO_THRESHOLD = float(os.getenv("FLOW_COMPLEX_RATIO_THRESHOLD", "0.50"))


def _secs(value: Any) -> Optional[int]:
    parts = str(value or "").strip().split(":")
    if len(parts) < 2:
        return None
    try:
        h, m = int(parts[0]), int(parts[1])
        s = int(parts[2]) if len(parts) > 2 else 0
    except (TypeError, ValueError):
        return None
    if not (0 <= h < 24 and 0 <= m < 60 and 0 <= s < 60):
        return None
    return h * 3600 + m * 60 + s


def clock_sync_distance_seconds(time_et: Any) -> Optional[int]:
    """Distance to the nearest hour or half-hour boundary."""
    sec = _secs(time_et)
    if sec is None:
        return None
    remainder = sec % 1800
    return min(remainder, 1800 - remainder)


def assess_cluster_authenticity(cluster: Dict[str, Any], *,
                                confirmation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return an auditable authenticity state for a flow cluster.

    `confirmation` is intentionally optional because persistence is a future fact.
    Supported fields are flow_persistence_30s, flow_persistence_2m,
    price_response_after_cluster, es_confirmation, and liquidity_response.
    Values should be booleans or None; absence means not yet measurable.
    """
    n = max(int(cluster.get("number_of_prints") or 0), 1)
    start_dist = clock_sync_distance_seconds(cluster.get("start_time"))
    end_dist = clock_sync_distance_seconds(cluster.get("end_time"))
    distances = [d for d in (start_dist, end_dist) if d is not None]
    near_boundary = bool(distances and min(distances) <= _CLOCK_WINDOW_S)

    intents = cluster.get("intent_summary") or {}
    complex_count = sum(int(intents.get(k) or 0) for k in
                        ("spread_leg_candidate", "likely_roll", "possible_hedge"))
    complex_ratio = min(1.0, complex_count / n)
    predominantly_complex = complex_ratio >= _COMPLEX_RATIO_THRESHOLD
    scheduled_candidate = near_boundary and predominantly_complex

    conf = confirmation or {}
    keys = ("flow_persistence_30s", "flow_persistence_2m",
            "price_response_after_cluster", "es_confirmation", "liquidity_response")
    measured = {k: conf.get(k) for k in keys if conf.get(k) is not None}
    positive = sum(v is True for v in measured.values())
    negative = sum(v is False for v in measured.values())

    if not scheduled_candidate:
        state = "OBSERVED_DIRECTIONAL_FLOW"
        multiplier = 1.0
        reason = "Cluster does not meet both clock-synchronisation and complex-order criteria."
    elif len(measured) < 3:
        state = "SCHEDULED_AUTOMATED_FLOW_PENDING_CONFIRMATION"
        multiplier = 0.45
        reason = "Clock-synchronised complex flow requires future persistence and market-response evidence."
    elif positive >= 3 and positive > negative:
        state = "SCHEDULED_FLOW_CONFIRMED_DIRECTIONAL"
        multiplier = 0.85
        reason = "The initially mechanical-looking burst received multi-source follow-through confirmation."
    else:
        state = "SCHEDULED_AUTOMATED_FLOW_UNCONFIRMED"
        multiplier = 0.25
        reason = "Follow-through evidence was insufficient or contradictory."

    return {
        "state": state,
        "scheduled_candidate": scheduled_candidate,
        "near_hour_or_half_hour": near_boundary,
        "boundary_distance_seconds": min(distances) if distances else None,
        "clock_sync_window_seconds": _CLOCK_WINDOW_S,
        "complex_print_count": complex_count,
        "complex_print_ratio": round(complex_ratio, 3),
        "predominantly_complex": predominantly_complex,
        "directional_confidence_multiplier": multiplier,
        "confirmation": {k: conf.get(k) for k in keys},
        "confirmation_measured_count": len(measured),
        "confirmation_positive_count": positive,
        "reason": reason,
        "version": FLOW_AUTHENTICITY_VERSION,
    }
