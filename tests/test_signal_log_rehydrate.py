"""Tests for signal_evaluator.recent_signals — the durable Pine signal log read.

Regression guard for a real defect: /tv_signal persisted every signal to the
pine_signals table, but /api/signal_log served SCANNER_STATE["signal_log"], an
in-memory list that starts empty on every boot. The dashboard's Pine Signal Log
therefore looked empty after each restart/deploy even though the data was safe on
disk. app.py now rehydrates that list from recent_signals() at startup.
"""
import importlib


def _fresh(tmp_path, monkeypatch):
    """Load signal_evaluator against a throwaway DB."""
    monkeypatch.setenv("SIGNAL_EVAL_DB_PATH", str(tmp_path / "sig.db"))
    import signal_evaluator as se
    importlib.reload(se)
    assert se.init_signal_eval_db()
    return se


def _sig(received_at, side="CALL", price=6300.0, **over):
    s = {
        "received_at": received_at,
        "received_at_et": "2026-07-14 10:00:00 ET",
        "ticker": "SPX",
        "signal": side,
        "direction": "BULLISH" if side == "CALL" else "BEARISH",
        "system": "PINE_APEX_OS_v1",
        "score": 82,
        "price": price,
        "apex_ici": 71,
        "apex_decision": "READY",
        "apex_auction": "TREND_DAY_UP",
        "poc": 6285, "vah": 6310, "val": 6270,
    }
    s.update(over)
    return s


def test_recent_signals_empty_table(tmp_path, monkeypatch):
    se = _fresh(tmp_path, monkeypatch)
    assert se.recent_signals(50) == []


def test_recent_signals_roundtrip_and_shape(tmp_path, monkeypatch):
    se = _fresh(tmp_path, monkeypatch)
    se.record_signal(_sig("2026-07-14T14:00:00+00:00", "CALL", 6301.5))
    out = se.recent_signals(50)
    assert len(out) == 1
    r = out[0]
    # Fields the dashboard's signal log renders.
    assert r["ticker"] == "SPX"
    assert r["signal"] == "CALL"
    assert r["price"] == 6301.5
    assert r["apex_ici"] == 71
    assert r["apex_decision"] == "READY"
    assert r["received_at"] == "2026-07-14T14:00:00+00:00"   # join key preserved verbatim
    assert r["hydrated"] is True
    assert r["outcome"] is None                              # ungraded on arrival
    # Display-only fields the scoring table doesn't persist are present but None,
    # so the renderer never hits an undefined key.
    for k in ("vwap", "bar_time", "signal_num", "intern_score",
              "apex_acceptance", "apex_poc_migration"):
        assert k in r and r[k] is None


def test_recent_signals_newest_first_and_limit(tmp_path, monkeypatch):
    se = _fresh(tmp_path, monkeypatch)
    for i in range(5):
        se.record_signal(_sig(f"2026-07-14T1{i}:00:00+00:00", "CALL", 6300 + i))
    out = se.recent_signals(3)
    assert len(out) == 3
    assert [r["received_at"] for r in out] == [
        "2026-07-14T14:00:00+00:00",
        "2026-07-14T13:00:00+00:00",
        "2026-07-14T12:00:00+00:00",
    ]


def test_recent_signals_carries_graded_outcome(tmp_path, monkeypatch):
    se = _fresh(tmp_path, monkeypatch)
    ra = "2026-07-14T14:00:00+00:00"
    se.record_signal(_sig(ra, "CALL", 6300.0))
    se._persist_outcome(ra, "WIN", 4.25, -0.75, "MFE +4.25 / MAE -0.75 pts", None, pnl=4.25)
    r = se.recent_signals(1)[0]
    assert r["outcome"] == "WIN"
    assert r["outcome_pnl"] == 4.25
    assert r["mfe_pts"] == 4.25 and r["mae_pts"] == -0.75


def test_recent_signals_never_raises_on_bad_db(tmp_path, monkeypatch):
    se = _fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(se, "_db_path", lambda: "/nonexistent-dir/x/y.db")
    assert se.recent_signals(10) == []   # degrades to empty, never crashes boot
