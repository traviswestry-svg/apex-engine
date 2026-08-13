from datetime import datetime, timedelta, timezone

from engine import trade_director_institutional_intent as p38


def test_long_dated_put_in_bull_market_is_likely_hedge(tmp_path, monkeypatch):
    monkeypatch.setattr(p38, "DB_PATH", tmp_path / "intent.db")
    now = datetime(2026, 7, 24, 14, 0, tzinfo=timezone.utc)
    result = p38.evaluate_large_order(
        {"symbol": "SPX", "option_type": "PUT", "side": "ASK", "opening": True,
         "expiration": (now + timedelta(days=240)).isoformat(), "strike": 6200,
         "trade_time": now.isoformat(), "underlying_position": "LONG_PORTFOLIO"},
        {"spot": 6400, "market_regime": "BULL_TREND", "gamma_regime": "POSITIVE"}, now=now,
    )
    assert result["likely_intent"] == "PORTFOLIO_HEDGE"
    assert result["momentum_burst_impact"] == "HEDGE_CONTEXT_ONLY"
    assert result["expiration_relevance_score"] < 20


def test_fresh_zero_dte_call_sweep_can_be_strong_bullish(tmp_path, monkeypatch):
    monkeypatch.setattr(p38, "DB_PATH", tmp_path / "intent.db")
    now = datetime(2026, 7, 24, 14, 0, tzinfo=timezone.utc)
    result = p38.evaluate_large_order(
        {"symbol": "SPX", "option_type": "CALL", "side": "ASK", "opening": True,
         "expiration": (now + timedelta(hours=5)).isoformat(), "strike": 6400,
         "trade_time": (now - timedelta(minutes=4)).isoformat(), "trade_kind": "SWEEP",
         "open_interest_change": 1200},
        {"spot": 6402, "market_regime": "BULL_TREND", "gamma_regime": "NEGATIVE",
         "subsequent_flow_alignment": 95, "market_reaction_alignment": 92}, now=now,
    )
    assert result["likely_intent"] == "DIRECTIONAL_BULLISH"
    assert result["current_influence"] in {"HIGH", "VERY_HIGH"}
    assert result["momentum_burst_impact"] in {"SUPPORTIVE_BULLISH", "STRONG_BULLISH"}


def test_old_order_decays_even_if_large(tmp_path, monkeypatch):
    monkeypatch.setattr(p38, "DB_PATH", tmp_path / "intent.db")
    now = datetime(2026, 7, 24, 14, 0, tzinfo=timezone.utc)
    result = p38.evaluate_large_order(
        {"symbol": "SPX", "option_type": "PUT", "side": "ASK", "opening": True,
         "expiration": (now + timedelta(days=7)).isoformat(), "strike": 6200,
         "trade_time": (now - timedelta(days=5)).isoformat()},
        {"spot": 6500, "subsequent_flow_alignment": 20, "market_reaction_alignment": 15,
         "major_catalyst_since_trade": True}, now=now,
    )
    assert result["persistence_score"] < 35
    assert result["current_influence"] == "LOW"


def test_closing_trade_not_read_as_directional(tmp_path, monkeypatch):
    monkeypatch.setattr(p38, "DB_PATH", tmp_path / "intent.db")
    now = datetime(2026, 7, 24, 14, 0, tzinfo=timezone.utc)
    result = p38.evaluate_large_order(
        {"symbol": "SPX", "option_type": "CALL", "side": "ASK", "opening": False,
         "expiration": (now + timedelta(days=1)).isoformat(), "trade_time": now.isoformat()},
        {"spot": 6400}, now=now,
    )
    assert result["likely_intent"] == "CLOSING_OR_ROLL"


def test_batch_returns_net_bias(tmp_path, monkeypatch):
    monkeypatch.setattr(p38, "DB_PATH", tmp_path / "intent.db")
    now = datetime.now(timezone.utc)
    orders = [
        {"symbol": "SPX", "option_type": "CALL", "side": "ASK", "opening": True,
         "expiration": (now + timedelta(hours=4)).isoformat(), "trade_time": now.isoformat(), "strike": 6400},
        {"symbol": "SPX", "option_type": "CALL", "side": "ASK", "opening": True,
         "expiration": (now + timedelta(hours=4)).isoformat(), "trade_time": now.isoformat(), "strike": 6405},
    ]
    batch = p38.evaluate_order_batch(orders, {"spot": 6402, "gamma_regime": "NEGATIVE",
                                             "subsequent_flow_alignment": 95, "market_reaction_alignment": 95})
    assert batch["order_count"] == 2
    assert batch["net_bias"] == "BULLISH"


def test_status_is_append_only(tmp_path, monkeypatch):
    monkeypatch.setattr(p38, "DB_PATH", tmp_path / "intent.db")
    now = datetime.now(timezone.utc)
    order = {"symbol": "SPX", "option_type": "PUT", "side": "ASK", "opening": True,
             "expiration": (now + timedelta(days=30)).isoformat(), "trade_time": now.isoformat()}
    p38.evaluate_large_order(order, {"spot": 6400})
    p38.evaluate_large_order(order, {"spot": 6400})
    status = p38.institutional_intent_status()
    assert status["assessment_count"] == 1
    assert status["version"] == "PHASE_38"
