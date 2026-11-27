"""APEX 69.10.33 — canonical historical US equity/options session calendar.

Read-only calendar authority for attribution. It classifies an arbitrary timestamp
using America/New_York, full-day closure dates already governed by APEX, and RTH
boundaries. Unknown calendar years fail closed for RTH eligibility.
"""
from __future__ import annotations
import datetime as dt
from typing import Any, Dict
from zoneinfo import ZoneInfo

VERSION = "69.10.33"
TZ = ZoneInfo("America/New_York")
FULL_DAY_CLOSURES = frozenset({
    "2026-01-01","2026-01-19","2026-02-16","2026-04-03","2026-05-25","2026-06-19","2026-07-03","2026-09-07","2026-11-26","2026-12-25",
    "2027-01-01","2027-01-18","2027-02-15","2027-03-26","2027-05-31","2027-06-18","2027-07-05","2027-09-06","2027-11-25","2027-12-24",
})
SUPPORTED_YEARS = frozenset({2026, 2027})
# Explicit, operator-reviewed conservative SPX/RTH early-close dates. This
# mapping is not a complete source of exchange calendars; it MUST be reviewed
# and extended before using other early-close dates for live authorization.
EARLY_CLOSE_ET = {
    "2026-11-27": "13:00",  # Friday after Thanksgiving
    "2026-12-24": "13:00",  # Christmas Eve
    "2027-11-26": "13:00",  # Friday after Thanksgiving
}

def session_schedule(value: Any) -> Dict[str, Any]:
    """Conservative US cash/SPX RTH schedule; never asserts futures hours.

    Calendar unavailable or unsupported year is closed for new entries.
    This is a bounded 2026-27 table, NOT a perpetual exchange calendar.
    """
    d = _parse(value)
    day = d.date().isoformat()
    supported = d.year in SUPPORTED_YEARS
    holiday = day in FULL_DAY_CLOSURES
    weekend = d.weekday() >= 5
    trading_day = supported and not holiday and not weekend
    close_et = EARLY_CLOSE_ET.get(day, "16:00") if trading_day else None
    early_close = day in EARLY_CLOSE_ET and trading_day
    return {
        "session_date": day, "trading_day": trading_day,
        "calendar_supported": supported, "is_holiday": holiday,
        "is_weekend": weekend, "early_close": early_close,
        "open_et": "09:30" if trading_day else None,
        "close_et": close_et,
        "calendar_authority": "APEX_CANONICAL_US_EQUITY_OPTIONS",
        "calendar_scope": "BOUNDED_2026_2027_REVIEW_REQUIRED",
    }

def rth_open(value: Any) -> bool:
    try:
        d = _parse(value)
        s = session_schedule(d)
        if not s["trading_day"] or not s["close_et"]:
            return False
        minute = d.hour * 60 + d.minute
        hour, minute_close = map(int, s["close_et"].split(":"))
        return 570 <= minute < hour * 60 + minute_close
    except (ValueError, TypeError, OverflowError):
        return False


def _parse(value: Any) -> dt.datetime:
    if isinstance(value, dt.datetime):
        d=value
    else:
        d=dt.datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if d.tzinfo is None:
        d=d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(TZ)

def classify(value: Any) -> Dict[str, Any]:
    d=_parse(value); iso=d.date().isoformat(); minute=d.hour*60+d.minute
    supported=d.year in SUPPORTED_YEARS
    holiday=iso in FULL_DAY_CLOSURES
    weekend=d.weekday() >= 5
    schedule=session_schedule(d)
    trading_day=schedule["trading_day"]
    hour, min_close=map(int,(schedule["close_et"] or "00:00").split(":"))
    close_minute=hour*60+min_close
    if not supported:
        state="MARKET_CLOSED"; reason="CALENDAR_YEAR_UNSUPPORTED"
    elif holiday:
        state="MARKET_CLOSED"; reason="FULL_DAY_MARKET_HOLIDAY"
    elif weekend:
        state="MARKET_CLOSED"; reason="WEEKEND"
    elif minute < 570:
        state="PREMARKET"; reason="VALID_TRADING_DAY_BEFORE_RTH"
    elif minute < 600:
        state="OPEN_DISCOVERY"; reason="RTH"
    elif minute < 660:
        state="MORNING_DEVELOPMENT"; reason="RTH"
    elif minute < 690:
        state="LATE_MORNING"; reason="RTH"
    elif minute >= close_minute:
        state="POSTMARKET"; reason="EARLY_CLOSE" if schedule["early_close"] else "VALID_TRADING_DAY_AFTER_RTH"
    elif minute < 780:
        state="MIDDAY"; reason="RTH"
    elif minute < close_minute:
        state="AFTERNOON"; reason="RTH"
    else:
        state="POSTMARKET"; reason="VALID_TRADING_DAY_AFTER_RTH"
    return {"session_phase":state,"rth_eligible":bool(trading_day and 570 <= minute < close_minute),
            "trading_day":trading_day,"calendar_supported":supported,"is_holiday":holiday,"is_weekend":weekend,
            "reason":reason,"timestamp_et":d.isoformat(),"session_date":iso,"calendar_authority":"APEX_CANONICAL_US_EQUITY_OPTIONS",
            "session_close_et":schedule["close_et"],"early_close":schedule["early_close"]}
