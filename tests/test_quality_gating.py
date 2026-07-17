from engine.quality_gating import quality_multiplier, gate_decision, apply_quality_gate


def _q(score=90, conf=100, passed=True, assessment="HIGH"):
    return {"score": score, "score_confidence_pct": conf,
            "gate_passed": passed, "assessment_confidence": assessment}


def test_quality_is_multiplicative_not_additive():
    out = apply_quality_gate({"confidence": 80, "gex_score": 70}, _q(score=80, conf=100))
    assert out["confidence"] == 64
    assert out["confidence_raw"] == 80
    assert out["gex_score"] == 70


def test_failed_gate_caps_multiplier():
    assert quality_multiplier(_q(score=99, conf=100, passed=False)) == .35
    assert gate_decision(_q(score=99, conf=100, passed=False))["action"] == "CAP"


def test_missing_or_low_confidence_suppresses():
    assert gate_decision(None)["action"] == "SUPPRESS"
    out = apply_quality_gate({"call_wall": 6000, "confidence": 90}, None)
    assert out["call_wall"] is None
    assert out["confidence"] == 0
