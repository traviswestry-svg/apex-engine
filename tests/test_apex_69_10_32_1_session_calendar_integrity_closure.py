import json, sqlite3
from pathlib import Path
from engine.canonical_market_calendar import classify
from engine import session_phase_excursion_attribution as sea

def test_weekend_and_holiday_fail_closed():
    assert classify("2026-10-04T13:35:00+00:00")["session_phase"] == "MARKET_CLOSED"
    assert classify("2026-10-04T13:35:00+00:00")["rth_eligible"] is False
    assert classify("2026-09-07T14:00:00+00:00")["reason"] == "FULL_DAY_MARKET_HOLIDAY"

def test_valid_day_distinguishes_pre_rth_post():
    assert classify("2026-10-02T13:29:59+00:00")["session_phase"] == "PREMARKET"
    assert classify("2026-10-02T13:30:00+00:00")["session_phase"] == "OPEN_DISCOVERY"
    assert classify("2026-10-02T20:00:00+00:00")["session_phase"] == "POSTMARKET"
    assert classify("2026-10-02T19:59:59+00:00")["rth_eligible"] is True

def test_unsupported_calendar_year_fails_closed():
    x=classify("2028-10-02T14:00:00+00:00")
    assert x["session_phase"] == "MARKET_CLOSED" and x["reason"] == "CALENDAR_YEAR_UNSUPPORTED"

def test_rth_attribution_excludes_closed_pre_and_post():
    cs=[
      {"anchor_at":"2026-10-04T13:35:00+00:00","classification":"MISSED_OPPORTUNITY"},
      {"anchor_at":"2026-10-02T13:20:00+00:00","classification":"PROTECTIVE_ABSTENTION"},
      {"anchor_at":"2026-10-02T13:35:00+00:00","classification":"MISSED_OPPORTUNITY"},
      {"anchor_at":"2026-10-02T20:30:00+00:00","classification":"PROTECTIVE_ABSTENTION"},
    ]
    rows,audit=sea._phase_attribution(cs)
    op=next(x for x in rows if x["session_phase"]=="OPEN_DISCOVERY")
    assert op["clusters"]==1 and op["missed_clusters"]==1
    assert audit["all_clusters"]==4 and audit["rth_eligible_clusters"]==1 and audit["excluded_clusters"]==3
    assert audit["excluded_by_session_state"]=={"MARKET_CLOSED":1,"POSTMARKET":1,"PREMARKET":1}

def test_release_metadata_6910321():
    root=Path(__file__).resolve().parents[1]; m=json.loads((root/'config/apex_release_manifest.json').read_text())
    assert m['apex_version']==m['semantic_version']==m['application_version']=='69.10.37'
    assert m['build_name']=='Forecast Diagnostics Production Promotion & Persistence Closure'
