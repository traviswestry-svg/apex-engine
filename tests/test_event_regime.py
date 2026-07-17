import datetime as dt
from zoneinfo import ZoneInfo

from engine.event_calendar import build_event_intelligence
from engine.event_regime import (
    NORMAL_SESSION, EVENT_PRE_RELEASE, EVENT_IMPULSE, EVENT_DISCOVERY,
    POST_EVENT_NORMALIZATION, apply_event_confidence,
    baseline_sample_eligibility, expected_move_decomposition,
)

ET = ZoneInfo("America/New_York")


def at(day, hhmm):
    return dt.datetime.fromisoformat(f"{day}T{hhmm}:00").replace(tzinfo=ET)


def state(day, hhmm):
    return build_event_intelligence(now=at(day, hhmm))["intraday_event_regime"]


def test_cpi_has_distinct_intraday_phases():
    assert state("2026-07-14", "07:30")["state"] == EVENT_PRE_RELEASE
    assert state("2026-07-14", "08:32")["state"] == EVENT_IMPULSE
    assert state("2026-07-14", "08:45")["state"] == EVENT_DISCOVERY
    assert state("2026-07-14", "09:20")["state"] == POST_EVENT_NORMALIZATION


def test_fomc_uses_1400_release_and_separate_profile():
    r = state("2026-07-29", "13:15")
    assert r["event_type"] == "FOMC"
    assert r["release_time_et"] == "14:00"
    assert r["state"] == EVENT_PRE_RELEASE
    assert r["slippage_multiplier"] > state("2026-07-14", "07:30")["slippage_multiplier"]


def test_non_event_day_is_normal_and_baseline_eligible():
    r = state("2026-07-16", "10:00")
    assert r["state"] == NORMAL_SESSION
    assert baseline_sample_eligibility(r)["eligible_for_normal_baseline"] is True


def test_event_day_never_contaminates_normal_baseline():
    r = state("2026-07-14", "15:30")
    assert r["state"] == NORMAL_SESSION
    e = baseline_sample_eligibility(r)
    assert e["eligible_for_normal_baseline"] is False
    assert e["baseline_bucket"] == "EVENT_CPI"


def test_confidence_is_multiplied_not_added():
    r = state("2026-07-14", "08:32")
    assert apply_event_confidence(80, r) == 28.0


def test_expected_move_decomposition_is_honest_when_baseline_missing():
    r = state("2026-07-14", "07:30")
    missing = expected_move_decomposition(observed_expected_move=24, normal_baseline_expected_move=None, regime=r)
    assert missing["incremental_scheduled_event_premium"] is None
    assert missing["measurable"] is False
    measured = expected_move_decomposition(observed_expected_move=24, normal_baseline_expected_move=16, regime=r)
    assert measured["incremental_scheduled_event_premium"] == 8.0
