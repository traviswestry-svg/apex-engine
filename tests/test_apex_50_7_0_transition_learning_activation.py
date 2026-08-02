import time

from engine import historical_level_calibration as hlce
from engine import level_transition_probability as ltpe


def test_learning_status_empty_store(tmp_path):
    db = str(tmp_path / "learning.db")
    st = ltpe.learning_status(path=db, now=time.time())
    assert st["ok"] is True
    assert st["version"] == "50.7.0_LEVEL_TRANSITION_LEARNING_ACTIVATION"
    assert st["observations"] == 0
    assert st["probability_policy"] == "EVIDENCE_ONLY_NO_FABRICATION"
    assert st["state"] == "COLLECTING"


def test_learning_cycle_is_idempotent_on_empty_store(tmp_path):
    db = str(tmp_path / "learning.db")
    a = ltpe.run_learning_cycle(path=db)
    b = ltpe.run_learning_cycle(path=db)
    assert a["ok"] and b["ok"]
    assert a["processed"]["recorded"] == 0
    assert b["processed"]["recorded"] == 0
    assert b["after"]["observations"] == 0


def test_service_tick_uses_learning_cycle(monkeypatch, tmp_path):
    db = str(tmp_path / "learning.db")
    service = hlce.CalibrationService(db)
    called = {"n": 0}

    def fake_cycle(*, path=None, limit=500):
        called["n"] += 1
        return {"ok": True, "processed": {"recorded": 1}, "statistics": {"statistics_written": 1}}

    monkeypatch.setattr(ltpe, "run_learning_cycle", fake_cycle)
    out = service.tick({}, now=time.time())
    assert out["ok"] is True
    assert called["n"] == 1
    assert out["transitions"]["recorded"] == 1
