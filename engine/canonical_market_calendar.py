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
    trading_day=supported and not holiday and not weekend
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
    elif minute < 780:
        state="MIDDAY"; reason="RTH"
    elif minute < 960:
        state="AFTERNOON"; reason="RTH"
    else:
        state="POSTMARKET"; reason="VALID_TRADING_DAY_AFTER_RTH"
    return {"session_phase":state,"rth_eligible":bool(trading_day and 570 <= minute < 960),
            "trading_day":trading_day,"calendar_supported":supported,"is_holiday":holiday,"is_weekend":weekend,
            "reason":reason,"timestamp_et":d.isoformat(),"session_date":iso,"calendar_authority":"APEX_CANONICAL_US_EQUITY_OPTIONS"}
