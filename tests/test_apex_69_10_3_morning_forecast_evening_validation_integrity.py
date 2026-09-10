import datetime as dt
import json
from pathlib import Path

import engine.evening_recap as er
from engine.morning_brief import _deterministic_forecast_regime


def _ms(day, hh, mm):
    z=dt.timezone(dt.timedelta(hours=-4))
    return int(dt.datetime.fromisoformat(f"{day}T{hh:02d}:{mm:02d}:00").replace(tzinfo=z).timestamp()*1000)

def test_release_truth_69103():
    m=json.loads(Path("config/apex_release_manifest.json").read_text())
    assert m["apex_version"] == m["semantic_version"] == m["application_version"] == "69.10.3"
    assert m["build_name"] == "Morning Forecast & Evening Validation Integrity Closure"
    assert m["guardrails"]["historical_forecasts_rewritten"] is False
    assert m["guardrails"]["evening_regime_validation_uses_free_text_markdown"] is False

def test_official_identity_uses_target_date_and_rejects_post_open(monkeypatch, tmp_path):
    monkeypatch.setattr(er, "DB_PATH", str(tmp_path/"gov.db"))
    pre={"session_date":"2026-09-09","source_session_date":"2026-09-09","target_session_date":"2026-09-10","generated_at":"2026-09-10T08:15:00-04:00","session_context":{"state":"PREMARKET","brief_mode":"PREMARKET"},"structured":{}}
    a=er.save_morning_snapshot(pre)
    assert a["session_date"] == "2026-09-10" and a["is_official"] is True
    post={**pre,"generated_at":"2026-09-10T16:15:00-04:00","session_context":{"state":"AFTER_HOURS","brief_mode":"AFTER_CLOSE"}}
    b=er.save_morning_snapshot(post)
    assert b["is_official"] is False and b["eligible_for_official"] is False
    snap=er.get_morning_snapshot("2026-09-10")
    assert snap["generated_at"] == pre["generated_at"]

def test_markdown_never_drives_regime_grade():
    morning={"markdown":"Scenario says Expansion then Trend.","structured":{"spot":100,"expected_move":{"one_sigma":10,"lower":90,"upper":110}}}
    bars=[{"t":_ms("2026-09-10",9,30),"o":100,"h":105,"l":95,"c":100}]
    out=er.build_comparison(morning,bars,"2026-09-10")
    assert not any(c["key"]=="regime" for c in out["checks"])
    assert out["projected_regime"] == "Not structurally classified"

def test_expected_move_uses_max_excursion_from_frozen_spot_not_half_range():
    morning={"structured":{"spot":100,"forecast_regime":"Balanced Auction","forecast_regime_source":"TEST","expected_move":{"one_sigma":10,"lower":90,"upper":110}}}
    bars=[{"t":_ms("2026-09-10",9,30),"o":100,"h":109,"l":96,"c":101}]
    out=er.build_comparison(morning,bars,"2026-09-10")
    size=next(c for c in out["checks"] if c["key"]=="expected_move_size")
    assert size["actual"] == 9.0
    assert size["actual_metric"] == "MAX_ABS_EXCURSION_FROM_FROZEN_MORNING_SPOT"
    assert out["score_method"] == "WEIGHTED_CONTINUOUS_V69_10_3"

def test_deterministic_regime_tie_fails_closed():
    class L:
        def __init__(self,h): self.regime_hint=h
    class D: trade_map=[L("trend"),L("balance")]
    out=_deterministic_forecast_regime(D())
    assert out["regime"] is None
    assert out["source"] == "AMBIGUOUS_TRADE_MAP_CONSENSUS"
