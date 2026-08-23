import datetime as dt
from pathlib import Path

from engine import historical_evidence_lifecycle as H
from engine.evidence_pipeline import readiness


def _result(ts: str, *, actionable: bool = True):
    return {
        "ticker": "SPX",
        "spot": 6700.0,
        "market_regime": {"state": "TREND"},
        "gamma_regime": {"state": "NEGATIVE"},
        "trade_horizon_intelligence": {
            "horizons": {
                "SCALP": {"direction": "BULLISH", "confidence": 70},
                "INTRADAY": {"direction": "BULLISH", "confidence": 65},
            }
        },
        "institutional_decision_object": {
            "timestamp": ts,
            "ticker": "SPX",
            "action": "ENTER_LONG" if actionable else "NO_TRADE",
            "direction": "BULLISH",
            "actionable": actionable,
            "strategy": "TEST_SETUP",
            "conviction": {"score": 72},
            "market_state": {"price": 6700.0},
        },
    }


def test_capture_decision_writes_canonical_snapshot_and_is_idempotent(tmp_path, monkeypatch):
    db = tmp_path / "evidence.db"
    monkeypatch.setenv("APEX_MARKET_MEMORY_CAPTURE_ENABLED", "false")
    ts = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=6)).isoformat()
    first = H.capture_decision(_result(ts), session_state="MARKET_OPEN", path=db)
    second = H.capture_decision(_result(ts), session_state="MARKET_OPEN", path=db)
    assert first["ok"] is True and first["inserted"] is True
    assert second["ok"] is True and second["inserted"] is False
    r = readiness(db)
    assert r["decisions_recorded"] == 1
    assert r["actionable_decisions"] == 1


def test_price_sampling_and_automatic_grading_close_lifecycle(tmp_path, monkeypatch):
    db = tmp_path / "evidence.db"
    monkeypatch.setenv("APEX_MARKET_MEMORY_CAPTURE_ENABLED", "false")
    now = dt.datetime.now(dt.timezone.utc)
    observed = now - dt.timedelta(minutes=6)
    H.capture_decision(_result(observed.isoformat()), session_state="MARKET_OPEN", path=db)
    H.sample_price("SPX", 6701.0, observed_at=(observed + dt.timedelta(minutes=1)).isoformat(), path=db)
    H.sample_price("SPX", 6705.0, observed_at=(observed + dt.timedelta(minutes=5)).isoformat(), path=db)
    out = H.grade(path=db)
    assert out["graded"] == 1
    r = readiness(db)
    assert r["graded_outcomes"] == 1
    assert r["price_samples"] == 2


def test_abstention_is_captured_but_not_calibration_eligible(tmp_path, monkeypatch):
    db = tmp_path / "evidence.db"
    monkeypatch.setenv("APEX_MARKET_MEMORY_CAPTURE_ENABLED", "false")
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    out = H.capture_decision(_result(ts, actionable=False), session_state="MARKET_OPEN", path=db)
    assert out["inserted"] is True
    r = readiness(db)
    assert r["decisions_recorded"] == 1
    assert r["actionable_decisions"] == 0


def test_snapshot_contains_horizon_and_regime_context():
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    snap = H.build_snapshot(_result(ts), session_state="MARKET_OPEN")
    assert snap["trade_horizon_intelligence"]["horizons"]["SCALP"]["direction"] == "BULLISH"
    assert snap["market_regime"] == "TREND"
    assert snap["gamma_regime"] == "NEGATIVE"
    assert snap["execution_authority"] is False


def test_production_wiring_is_present_in_canonical_paths():
    app = Path("app.py").read_text()
    scanner = Path("scanner_worker.py").read_text()
    writer = Path("engine/feature_store_writer.py").read_text()
    assert "_apex69_capture_decision(result, session_state=_session_state_now)" in app
    assert "evidence_sample_price(" in scanner
    assert "evidence_grade()" in scanner
    assert "settle_pending_labels(" in app
    assert "def settle_pending_labels" in writer
