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
