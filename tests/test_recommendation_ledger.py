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


def _unpriceable_panel():
    """A structure the chain could not price — the broken-condor class."""
    return {
        "available": True, "tradeable": False, "strategy": "IRON_CONDOR",
        "premium_kind": "CREDIT", "confidence": 71.0,
        "legs": {"put_short": 7400.0, "call_short": 7570.0,
                 "economics_available": False,
                 "pricing_basis": "unpriceable_chain_unavailable"},
    }


def _reload(monkeypatch, tmp_path):
    monkeypatch.setenv("RECOMMENDATION_LEDGER_DB_PATH", str(tmp_path / "ledger.db"))
    import engine.recommendation_ledger as L
    importlib.reload(L)
    L.init_db()
    return L


def _record(L, panel):
    cap = L.build_capture(ticker="SPX", panel=panel, session_date="2026-07-16", spot=6300.0)
    return L.record_recommendation(cap)["recommendation_id"]


def test_unexecutable_outcome_is_forced_not_executable(tmp_path, monkeypatch):
    """Settling an unfillable trade as a directional WIN must be overridden."""
    L = _reload(monkeypatch, tmp_path)
    rid = _record(L, _unpriceable_panel())
    # caller tries to record it as a +330 win
    L.append_event(rid, "GRADED", {"outcome_label": "WIN", "realized_pnl": 330.0})
    rec = L.get_recommendation(rid)
    assert rec["outcome_label"] == "NOT_EXECUTABLE"
    assert rec["realized_pnl"] == 0.0
    assert "could not be filled" in (rec["outcome_notes"] or "")


def test_executable_outcome_is_preserved(tmp_path, monkeypatch):
    """A genuine, chain-priced credit keeps its realized outcome."""
    L = _reload(monkeypatch, tmp_path)
    rid = _record(L, _panel())   # the fixture panel is executable
    L.append_event(rid, "GRADED", {"outcome_label": "WIN", "realized_pnl": 180.0, "realized_r": 0.22})
    rec = L.get_recommendation(rid)
    assert rec["outcome_label"] == "WIN"
    assert rec["realized_pnl"] == 180.0


def test_not_executable_rows_excluded_from_gradeable_count(tmp_path, monkeypatch):
    """Calibration must not think it has more executable history than it does."""
    L = _reload(monkeypatch, tmp_path)
    good = _record(L, _panel())
    bad = _record(L, _unpriceable_panel())
    L.append_event(good, "GRADED", {"outcome_label": "WIN", "realized_pnl": 180.0})
    L.append_event(bad, "GRADED", {"outcome_label": "WIN", "realized_pnl": 330.0})
    c = L.counts()
    assert c["gradeable"] == 1
    assert c["not_executable"] == 1


def test_uppercase_pricing_basis_is_recognized_executable(tmp_path, monkeypatch):
    """The capture may store LIVE_CHAIN_EXECUTABLE in any case — the guard must match."""
    L = _reload(monkeypatch, tmp_path)
    rid = _record(L, _panel())   # fixture uses 'LIVE_CHAIN_EXECUTABLE'
    L.append_event(rid, "SETTLED", {"outcome_label": "LOSS", "realized_pnl": -680.0})
    rec = L.get_recommendation(rid)
    assert rec["outcome_label"] == "LOSS"   # preserved, not forced


def test_override_is_persisted_consistently_in_event_and_ledger(tmp_path, monkeypatch):
    """The immutable event and current row must carry the same governed outcome."""
    L = _reload(monkeypatch, tmp_path)
    rid = _record(L, _unpriceable_panel())
    result = L.append_event(
        rid, "GRADED",
        {"outcome_label": "WIN", "realized_pnl": 330.0, "realized_r": 0.48},
    )
    rec = L.get_recommendation(rid)
    event = rec["events"][-1]["payload"]

    assert result["executability_override"] is True
    assert rec["outcome_label"] == event["outcome_label"] == "NOT_EXECUTABLE"
    assert rec["realized_pnl"] == event["realized_pnl"] == 0.0
    assert event["requested_outcome_label"] == "WIN"
    assert event["requested_realized_pnl"] == 330.0
    assert event["requested_realized_r"] == 0.48
    assert event["override_reason"] == "ENTRY_NOT_EXECUTABLE"


def test_missing_pricing_basis_fails_closed(tmp_path, monkeypatch):
    """Missing entry provenance must not silently count as executable history."""
    L = _reload(monkeypatch, tmp_path)
    panel = _panel()
    panel["legs"] = dict(panel["legs"])
    panel["legs"].pop("pricing_basis")
    rid = _record(L, panel)
    L.append_event(rid, "SETTLED", {"outcome_label": "WIN", "realized_pnl": 100.0})
    rec = L.get_recommendation(rid)
    assert rec["outcome_label"] == "NOT_EXECUTABLE"
    assert rec["realized_pnl"] == 0.0


def test_missing_or_zero_entry_credit_fails_closed(tmp_path, monkeypatch):
    """A credit strategy without positive captured credit is not gradeable."""
    for credit in (None, 0.0, -0.1):
        local = tmp_path / str(credit).replace(".", "_")
        local.mkdir()
        L = _reload(monkeypatch, local)
        panel = _panel()
        panel["legs"] = dict(panel["legs"])
        panel["legs"]["entry_credit"] = credit
        rid = _record(L, panel)
        L.append_event(rid, "GRADED", {"outcome_label": "WIN", "realized_pnl": 50.0})
        assert L.get_recommendation(rid)["outcome_label"] == "NOT_EXECUTABLE"
