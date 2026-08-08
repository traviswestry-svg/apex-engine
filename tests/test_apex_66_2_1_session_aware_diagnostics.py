import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from engine.evidence_accumulation_observatory import _level_source_coverage
from engine.historical_level_calibration import initialize_store, resolve_evidence_session_date


def _seed_level(db: str, session_date: str, level_id: str = "g1", level_type: str = "call_wall"):
    initialize_store(db)
    with sqlite3.connect(db) as c:
        c.execute(
            "INSERT INTO daily_levels(level_id,session_date,symbol,level_type,price,registered_at,active) VALUES(?,?,?,?,?,?,?)",
            (level_id, session_date, "SPX", level_type, 7000.0, f"{session_date}T13:00:00+00:00", 1),
        )
        c.commit()


def test_weekend_resolves_to_most_recent_registered_session(tmp_path):
    db = str(tmp_path / "calibration.db")
    _seed_level(db, "2026-08-07")
    saturday = datetime(2026, 8, 8, 12, 0, tzinfo=ZoneInfo("America/New_York")).timestamp()

    resolved = resolve_evidence_session_date(path=db, symbol="SPX", now_epoch=saturday)

    assert resolved["requested_date"] == "2026-08-08"
    assert resolved["effective_session_date"] == "2026-08-07"
    assert resolved["session_resolution"] == "MOST_RECENT_REGISTERED_TRADING_SESSION"
    assert resolved["market_session_today"] is False


def test_explicit_override_is_honored_exactly_even_when_weekend(tmp_path):
    db = str(tmp_path / "calibration.db")
    _seed_level(db, "2026-08-07")

    saturday = datetime(2026, 8, 8, 12, 0, tzinfo=ZoneInfo("America/New_York")).timestamp()
    resolved = resolve_evidence_session_date(
        path=db, symbol="SPX", requested_date="2026-08-08", now_epoch=saturday
    )

    assert resolved["requested_date"] == "2026-08-08"
    assert resolved["effective_session_date"] == "2026-08-08"
    assert resolved["session_resolution"] == "EXPLICIT_OVERRIDE"
    assert resolved["market_session_today"] is False


def test_level_source_coverage_exposes_requested_and_effective_dates(tmp_path):
    db = str(tmp_path / "calibration.db")
    _seed_level(db, "2026-08-07")

    out = _level_source_coverage(db, symbol="SPX", session_date="2026-08-07")

    assert out["session_date"] == "2026-08-07"
    assert out["requested_date"] == "2026-08-07"
    assert out["effective_session_date"] == "2026-08-07"
    assert out["session_resolution"] == "EXPLICIT_OVERRIDE"
    assert out["families"]["GAMMA"]["registered"] == 1
    assert out["families"]["GAMMA"]["active"] == 1
    assert out["families"]["GAMMA"]["unavailable"] is False


def test_invalid_explicit_session_date_is_rejected(tmp_path):
    db = str(tmp_path / "calibration.db")
    initialize_store(db)
    try:
        resolve_evidence_session_date(path=db, requested_date="08-07-2026")
    except ValueError as exc:
        assert "YYYY-MM-DD" in str(exc)
    else:
        raise AssertionError("invalid date was accepted")
