import datetime as dt
import json
import os
import tempfile

from engine.premium_discipline import REFUSE, RefusalLedger
from engine.refusal_replay import (AVOIDED_LOSS, AVOIDED_STOP, MISSED_WIN,
                                   NOT_EXECUTABLE, grade_refusal,
                                   replay_due_refusals)


def candidate(strategy="BULL_PUT_CREDIT_SPREAD", **legs):
    base = {"sell_leg": 6000, "buy_leg": 5990, "width": 10, "entry_credit": 1.50}
    base.update(legs)
    return {"strategy": strategy, "premium_kind": "CREDIT", "tradeable": True,
            "economics_available": True, "legs": base}


def bar(ts, o, h, l, c):
    return {"t": int(ts.timestamp() * 1000), "o": o, "h": h, "l": l, "c": c}


def test_refused_spread_that_never_breaches_and_expires_otm_is_missed_win():
    now = dt.datetime(2026, 7, 20, 19, 0, tzinfo=dt.timezone.utc)
    bars = [bar(now, 6010, 6020, 6005, 6015)]
    out = grade_refusal(candidate(), bars)
    assert out["outcome"] == MISSED_WIN
    assert out["pnl"] == 150.0


def test_short_strike_touch_is_avoided_stop_even_if_expiry_recovers():
    now = dt.datetime(2026, 7, 20, 19, 0, tzinfo=dt.timezone.utc)
    bars = [bar(now, 6010, 6012, 5999, 6008)]
    out = grade_refusal(candidate(), bars)
    assert out["outcome"] == AVOIDED_STOP
    assert out["metrics"]["short_strike_breached"] is True


def test_expiry_loss_without_intraday_touch_impossible_but_settlement_logic_is_loss():
    # Bear call settles ITM and its short strike is necessarily breached; path rule
    # intentionally classifies this as the more conservative AVOIDED_STOP.
    now = dt.datetime(2026, 7, 20, 19, 0, tzinfo=dt.timezone.utc)
    c = candidate("BEAR_CALL_CREDIT_SPREAD", sell_leg=6020, buy_leg=6030)
    out = grade_refusal(c, [bar(now, 6025, 6035, 6022, 6030)])
    assert out["outcome"] == AVOIDED_STOP
    assert out["pnl"] < 0


def test_missing_credit_is_not_executable():
    now = dt.datetime(2026, 7, 20, 19, 0, tzinfo=dt.timezone.utc)
    out = grade_refusal(candidate(entry_credit=None), [bar(now, 6010, 6020, 6005, 6015)])
    assert out["outcome"] == NOT_EXECUTABLE


def test_due_replay_is_idempotent_and_persists_scorecard():
    with tempfile.TemporaryDirectory() as td:
        ledger = RefusalLedger(os.path.join(td, "replay.db"))
        c = candidate()
        d = {"decision": REFUSE, "score": 60, "threshold": 65,
             "blockers": ["below threshold"], "warnings": []}
        rec = ledger.record(session_date="2026-07-20", ticker="SPX", candidate=c, decision=d)
        decision_time = dt.datetime.fromisoformat(rec["ts"])
        bars = [bar(decision_time + dt.timedelta(minutes=5), 6010, 6020, 6005, 6015)]

        def fetch(*args):
            return bars

        now_et = dt.datetime(2026, 7, 21, 10, 0, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
        first = replay_due_refusals(ledger, fetch, now_et=now_et)
        second = replay_due_refusals(ledger, fetch, now_et=now_et)
        assert first["graded"] == 1
        assert second["graded"] == 0
        score = ledger.replay_scorecard()
        assert score["graded"] == 1
        assert score["missed_winners"] == 1
        assert ledger.recent(1)[0]["counterfactual_outcome"] == MISSED_WIN


def test_replay_routes_are_registered(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "routes.db"))
    import app as apex_app
    client = apex_app.app.test_client()
    assert client.get("/api/premium_discipline/replay").status_code == 200
    run = client.post("/api/premium_discipline/replay/run")
    assert run.status_code == 200
    assert run.get_json()["ok"] is True
