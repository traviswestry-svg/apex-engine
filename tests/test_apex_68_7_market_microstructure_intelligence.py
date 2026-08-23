from engine.market_microstructure import analyze, capability_audit


def test_capability_audit_is_truthful_about_current_aggregate_feed(monkeypatch):
    monkeypatch.setenv("POLYGON_API_KEY", "configured")
    out = capability_audit()
    c = out["current_repository_capabilities"]
    assert c["massive_polygon_futures_aggregate_bars"] is True
    assert c["massive_polygon_api_key_configured"] is True
    assert c["resting_l2_depth"] is False
    assert c["market_by_order_mbo"] is False
    assert c["true_cvd"] is False
    assert out["governance"]["execution_authority"] is False


def test_missing_depth_fails_visible_not_fabricated():
    out = analyze({"instrument": "ES", "source": "aggregate-bars-only"})
    assert out["status"] == "FEED_REQUIRED"
    assert out["book"]["l2_available"] is False
    assert out["book"]["bid_depth"] is None
    assert out["execution"]["delta"] is None
    assert out["microstructure_confirmation"]["score"] is None


def test_l2_delta_liquidity_change_and_absorption_candidate():
    out = analyze({
        "instrument": "ES",
        "source": "TEST_L2",
        "tick_size": 0.25,
        "price_change": 0.0,
        "previous_book": {
            "bids": [[6499.75, 100], [6499.50, 80]],
            "asks": [[6500.00, 100], [6500.25, 100]],
        },
        "book": {
            "bids": [[6499.75, 140], [6499.50, 80]],
            "asks": [[6500.00, 180], [6500.25, 80]],
        },
        "trades": [
            {"price": 6500.00, "size": 80, "aggressor_side": "BUY"},
            {"price": 6499.75, "size": 20, "aggressor_side": "SELL"},
        ],
    })
    assert out["status"] == "READY"
    assert out["book"]["depth_imbalance"] is not None
    assert out["liquidity_change"]["available"] is True
    assert out["liquidity_change"]["ask"]["added_size"] == 80.0
    assert out["liquidity_change"]["ask"]["pulled_size"] == 20.0
    assert out["execution"]["delta"] == 60.0
    assert out["interaction"]["absorption_candidate"]["detected"] is True
    assert out["interaction"]["absorption_candidate"]["side"] == "ASK_SELLER"


def test_iceberg_candidate_requires_repeated_replenishment_events():
    out = analyze({
        "book": {"bids": [[6499.75, 10]], "asks": [[6500, 10]]},
        "order_events": [
            {"action": "REPLENISH", "side": "ASK", "price": 6500, "order_id": "a"},
            {"action": "REPLENISH", "side": "ASK", "price": 6500, "order_id": "b"},
            {"action": "REPLENISH", "side": "ASK", "price": 6500, "order_id": "c"},
        ],
    })
    assert len(out["interaction"]["iceberg_candidates"]) == 1
    assert out["interaction"]["mbo_available"] is True
    assert out["interaction"]["iceberg_detection_authoritative"] is True
