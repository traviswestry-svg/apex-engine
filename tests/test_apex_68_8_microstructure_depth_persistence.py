from engine.market_microstructure import capability_audit
from engine.market_microstructure_ingest import ingest, validate_observation, MicrostructureValidationError
from engine.market_microstructure_store import MicrostructureStore


def _payload(ts, bid=6499.75, bid_size=100, ask=6500.0, ask_size=100, buy=20, sell=10):
    trades = []
    if buy:
        trades.append({"price": ask, "size": buy, "aggressor_side": "BUY"})
    if sell:
        trades.append({"price": bid, "size": sell, "aggressor_side": "SELL"})
    return {
        "instrument": "ES",
        "source": "TEST_LICENSED_DEPTH",
        "feed_quality": "L2",
        "observed_at": ts,
        "tick_size": 0.25,
        "price_change": 0.0,
        "book": {
            "bids": [[bid, bid_size], [bid - 0.25, 50]],
            "asks": [[ask, ask_size], [ask + 0.25, 50]],
        },
        "trades": trades,
    }


def test_capability_exposes_depth_bridge_without_claiming_unconfigured_feed(monkeypatch):
    monkeypatch.delenv("MICROSTRUCTURE_FEED_PROVIDER", raising=False)
    monkeypatch.delenv("MICROSTRUCTURE_INGEST_ENABLED", raising=False)
    out = capability_audit()
    c = out["current_repository_capabilities"]
    assert c["normalized_depth_bridge"] is True
    assert c["bounded_liquidity_persistence"] is True
    assert c["resting_l2_depth"] is False
    assert out["status"] == "DEPTH_BRIDGE_CONFIG_REQUIRED"


def test_capability_marks_bridge_ready_only_when_provider_and_ingest_configured(monkeypatch):
    monkeypatch.setenv("MICROSTRUCTURE_FEED_PROVIDER", "licensed-test-feed")
    monkeypatch.setenv("MICROSTRUCTURE_INGEST_ENABLED", "true")
    out = capability_audit()
    assert out["status"] == "DEPTH_BRIDGE_READY"
    assert out["current_repository_capabilities"]["resting_l2_depth"] is True
    assert out["current_repository_capabilities"]["configured_depth_provider"] == "licensed-test-feed"


def test_aggregate_proxy_is_rejected_at_ingestion_boundary():
    bad = _payload("2026-08-23T13:30:00+00:00")
    bad["feed_quality"] = "AGGREGATE"
    try:
        validate_observation(bad)
        assert False, "expected validation error"
    except MicrostructureValidationError as exc:
        assert "L2 or MBO" in str(exc)


def test_ingest_attaches_prior_book_and_persists_liquidity_change(tmp_path):
    store = MicrostructureStore(str(tmp_path / "micro.sqlite3"), max_snapshots=100, max_age_minutes=100000)
    first = ingest(_payload("2026-08-23T13:30:00+00:00", bid_size=100, ask_size=100), store)
    second = ingest(_payload("2026-08-23T13:30:01+00:00", bid_size=140, ask_size=180), store)
    assert first["persistence"]["previous_book_attached"] is False
    assert second["persistence"]["previous_book_attached"] is True
    assert second["liquidity_change"]["available"] is True
    assert second["liquidity_change"]["bid"]["added_size"] == 40.0
    assert second["liquidity_change"]["ask"]["added_size"] == 80.0
    assert store.health("ES")["observations_present"] is True


def test_rolling_cvd_uses_only_aggressor_classified_trade_evidence(tmp_path):
    store = MicrostructureStore(str(tmp_path / "micro.sqlite3"), max_snapshots=100, max_age_minutes=100000)
    ingest(_payload("2026-08-23T13:30:00+00:00", buy=20, sell=10), store)
    ingest(_payload("2026-08-23T13:30:01+00:00", buy=5, sell=15), store)
    cvd = store.rolling_cvd("ES", limit=10)
    assert cvd["available"] is True
    assert cvd["authoritative_for_window"] is True
    assert cvd["cvd"] == 0.0
    assert len(cvd["points"]) == 2


def test_heatmap_reports_persistent_liquidity_levels(tmp_path):
    store = MicrostructureStore(str(tmp_path / "micro.sqlite3"), max_snapshots=100, max_age_minutes=100000)
    ingest(_payload("2026-08-23T13:30:00+00:00", bid_size=100, ask_size=100), store)
    ingest(_payload("2026-08-23T13:30:01+00:00", bid_size=120, ask_size=110), store)
    ingest(_payload("2026-08-23T13:30:02+00:00", bid_size=150, ask_size=130), store)
    heat = store.heatmap("ES", limit=10, min_persistence=0.5)
    target = [x for x in heat["levels"] if x["side"] == "ASK" and x["price"] == 6500.0]
    assert heat["available"] is True
    assert heat["snapshots"] == 3
    assert len(target) == 1
    assert target[0]["persistence"] == 1.0
    assert target[0]["max_size"] == 130.0


def test_store_is_bounded_by_snapshot_count(tmp_path):
    # implementation clamps lower bound to 100; insert 110 and verify pruning.
    store = MicrostructureStore(str(tmp_path / "micro.sqlite3"), max_snapshots=100, max_age_minutes=100000)
    for i in range(110):
        ingest(_payload(f"2026-08-23T13:{30 + (i // 60):02d}:{i % 60:02d}+00:00"), store)
    assert len(store.history("ES", limit=200)) == 100
