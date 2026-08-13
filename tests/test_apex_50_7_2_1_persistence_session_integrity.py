import os, sqlite3
from datetime import datetime, timezone


def test_hlce_friday_evening_utc_rolls_to_friday_et():
    import engine.historical_level_calibration as h
    # 2026-08-08 01:27 UTC == 2026-08-07 21:27 America/New_York
    ts=datetime(2026,8,8,1,27,tzinfo=timezone.utc).timestamp()
    assert h._canonical_learning_session_date(ts) == '2026-08-07'


def test_weekend_legacy_rows_repaired_without_collision(tmp_path):
    import engine.historical_level_calibration as h
    p=str(tmp_path/'cal.db')
    h.initialize_store(p)
    with sqlite3.connect(p) as c:
        c.execute("INSERT INTO daily_levels(level_id,session_date,symbol,level_type,price,source,confidence,spot_price,distance_from_spot,gamma_regime,auction_regime,trend_regime,expected_move_regime,volatility_regime,registered_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  ('x','2026-08-08','SPX','prev_close',100,'t',1,100,0,'U','U','U','U','U','2026-08-08T01:27:00+00:00'))
        c.commit()
    h.initialize_store(p)
    with sqlite3.connect(p) as c:
        assert c.execute("SELECT session_date FROM daily_levels WHERE level_id='x'").fetchone()[0]=='2026-08-07'


def test_persistent_store_honors_explicit_env(monkeypatch, tmp_path):
    from engine.persistent_store import persistent_sqlite_path
    p=str(tmp_path/'explicit.db')
    monkeypatch.setenv('APEX_TEST_DB', p)
    assert persistent_sqlite_path('APEX_TEST_DB','ignored.db') == p
