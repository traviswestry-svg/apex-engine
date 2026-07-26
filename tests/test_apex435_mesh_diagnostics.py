from engine.institutional_intelligence_mesh import build_intelligence_mesh

def sample():
    return {
        "gamma":{"direction":"CALL","score":90,"reliability":90,"freshness":True},
        "auction":{"direction":"CALL","score":80,"reliability":90,"freshness":True},
        "order_flow":{"direction":"PUT","score":60,"reliability":80,"freshness":True},
    }

def test_diagnostics_exposes_contribution_math():
    r=build_intelligence_mesh(sample(), now=1000)
    assert r["version"]=="43.5"
    assert "pre_penalty_confidence" in r and "conflict_penalty" in r
    assert r["diagnostics"]["active_engines"]==3
    assert all("contribution" in n for n in r["nodes"])

def test_temporary_calibration_can_disable_engine_and_raise_threshold():
    r=build_intelligence_mesh(sample(), now=1000, calibration={"disabled_engines":["order_flow"],"min_engines":3,"min_confidence":99})
    assert r["decision"]=="WAIT"
    assert "order_flow" in r["diagnostics"]["disabled_engines"]
    assert r["diagnostics"]["temporary_calibration"] is True

def test_default_contract_keeps_broker_locked():
    r=build_intelligence_mesh(sample(), now=1000)
    assert r["broker_action"]=="NONE"
    assert r["governed"] is True
