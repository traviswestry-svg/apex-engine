import datetime as dt

from engine.morning_brief import (
    _canonical_event_context,
    _enforce_canonical_event_section,
    _render_canonical_events,
)


def test_aug_12_cpi_is_canonical_today_event():
    e = _canonical_event_context("2026-08-12", {"brief_mode": "PREMARKET"})
    assert e["available"] is True
    assert any(x.get("key") == "CPI" for x in e.get("today_events", []))


def test_canonical_section_replaces_conflicting_ai_calendar_text():
    e = _canonical_event_context("2026-08-12", {"brief_mode": "PREMARKET"})
    section = _render_canonical_events(e, "2026-08-12")
    ai = "## SECTION 1 — EXECUTIVE SUMMARY\nX\n\n## SECTION 2 — TODAY'S EVENTS\nNo scheduled macro/economic catalysts were provided.\n\n## SECTION 12 — RISK WATCH\nY"
    fixed = _enforce_canonical_event_section(ai, section)
    assert "CPI (Jul)" in fixed
    assert "No scheduled macro/economic catalysts were provided" not in fixed
    assert "## SECTION 12 — RISK WATCH" in fixed


def test_unavailable_calendar_never_claims_no_events():
    section = _render_canonical_events({"available": False, "today_events": []}, "2026-08-12")
    assert "EVENT DATA UNAVAILABLE" in section
    assert "no-event session" in section
