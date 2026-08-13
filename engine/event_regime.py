"""Event-specific intraday regime controls for SPX 0DTE systems.

This module deliberately separates scheduled-event identity from intraday phase.
It does not create trade direction. It supplies calibration, eligibility, and
risk-control context to downstream engines.
"""
from __future__ import annotations

import datetime as dt
from copy import deepcopy
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

VERSION = "10.0.0_EVENT_REGIME"
EASTERN = ZoneInfo("America/New_York")

NORMAL_SESSION = "NORMAL_SESSION"
EVENT_PRE_RELEASE = "EVENT_PRE_RELEASE"
EVENT_IMPULSE = "EVENT_IMPULSE"
EVENT_DISCOVERY = "EVENT_DISCOVERY"
POST_EVENT_NORMALIZATION = "POST_EVENT_NORMALIZATION"

# Event-specific settings are intentionally distinct. Values are calibration
# controls, not directional signals or predictions.
EVENT_PROFILES: Dict[str, Dict[str, Any]] = {
    "CPI": {
        "release_time_et": "08:30",
        "pre_release_minutes": 90,
        "impulse_minutes": 5,
        "discovery_minutes": 30,
        "normalization_minutes": 120,
        "alert_confidence_multiplier": {
            EVENT_PRE_RELEASE: 0.55, EVENT_IMPULSE: 0.35,
            EVENT_DISCOVERY: 0.70, POST_EVENT_NORMALIZATION: 0.90,
            NORMAL_SESSION: 1.0,
        },
        "slippage_multiplier": 1.45,
        "flow_velocity_multiplier": 1.35,
        "gamma_reliability_multiplier": 0.70,
    },
    "NFP": {
        "release_time_et": "08:30",
        "pre_release_minutes": 75,
        "impulse_minutes": 5,
        "discovery_minutes": 25,
        "normalization_minutes": 90,
        "alert_confidence_multiplier": {
            EVENT_PRE_RELEASE: 0.60, EVENT_IMPULSE: 0.40,
            EVENT_DISCOVERY: 0.72, POST_EVENT_NORMALIZATION: 0.92,
            NORMAL_SESSION: 1.0,
        },
        "slippage_multiplier": 1.35,
        "flow_velocity_multiplier": 1.25,
        "gamma_reliability_multiplier": 0.75,
    },
    "FOMC": {
        "release_time_et": "14:00",
        "pre_release_minutes": 120,
        "impulse_minutes": 10,
        "discovery_minutes": 45,
        "normalization_minutes": 120,
        "alert_confidence_multiplier": {
            EVENT_PRE_RELEASE: 0.50, EVENT_IMPULSE: 0.30,
            EVENT_DISCOVERY: 0.65, POST_EVENT_NORMALIZATION: 0.88,
            NORMAL_SESSION: 1.0,
        },
        "slippage_multiplier": 1.60,
        "flow_velocity_multiplier": 1.50,
        "gamma_reliability_multiplier": 0.65,
    },
    "PPI": {
        "release_time_et": "08:30",
        "pre_release_minutes": 60,
        "impulse_minutes": 5,
        "discovery_minutes": 20,
        "normalization_minutes": 75,
        "alert_confidence_multiplier": {
            EVENT_PRE_RELEASE: 0.70, EVENT_IMPULSE: 0.50,
            EVENT_DISCOVERY: 0.78, POST_EVENT_NORMALIZATION: 0.94,
            NORMAL_SESSION: 1.0,
        },
        "slippage_multiplier": 1.25,
        "flow_velocity_multiplier": 1.20,
        "gamma_reliability_multiplier": 0.82,
    },
}


def _as_et(now: Optional[dt.datetime]) -> dt.datetime:
    if now is None:
        return dt.datetime.now(EASTERN)
    if now.tzinfo is None:
        return now.replace(tzinfo=EASTERN)
    return now.astimezone(EASTERN)


def _release_at(now: dt.datetime, hhmm: str) -> dt.datetime:
    hour, minute = (int(x) for x in hhmm.split(":"))
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _primary_scheduled_event(event_intelligence: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    today = list(event_intelligence.get("today_events") or [])
    candidates = [e for e in today if str(e.get("key", "")).upper() in EVENT_PROFILES]
    if not candidates:
        return None
    priority = {"FOMC": 0, "CPI": 1, "NFP": 2, "PPI": 3}
    candidates.sort(key=lambda e: priority.get(str(e.get("key", "")).upper(), 99))
    return candidates[0]


def build_event_regime(*, now: Optional[dt.datetime] = None,
                       event_intelligence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build an event-specific intraday regime with honest measurability.

    If no supported scheduled release is present today, returns NORMAL_SESSION.
    """
    now_et = _as_et(now)
    event_intelligence = event_intelligence or {}
    event = _primary_scheduled_event(event_intelligence)
    if not event:
        return {
            "available": True, "version": VERSION, "state": NORMAL_SESSION,
            "event_type": None, "event_label": None, "release_time_et": None,
            "minutes_from_release": None, "profile": None,
            "alert_confidence_multiplier": 1.0,
            "gamma_reliability_multiplier": 1.0,
            "slippage_multiplier": 1.0,
            "flow_velocity_multiplier": 1.0,
            "baseline_bucket": "NORMAL", "baseline_eligible": True,
            "reason": "No supported scheduled macro release today.",
        }

    event_type = str(event.get("key", "")).upper()
    profile = deepcopy(EVENT_PROFILES[event_type])
    release = _release_at(now_et, profile["release_time_et"])
    minutes = (now_et - release).total_seconds() / 60.0

    if minutes < -float(profile["pre_release_minutes"]):
        state = NORMAL_SESSION
    elif minutes < 0:
        state = EVENT_PRE_RELEASE
    elif minutes <= float(profile["impulse_minutes"]):
        state = EVENT_IMPULSE
    elif minutes <= float(profile["discovery_minutes"]):
        state = EVENT_DISCOVERY
    elif minutes <= float(profile["normalization_minutes"]):
        state = POST_EVENT_NORMALIZATION
    else:
        state = NORMAL_SESSION

    # Event-day observations remain event-bucket observations even after the
    # active phase ends. This prevents contamination of ordinary baselines.
    baseline_bucket = f"EVENT_{event_type}"
    baseline_eligible = False
    mult = float(profile["alert_confidence_multiplier"].get(state, 1.0))
    return {
        "available": True, "version": VERSION, "state": state,
        "event_type": event_type, "event_label": event.get("label"),
        "release_time_et": profile["release_time_et"],
        "release_at": release.isoformat(),
        "minutes_from_release": round(minutes, 2),
        "profile": profile,
        "alert_confidence_multiplier": mult,
        "gamma_reliability_multiplier": float(profile["gamma_reliability_multiplier"]),
        "slippage_multiplier": float(profile["slippage_multiplier"]),
        "flow_velocity_multiplier": float(profile["flow_velocity_multiplier"]),
        "baseline_bucket": baseline_bucket,
        "baseline_eligible": baseline_eligible,
        "reason": _reason(state, event_type, minutes),
    }


def _reason(state: str, event_type: str, minutes: float) -> str:
    if state == EVENT_PRE_RELEASE:
        return f"{event_type} release pending; pre-release observations are separately calibrated."
    if state == EVENT_IMPULSE:
        return f"{event_type} initial impulse; confidence and gamma reliability are heavily reduced."
    if state == EVENT_DISCOVERY:
        return f"{event_type} price discovery; require post-release confirmation before full confidence."
    if state == POST_EVENT_NORMALIZATION:
        return f"{event_type} normalization; conditions are improving but remain event-calibrated."
    return f"{event_type} event day outside the active release window; retain event-specific baseline bucket."


def apply_event_confidence(raw_confidence: Optional[float], regime: Dict[str, Any]) -> Optional[float]:
    """Multiplicatively calibrate confidence; never add event points."""
    if raw_confidence is None:
        return None
    try:
        return round(max(0.0, min(100.0, float(raw_confidence) *
                                  float(regime.get("alert_confidence_multiplier", 1.0)))), 2)
    except (TypeError, ValueError):
        return None


def expected_move_decomposition(*, observed_expected_move: Optional[float],
                                normal_baseline_expected_move: Optional[float],
                                regime: Dict[str, Any]) -> Dict[str, Any]:
    """Separate baseline expected move from incremental scheduled-event premium.

    No baseline is inferred. If a leakage-safe normal baseline is unavailable,
    event premium remains unmeasurable rather than being fabricated.
    """
    try:
        observed = float(observed_expected_move) if observed_expected_move is not None else None
    except (TypeError, ValueError):
        observed = None
    try:
        baseline = (float(normal_baseline_expected_move)
                    if normal_baseline_expected_move is not None else None)
    except (TypeError, ValueError):
        baseline = None
    event_type = regime.get("event_type")
    premium = None
    reason = None
    if observed is not None and baseline is not None:
        premium = max(0.0, observed - baseline)
    elif event_type:
        reason = "Leakage-safe normal-session baseline unavailable."
    return {
        "observed_expected_move": observed,
        "baseline_expected_move": baseline,
        "incremental_scheduled_event_premium": round(premium, 4) if premium is not None else None,
        "event_type": event_type,
        "baseline_bucket": regime.get("baseline_bucket", "NORMAL"),
        "measurable": premium is not None,
        "unavailable_reason": reason,
    }


def baseline_sample_eligibility(regime: Dict[str, Any]) -> Dict[str, Any]:
    """Declare whether a sample may enter the ordinary no-event baseline."""
    eligible = bool(regime.get("baseline_eligible", False))
    return {
        "eligible_for_normal_baseline": eligible,
        "baseline_bucket": regime.get("baseline_bucket", "NORMAL"),
        "event_type": regime.get("event_type"),
        "event_state": regime.get("state", NORMAL_SESSION),
        "reason": ("Normal-session sample." if eligible else
                   "Scheduled-event-day sample must remain in its event-specific bucket."),
    }
