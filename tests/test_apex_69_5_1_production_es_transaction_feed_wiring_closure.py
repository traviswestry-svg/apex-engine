from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from engine.tick_momentum_feed import normalize_provider_results, poll_futures_trades
from engine.tick_momentum_store import TickMomentumStore

ROOT = Path(__file__).resolve().parents[1]


def _ns(dt: datetime) -> int:
    return int(dt.timestamp() * 1_000_000_000)


def _payload(rows):
    return {"status": "OK", "results": rows}


def test_release_truth_registers_production_trade_feed_without_authority():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    major, minor, patch = (int(x) for x in manifest["apex_version"].split("."))
    assert (major, minor, patch) >= (69, 5, 1)
    assert manifest["semantic_version"] == manifest["application_version"] == manifest["apex_version"]
    g = manifest["guardrails"]
    assert g["tick_momentum_production_es_transaction_feed_wired"] is True
    assert g["tick_momentum_feed_source"] == "MASSIVE_POLYGON_FUTURES_TRADES"
    assert g["tick_momentum_feed_aggregate_bars_allowed"] is False
    assert g["tick_momentum_feed_cursor_dedup_required"] is True
    assert g["tick_momentum_feed_failure_changes_trade_decisions"] is False
    assert g["tick_momentum_feed_failure_changes_execution_authority"] is False
    registry = (ROOT / "config/apex_capability_registry.yaml").read_text()
    assert "engine.tick_momentum_feed" in registry
    assert "/futures/v1/trades/{ticker}" in registry
    assert "aggregate_bars_allowed: false" in registry
    assert "owner: scanner_worker" in registry


def test_provider_normalization_accepts_individual_trades_and_rejects_aggregate_rows():
    now = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)
    rows = normalize_provider_results(_payload([
        {"ticker": "ESU6", "price": 6500.25, "size": 2, "timestamp": _ns(now), "sequence_number": 2},
        {"ticker": "ESU6", "open": 6500, "high": 6501, "low": 6499, "close": 6500.5, "window_start": _ns(now)},
    ]))
    assert len(rows) == 1
    assert rows[0]["price"] == 6500.25
    assert rows[0]["size"] == 2.0
    assert rows[0]["provider_timestamp_ns"] == _ns(now)


def test_bootstrap_live_provider_trades_feed_canonical_tick_state(tmp_path, monkeypatch):
    monkeypatch.setattr("engine.tick_momentum_feed.MAX_LIVE_LAG_SECONDS", 10**12)
    now = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)
    base_ns = _ns(now)
    response = _payload([
        {"ticker": "ESU6", "price": 6500 + i * 0.25, "size": 1, "timestamp": base_ns + i * 1_000_000, "sequence_number": i + 1}
        for i in range(233)
    ])
    calls = []
    def get_json(url, params=None, timeout=None):
        calls.append((url, dict(params or {})))
        return response
    store = TickMomentumStore(tmp_path / "tick.db")
    result = poll_futures_trades(get_json, base_url="https://api.polygon.io", api_key="k", ticker="ESU6", store=store)
    state = store.load_state("ES")
    assert result["status"] == "OBSERVING"
    assert result["transactions_accepted"] == 233
    assert state["transactions_seen"] == 233
    assert state["horizons"]["233"]["buckets_closed"] == 1
    assert state["feed"]["provider_timestamp_ns"] == base_ns + 232 * 1_000_000
    assert calls[0][0].endswith("/futures/v1/trades/ESU6")
    assert calls[0][1]["sort"] == "timestamp.desc"


def test_incremental_overlap_deduplicates_cursor_trade(tmp_path, monkeypatch):
    monkeypatch.setattr("engine.tick_momentum_feed.MAX_LIVE_LAG_SECONDS", 10**12)
    now = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)
    base_ns = _ns(now)
    store = TickMomentumStore(tmp_path / "tick.db")
    first = _payload([
        {"ticker": "ESU6", "price": 6500.0, "size": 1, "timestamp": base_ns, "sequence_number": 1},
        {"ticker": "ESU6", "price": 6500.25, "size": 1, "timestamp": base_ns + 1_000_000, "sequence_number": 2},
    ])
    second = _payload([
        {"ticker": "ESU6", "price": 6500.25, "size": 1, "timestamp": base_ns + 1_000_000, "sequence_number": 2},
        {"ticker": "ESU6", "price": 6500.50, "size": 1, "timestamp": base_ns + 2_000_000, "sequence_number": 3},
    ])
    responses = iter([first, second])
    calls = []
    def get_json(url, params=None, timeout=None):
        calls.append(dict(params or {}))
        return next(responses)
    r1 = poll_futures_trades(get_json, base_url="https://api.polygon.io", api_key="k", ticker="ESU6", store=store)
    r2 = poll_futures_trades(get_json, base_url="https://api.polygon.io", api_key="k", ticker="ESU6", store=store)
    assert r1["transactions_accepted"] == 2
    assert r2["transactions_accepted"] == 1
    assert store.load_state("ES")["transactions_seen"] == 3
    assert "timestamp.gte" in calls[1]


def test_stale_entitlement_is_observable_and_not_counted_as_live_tick_momentum(tmp_path):
    stale = datetime(2026, 8, 26, 14, 0, tzinfo=timezone.utc)
    response = _payload([
        {"ticker": "ESU6", "price": 6500.0, "size": 1, "timestamp": _ns(stale), "sequence_number": 1}
    ])
    store = TickMomentumStore(tmp_path / "tick.db")
    result = poll_futures_trades(lambda *a, **k: response, base_url="https://api.polygon.io", api_key="k", ticker="ESU6", store=store)
    state = store.load_state("ES")
    assert result["status"] == "STALE_TRANSACTION_FEED"
    assert result["transactions_accepted"] == 0
    assert state["transactions_seen"] == 0
    assert state["feed"]["provider_timestamp_ns"] == _ns(stale)
    assert state["feed"]["provider_lag_seconds"] > state["feed"]["max_live_lag_seconds"]


def test_scanner_owns_feed_and_aggregate_futures_bars_are_not_wired_as_ticks():
    scanner = (ROOT / "scanner_worker.py").read_text()
    app = (ROOT / "app.py").read_text()
    feed = (ROOT / "engine/tick_momentum_feed.py").read_text()
    assert "_poll_production_tick_momentum" in scanner
    assert "_poll_futures_trades(" in scanner
    assert "_resolve_polygon_futures_ticker(\"ES\")" in scanner
    assert "tick_momentum_feed" in scanner
    assert "/futures/v1/trades/{ticker}" in feed
    assert "STALE_TRANSACTION_FEED" in feed
    assert "_futures_fetch_bars" in app  # existing aggregate path remains separate
    assert "aggregate futures bars remain ineligible" in scanner.lower()
