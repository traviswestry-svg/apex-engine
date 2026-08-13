import tempfile
from pathlib import Path

from engine import canonical_session_context as csc
from engine import historical_level_calibration as hlce


def _payload(levels, target="2026-08-03"):
    return {
        "generated_at": "2026-08-03T14:00:00+00:00",
        "source_session_date": "2026-07-31",
        "target_session_date": target,
        "version": "test",
        "structured": {"spot": 7500.0, "levels": levels},
    }


def test_registry_normalizes_taxonomy_and_preserves_or_identity(tmp_path):
    db=str(tmp_path/"ctx.db")
    levels=[
        {"kind":"em_upper","price":7550,"source":"computed"},
        {"kind":"high_volume_node","price":7510,"source":"volume_profile_engine"},
        {"kind":"or5_high","price":7505,"source":"computed"},
        {"kind":"or15_high","price":7515,"source":"computed"},
    ]
    out=csc.save_from_morning_brief(_payload(levels), path=db)
    assert out["active_registry"]["active_count"] == 4
    rows=csc.active_levels("SPX", target_session_date="2026-08-03", path=db)
    kinds={r["kind"] for r in rows}
    assert "expected_move_high" in kinds
    assert "hvn" in kinds
    assert "or5_high" in kinds
    assert "or15_high" in kinds
    assert "or_high" not in kinds


def test_latest_context_can_be_constrained_to_target_session(tmp_path):
    db=str(tmp_path/"ctx.db")
    csc.save_from_morning_brief(_payload([{"kind":"prev_close","price":7490}], "2026-08-03"), path=db)
    p=_payload([{"kind":"prev_close","price":7600}], "2026-08-04")
    p["generated_at"]="2026-08-04T14:00:00+00:00"
    csc.save_from_morning_brief(p,path=db)
    row=csc.latest("SPX", target_session_date="2026-08-03", path=db)
    assert row["target_session_date"] == "2026-08-03"
    assert row["reference_spot"] == 7500.0


def test_registry_supersedes_stale_mutable_price(tmp_path):
    db=str(tmp_path/"ctx.db")
    csc.save_from_morning_brief(_payload([{"kind":"developing_poc","price":7500,"source":"vp"}]),path=db)
    p=_payload([{"kind":"developing_poc","price":7510,"source":"vp"}])
    p["generated_at"]="2026-08-03T15:00:00+00:00"
    csc.save_from_morning_brief(p,path=db)
    active=csc.active_levels("SPX",target_session_date="2026-08-03",path=db)
    assert len(active)==1 and active[0]["price"]==7510
    import sqlite3
    with sqlite3.connect(db) as conn:
        rows=conn.execute("select price,active,valid_to from canonical_active_levels order by price").fetchall()
    assert rows[0][0]==7500 and rows[0][1]==0 and rows[0][2]
    assert rows[1][0]==7510 and rows[1][1]==1


def test_hlce_retires_stale_rows_and_tracks_only_active(tmp_path):
    db=str(tmp_path/"cal.db")
    snap1={"symbol":"SPX","spot":7500,"canonical_levels":[{"canonical_level_id":"a","kind":"developing_poc","price":7500,"source":"vp"},{"canonical_level_id":"b","kind":"or5_high","price":7510,"source":"computed"}]}
    hlce.register_daily_levels(snap1,path=db,session_date="2026-08-03")
    snap2={"symbol":"SPX","spot":7520,"canonical_levels":[{"canonical_level_id":"c","kind":"developing_poc","price":7520,"source":"vp"},{"canonical_level_id":"b","kind":"or5_high","price":7510,"source":"computed"}]}
    out=hlce.register_daily_levels(snap2,path=db,session_date="2026-08-03")
    rows=hlce.active_levels("2026-08-03","SPX",path=db)
    assert {(r["level_type"],r["price"]) for r in rows} == {("developing_poc",7520.0),("or5_high",7510.0)}
    assert out["retired"] >= 1


def test_collector_sync_removes_retired_tracks(tmp_path):
    db=str(tmp_path/"cal.db")
    c=hlce.Collector(db)
    s1={"symbol":"SPX","spot":7500,"canonical_levels":[{"kind":"developing_poc","price":7500}]}
    c.observe(s1,now=1785765600.0)
    assert any(t.level_price==7500 for t in c._tracks.values())
    s2={"symbol":"SPX","spot":7520,"canonical_levels":[{"kind":"developing_poc","price":7520}]}
    c.observe(s2,now=1785765620.0)
    assert all(t.level_price!=7500 for t in c._tracks.values())
    assert any(t.level_price==7520 for t in c._tracks.values())
