from engine.options.options_data_bus import OptionsDataBus


def test_contract_recommendations_refuse_failed_quality_gate():
    rows = [{"side":"CALL", "strike":6000, "bid":10, "ask":10.2,
             "spread_pct":2, "volume":100, "liquidity_score":90}]
    q = {"score":99, "score_confidence_pct":100, "assessment_confidence":"HIGH", "gate_passed":False}
    assert OptionsDataBus().recommend_contracts(rows, spot=5995, chain_quality=q) == []


def test_contract_recommendations_allow_passed_gate():
    rows = [{"side":"CALL", "strike":6000, "bid":10, "ask":10.2,
             "spread_pct":2, "volume":100, "liquidity_score":90}]
    q = {"score":90, "score_confidence_pct":100, "assessment_confidence":"HIGH", "gate_passed":True}
    assert len(OptionsDataBus().recommend_contracts(rows, spot=5995, chain_quality=q)) == 1
