"""
engine/event_calendar.py — APEX 7.5.4 Event Intelligence.

WHAT THIS IS
------------
A self-contained calendar of the recurring, schedule-known market events that
matter for SPX 0DTE, with logic to compute the next occurrence of each and
surface proximity-aware guidance ("FOMC in 2 days — expect compression into it",
"today is OPEX — pin risk elevated").

DESIGN
------
- NO external data dependency. It computes dates from known rules (OPEX = 3rd
  Friday; FOMC/CPI/NFP from a curated schedule) plus a small hardcoded table of
  fixed-date releases that must be refreshed periodically. Anything computable
  from a rule is computed; anything not is in DATED_EVENTS with an explicit
  "verify/refresh" expectation.
- Returns a plain dict; never raises into the caller.
- The guidance is descriptive context, NOT a trade signal. It tells you the
  event landscape; it never says buy/sell.

IMPORTANT MAINTENANCE NOTE
--------------------------
DATED_EVENTS (CPI, PPI, NFP, FOMC decision dates) are release-schedule facts that
change and must be refreshed from the official calendars (BLS, Federal Reserve).
The rule-derived events (OPEX, quad witching, month/quarter end) need no upkeep.
The engine flags when its dated table has gone stale so it never silently serves
outdated event proximity.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

VERSION = "7.5.4_EVENT_INTELLIGENCE"
EASTERN = ZoneInfo("America/New_York")

# ── Curated fixed-date releases (REFRESH PERIODICALLY from official sources) ──
# Format: (ISO date, event key, human label, impact tier).
# Tier: HIGH (regime-moving), MED (notable), LOW (minor).
# These are known scheduled US releases. Update from BLS/Fed calendars.
DATED_EVENTS: List[tuple] = [
    # 2026 FOMC decision days (Fed schedule)
    ("2026-01-28", "FOMC", "FOMC rate decision", "HIGH"),
    ("2026-03-18", "FOMC", "FOMC rate decision + SEP", "HIGH"),
    ("2026-04-29", "FOMC", "FOMC rate decision", "HIGH"),
    ("2026-06-17", "FOMC", "FOMC rate decision + SEP", "HIGH"),
    ("2026-07-29", "FOMC", "FOMC rate decision", "HIGH"),
    ("2026-09-16", "FOMC", "FOMC rate decision + SEP", "HIGH"),
    ("2026-10-28", "FOMC", "FOMC rate decision", "HIGH"),
    ("2026-12-09", "FOMC", "FOMC rate decision + SEP", "HIGH"),
    # 2026 CPI (BLS release schedule — typically ~8:30 ET)
    ("2026-01-13", "CPI", "CPI (Dec)", "HIGH"),
    ("2026-02-11", "CPI", "CPI (Jan)", "HIGH"),
    ("2026-03-11", "CPI", "CPI (Feb)", "HIGH"),
    ("2026-04-10", "CPI", "CPI (Mar)", "HIGH"),
    ("2026-05-13", "CPI", "CPI (Apr)", "HIGH"),
    ("2026-06-10", "CPI", "CPI (May)", "HIGH"),
    ("2026-07-14", "CPI", "CPI (Jun)", "HIGH"),
    ("2026-08-12", "CPI", "CPI (Jul)", "HIGH"),
    ("2026-09-11", "CPI", "CPI (Aug)", "HIGH"),
    ("2026-10-13", "CPI", "CPI (Sep)", "HIGH"),
    ("2026-11-13", "CPI", "CPI (Oct)", "HIGH"),
    ("2026-12-10", "CPI", "CPI (Nov)", "HIGH"),
    # 2026 NFP / jobs report (first Friday, but BLS schedule is authoritative)
    ("2026-01-09", "NFP", "Nonfarm Payrolls (Dec)", "HIGH"),
    ("2026-02-06", "NFP", "Nonfarm Payrolls (Jan)", "HIGH"),
    ("2026-03-06", "NFP", "Nonfarm Payrolls (Feb)", "HIGH"),
    ("2026-04-03", "NFP", "Nonfarm Payrolls (Mar)", "HIGH"),
    ("2026-05-08", "NFP", "Nonfarm Payrolls (Apr)", "HIGH"),
    ("2026-06-05", "NFP", "Nonfarm Payrolls (May)", "HIGH"),
    ("2026-07-02", "NFP", "Nonfarm Payrolls (Jun)", "HIGH"),
    ("2026-08-07", "NFP", "Nonfarm Payrolls (Jul)", "HIGH"),
    ("2026-09-04", "NFP", "Nonfarm Payrolls (Aug)", "HIGH"),
    ("2026-10-02", "NFP", "Nonfarm Payrolls (Sep)", "HIGH"),
    ("2026-11-06", "NFP", "Nonfarm Payrolls (Oct)", "HIGH"),
    ("2026-12-04", "NFP", "Nonfarm Payrolls (Nov)", "HIGH"),
    # PPI (typically day after or near CPI)
    ("2026-01-14", "PPI", "PPI (Dec)", "MED"),
    ("2026-02-12", "PPI", "PPI (Jan)", "MED"),
    ("2026-03-12", "PPI", "PPI (Feb)", "MED"),
    ("2026-04-09", "PPI", "PPI (Mar)", "MED"),
    ("2026-05-14", "PPI", "PPI (Apr)", "MED"),
    ("2026-06-11", "PPI", "PPI (May)", "MED"),
    ("2026-07-15", "PPI", "PPI (Jun)", "MED"),
    ("2026-08-13", "PPI", "PPI (Jul)", "MED"),
    ("2026-09-10", "PPI", "PPI (Aug)", "MED"),
    ("2026-10-14", "PPI", "PPI (Sep)", "MED"),
    ("2026-11-12", "PPI", "PPI (Oct)", "MED"),
    ("2026-12-11", "PPI", "PPI (Nov)", "MED"),
]

# The latest date in DATED_EVENTS; past this the dated table is "stale".
def _dated_horizon() -> Optional[dt.date]:
    try:
        return max(dt.date.fromisoformat(d) for d, *_ in DATED_EVENTS)
    except Exception:
        return None


# ── Rule-derived events (no maintenance needed) ──────────────────────────────
def _third_friday(year: int, month: int) -> dt.date:
    """Monthly OPEX = third Friday of the month."""
    d = dt.date(year, month, 1)
    # weekday(): Mon=0 … Fri=4
    first_friday_offset = (4 - d.weekday()) % 7
    return d + dt.timedelta(days=first_friday_offset + 14)


def _is_quad_witching(d: dt.date) -> bool:
    """Quad witching = third Friday of Mar, Jun, Sep, Dec."""
    return d.month in (3, 6, 9, 12) and d == _third_friday(d.year, d.month)


def _next_monthly_opex(today: dt.date) -> dt.date:
    this = _third_friday(today.year, today.month)
    if this >= today:
        return this
    ny, nm = (today.year + (1 if today.month == 12 else 0),
              1 if today.month == 12 else today.month + 1)
    return _third_friday(ny, nm)


def _is_month_end(d: dt.date) -> bool:
    return (d + dt.timedelta(days=1)).month != d.month


def _is_quarter_end(d: dt.date) -> bool:
    return d.month in (3, 6, 9, 12) and _is_month_end(d)


# ── Proximity guidance ───────────────────────────────────────────────────────
def _proximity_note(key: str, label: str, days: int, tier: str) -> str:
    """Descriptive context only — never a trade instruction."""
    when = ("today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days")
    if key == "OPEX":
        if days == 0:
            return ("OPEX today — dealer gamma concentrated at round strikes; "
                    "pin risk elevated, ranges often compress toward large strikes.")
        return f"Monthly OPEX {when} — expect gamma to build into it; positioning may pin price."
    if key == "QUAD":
        return (f"Quad witching {when} — quarterly futures+options expiry; "
                f"elevated volume and pin dynamics, watch for late-day unwinds.")
    if key in ("CPI", "NFP", "FOMC", "PPI"):
        if days == 0:
            return (f"{label} today — typically an 8:30 ET print (FOMC 2:00 ET). "
                    f"Expect a volatility event; pre-release drift + post-release expansion.")
        if days == 1:
            return (f"{label} tomorrow — markets often compress/coil into a known "
                    f"{tier}-impact release; breakouts into it are suspect.")
        return f"{label} {when} — on the radar; {tier}-impact scheduled release."
    if key in ("MONTH_END", "QUARTER_END"):
        return (f"{label} {when} — potential rebalancing flows (pension/index) "
                f"into the close; can distort late-day direction.")
    return f"{label} {when}."


def build_event_intelligence(now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Return the event landscape around `now` (defaults to current ET)."""
    try:
        now = now or dt.datetime.now(EASTERN)
        today = now.date()
        horizon = 10  # look-ahead window in days

        upcoming: List[Dict[str, Any]] = []

        # 1. Dated releases within horizon
        stale = False
        h = _dated_horizon()
        if h is not None and today > h:
            stale = True
        for iso, key, label, tier in DATED_EVENTS:
            try:
                d = dt.date.fromisoformat(iso)
            except ValueError:
                continue
            delta = (d - today).days
            if 0 <= delta <= horizon:
                upcoming.append({
                    "key": key, "label": label, "date": iso,
                    "days_away": delta, "impact": tier,
                    "note": _proximity_note(key, label, delta, tier),
                })

        # 2. Rule-derived: monthly OPEX / quad witching
        opex = _next_monthly_opex(today)
        opex_delta = (opex - today).days
        if 0 <= opex_delta <= horizon:
            if _is_quad_witching(opex):
                upcoming.append({
                    "key": "QUAD", "label": "Quad witching", "date": opex.isoformat(),
                    "days_away": opex_delta, "impact": "HIGH",
                    "note": _proximity_note("QUAD", "Quad witching", opex_delta, "HIGH"),
                })
            else:
                upcoming.append({
                    "key": "OPEX", "label": "Monthly OPEX", "date": opex.isoformat(),
                    "days_away": opex_delta, "impact": "MED",
                    "note": _proximity_note("OPEX", "Monthly OPEX", opex_delta, "MED"),
                })

        # 3. Rule-derived: month / quarter end within horizon
        for offset in range(horizon + 1):
            d = today + dt.timedelta(days=offset)
            if _is_quarter_end(d):
                upcoming.append({
                    "key": "QUARTER_END", "label": "Quarter end", "date": d.isoformat(),
                    "days_away": offset, "impact": "MED",
                    "note": _proximity_note("QUARTER_END", "Quarter end", offset, "MED"),
                })
                break
            if _is_month_end(d):
                upcoming.append({
                    "key": "MONTH_END", "label": "Month end", "date": d.isoformat(),
                    "days_away": offset, "impact": "LOW",
                    "note": _proximity_note("MONTH_END", "Month end", offset, "LOW"),
                })
                break

        upcoming.sort(key=lambda e: (e["days_away"], {"HIGH": 0, "MED": 1, "LOW": 2}.get(e["impact"], 3)))

        today_events = [e for e in upcoming if e["days_away"] == 0]
        # The single most relevant headline event (nearest high-impact, else nearest).
        high = [e for e in upcoming if e["impact"] == "HIGH"]
        headline = (today_events[0] if today_events
                    else (high[0] if high else (upcoming[0] if upcoming else None)))

        # Regime hint: are we in a "coiling into an event" posture?
        event_regime = "CLEAR"
        if any(e["impact"] == "HIGH" and e["days_away"] == 0 for e in upcoming):
            event_regime = "EVENT_DAY"
        elif any(e["key"] in ("OPEX", "QUAD") and e["days_away"] == 0 for e in upcoming):
            event_regime = "OPEX_DAY"        # pin dynamics matter for 0DTE
        elif any(e["impact"] == "HIGH" and e["days_away"] <= 1 for e in upcoming):
            event_regime = "PRE_EVENT_COMPRESSION"

        summary = _overall_summary(event_regime, headline, today_events)

        return {
            "available": True,
            "version": VERSION,
            "as_of": today.isoformat(),
            "event_regime": event_regime,          # CLEAR | PRE_EVENT_COMPRESSION | EVENT_DAY
            "headline_event": headline,
            "today_events": today_events,
            "upcoming": upcoming,
            "summary": summary,
            "data_stale": stale,
            "stale_note": (None if not stale else
                           "Dated event table is past its horizon — refresh DATED_EVENTS "
                           "from BLS/Fed calendars; only rule-derived events are current."),
        }
    except Exception as e:
        return {
            "available": False, "version": VERSION,
            "event_regime": "CLEAR", "headline_event": None,
            "today_events": [], "upcoming": [],
            "summary": f"Event intelligence recovered from error: {e}",
            "data_stale": False, "stale_note": None,
        }


def _overall_summary(regime: str, headline: Optional[Dict[str, Any]],
                     today_events: List[Dict[str, Any]]) -> str:
    if regime == "EVENT_DAY" and today_events:
        labels = ", ".join(e["label"] for e in today_events)
        return f"EVENT DAY: {labels} today. Expect a volatility event; respect wider ranges and post-print expansion."
    if regime == "OPEX_DAY":
        return ("OPEX today — dealer gamma concentrated at large strikes; pin risk elevated, "
                "ranges often compress toward round numbers. Fade-the-edges over breakouts.")
    if regime == "PRE_EVENT_COMPRESSION" and headline:
        return (f"Coiling into {headline['label']} ({_when(headline['days_away'])}). "
                f"Markets often compress ahead of it — breakouts into a known event are suspect.")
    if headline:
        return f"No high-impact event today. Next notable: {headline['label']} ({_when(headline['days_away'])})."
    return "No scheduled high-impact events on the near horizon."


def _when(days: int) -> str:
    return "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
