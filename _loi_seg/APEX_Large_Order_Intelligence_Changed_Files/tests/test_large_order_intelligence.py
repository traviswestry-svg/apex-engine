from engine.flow_tape import build_flow_tape


def _row(strike, premium, side, time="15:55:00", underlying=7780):
    return {
        "ticker": "SPX", "contractType": "CALL", "strike": strike,
        "expiration": "2026-08-14", "premium": premium,
        "tradeSideCode": side, "tradeConsolidationType": "BLOCK",
        "tradeTime": time, "stockPrice": underlying, "size": 100,
    }


def test_large_blocks_are_clustered_and_price_confirmed():
    out = build_flow_tape(
        [_row(7790, 11_500_000, "AT_ASK")], ["SPX"],
        min_premium=100_000, current_prices={"SPX": 7795},
    )
    row = out["rows"][0]
    assert row["directional_bias"] == "BULLISH"
    assert row["price_confirmation"] == "CONFIRMED"
    assert row["importance_score"] >= 90
    assert out["strike_clusters"][0]["institutional_size"] is True
    assert out["institutional_alerts"][0]["total_premium"] == 11_500_000


def test_missing_execution_side_never_infers_call_is_bullish():
    row = _row(7810, 7_900_000, "")
    out = build_flow_tape([row], ["SPX"], current_prices={"SPX": 7820})
    normalized = out["rows"][0]
    assert normalized["aggressor_side"] == "NEUTRAL"
    assert normalized["directional_bias"] == "UNRESOLVED"
    assert normalized["interpretation_status"] == "SIDE_UNKNOWN"
    assert normalized["price_confirmation"] == "UNAVAILABLE"


def test_opposite_nearby_legs_are_only_possible_spread():
    rows = [
        _row(7790, 11_500_000, "AT_ASK", "15:55:00"),
        _row(7810, 7_900_000, "AT_BID", "15:55:04"),
    ]
    out = build_flow_tape(rows, ["SPX"])
    candidate = out["spread_candidates"][0]
    assert candidate["classification"] == "POSSIBLE_VERTICAL_SPREAD"
    assert candidate["strikes"] == [7790.0, 7810.0]
    assert candidate["confidence"] == "MEDIUM"

