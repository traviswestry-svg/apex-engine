import importlib


def _panel():
    return {
        "available": True,
        "tradeable": True,
        "strategy": "BULL_PUT_CREDIT_SPREAD",
        "premium_kind": "CREDIT",
        "confidence": 78.0,
        "legs": {
            "sell_leg": 7490.0,
            "buy_leg": 7480.0,
            "width": 10.0,
            "entry_credit": 3.2,
            "max_profit": 320.0,
            "max_loss": 680.0,
            "pricing_basis": "LIVE_CHAIN_EXECUTABLE",
            "chain_grade": "A",
            "execution_confidence": 0.92,
            "chain_quality": {"grade": "A", "score": 94.0, "execution_confidence": 0.92},
            "chain_legs": [
                {"strike": 7490, "bid": 4.0, "ask": 4.2, "quote_age_seconds": 1.0},
                {"strike": 7480, "bid": 0.8, "ask": 1.0, "quote_age_seconds": 2.0},
            ],
        },
    }


def test_capture_is_idempotent_and_preserves_chain_economics(tmp_path, monkeypatch):
    monkeypatch.setenv("RECOMMENDATION_LEDGER_DB_PATH", str(tmp_path / "ledger.db"))
    import engine.recommendation_ledger as ledger
    importlib.reload(ledger)
    capture = ledger.build_capture(
        ticker="SPX", panel=_panel(), last_result={"market_state": {"price": 7560}},
        session_date="2026-07-18", application_version="11.0E")
    first = ledger.record_recommendation(capture)
    second = ledger.record_recommendation(capture)
    assert first["created"] is True
    assert second["duplicate"] is True
    row = ledger.get_recommendation(first["recommendation_id"])
    assert row["entry_credit"] == 3.2
    assert row["chain_grade"] == "A"
    assert row["quote_age_max_seconds"] == 2.0
    assert row["feature_hash"]


def test_lifecycle_events_do_not_overwrite_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("RECOMMENDATION_LEDGER_DB_PATH", str(tmp_path / "ledger.db"))
    import engine.recommendation_ledger as ledger
    importlib.reload(ledger)
    cap = ledger.build_capture(ticker="SPX", panel=_panel(), session_date="2026-07-18")
    rec = ledger.record_recommendation(cap)
    ledger.append_event(rec["recommendation_id"], "QUOTE_SNAPSHOT", {"buy_to_close_ask": 1.0})
    ledger.append_event(rec["recommendation_id"], "CLOSED", {"realized_pnl": 220, "outcome_label": "WIN"})
    row = ledger.get_recommendation(rec["recommendation_id"])
    assert row["entry_credit"] == 3.2
    assert row["realized_pnl"] == 220
    assert row["state"] == "CLOSED"
    assert [e["event_type"] for e in row["events"]] == ["CAPTURED", "QUOTE_SNAPSHOT", "CLOSED"]


def test_calibration_is_blocked_without_history(tmp_path, monkeypatch):
    monkeypatch.setenv("RECOMMENDATION_LEDGER_DB_PATH", str(tmp_path / "ledger.db"))
    import engine.recommendation_ledger as ledger
    importlib.reload(ledger)
    readiness = ledger.calibration_readiness(50)
    assert readiness["status"] == "INSUFFICIENT_HISTORY"
    assert readiness["calibration_enabled"] is False
