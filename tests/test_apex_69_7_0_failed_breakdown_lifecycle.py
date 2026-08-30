from datetime import datetime, timedelta, timezone

from engine.failed_breakdown_lifecycle import (
    capability, current_state, history, initialize_store, observe,
)


def _level():
    return {"level_id": "pdl-1", "type": "PDL", "price": 7700.0,
            "source": "SPX", "significance_score": 90}


def test_capability_is_observational_only():
    out = capability()
    assert out["version"] == "69.7.0"
    assert out["changes_trade_decisions"] is False
    assert out["execution_authority"] is False
    assert out["automatic_promotion"] is False


def test_failed_breakdown_chronology_persists(tmp_path, monkeypatch):
    monkeypatch.setattr("engine.failed_breakdown_lifecycle.CONFIRM_HOLD_SECONDS", 60)
    db = str(tmp_path / "fbd.db")
    initialize_store(db)
    t0 = datetime(2026, 8, 31, 14, 30, tzinfo=timezone.utc)
    levels = [_level(), {"level_id": "t1", "type": "VWAP", "price": 7710.0,
                         "source": "SPX", "significance_score": 70},
              {"level_id": "t2", "type": "PDH", "price": 7725.0,
                         "source": "SPX", "significance_score": 90}]
    observe(symbol="SPX", price=7712, levels=levels, observed_at=t0, path=db)
    observe(symbol="SPX", price=7696, levels=levels, observed_at=t0 + timedelta(seconds=120), path=db)
    observe(symbol="SPX", price=7701, levels=levels, observed_at=t0 + timedelta(seconds=180), path=db)
    observe(symbol="SPX", price=7706, levels=levels, observed_at=t0 + timedelta(seconds=250), path=db)
    state = current_state(symbol="SPX", path=db)
    eligible = [x for x in state["active"] if x["level_id"] == "pdl-1"]
    assert eligible and eligible[0]["state"] == "ENTRY_ELIGIBLE"
    assert eligible[0]["sweep_depth"] == 4.0
    assert eligible[0]["time_to_reclaim_seconds"] == 60.0
    detail = history(lifecycle_id=eligible[0]["lifecycle_id"], path=db)
    event_types = [x["event_type"] for x in detail["events"]]
    assert "LEVEL_SWEPT" in event_types
    assert "LEVEL_RECLAIMED" in event_types
    assert "NON_ACCEPTANCE_CONFIRMED" in event_types


def test_no_reclaim_is_terminal(tmp_path, monkeypatch):
    monkeypatch.setattr("engine.failed_breakdown_lifecycle.RECLAIM_MAX_SECONDS", 30)
    db = str(tmp_path / "fbd.db")
    t0 = datetime(2026, 8, 31, 14, 30, tzinfo=timezone.utc)
    observe(symbol="SPX", price=7702, levels=[_level()], observed_at=t0, path=db)
    observe(symbol="SPX", price=7695, levels=[_level()], observed_at=t0 + timedelta(seconds=10), path=db)
    observe(symbol="SPX", price=7694, levels=[_level()], observed_at=t0 + timedelta(seconds=50), path=db)
    rows = history(symbol="SPX", path=db)["lifecycles"]
    assert any(x["state"] == "NO_RECLAIM" and x["terminal_at"] for x in rows)


def test_read_path_does_not_create_store(tmp_path, monkeypatch):
    missing = tmp_path / "missing.db"
    out = current_state(path=str(missing))
    assert out["status"] == "WAITING_FOR_OBSERVATIONS"
    assert not missing.exists()
