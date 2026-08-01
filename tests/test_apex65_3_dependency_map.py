from engine.runtime_dependency_map import build_dependency_map, clear_dependency_map_cache
from engine.runtime_health import build_runtime_health


def test_dependency_map_is_healthy_and_critical_path_active():
    clear_dependency_map_cache()
    payload = build_dependency_map()
    assert payload["ok"] is True
    assert payload["status"] == "HEALTHY"
    assert payload["schema_version"] in {"65.3", "65.4"}
    assert payload["summary"]["monday_critical_missing"] == []
    assert payload["summary"]["monday_critical_not_active"] == []
    assert payload["summary"]["engine_modules"] >= 300
    assert payload["architecture_hash"]


def test_dependency_map_has_classification_and_route_consumers():
    payload = build_dependency_map()
    classes = {row["classification"] for row in payload["engines"]}
    assert "ACTIVE" in classes
    assert "ORPHANED" in classes
    assert all("monday_critical" in row for row in payload["engines"])
    assert all("dashboard_consumers" in route for route in payload["routes"])


def test_closed_market_engine_aggregate_uses_standby_not_red():
    payload = build_runtime_health(
        version="test",
        route_audit={"status": "HEALTHY", "duplicate_route_count": 0, "critical_missing": [], "route_count": 1},
        scanner={"state": "CLOSED", "session": "CLOSED", "detail": "Market closed"},
        sources={},
        engine_health={"red": 14, "yellow": 0, "available": 0, "total": 14, "expected": False},
        trade_director={
            "market_memory": {"state": "HEALTHY"},
            "cross_asset_intelligence": {"state": "HEALTHY"},
            "strategy_orchestration": {"state": "HEALTHY"},
        },
        auth_layer_available=True,
    )
    engines = next(c for c in payload["components"] if c["name"] == "Institutional Engines")
    assert engines["state"] == "HEALTHY"
    assert engines["data"]["red"] == 0
    assert engines["data"]["standby"] == 14
    assert engines["data"]["raw_red"] == 14
    assert payload["runtime_ready"] is True
    assert payload["tradeable_runtime"] is False
