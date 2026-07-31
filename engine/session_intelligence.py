"""APEX 50.4.2 — centralized US/Eastern session intelligence."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, asdict
from typing import Optional

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    ET = dt.timezone(dt.timedelta(hours=-5))


@dataclass(frozen=True)
class SessionContext:
    state: str
    brief_mode: str
    label: str
    market_open: bool
    narrative_policy: str
    generated_at_et: str

    def to_dict(self) -> dict:
        return asdict(self)


def classify_session(now: Optional[dt.datetime] = None) -> SessionContext:
    now = (now or dt.datetime.now(ET)).astimezone(ET)
    minute = now.hour * 60 + now.minute
    weekday = now.weekday()

    if weekday >= 5:
        state, mode, label, opened, policy = (
            "WEEKEND", "NEXT_SESSION_PREP", "Weekend / next-session preparation", False, "SESSION_AWARE"
        )
    elif minute < 4 * 60:
        state, mode, label, opened, policy = (
            "OVERNIGHT", "NEXT_SESSION_PREP", "Overnight / next-session preparation", False, "SESSION_AWARE"
        )
    elif minute < 9 * 60 + 30:
        state, mode, label, opened, policy = (
            "PREMARKET", "PREMARKET", "Pre-market", False, "SESSION_AWARE"
        )
    elif minute < 10 * 60 + 30:
        state, mode, label, opened, policy = (
            "OPENING_DRIVE", "LIVE_SESSION", "Opening drive", True, "SESSION_AWARE"
        )
    elif minute < 11 * 60 + 30:
        state, mode, label, opened, policy = (
            "MID_MORNING", "LIVE_SESSION", "Mid-morning", True, "SESSION_AWARE"
        )
    elif minute < 13 * 60 + 30:
        state, mode, label, opened, policy = (
            "LUNCH", "LIVE_SESSION", "Lunch auction", True, "SESSION_AWARE"
        )
    elif minute < 15 * 60:
        state, mode, label, opened, policy = (
            "AFTERNOON", "LIVE_SESSION", "Afternoon session", True, "SESSION_AWARE"
        )
    elif minute < 16 * 60:
        state, mode, label, opened, policy = (
            "POWER_HOUR", "LIVE_SESSION", "Power hour", True, "SESSION_AWARE"
        )
    elif minute < 20 * 60:
        state, mode, label, opened, policy = (
            "AFTER_HOURS", "AFTER_CLOSE", "After hours", False, "SESSION_AWARE"
        )
    else:
        state, mode, label, opened, policy = (
            "OVERNIGHT", "NEXT_SESSION_PREP", "Overnight / next-session preparation", False, "SESSION_AWARE"
        )

    return SessionContext(
        state=state,
        brief_mode=mode,
        label=label,
        market_open=opened,
        narrative_policy=policy,
        generated_at_et=now.isoformat(),
    )
