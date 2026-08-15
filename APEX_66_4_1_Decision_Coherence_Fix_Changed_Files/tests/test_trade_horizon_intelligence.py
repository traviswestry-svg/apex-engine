from engine.trade_horizon_intelligence import build_trade_horizon_intelligence


def bars(start, step, n=30):
    return [{"c": start + step * i} for i in range(n)]


def test_horizons_can_disagree_without_overwriting_each_other():
    context = {
        "ticker": "SPX",
        "confidence": 80,
        "flow": {"bias": "PUT", "flow_score": 82},
        "consensus": {"consensus_direction": "BULLISH"},
        "structure": {"direction": "BULLISH"},
        "auction": {"direction": "BULLISH"},
        "macro_regime": {"direction": "BULLISH"},
        "cross_asset_intelligence": {"direction": "BULLISH"},
    }
    out = build_trade_horizon_intelligence(context, daily_bars=bars(6000, 2), intraday_bars=bars(6100, -1.2))
    assert out["horizons"]["INTRADAY"]["bias"] == "BULLISH"
    assert out["horizons"]["SWING"]["bias"] == "BULLISH"
    assert out["horizons"]["SCALP"]["bias"] in {"BEARISH", "NEUTRAL"}
    assert out["execution_authority"] == "NONE"


def test_data_limited_fails_closed():
    out = build_trade_horizon_intelligence({"ticker": "SPX"})
    for h in ("SCALP", "INTRADAY", "SWING"):
        assert out["horizons"][h]["status"] == "DATA_LIMITED"
        assert out["horizons"][h]["trade_focus"] == "NO_TRADE"


def test_daily_structure_has_more_swing_than_scalp_relevance():
    out = build_trade_horizon_intelligence({"ticker": "SPX"}, daily_bars=bars(6000, 3), intraday_bars=bars(6100, -1))
    assert out["source_relevance"]["daily_structure"]["SWING"] > out["source_relevance"]["daily_structure"]["SCALP"]


def test_authoritative_conflict_fails_closed_and_caps_confidence():
    context = {
        "ticker": "SPX", "session_state": "MARKET_OPEN", "partial": True,
        "institutional_decision_object": {
            "authoritative_contract": True, "decision_authority": "institutional_decision_object",
            "direction": "BEARISH", "action": "NO_TRADE", "actionable": False,
            "raw_conviction": 98, "timestamp": "2026-08-14T20:00:00+00:00",
        },
        "flow": {"bias": "BULLISH", "flow_score": 95},
        "consensus": {"consensus_direction": "BULLISH"},
        "structure": {"direction": "BULLISH"},
        "auction": {"direction": "BULLISH"},
        "breadth_regime": {"state": "DATA_LIMITED"},
    }
    out = build_trade_horizon_intelligence(
        context, daily_bars=bars(6000, 3), intraday_bars=bars(6100, 2)
    )
    assert out["snapshot"]["single_snapshot_contract"] is True
    assert out["relationship"]["authoritative_conflict"] is True
    for horizon in out["horizons"].values():
        assert horizon["trade_focus"] == "NO_TRADE"
        assert horizon["status"] == "CONFLICT"
        assert horizon["confidence"] <= 50
        assert "AUTHORITATIVE_DIRECTION_CONFLICT" in horizon["confidence_cap_reasons"]


def test_closed_session_is_context_only_not_ready():
    context = {
        "ticker": "SPX", "session_state": "CLOSED",
        "breadth_regime": {"state": "CONFIRMED_RECOVERY"},
        "flow": {"bias": "BULLISH", "flow_score": 90},
        "structure": {"direction": "BULLISH"},
    }
    out = build_trade_horizon_intelligence(
        context, daily_bars=bars(6000, 2), intraday_bars=bars(6100, 2)
    )
    for horizon in out["horizons"].values():
        assert horizon["status"] == "CONTEXT_ONLY"
        assert horizon["trade_focus"] == "NO_TRADE"
        assert horizon["confidence"] <= 60
