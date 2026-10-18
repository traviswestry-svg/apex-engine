from engine.scanner_entrypoint_policy import scan_session_allowed, quantdata_consolidated_size


def test_closed_and_unknown_fail_closed():
    assert not scan_session_allowed("CLOSED")
    assert not scan_session_allowed("UNKNOWN")
    assert not scan_session_allowed("")


def test_existing_eligible_sessions_preserved():
    for session in ("MARKET_OPEN", "PREMARKET", "AFTER_HOURS", "OVERNIGHT"):
        assert scan_session_allowed(session)


def test_quantdata_contract():
    assert quantdata_consolidated_size(200) == 100
    assert quantdata_consolidated_size(0) == 1
    assert quantdata_consolidated_size(75) == 75
    assert quantdata_consolidated_size(None) == 50
    assert quantdata_consolidated_size("bad") == 50


def test_app_entrypoints_use_central_gate_and_provider_bounds():
    from pathlib import Path
    app = (Path(__file__).resolve().parents[1] / "app.py").read_text()
    assert 'if not scan_session_allowed(_entry_session):' in app
    assert 'if not scan_session_allowed(_session):' in app
    assert 'run_scan_once(force=True, source="API_RUN")' in app
    assert '"size": quantdata_consolidated_size(size_per_ticker)' in app
