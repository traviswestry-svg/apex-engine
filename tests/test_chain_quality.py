import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.chain_quality import evaluate_chain_quality
from engine.options.options_data_bus import OptionsDataBus


def _c(strike, bid, ask, *, side="CALL", age=2, volume=100, oi=500, delta=.5):
    mid = None if bid is None or ask is None else (bid + ask) / 2
    spread = None if not mid else (ask - bid) / mid * 100
    return {"strike": strike, "side": side, "bid": bid, "ask": ask, "mid": mid,
            "spread_pct": spread, "quote_age_seconds": age, "volume": volume,
            "open_interest": oi, "delta": delta}


def test_high_quality_chain_passes():
    q = evaluate_chain_quality([_c(6000, 12, 12.2), _c(6005, 9, 9.2), _c(6010, 6, 6.2)])
    assert q["gate_passed"] is True
    assert q["grade"] == "HIGH"
    assert q["score"] >= 85


def test_crossed_and_missing_quotes_fail_gate():
    q = evaluate_chain_quality([_c(6000, 12, 11), _c(6005, None, 9), _c(6010, 6, 6.2)])
    assert q["gate_passed"] is False
    assert q["crossed_quote_count"] == 1
    assert q["missing_quote_count"] == 1


def test_stale_wide_chain_is_degraded():
    q = evaluate_chain_quality([_c(6000, 10, 14, age=60), _c(6005, 7, 11, age=60)])
    assert q["gate_passed"] is False
    assert q["stale_quote_count"] == 2
    assert q["wide_spread_count"] == 2


def test_call_vertical_shape_violation_detected():
    q = evaluate_chain_quality([_c(6000, 4, 4.2), _c(6005, 6, 6.2)])
    assert q["shape_violation_count"] == 1


def test_put_vertical_shape_violation_detected():
    q = evaluate_chain_quality([_c(6000, 6, 6.2, side="PUT"), _c(6005, 4, 4.2, side="PUT")])
    assert q["shape_violation_count"] == 1


def test_empty_chain_is_unavailable_not_zero_quality_claim():
    q = evaluate_chain_quality([])
    assert q["available"] is False
    assert q["grade"] == "UNAVAILABLE"


def test_options_bus_attaches_quality_lineage():
    bus = OptionsDataBus()
    bus.register("fixture", lambda symbol, exp, side: [
        {"strike": 6000, "side": side, "bid": 10, "ask": 10.2, "volume": 100,
         "open_interest": 500, "quote_age_seconds": 2, "greeks": {"delta": .5}},
        {"strike": 6005, "side": side, "bid": 8, "ask": 8.2, "volume": 100,
         "open_interest": 500, "quote_age_seconds": 2, "greeks": {"delta": .45}},
    ])
    out = bus.get_chain("SPX", "2026-07-17", "CALL")
    assert out["chain_quality"]["gate_passed"] is True
    assert out["chain_quality"]["valid_contract_count"] == 2


def test_polygon_nanosecond_timestamp_is_extracted_relative_to_fetch_time():
    import datetime as dt
    from engine.options.options_data_bus import normalize_contract
    now = dt.datetime(2026, 7, 17, 14, 30, 10, tzinfo=dt.timezone.utc)
    ts_ns = int(dt.datetime(2026, 7, 17, 14, 30, 5, tzinfo=dt.timezone.utc).timestamp() * 1e9)
    c = normalize_contract({
        "strike": 6000, "side": "CALL", "bid": 10, "ask": 10.2,
        "last_updated": ts_ns,
    }, now=now)
    assert c is not None
    assert c.quote_age_seconds == 5.0


def test_missing_timestamps_are_unmeasurable_and_do_not_score_as_fresh():
    rows = [_c(6000, 10, 10.2), _c(6005, 8, 8.2)]
    for row in rows:
        row.pop("quote_age_seconds")
    q = evaluate_chain_quality(rows)
    assert q["fresh_quote_pct"] is None
    assert q["freshness_unavailable_reason"]
    assert "freshness" in q["unmeasurable_components"]
    assert q["score_confidence_pct"] == 80.0
    assert q["gate_passed"] is False


def test_locked_quotes_reduce_score_and_fully_locked_chain_fails():
    normal = evaluate_chain_quality([_c(6000, 10, 10.2), _c(6005, 8, 8.2)])
    locked = evaluate_chain_quality([_c(6000, 10, 10), _c(6005, 8, 8)])
    assert locked["locked_quote_count"] == 2
    assert locked["unlocked_quote_pct"] == 0.0
    assert locked["score"] < normal["score"]
    assert locked["gate_passed"] is False
