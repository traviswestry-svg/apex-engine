import datetime as dt
import json
from pathlib import Path

import engine.evening_recap as er


def _morning():
    return {
        "session_date":"2026-10-02", "source_session_date":"2026-10-01", "target_session_date":"2026-10-02",
        "generated_at":"2026-10-02T08:15:00-04:00",
        "session_context":{"state":"PREMARKET","brief_mode":"PREMARKET"},
        "structured":{"spot":7666.7,"forecast_regime":"Balanced Auction","forecast_regime_source":"TEST",
                      "expected_move":{"one_sigma":38.5,"lower":7628.2,"upper":7705.2},
                      "levels":[{"kind":"PDL","label":"Prev Day Low","price":7651.54}]},
    }


def _ms(hh, mm):
    z=dt.timezone(dt.timedelta(hours=-4))
    return int(dt.datetime(2026,10,2,hh,mm,tzinfo=z).timestamp()*1000)


def test_release_truth_691028():
    m=json.loads(Path("config/apex_release_manifest.json").read_text())
    assert m["apex_version"] == m["semantic_version"] == m["application_version"] == "69.10.34"
    assert m["build_name"] == "Open Discovery Shadow Candidate Forward Validation & Structural Evidence Capture"
    assert m["guardrails"]["canonical_forecast_exact_identity_required_for_evening_grading"] is True
    assert m["guardrails"]["evening_forecast_reconstruction"] is False


def test_official_forecast_gets_stable_canonical_identity(monkeypatch,tmp_path):
    monkeypatch.setattr(er,"DB_PATH",str(tmp_path/"gov.db"))
    a=er.save_morning_snapshot(_morning())
    assert a["is_official"] is True and a["canonical_provenance"] is True
    assert a["forecast_id"].startswith("fcst_") and len(a["snapshot_hash"]) == 64
    snap=er.get_morning_snapshot("2026-10-02")
    v=er.verify_canonical_forecast(snap,"2026-10-02","SPX")
    assert v["ok"] is True and v["forecast_id"] == a["forecast_id"]


def test_revision_cannot_replace_official_identity(monkeypatch,tmp_path):
    monkeypatch.setattr(er,"DB_PATH",str(tmp_path/"gov.db"))
    a=er.save_morning_snapshot(_morning())
    revised=_morning(); revised["generated_at"]="2026-10-02T08:45:00-04:00"; revised["structured"]["spot"]=9999
    b=er.save_morning_snapshot(revised)
    assert b["is_official"] is False and b["forecast_id"] == a["forecast_id"]
    assert er.get_morning_snapshot("2026-10-02")["structured"]["spot"] == 7666.7


def test_tamper_fails_closed_before_grading(monkeypatch,tmp_path):
    monkeypatch.setattr(er,"DB_PATH",str(tmp_path/"gov.db"))
    er.save_morning_snapshot(_morning()); snap=er.get_morning_snapshot("2026-10-02")
    snap["structured"]["spot"]=7000
    out=er.generate_evening_recap(morning=snap,intraday_bars=[],session_date="2026-10-02")
    assert out["ok"] is False and out["status"] == "CANONICAL_FORECAST_INTEGRITY_FAILURE"
    assert out["score"] is None


def test_legacy_unverified_forecast_cannot_be_graded():
    out=er.generate_evening_recap(morning=_morning(),intraday_bars=[],session_date="2026-10-02")
    assert out["ok"] is False and out["status"] == "CANONICAL_FORECAST_PROVENANCE_REQUIRED"
    assert out["grade"] == "N/A"


def test_verified_forecast_id_propagates_into_evening_result(monkeypatch,tmp_path):
    monkeypatch.setattr(er,"DB_PATH",str(tmp_path/"gov.db"))
    saved=er.save_morning_snapshot(_morning()); snap=er.get_morning_snapshot("2026-10-02")
    bars=[{"t":_ms(9,30),"o":7666.7,"h":7680,"l":7640,"c":7670}]
    out=er.generate_evening_recap(morning=snap,intraday_bars=bars,session_date="2026-10-02",force=True)
    assert out["ok"] is True and out["forecast_provenance_verified"] is True
    assert out["forecast_id"] == saved["forecast_id"]
    assert out["forecast_snapshot_hash"] == saved["snapshot_hash"]

def test_canonical_db_row_is_immutable(monkeypatch,tmp_path):
    import sqlite3
    monkeypatch.setattr(er,"DB_PATH",str(tmp_path/"gov.db"))
    er.save_morning_snapshot(_morning())
    try:
        with sqlite3.connect(er.DB_PATH) as c:
            c.execute("UPDATE apex49_morning_snapshots SET generated_at=? WHERE session_date=?",("2099-01-01T00:00:00Z","2026-10-02"))
        assert False, "canonical row mutation should fail"
    except sqlite3.IntegrityError as exc:
        assert "immutable" in str(exc)
