import sqlite3

from engine.evidence_accumulation_observatory import _level_source_coverage
from engine.historical_level_calibration import (
    compare_session_level_identity,
    initialize_store,
    session_levels,
)


def _insert_level(conn, *, level_id, canonical_id, level_type, price, active):
    conn.execute(
        """INSERT INTO daily_levels(
            level_id,session_date,symbol,level_type,price,registered_at,canonical_level_id,active
        ) VALUES(?,?,?,?,?,?,?,?)""",
        (
            level_id,
            "2026-08-07",
            "SPX",
            level_type,
            price,
            "2026-08-07T13:30:00+00:00",
            canonical_id,
            active,
        ),
    )


def test_historical_coverage_treats_retired_registered_family_as_available(tmp_path):
    db = str(tmp_path / "calibration.db")
    initialize_store(db)
    with sqlite3.connect(db) as conn:
        _insert_level(
            conn,
            level_id="g1",
            canonical_id="canon-gamma",
            level_type="gamma_flip",
            price=7752.5,
            active=0,
        )
        conn.execute(
            "INSERT INTO level_interactions(interaction_id,level_id,session_date,symbol,level_type,interaction_type,touch_ordinal,ts,graded) VALUES(?,?,?,?,?,?,?,?,?)",
            ("i1", "g1", "2026-08-07", "SPX", "gamma_flip", "FIRST_TOUCH", 1, "2026-08-07T14:00:00+00:00", 1),
        )
        conn.commit()

    out = _level_source_coverage(db, symbol="SPX", session_date="2026-08-07")
    gamma = out["families"]["GAMMA"]
    assert gamma["registered"] == 1
    assert gamma["registered_for_session"] == 1
    assert gamma["active_during_session"] == 1
    assert gamma["active"] == 0
    assert gamma["currently_active"] == 0
    assert gamma["retired_after_session"] == 1
    assert gamma["stale"] == 1
    assert gamma["touched"] == 1
    assert gamma["unavailable"] is False


def test_session_levels_includes_retired_rows(tmp_path):
    db = str(tmp_path / "calibration.db")
    initialize_store(db)
    with sqlite3.connect(db) as conn:
        _insert_level(conn, level_id="a", canonical_id="ca", level_type="call_wall", price=7760.0, active=0)
        _insert_level(conn, level_id="b", canonical_id="cb", level_type="put_wall", price=7755.0, active=1)
        conn.commit()

    rows = session_levels("2026-08-07", "SPX", path=db)
    assert len(rows) == 2
    assert {r["level_id"] for r in rows} == {"a", "b"}


def test_historical_identity_prefers_canonical_id_over_changed_kind_price():
    registry = [
        {"canonical_level_id": "canon-1", "kind": "gamma_flip", "price": 7752.5},
    ]
    hlce = [
        {
            "canonical_level_id": "canon-1",
            "level_type": "zero_gamma",
            "price": 7753.0,
            "active": 0,
        }
    ]
    out = compare_session_level_identity(registry, hlce)
    assert out["historical_sync"] is True
    assert out["historical_identity_matches"] == 1
    assert out["hlce_currently_active"] == 0
    assert out["hlce_retired_after_session"] == 1


def test_historical_identity_uses_kind_price_fallback_for_legacy_rows():
    registry = [{"kind": "prev_close", "price": 7709.96}]
    hlce = [{"level_type": "prev_close", "price": 7709.96001, "active": 0}]
    out = compare_session_level_identity(registry, hlce)
    assert out["historical_sync"] is True
    assert out["historical_identity_matches"] == 1


def test_historical_identity_reports_true_missing_rows():
    registry = [{"canonical_level_id": "canon-1", "kind": "call_wall", "price": 7760.0}]
    hlce = []
    out = compare_session_level_identity(registry, hlce)
    assert out["historical_sync"] is False
    assert out["historical_identity_matches"] == 0
    assert len(out["registry_only_rows"]) == 1
