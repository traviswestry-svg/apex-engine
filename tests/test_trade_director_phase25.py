from engine.trade_director_shadow_validation import build_shadow_validation, evaluate_shadow_trial


def proposal(samples=30):
    return {"proposal_id":"P24-X","target_phase":"PHASE_21","policy_area":"EXIT_MANAGEMENT","evidence_samples":samples,"shadow_mode_required":True,"human_approval_required":True,"auto_apply":False,"implementation_risk":"MEDIUM","rollback_plan_required":True}


def records(n=25):
    return [{"trade_id":f"T{i}","strategy":"MOMENTUM","r_multiple":0.2,"mfe":1.2,"mae":-0.3,"decision_confidence":75} for i in range(n)]


def test_phase25_blocks_non_governed_trial():
    out=evaluate_shadow_trial(proposal(5),records(5),minimum_cases=20)
    assert out["status"] == "BLOCKED"
    assert out["promotion_control"]["production_applied"] is False


def test_phase25_can_create_human_review_candidate():
    out=evaluate_shadow_trial(proposal(),records(),minimum_cases=20,promotion_margin_r=0.05)
    assert out["status"] == "PROMOTION_CANDIDATE"
    assert out["validation"]["passed"] is True
    assert out["promotion_control"]["automatic_promotion"] is False


def test_phase25_surface_never_mutates_live_policy(monkeypatch,tmp_path):
    monkeypatch.setenv("APEX_TRADE_LEARNING_DB",str(tmp_path/"learning.db"))
    out=build_shadow_validation({"policy_governance":{"proposals":[]}})
    assert out["version"] == "PHASE_25"
    assert out["controls"]["live_policy_mutation"] is False
    assert out["controls"]["broker_access"] is False
