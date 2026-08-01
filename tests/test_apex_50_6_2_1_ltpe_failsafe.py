
from engine import level_transition_probability as ltpe


def _brief():
    return {
        "source_session_date": "2026-07-31",
        "target_session_date": "2026-08-03",
        "session_context": {"state": "WEEKEND", "brief_mode": "NEXT_SESSION_PREP"},
        "structured": {
            "spot": 7489.52,
            "expected_move": {"lower": 7450.04, "upper": 7529.00},
            "levels": [
                {"kind": "prev_day_high", "price": 7512.04, "source": "polygon"},
                {"kind": "em_upper", "price": 7529.00, "source": "computed"},
            ],
        },
    }


def test_broken_persistence_falls_through_to_brief(tmp_path, monkeypatch):
    db = str(tmp_path / "ltpe.db")
    monkeypatch.setattr(ltpe, "_load_latest_morning_brief", lambda symbol="SPX": _brief())
    monkeypatch.setattr(ltpe, "_latest_persisted_levels", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db")))
    monkeypatch.setattr(ltpe, "_latest_persisted_spot", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db")))
    out = ltpe.current_transition_path({"ticker": "SPX"}, path=db, direction="UP")
    assert out["ok"] is True
    assert out["spot_mode"] == "CANONICAL_NEXT_SESSION_SPOT"
    assert [x["level_type"] for x in out["steps"]] == ["prev_day_high", "expected_move_high"]


def test_statistics_failure_keeps_structural_path(tmp_path, monkeypatch):
    db = str(tmp_path / "ltpe.db")
    monkeypatch.setattr(ltpe, "_load_latest_morning_brief", lambda symbol="SPX": _brief())
    monkeypatch.setattr(ltpe, "next_level_probability", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stats")))
    out = ltpe.current_transition_path({"ticker": "SPX"}, path=db, direction="UP")
    assert out["ok"] is True
    assert len(out["steps"]) == 2
    edge = out["steps"][1]["transition"]
    assert edge["source"] == "STATISTICS_UNAVAILABLE"
    assert edge["probability"] is None
    assert out["resolution_warnings"][0]["stage"] == "TRANSITION_STATISTICS"


def test_unexpected_level_resolution_returns_structured_failure(tmp_path, monkeypatch):
    db = str(tmp_path / "ltpe.db")
    monkeypatch.setattr(ltpe, "_canonical_level_universe", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = ltpe.current_transition_path({"ticker": "SPX"}, path=db, direction="UP")
    assert out["ok"] is False
    assert out["error"] == "LEVEL_CONTEXT_RESOLUTION_FAILED"
    assert out["failure_stage"] == "LEVEL_UNIVERSE"
    assert out["exception_type"] == "RuntimeError"
    assert out["steps"] == []
    assert out["version"] == "50.6.2.1_LEVEL_TRANSITION_PROBABILITY"
