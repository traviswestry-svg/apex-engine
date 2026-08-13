import sqlite3
from pathlib import Path

from engine.evidence_accumulation_observatory import _level_source_coverage
from engine.historical_level_calibration import initialize_store


def test_level_source_coverage_reports_family_lifecycle(tmp_path):
    db = str(tmp_path / "calibration.db")
    initialize_store(db)
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO daily_levels(level_id,session_date,symbol,level_type,price,registered_at,active) VALUES(?,?,?,?,?,?,?)",
                  ("g1","2026-08-08","SPX","call_wall",7000,"2026-08-08T13:00:00+00:00",1))
        c.execute("INSERT INTO daily_levels(level_id,session_date,symbol,level_type,price,registered_at,active) VALUES(?,?,?,?,?,?,?)",
                  ("e1","2026-08-08","SPX","expected_move_high",7100,"2026-08-08T13:00:00+00:00",1))
        c.execute("INSERT INTO level_interactions(interaction_id,level_id,session_date,symbol,level_type,interaction_type,touch_ordinal,ts,graded) VALUES(?,?,?,?,?,?,?,?,?)",
                  ("i1","g1","2026-08-08","SPX","call_wall","FIRST_TOUCH",1,"2026-08-08T14:00:00+00:00",1))
        c.execute("INSERT INTO level_interactions(interaction_id,level_id,session_date,symbol,level_type,interaction_type,touch_ordinal,ts,graded) VALUES(?,?,?,?,?,?,?,?,?)",
                  ("i2","g1","2026-08-08","SPX","call_wall","BREAK",1,"2026-08-08T14:01:00+00:00",0))
        c.execute("INSERT INTO level_interactions(interaction_id,level_id,session_date,symbol,level_type,interaction_type,touch_ordinal,ts,graded) VALUES(?,?,?,?,?,?,?,?,?)",
                  ("i3","g1","2026-08-08","SPX","call_wall","RECLAIM",1,"2026-08-08T14:02:00+00:00",0))
        c.execute("INSERT INTO level_outcomes(outcome_id,interaction_id,level_id,session_date,symbol,level_type,classification,reacted,broke,reversed,accepted,retested,graded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  ("o1","i1","g1","2026-08-08","SPX","call_wall","FAILED_BREAK",1,0,0,0,0,"2026-08-08T14:10:00+00:00"))
        c.commit()
    out = _level_source_coverage(db, symbol="SPX", session_date="2026-08-08")
    gamma = out["families"]["GAMMA"]
    assert gamma["registered"] == 1
    assert gamma["active"] == 1
    assert gamma["touched"] == 1
    assert gamma["crossed"] == 1
    assert gamma["reclaimed"] == 1
    assert gamma["graded"] == 1
    assert gamma["rejected"] == 1
    assert gamma["unavailable"] is False
    assert out["families"]["VOLUME_PROFILE"]["unavailable"] is True
