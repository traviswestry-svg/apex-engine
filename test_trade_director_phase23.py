def _context():
    return {
        "symbol": "SPX",
        "strategy_orchestration": {"selected_strategy": "OPENING_DRIVE"},
        "options_intelligence": {"best_contract": {"symbol": "SPXW-C-6000"}},
        "multi_timeframe_intelligence": {"decision_gate": "ALIGNED", "dominant_direction": "BULLISH"},
        "flow_intelligence": {"decision_gate": "INSTITUTIONAL_CONFIRMATION", "institutional_bias": "BULLISH"},
        "institutional_decision_engine": {"decision_id": "D1", "decision_gate": "AUTHORIZED", "dominant_direction": "BULLISH", "confidence": 84},
        "position": {"trade_id": "T23-1", "side": "CALL", "entered_at": "2026-07-22T14:00:00Z"},
        "trade_lifecycle": {"lifecycle_id": "L21-X", "lifecycle_state": "EXIT", "provenance": [{"engine": "PHASE_17", "value": "ALIGNED"}]},
    }


def test_phase23_reconstructs_archived_case(tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_TRADE_LEARNING_DB", str(tmp_path / "learning.db"))
    from engine.trade_director_institutional_learning import archive_learning_record
    from engine.trade_director_replay_lab import build_replay_case
    archive_learning_record(_context(), {"trade_id": "T23-1", "realized_pnl": 600, "r_multiple": 1.6, "mfe": 2.2, "mae": -0.4, "duration_minutes": 6})
    replay = build_replay_case("T23-1")
    assert replay["ok"] is True
    assert replay["version"] == "PHASE_23"
    assert replay["lookahead_policy"]["future_data_used_in_reconstruction"] is False
    assert replay["decision_timeline"]
    assert replay["counterfactuals"][0]["scenario"] == "ACTUAL"
    assert replay["decision_scorecard"]["overall_institutional_score"] >= 0


def test_phase23_library_is_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_TRADE_LEARNING_DB", str(tmp_path / "learning.db"))
    from engine.trade_director_institutional_learning import archive_learning_record
    from engine.trade_director_replay_lab import build_replay_lab
    archive_learning_record(_context(), {"trade_id": "T23-1", "realized_pnl": -100, "r_multiple": -0.3})
    lab = build_replay_lab()
    assert lab["read_only"] is True
    assert lab["case_count"] == 1
    assert lab["replay_case"]["trade_id"] == "T23-1"
