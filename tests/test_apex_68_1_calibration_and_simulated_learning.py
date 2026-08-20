import datetime as dt


def _canonical(direction="BEARISH"):
    return {
        "ticker": "SPX", "session_state": "MARKET_OPEN",
        "institutional_decision_object": {
            "authoritative_contract": True, "direction": direction,
            "action": "NO_TRADE", "actionable": False,
            "calibrated_conviction": 61, "timestamp": "2026-08-20T15:00:00+00:00",
        },
        "flow": {"bias": "BULLISH", "flow_score": 70},
        "structure": {"direction": "BULLISH"},
        "consensus": {"direction": "BULLISH"},
        "breadth_regime": {"state": "DATA_LIMITED"},
    }


def test_intraday_conflict_is_governed_to_canonical_session():
    from engine.trade_horizon_intelligence import build_trade_horizon_intelligence
    out = build_trade_horizon_intelligence(_canonical())
    intraday = out["horizons"]["INTRADAY"]
    assert intraday["trend"] == "BEARISH"
    assert intraday["bias"] == "BEARISH"
    assert intraday["raw_context_bias"] == "BULLISH"
    assert intraday["status"] == "CONFLICT"
    assert intraday["trade_focus"] == "NO_TRADE"


def test_gross_call_premium_without_tape_is_unconfirmed():
    from engine.flow_intelligence import build_flow_intelligence_2
    out = build_flow_intelligence_2(
        flow_snapshot={"call_premium": 6260e6, "put_premium": 4240e6,
                       "net_premium": 2020e6, "call_ratio_pct": 59.6,
                       "flow_score": 50, "order_flow_score": 50, "sweep_count": 0,
                       "bias": "BULLISH"},
        tape_rows=[], tape_summary={})
    assert out["flow_intent"] == "CALL_DOMINANT_UNCONFIRMED"
    assert out["directional_confirmed"] is False


def test_style_fit_score_is_not_presented_as_sample_count():
    from engine.trade_director_trade_function_router import build_trade_function_router
    out = build_trade_function_router({})
    assert "Heuristic" in out["score_definition"]
    assert all(r["score_kind"] == "HEURISTIC_STYLE_FIT" for r in out["rankings"])
    assert all(r["sample_count"] == 0 for r in out["rankings"])


def test_completed_pine_signal_promotes_once_to_phase22(tmp_path, monkeypatch):
    import signal_evaluator as se
    import engine.trade_director_institutional_learning as learning
    signal_db = tmp_path / "signals.db"
    learning_db = tmp_path / "learning.db"
    monkeypatch.setenv("SIGNAL_EVAL_DB_PATH", str(signal_db))
    monkeypatch.setenv("APEX_TRADE_LEARNING_DB", str(learning_db))
    se._READY = False
    received = "2026-08-20T14:00:00+00:00"
    se.record_signal({"received_at": received, "ticker": "SPX", "signal": "PUT",
                      "direction": "BEARISH", "system": "APEX_PINE", "score": 72,
                      "price": 6500})
    se._persist_outcome(received, "WIN", 5.0, -1.0, "graded", None, pnl=5.0)
    first = se.sync_completed_to_learning()
    second = se.sync_completed_to_learning()
    assert first == {"eligible": 1, "synced": 1, "failed": 0}
    assert second == {"eligible": 0, "synced": 0, "failed": 0}
    rows = learning.learning_history()
    assert len(rows) == 1
    assert rows[0]["outcome_context"]["source"] == "SIMULATED_TRIGGER_TRADE"
    assert rows[0]["direction"] == "BEARISH"
