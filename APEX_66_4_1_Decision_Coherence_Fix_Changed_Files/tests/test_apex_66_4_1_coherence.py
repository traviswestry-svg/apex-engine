from engine.institutional_execution_optimizer_v201 import build_execution_plan


def _decision(eligible=True):
    return {
        "ticker": "SPX", "bias": "BEARISH", "confidence": 85,
        "execution_eligible": eligible, "levels": {}, "blocking_reasons": [],
    }


def test_execution_plan_reads_canonical_market_state_price():
    out = build_execution_plan(
        {"market_state": {"price": 7786.01, "atr": 20}}, _decision(True)
    )
    assert out["plan_valid"] is True
    assert out["entry_zone"]["anchor"] > 7000
    assert out["targets"]["tp1"] > 0


def test_ineligible_or_missing_price_plan_is_hidden():
    closed = build_execution_plan(
        {"market_state": {"price": 7786.01, "atr": 20}}, _decision(False)
    )
    assert closed["state"] == "STAND_DOWN"
    assert closed["entry_zone"] is None
    assert closed["invalidation"] is None
    assert closed["targets"] == {}

    missing = build_execution_plan({}, _decision(True))
    assert missing["plan_valid"] is False
    assert "UNDERLYING_PRICE_UNAVAILABLE" in missing["blocking_reasons"]
    assert missing["entry_zone"] is None
