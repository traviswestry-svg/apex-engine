import sqlite3

from engine import level_transition_probability as ltpe
from engine import historical_level_calibration as hlce


def _brief():
    return {
        "source_session_date": "2026-07-31",
        "target_session_date": "2026-08-03",
        "session_context": {
            "state": "WEEKEND",
            "brief_mode": "NEXT_SESSION_PREP",
            "source_session_date": "2026-07-31",
            "target_session_date": "2026-08-03",
        },
        "structured": {
            "spot": 7489.52,
            "gamma_regime": "unknown",
            "expected_move": {"lower": 7450.04, "upper": 7529.00},
            "levels": [
                {"kind": "call_wall", "price": 7490.00, "source": "gamma_provider"},
                {"kind": "prev_day_high", "price": 7512.04, "source": "polygon"},
                {"kind": "em_upper", "price": 7529.00, "source": "computed"},
                {"kind": "or5_high", "price": "[FEED REQUIRED]", "source": "computed"},
                {"kind": "ib_high", "price": "[FEED REQUIRED]", "source": "computed"},
            ],
        },
    }


def test_next_session_path_resolves_spot_levels_and_closed_context(tmp_path, monkeypatch):
    db = str(tmp_path / "hlce.db")
    monkeypatch.setattr(ltpe, "_load_latest_morning_brief", lambda symbol="SPX": _brief())

    # Deliberately no live spot/levels and a Saturday timestamp around the old
    # heuristic's lunch window.  50.6.2 must not emit LUNCH_SESSION.
    snapshot = {"ticker": "SPX", "generated_at": "2026-08-01T16:12:24+00:00"}
    out = ltpe.current_transition_path(snapshot, path=db, direction="UP", max_steps=6)

    assert out["ok"] is True
    assert out["version"] == "50.6.2_LEVEL_TRANSITION_PROBABILITY"
    assert out["spot"] == 7489.52
    assert out["spot_mode"] == "CANONICAL_NEXT_SESSION_SPOT"
    assert out["spot_session"] == "2026-07-31"
    assert out["spot_is_observation_input"] is False
    assert out["level_universe_mode"] == "NEXT_SESSION_DAILY_KEY_LEVELS"
    assert out["source_session_date"] == "2026-07-31"
    assert out["target_session_date"] == "2026-08-03"
    assert out["context"]["session_bucket"] == "NEXT_SESSION_PREP"

    # 7490 is inside LTPE's 3-point source cluster around spot, so the next
    # distinct upward targets are PDH then expected-move high.
    assert [s["level_type"] for s in out["steps"]] == ["prev_day_high", "expected_move_high"]
    assert [round(s["price"], 2) for s in out["steps"]] == [7512.04, 7529.00]
    assert out["steps"][1]["transition"]["source"] == "INSUFFICIENT_HISTORY"
    assert out["steps"][1]["transition"]["probability"] is None

    # Read-model fallback context must never create training observations.
    status = ltpe.status(path=db)
    assert status["observations"] == 0


def test_explicit_spot_still_uses_next_session_level_universe(tmp_path, monkeypatch):
    db = str(tmp_path / "hlce.db")
    monkeypatch.setattr(ltpe, "_load_latest_morning_brief", lambda symbol="SPX": _brief())
    out = ltpe.current_transition_path(
        {"ticker": "SPX"}, path=db, direction="UP", spot=7489.52, max_steps=6
    )
    assert out["ok"] is True
    assert out["spot_mode"] == "EXPLICIT_SPOT"
    assert out["level_universe_mode"] == "NEXT_SESSION_DAILY_KEY_LEVELS"
    assert len(out["steps"]) == 2
    assert out["context"]["session_bucket"] == "NEXT_SESSION_PREP"


def test_persisted_hlce_context_is_last_resort_without_brief(tmp_path, monkeypatch):
    db = str(tmp_path / "hlce.db")
    ltpe.initialize_transition_store(db)
    monkeypatch.setattr(ltpe, "_load_latest_morning_brief", lambda symbol="SPX": None)
    with hlce._connect(db) as conn:
        rows = [
            ("a", "2026-07-31", "SPX", "prev_close", 7489.72, "polygon", 1.0, 7489.52),
            ("b", "2026-07-31", "SPX", "prev_day_high", 7512.04, "polygon", 1.0, 7489.52),
            ("c", "2026-07-31", "SPX", "expected_move_high", 7529.0, "computed", 1.0, 7489.52),
        ]
        for level_id, session_date, symbol, level_type, price, source, conf, spot in rows:
            conn.execute(
                """INSERT INTO daily_levels
                   (level_id,session_date,symbol,level_type,price,source,confidence,
                    spot_price,distance_from_spot,gamma_regime,auction_regime,trend_regime,
                    expected_move_regime,volatility_regime,registered_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (level_id, session_date, symbol, level_type, price, source, conf, spot,
                 price-spot, "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN",
                 "2026-07-31T20:00:00+00:00"),
            )
        conn.commit()

    out = ltpe.current_transition_path({"ticker": "SPX"}, path=db, direction="UP")
    assert out["ok"] is True
    assert out["spot_mode"] == "LAST_SESSION_SPOT"
    assert out["level_universe_mode"] == "LAST_HLCE_SESSION_LEVELS"
    assert [s["level_type"] for s in out["steps"]] == ["prev_day_high", "expected_move_high"]
