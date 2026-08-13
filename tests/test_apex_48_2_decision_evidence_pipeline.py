import os
import tempfile


def test_capture_and_terminal_label(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "apex.db")
        monkeypatch.setenv("DB_PATH", db)
        from engine import feature_store_db
        feature_store_db._DB_READY = False
        from engine.decision_evidence_pipeline import capture_recommendation, process_terminal_event, readiness
        capture = {
            "recommendation_id":"rec-1", "captured_at":"2026-07-26T14:00:00+00:00",
            "session_date":"2026-07-26", "ticker":"SPX", "strategy":"CALL_DEBIT",
            "tradeable":True, "state":"ACTIONABLE", "spot":7000, "final_live_confidence":81,
            "snapshot":{"market_state":{"trend":"UP"}}, "feature_hash":"abc"
        }
        result = capture_recommendation(capture)
        assert result["feature_created"] is True
        assert result["signal_created"] is True
        label = process_terminal_event(capture, "SETTLED", {"outcome_label":"WIN","realized_r":1.2})
        assert label["label_created"] is True
        state = readiness()
        assert state["counts"]["features"] == 1
        assert state["counts"]["labels"] == 1


def test_no_fabricated_label_without_outcome(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("DB_PATH", os.path.join(td, "apex.db"))
        from engine import feature_store_db
        feature_store_db._DB_READY = False
        from engine.decision_evidence_pipeline import capture_recommendation, process_terminal_event
        capture={"recommendation_id":"rec-2","captured_at":"2026-07-26T14:00:00+00:00","session_date":"2026-07-26","ticker":"SPX","strategy":"NO_TRADE","snapshot":{}}
        capture_recommendation(capture)
        result=process_terminal_event(capture,"SETTLED",{})
        assert result["label_created"] is False
        assert result["reason"] == "OUTCOME_NOT_SUPPLIED"
