import importlib as stdlib_importlib

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


def _build(**overrides):
    kwargs = dict(
        version="x", runtime_health=_runtime("CLOSED"), dependency_map=_deps(),
        registered_routes=_routes(), tv_webhook_secret_configured=True,
        broker_credentials_configured=True, live_trading_enabled=False,
        generated_at="2026-08-01T14:00:00+00:00",
    )
    kwargs.update(overrides)
    return build_monday_readiness(**kwargs)


def _check(payload, step):
    return next(c for c in payload["checks"] if c["step"] == step)


def test_closed_market_preflight_passes_with_live_validation_pending():
    p = _build()
    assert p["monday_ready"] is True
    assert p["validation_mode"] == "STATIC_PREFLIGHT"
    assert p["live_validation_pending"] is True
    assert p["status"] == "PREFLIGHT_PASS_LIVE_VALIDATION_PENDING"
    assert p["summary"]["fail"] == 0
    assert p["summary"]["standby"] == 3
    assert p["summary"]["warn"] == 0
    assert p["summary"]["info"] == 1
    assert p["execution_mode"] == "PREVIEW_ONLY"
    assert p["safety"]["imports_performed"] is True
    assert p["safety"]["broker_order_submitted"] is False


def test_missing_critical_route_blocks_readiness():
    routes = _routes()
    routes.remove(("POST", "/tv_signal"))
    p = _build(registered_routes=routes)
    assert p["monday_ready"] is False
    assert p["status"] == "BLOCKED"
    assert any(x["step"] == "route:signal_ingest" for x in p["blockers"])


def test_missing_webhook_secret_blocks_readiness():
    p = _build(tv_webhook_secret_configured=False)
    assert p["monday_ready"] is False
    assert any(x["step"] == "tradingview_auth" for x in p["blockers"])


def test_missing_broker_credentials_blocks_executable_path():
    p = _build(broker_credentials_configured=False)
    assert p["monday_ready"] is False
    assert any(x["step"] == "broker_credentials" for x in p["blockers"])


def test_market_open_all_green_is_ready_even_when_live_switch_is_off():
    p = _build(runtime_health=_runtime("MARKET_OPEN"))
    assert p["monday_ready"] is True
    assert p["validation_mode"] == "LIVE_SESSION"
    assert p["summary"]["standby"] == 0
    assert p["summary"]["warn"] == 0
    assert p["summary"]["info"] == 1
    assert p["status"] == "READY"


def test_critical_engine_gap_blocks_readiness():
    deps = {"summary": {"monday_critical_missing": ["engine.gamma"], "monday_critical_not_active": []}}
    p = _build(dependency_map=deps)
    assert p["monday_ready"] is False
    assert any(x["step"] == "critical_engines" for x in p["blockers"])


def test_import_smoke_imports_critical_engine_modules():
    p = _build()
    row = _check(p, "critical_import_smoke")
    assert row["state"] == "PASS"
    assert row["data"]["total"] == 12
    assert "app" not in row["data"]["imported"]
    assert row["data"]["failures"] == []


def test_import_smoke_failure_is_hard_blocker(monkeypatch):
    import engine.monday_readiness as mr
    real_import = stdlib_importlib.import_module

    def fake_import(name):
        if name == "engine.gamma":
            raise ImportError("simulated missing dependency")
        return real_import(name)

    monkeypatch.setattr(mr.importlib, "import_module", fake_import)
    p = _build()
    row = _check(p, "critical_import_smoke")
    assert row["state"] == "FAIL"
    assert p["monday_ready"] is False
    assert any(x["step"] == "critical_import_smoke" for x in p["blockers"])
    assert row["data"]["failures"][0]["error_type"] == "ImportError"


def test_credential_freshness_unknown_is_observable_but_not_warning():
    p = _build(broker_credential_freshness={})
    row = _check(p, "broker_credential_freshness")
    assert row["state"] == "PASS"
    assert row["data"]["freshness_state"] == "UNKNOWN"
    assert row["data"]["metadata_available"] is False


def test_credential_expiry_metadata_warns_without_blocking():
    p = _build(broker_credential_freshness={
        "refreshed_at": "2026-08-01T10:00:00+00:00",
        "expires_at": "2026-08-01T13:59:00+00:00",
    })
    row = _check(p, "broker_credential_freshness")
    assert row["state"] == "WARN"
    assert row["data"]["freshness_state"] == "EXPIRED"
    assert p["monday_ready"] is True
    assert p["status"] == "READY_WITH_WARNINGS"


def test_credential_age_policy_warns_when_stale():
    p = _build(broker_credential_freshness={
        "refreshed_at": "2026-08-01T10:00:00+00:00",
        "max_age_seconds": 3600,
    })
    row = _check(p, "broker_credential_freshness")
    assert row["state"] == "WARN"
    assert row["data"]["freshness_state"] == "STALE"


def test_missing_runtime_component_fails_loudly_instead_of_warn():
    runtime = _runtime()
    runtime["components"] = [c for c in runtime["components"] if c["name"] != "Trade Director Intelligence"]
    p = _build(runtime_health=runtime)
    row = _check(p, "trade_director_live_cycle")
    assert row["state"] == "FAIL"
    assert p["monday_ready"] is False
