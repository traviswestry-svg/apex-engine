from engine.trade_director_policy_governance import build_policy_governance, evaluate_policy_proposal


def test_phase24_blocks_small_sample_policy_change():
    proposal = {"target_phase":"PHASE_20","policy_area":"CONFIDENCE","evidence_samples":5,"shadow_mode_required":True,"human_approval_required":True,"auto_apply":False,"implementation_risk":"LOW"}
    out = evaluate_policy_proposal(proposal, minimum_samples=20)
    assert out["status"] == "DRAFT"
    assert out["governance_evaluation"]["decision"] == "INSUFFICIENT_EVIDENCE"
    assert "sufficient_samples" in out["governance_evaluation"]["failed_gates"]


def test_phase24_allows_shadow_review_but_never_auto_apply():
    proposal = {"target_phase":"PHASE_14","policy_area":"STRATEGY_PRIORITY","evidence_samples":30,"shadow_mode_required":True,"human_approval_required":True,"auto_apply":False,"implementation_risk":"MEDIUM"}
    out = evaluate_policy_proposal(proposal, minimum_samples=20)
    assert out["status"] == "SHADOW_READY"
    assert out["auto_apply"] is False


def test_phase24_governance_surface_is_advisory(monkeypatch, tmp_path):
    monkeypatch.setenv("APEX_TRADE_LEARNING_DB", str(tmp_path / "learning.db"))
    out = build_policy_governance({"institutional_learning":{"summary":{"trades_learned":0},"confidence_calibration":{},"strategy_scorecards":[]},"replay_laboratory":{"replay_case":{"ok":False}}})
    assert out["version"] == "PHASE_24"
    assert out["change_control"]["direct_configuration_mutation"] is False
    assert out["change_control"]["automatic_policy_promotion"] is False
