import sqlite3

from engine import historical_level_calibration as hlce


def _snapshot(spot, levels):
    return {
        "ticker": "SPX",
        "spot": spot,
        "market_state": {"price": spot},
        "canonical_levels": [
            {"kind": kind, "price": price, "source": "test"}
            for kind, price in levels
        ],
    }


def _interaction_rows(path):
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(
            "SELECT interaction_type, touch_price, level_price FROM level_interactions ORDER BY ts"
        ).fetchall()]


def test_sparse_sample_crossing_records_real_first_touch(tmp_path):
    db = str(tmp_path / "cal.db")
    hlce.initialize_store(db)
    c = hlce.Collector(db)
    t0 = 1_785_000_000.0
    c.observe(_snapshot(100.0, [("poc", 105.0)]), now=t0)
    out = c.observe(_snapshot(110.0, [("poc", 105.0)]), now=t0 + 15)

    rows = _interaction_rows(db)
    assert any(r["interaction_type"] == "FIRST_TOUCH" for r in rows)
    first = next(r for r in rows if r["interaction_type"] == "FIRST_TOUCH")
    assert first["touch_price"] == 105.0
    assert out["interaction_diagnostics"]["crossing_touches_this_observation"] == 1
    assert c.stats["crossing_touches"] == 1


def test_zero_interactions_is_explainable_when_price_never_nears_level(tmp_path):
    db = str(tmp_path / "cal.db")
    hlce.initialize_store(db)
    c = hlce.Collector(db)
    t0 = 1_785_000_000.0
    c.observe(_snapshot(100.0, [("poc", 120.0)]), now=t0)
    out = c.observe(_snapshot(101.0, [("poc", 120.0)]), now=t0 + 15)

    assert _interaction_rows(db) == []
    d = out["interaction_diagnostics"]
    assert d["state"] == "NO_QUALIFYING_INTERACTION"
    assert d["nearest_level"]["distance"] > d["nearest_level"]["touch_band"]
    assert d["fabrication_allowed"] is False


def test_new_intraday_levels_join_tracks_without_resetting_touch_state(tmp_path):
    db = str(tmp_path / "cal.db")
    hlce.initialize_store(db)
    c = hlce.Collector(db)
    t0 = 1_785_000_000.0
    c.observe(_snapshot(100.0, [("poc", 100.5)]), now=t0)
    assert len(c._tracks) == 1
    touched = [t for t in c._tracks.values() if t.touched]
    assert len(touched) == 1

    c.observe(_snapshot(100.2, [("poc", 100.5), ("or_high", 110.0)]), now=t0 + 15)
    assert len(c._tracks) == 2
    assert any(t.level_type == "poc" and t.touched for t in c._tracks.values())
    assert any(t.level_type == "or_high" for t in c._tracks.values())


def test_near_touch_is_not_spammed_every_collector_cycle(tmp_path):
    db = str(tmp_path / "cal.db")
    hlce.initialize_store(db)
    c = hlce.Collector(db)
    t0 = 1_785_000_000.0
    # At level 100, touch band is 1.5; 102 lies in the 2x near band, outside direct band.
    for i in range(4):
        c.observe(_snapshot(102.0, [("poc", 100.0)]), now=t0 + i * 15)
    rows = _interaction_rows(db)
    assert [r["interaction_type"] for r in rows].count("NEAR_TOUCH") == 1


def test_crossing_first_touch_can_mature_into_outcome(tmp_path):
    db = str(tmp_path / "cal.db")
    hlce.initialize_store(db)
    c = hlce.Collector(db)
    t0 = 1_785_000_000.0
    c.observe(_snapshot(100.0, [("poc", 105.0)]), now=t0)
    c.observe(_snapshot(110.0, [("poc", 105.0)]), now=t0 + 15)
    # Persist forward samples beyond the interaction timestamp.
    c.observe(_snapshot(111.0, [("poc", 105.0)]), now=t0 + 30)
    c.observe(_snapshot(112.0, [("poc", 105.0)]), now=t0 + 45)

    graded = hlce.run_grader(path=db, horizon_seconds=30, now=t0 + 60)
    assert graded["graded"] >= 1
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM level_outcomes").fetchone()[0] >= 1
