from engine.institutional_intelligence_mesh import build_intelligence_mesh


def test_mesh_builds_bullish_consensus():
    result = build_intelligence_mesh({
        "gamma": {"regime": "positive", "confidence": 90},
        "auction": {"state": "acceptance above value", "confidence": 88},
        "flow": {"bias": "aggressive buyers", "confidence": 85},
        "structure": {"bias": "bullish", "confidence": 82},
    }, now=1000)
    assert result["decision"] == "CALL"
    assert result["confidence"] >= 58
    assert result["broker_action"] == "NONE"


def test_mesh_waits_on_conflict():
    result = build_intelligence_mesh({
        "gamma": {"regime": "positive", "confidence": 95},
        "auction": {"state": "acceptance below value", "confidence": 95},
        "flow": {"bias": "aggressive buyers", "confidence": 95},
        "structure": {"bias": "bearish", "confidence": 95},
    }, now=1000)
    assert result["decision"] == "WAIT"
    assert result["conflict"] > 30


def test_mesh_waits_with_insufficient_coverage():
    result = build_intelligence_mesh({"gamma": {"regime": "positive", "confidence": 99}}, now=1000)
    assert result["decision"] == "WAIT"
    assert result["coverage"] < 40
