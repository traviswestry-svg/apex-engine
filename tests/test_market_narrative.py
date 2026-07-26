from engine.market_narrative import evaluate, record_timeline, timeline_summary


def test_bullish_aligned_narrative():
    r = evaluate({"liquidity_intelligence":{"race":{"leader":"UPPER","edge_pct":30,"upper":{"level":7030}},"institutional_intent":{"state":"ACCUMULATION","score":70},"sweep_detection":{"state":"NO_ACTIVE_SWEEP"}},"flow_intelligence":{"flow_score":72,"delta_score":68},"auction_intelligence":{"auction_score":64},"structure_score":67,"momentum_score":70,"dealer_score":60,"vwap_score":65})
    assert r["thesis"]["direction"] == "BULLISH"
    assert r["thesis"]["target_level"] == 7030
    assert "bullish" in r["market_story"]


def test_conflict_engine_flags_opposition():
    r = evaluate({"liquidity_intelligence":{"race":{"leader":"UPPER","edge_pct":25,"upper":{"level":7030}},"institutional_intent":{"state":"DISTRIBUTION","score":30},"sweep_detection":{"state":"BUY_SIDE_FAILED_SWEEP"}},"flow_intelligence":{"flow_score":75,"delta_score":25},"auction_intelligence":{"auction_score":30},"structure_score":70,"momentum_score":70})
    assert r["contradiction_engine"]["items"]
    assert r["contradiction_engine"]["conflict_score"] > 0


def test_timeline_memory(tmp_path):
    db = tmp_path / "n.db"
    record_timeline({"ticker":"SPX","event_type":"ENTRY","direction":"BULLISH","confidence":78,"narrative":"test"}, db)
    s = timeline_summary(db)
    assert s["events"] == 1
    assert s["timeline"][0]["event_type"] == "ENTRY"
