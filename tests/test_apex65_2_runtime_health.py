from pathlib import Path

from engine.runtime_health import build_runtime_health, normalize_state

ROOT = Path(__file__).resolve().parents[1]


def _base(**overrides):
    payload = dict(
        version="test",
        route_audit={"status": "HEALTHY", "duplicate_route_count": 0, "critical_missing": [], "route_count": 877},
        scanner={"state": "CLOSED", "detail": "weekend", "session": "CLOSED"},
        sources={},
        engine_health={"red": 14, "yellow": 0, "available": 0, "total": 14, "expected": False},
        trade_director={
            "market_memory": {"state": "HEALTHY"},
            "cross_asset_intelligence": {"state": "HEALTHY"},
            "strategy_orchestration": {"state": "HEALTHY"},
        },
        auth_layer_available=True,
    )
    payload.update(overrides)
    return build_runtime_health(**payload)


def test_closed_market_is_not_false_failure():
    result = _base()
    assert result["status"] == "HEALTHY"
    assert result["blockers"] == []
    assert result["runtime_ready"] is True
    assert result["tradeable_runtime"] is False
    assert result["tradeability_reason"] == "MARKET_CLOSED"
    assert result["session"] == "CLOSED"


def test_required_failed_component_blocks_runtime():
    td = {
        "market_memory": {"state": "FAILED"},
        "cross_asset_intelligence": {"state": "HEALTHY"},
        "strategy_orchestration": {"state": "HEALTHY"},
    }
    result = _base(trade_director=td)
    assert result["status"] == "FAILED"
    assert "Trade Director Intelligence" in result["blockers"]
    assert result["tradeable_runtime"] is False


def test_degraded_component_is_warning_not_hard_blocker():
    td = {
        "market_memory": {"state": "DEGRADED", "fallback_used": True},
        "cross_asset_intelligence": {"state": "HEALTHY"},
        "strategy_orchestration": {"state": "HEALTHY"},
    }
    result = _base(trade_director=td)
    assert result["status"] == "DEGRADED"
    assert result["blockers"] == []
    assert "Trade Director Intelligence" in result["warnings"]


def test_runtime_route_and_frontend_hooks_exist():
    app_text = (ROOT / "app.py").read_text()
    assistant = (ROOT / "templates/assistant.html").read_text()
    os_js = (ROOT / "static/js/apex_os.js").read_text()
    api_js = (ROOT / "static/js/apex_api.js").read_text()
    assert '@app.get("/api/runtime/health")' in app_text
    assert "_apex65_record_component_health" in app_text
    assert "apexRuntimeState" in assistant
    assert "loadRuntimeHealth" in assistant
    assert "runtimeHealth" in api_js
    assert "apexRuntimeHealthBadge" in os_js


def test_runtime_state_aliases_preserve_scheduled_idle_truth():
    assert normalize_state("CLOSED") == "HEALTHY"
    assert normalize_state("WARMING") == "DEGRADED"


def test_market_open_healthy_runtime_is_tradeable():
    result = _base(
        scanner={"state": "HEALTHY", "detail": "live", "session": "MARKET_OPEN"},
        engine_health={"red": 0, "yellow": 0, "available": 14, "total": 14, "expected": True},
    )
    assert result["runtime_ready"] is True
    assert result["tradeable_runtime"] is True
    assert result["tradeability_reason"] == "READY"


def test_degraded_runtime_is_ready_but_not_tradeable():
    td = {
        "market_memory": {"state": "DEGRADED", "fallback_used": True},
        "cross_asset_intelligence": {"state": "HEALTHY"},
        "strategy_orchestration": {"state": "HEALTHY"},
    }
    result = _base(
        scanner={"state": "HEALTHY", "detail": "live", "session": "MARKET_OPEN"},
        engine_health={"red": 0, "yellow": 0, "available": 14, "total": 14, "expected": True},
        trade_director=td,
    )
    assert result["runtime_ready"] is True
    assert result["tradeable_runtime"] is False
    assert result["tradeability_reason"] == "RUNTIME_DEGRADED"


def test_runtime_route_maps_idle_red_rows_to_standby():
    app_text = (ROOT / "app.py").read_text()
    assert '"STANDBY" if not engines_expected' in app_text
    assert '"raw_status": row.get("status")' in app_text
