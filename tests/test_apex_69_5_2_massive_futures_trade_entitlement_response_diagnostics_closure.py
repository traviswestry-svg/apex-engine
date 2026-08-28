from __future__ import annotations

import json
from pathlib import Path

from engine.tick_momentum_feed import poll_futures_trades
from engine.tick_momentum_store import TickMomentumStore

ROOT = Path(__file__).resolve().parents[1]


def _envelope(status: int, *, payload=None, kind="JSON", content_type="application/json", message=None):
    return {
        "__apex_provider_response__": True,
        "payload": payload,
        "diagnostics": {
            "provider_http_status": status,
            "provider_content_type": content_type,
            "provider_response_bytes": 123,
            "provider_response_kind": kind,
            "provider_json_parse_error": None if payload is not None else "JSONDecodeError",
            "provider_error_code": str(status),
            "provider_error_message": message,
            "provider_request_host": "api.polygon.io",
        },
    }


def test_release_truth_registers_secret_safe_feed_diagnostics():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert tuple(map(int, manifest["apex_version"].split("."))) >= (69, 5, 2)
    assert manifest["semantic_version"] == manifest["application_version"] == manifest["apex_version"]
    g = manifest["guardrails"]
    assert g["tick_momentum_feed_http_diagnostics_exposed"] is True
    assert g["tick_momentum_feed_api_key_exposed"] is False
    assert g["tick_momentum_feed_explicit_credential_preserved"] is True
    assert g["tick_momentum_feed_entitlement_state_classified"] is True
    assert g["tick_momentum_feed_diagnostics_change_trade_decisions"] is False
    assert g["tick_momentum_feed_diagnostics_change_execution_authority"] is False


def test_403_is_classified_without_exposing_api_key(tmp_path):
    store = TickMomentumStore(tmp_path / "tick.db")
    result = poll_futures_trades(
        lambda *a, **k: _envelope(403, payload={"status": "ERROR", "error": "not entitled"}, message="not entitled"),
        base_url="https://api.polygon.io", api_key="SUPER_SECRET_KEY", ticker="ESU6",
        credential_source="MASSIVE_API_KEY", store=store,
    )
    assert result["status"] == "PROVIDER_UNAVAILABLE_OR_NOT_ENTITLED"
    assert result["provider_http_status"] == 403
    assert result["entitlement_state"] == "NOT_ENTITLED_OR_FORBIDDEN"
    assert result["credential_source"] == "MASSIVE_API_KEY"
    assert result["api_key_exposed"] is False
    assert "SUPER_SECRET_KEY" not in json.dumps(result)


def test_non_json_response_classifies_response_kind(tmp_path):
    store = TickMomentumStore(tmp_path / "tick.db")
    result = poll_futures_trades(
        lambda *a, **k: _envelope(200, payload=None, kind="HTML", content_type="text/html"),
        base_url="https://api.polygon.io", api_key="k", ticker="ESU6", store=store,
    )
    assert result["provider_http_status"] == 200
    assert result["provider_response_kind"] == "HTML"
    assert result["entitlement_state"] == "UNKNOWN"


def test_successful_json_access_is_classified(tmp_path):
    store = TickMomentumStore(tmp_path / "tick.db")
    result = poll_futures_trades(
        lambda *a, **k: _envelope(200, payload={"status":"OK", "results": []}),
        base_url="https://api.polygon.io", api_key="k", ticker="ESU6", store=store,
    )
    assert result["status"] == "NO_NEW_TRANSACTIONS"
    assert result["entitlement_state"] == "ACCESS_CONFIRMED"
    assert result["provider_http_status"] == 200


def test_explicit_api_key_is_not_clobbered_by_shared_polygon_helper():
    app_text = (ROOT / "app.py").read_text()
    assert 'params.setdefault("apiKey", POLYGON_API_KEY)' in app_text
    assert 'params["apiKey"] = POLYGON_API_KEY' not in app_text
    scanner = (ROOT / "scanner_worker.py").read_text()
    assert "safe_get_json_diagnostic" in scanner
    assert 'credential_source="MASSIVE_API_KEY" if massive_key else' in scanner


def test_diagnostic_transport_never_returns_query_or_key_material():
    app_text = (ROOT / "app.py").read_text()
    block = app_text.split("def safe_get_json_diagnostic", 1)[1].split("def safe_post_json", 1)[0]
    assert '"provider_request_host": host' in block
    assert '"apiKey"' not in block.split("return {", 1)[1]  # returned diagnostics do not carry key names
    assert "r.text" not in block  # response body is not persisted/exposed
