from engine.liquidity_intelligence import build_liquidity_map, evaluate, infer_intent, record_outcome, memory_summary


def test_map_ranks_real_levels_and_keeps_both_sides():
    pools = build_liquidity_map({"current_price": 7000, "pdh": 7030, "pdl": 6980, "call_wall": 7050, "put_wall": 6975, "atr": 18})
    assert any(p["type"] == "PDH" for p in pools)
    assert {p["side"] for p in pools} == {"UPPER", "LOWER"}
    assert all(0 <= p["strength_score"] <= 100 for p in pools)


def test_equal_distance_uses_directional_intent():
    result = evaluate({"current_price": 7000, "pdh": 7030, "pdl": 6970,
                       "order_flow_score": 80, "delta_score": 75, "momentum_score": 70,
                       "structure_score": 65, "auction_score": 62})
    assert result["race"]["leader"] == "UPPER"
    assert result["institutional_intent"]["state"] == "ACCUMULATION"
    assert result["trade_director_context"]["preferred_target_side"] == "UPPER"


def test_failed_buy_side_sweep_is_classified():
    result = evaluate({"current_price": 7028, "previous_price": 7025, "bar_high": 7032,
                       "bar_low": 7024, "pdh": 7030, "pdl": 6980})
    assert result["sweep_detection"]["state"] == "BUY_SIDE_FAILED_SWEEP"


def test_memory_records_and_summarizes(tmp_path):
    db = tmp_path / "liq.db"
    record_outcome({"ticker":"SPX","pool_type":"PDH","side":"UPPER","level":7030,"strength":80,
                    "outcome":"HIT","reaction":"REVERSAL","minutes_to_hit":12}, db)
    summary = memory_summary(db)
    assert summary["observations"] == 1
    assert summary["by_pool_type"][0]["hit_rate"] == 100.0
