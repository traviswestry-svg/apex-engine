from engine.monday_readiness import build_monday_readiness, CRITICAL_ROUTE_STEPS


def _runtime(session="CLOSED"):
    return {
        "runtime_ready": True,
        "status": "HEALTHY",
        "session": session,
        "tradeability_reason": "READY" if session == "MARKET_OPEN" else "MARKET_CLOSED",
        "blockers": [], "warnings": [],
        "components": [
            {"name": "Scanner / Freshness", "state": "HEALTHY", "data": {"scanner_state": "SCHEDULED_IDLE" if session != "MARKET_OPEN" else "RUNNING"}},
            {"name": "Institutional Engines", "state": "HEALTHY", "data": {"standby": 14 if session != "MARKET_OPEN" else 0}},
            {"name": "Trade Director Intelligence", "state": "HEALTHY", "data": {"components": []}},
        ],
    }


def _deps():
    return {"summary": {"monday_critical_missing": [], "monday_critical_not_active": []}}


def _routes():
    return {(method, path) for _, _, method, path in CRITICAL_ROUTE_STEPS}


def test_closed_market_preflight_passes_with_live_validation_pending():
    p = build_monday_readiness(
        version="x", runtime_health=_runtime("CLOSED"), dependency_map=_deps(),
        registered_routes=_routes(), tv_webhook_secret_configured=True,
        broker_credentials_configured=True, live_trading_enabled=False,
    )
    assert p["monday_ready"] is True
    assert p["validation_mode"] == "STATIC_PREFLIGHT"
    assert p["live_validation_pending"] is True
    assert p["summary"]["fail"] == 0
    assert p["summary"]["standby"] == 3
    assert p["execution_mode"] == "PREVIEW_ONLY"
    assert p["safety"]["broker_order_submitted"] is False


def test_missing_critical_route_blocks_readiness():
    routes = _routes()
    routes.remove(("POST", "/tv_signal"))
    p = build_monday_readiness(
        version="x", runtime_health=_runtime(), dependency_map=_deps(),
        registered_routes=routes, tv_webhook_secret_configured=True,
        broker_credentials_configured=True, live_trading_enabled=False,
    )
    assert p["monday_ready"] is False
    assert p["status"] == "BLOCKED"
    assert any(x["step"] == "route:signal_ingest" for x in p["blockers"])


def test_missing_webhook_secret_blocks_readiness():
    p = build_monday_readiness(
        version="x", runtime_health=_runtime(), dependency_map=_deps(),
        registered_routes=_routes(), tv_webhook_secret_configured=False,
        broker_credentials_configured=True, live_trading_enabled=False,
    )
    assert p["monday_ready"] is False
    assert any(x["step"] == "tradingview_auth" for x in p["blockers"])


def test_missing_broker_credentials_blocks_executable_path():
    p = build_monday_readiness(
        version="x", runtime_health=_runtime(), dependency_map=_deps(),
        registered_routes=_routes(), tv_webhook_secret_configured=True,
        broker_credentials_configured=False, live_trading_enabled=False,
    )
    assert p["monday_ready"] is False
    assert any(x["step"] == "broker_credentials" for x in p["blockers"])


def test_market_open_all_green_is_ready_even_when_live_switch_is_off():
    p = build_monday_readiness(
        version="x", runtime_health=_runtime("MARKET_OPEN"), dependency_map=_deps(),
        registered_routes=_routes(), tv_webhook_secret_configured=True,
        broker_credentials_configured=True, live_trading_enabled=False,
    )
    assert p["monday_ready"] is True
    assert p["validation_mode"] == "LIVE_SESSION"
    assert p["summary"]["standby"] == 0
    assert p["summary"]["warn"] == 1  # live kill-switch intentionally off


def test_critical_engine_gap_blocks_readiness():
    deps = {"summary": {"monday_critical_missing": ["engine.gamma"], "monday_critical_not_active": []}}
    p = build_monday_readiness(
        version="x", runtime_health=_runtime(), dependency_map=deps,
        registered_routes=_routes(), tv_webhook_secret_configured=True,
        broker_credentials_configured=True, live_trading_enabled=False,
    )
    assert p["monday_ready"] is False
    assert any(x["step"] == "critical_engines" for x in p["blockers"])
