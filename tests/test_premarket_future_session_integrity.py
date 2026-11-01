from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from engine.premarket_directional_features import archive_diagnostics
from engine.premarket_availability_diagnostics import diagnose
from engine.premarket_feature_provider import derive_es_features
ET=ZoneInfo("America/New_York")
def bar(at,price=7000):
    return {"t":int(at.timestamp()*1000),"c":price,"h":price+2,"l":price-2,"v":10}
def test_sunday_preparation_not_scored_as_monday_premarket():
    report=archive_diagnostics({"2026-11-02":{"generated_at":"2026-11-01T08:00:00-05:00","forecast_identity":{"brief_mode":"NEXT_SESSION_PREP"},"structured":{}}})
    assert report["status_counts"]=={"NEXT_SESSION_PREPARATION_NOT_PREMARKET":1}
def test_future_target_without_mode_also_classified():
    report=archive_diagnostics({"2026-11-02":{"generated_at":"2026-11-01T08:00:00-05:00","structured":{}}})
    assert report["details"][0]["status"]=="NEXT_SESSION_PREPARATION_NOT_PREMARKET"
def test_same_day_missing_stays_missing():
    report=archive_diagnostics({"2026-11-02":{"generated_at":"2026-11-02T08:00:00-05:00","structured":{}}})
    assert report["details"][0]["status"]=="SNAPSHOT_NOT_ARCHIVED"
def test_prior_rth_metadata_and_incomplete_reason():
    start=datetime(2026,10,29,18,tzinfo=ET)
    prior=datetime(2026,10,29,9,30,tzinfo=ET)
    ctx={"status":"ok","ticker":"ES","bars":[bar(start+timedelta(minutes=5*i)) for i in range(168)],
         "prior_rth_bars":[bar(prior+timedelta(minutes=5*i)) for i in range(30)]}
    d=diagnose(ctx,decision_at="2026-10-30T08:05:00-04:00",target_session_date="2026-10-30",available=derive_es_features(ctx,decision_at="2026-10-30T08:05:00-04:00",target_session_date="2026-10-30"))
    assert d["prior_rth_session"]["selected_session_date"]=="2026-10-29"
    assert d["prior_rth_session"]["bar_count"]==30
    assert d["feature_reasons"]["prior_day_range_position"]=="PRIOR_RTH_SESSION_INCOMPLETE"
