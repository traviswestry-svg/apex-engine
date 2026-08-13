"""Tests for APEX 7.5.4 Event Intelligence."""
import datetime as dt
from zoneinfo import ZoneInfo
from engine.event_calendar import (_third_friday, _is_quad_witching,
                                    build_event_intelligence)

ET = ZoneInfo("America/New_York")


def _at(iso):
    return dt.datetime.fromisoformat(iso + "T10:00").replace(tzinfo=ET)


def test_third_friday_known_dates():
    assert _third_friday(2026, 1).isoformat() == "2026-01-16"
    assert _third_friday(2026, 7).isoformat() == "2026-07-17"


def test_quad_witching_only_quarter_end_months():
    assert _is_quad_witching(_third_friday(2026, 3)) is True
    assert _is_quad_witching(_third_friday(2026, 6)) is True
    assert _is_quad_witching(_third_friday(2026, 7)) is False


def test_cpi_day_is_event_day():
    r = build_event_intelligence(now=_at("2026-07-14"))
    assert r["event_regime"] == "EVENT_DAY"
    assert any(e["key"] == "CPI" for e in r["today_events"])


def test_pre_fomc_is_compression():
    r = build_event_intelligence(now=_at("2026-07-28"))
    assert r["event_regime"] == "PRE_EVENT_COMPRESSION"


def test_opex_day_regime():
    r = build_event_intelligence(now=_at("2026-07-17"))
    assert r["event_regime"] == "OPEX_DAY"


def test_never_crashes_and_has_shape():
    r = build_event_intelligence()
    assert "event_regime" in r and "upcoming" in r and r["available"] in (True, False)
