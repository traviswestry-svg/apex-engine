import os


def _context():
    return {
        "symbol": "SPX",
        "strategy_orchestration": {"selected_strategy": "OPENING_DRIVE"},
        "options_intelligence": {"best_contract": {"symbol": "SPXW-C-6000"}},
        "multi_timeframe_intelligence": {"decision_gate": "ALIGNED", "dominant_direction": "BULLISH"},
        "flow_intelligence": {"decision_gate": "INSTITUTIONAL_CONFIRMATION", "institutional_bias": "BULLISH"},
        "institutional_decision_engine": {"decision_id": "D1", "dominant_direction": "BULLISH", "confidence": 80},
        "position": {"trade_id": "T22-1", "side": "CALL", "entered_at": "2026-07-22T14:00:00Z"},
        "trade_lifecycle": {"lifecycle_id": "L21-X", "provenance": [{"engine": "PHASE_17", "value": "ALIGNED"}, {"engine": "PHASE_18", "value": "INSTITUTIONAL_CONFIRMATION"}]},
    }


def test_phase22_archives_and_scores(tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_TRADE_LEARNING_DB", str(tmp_path / "learning.db"))
    from engine.trade_director_institutional_learning import archive_learning_record, build_learning_intelligence
    archived = archive_learning_record(_context(), {"trade_id": "T22-1", "realized_pnl": 500, "r_multiple": 1.5, "mfe": 2.0, "mae": -0.5, "duration_minutes": 4})
    assert archived["ok"] is True
    report = build_learning_intelligence(_context())
    assert report["version"] == "PHASE_22"
    assert report["summary"]["trades_learned"] == 1
    assert report["summary"]["win_rate"] == 100.0
    assert report["feedback_contract"]["automatic_live_mutation"] is False


def test_phase22_upsert_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_TRADE_LEARNING_DB", str(tmp_path / "learning.db"))
    from engine.trade_director_institutional_learning import archive_learning_record, learning_history
    archive_learning_record(_context(), {"trade_id": "T22-1", "realized_pnl": -100, "r_multiple": -0.5})
    archive_learning_record(_context(), {"trade_id": "T22-1", "realized_pnl": 250, "r_multiple": 0.8})
    rows = learning_history()
    assert len(rows) == 1
    assert rows[0]["realized_pnl"] == 250
