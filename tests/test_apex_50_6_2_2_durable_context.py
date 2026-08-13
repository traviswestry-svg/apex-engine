from engine import canonical_session_context as csc
from engine import level_transition_probability as ltpe


def _payload():
    return {
        "generated_at":"2026-08-01T12:05:06-04:00",
        "source_session_date":"2026-07-31",
        "target_session_date":"2026-08-03",
        "version":"50.5.0_HISTORICAL_LEVEL_CALIBRATION",
        "structured":{
            "spot":7489.52,
            "levels":[
                {"kind":"prev_close","price":7489.72,"source":"polygon"},
                {"kind":"call_wall","price":7490.0,"source":"gamma_provider"},
                {"kind":"prev_day_high","price":7512.04,"source":"polygon"},
                {"kind":"em_upper","price":7529.0,"source":"computed"},
                {"kind":"or5_high","price":"[FEED REQUIRED]","source":"computed"},
            ],
        },
    }


def test_durable_context_survives_without_process_local_brief(tmp_path, monkeypatch):
    context_db=str(tmp_path/"canonical.db")
    hlce_db=str(tmp_path/"hlce.db")
    monkeypatch.setattr(csc,"DB_PATH",context_db)
    saved=csc.save_from_morning_brief(_payload(), symbol="SPX")
    assert saved["ok"] is True
    monkeypatch.setattr(ltpe,"_load_latest_morning_brief",lambda symbol="SPX":None)
    out=ltpe.current_transition_path({"ticker":"SPX"},path=hlce_db,direction="UP")
    assert out["ok"] is True
    assert out["version"] == "50.6.2.2_LEVEL_TRANSITION_PROBABILITY"
    assert out["spot"] == 7489.52
    assert out["spot_mode"] == "DURABLE_CANONICAL_SPOT"
    assert out["level_universe_mode"] == "DURABLE_NEXT_SESSION_LEVELS"
    assert out["source_session_date"] == "2026-07-31"
    assert out["target_session_date"] == "2026-08-03"
    assert out["context"]["session_bucket"] == "NEXT_SESSION_PREP"
    assert [x["level_type"] for x in out["steps"]] == ["prev_day_high","expected_move_high"]
    assert ltpe.status(path=hlce_db)["observations"] == 0


def test_durable_context_stores_level_universe_even_without_spot(tmp_path, monkeypatch):
    context_db=str(tmp_path/"canonical.db")
    monkeypatch.setattr(csc,"DB_PATH",context_db)
    p=_payload(); p["structured"]["spot"]=None
    csc.save_from_morning_brief(p,symbol="SPX")
    row=csc.latest("SPX")
    assert row and len(row["levels"]) == 5
    assert row["reference_spot"] is None
    assert row["prev_close"] == 7489.72
