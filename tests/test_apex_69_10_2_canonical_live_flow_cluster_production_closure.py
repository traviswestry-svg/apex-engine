import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from engine.flow_tape import build_flow_tape
from engine.flow_classifier import classify_flow_events
from engine.flow_pl_pipeline import run_flow_pl

ROOT = Path(__file__).resolve().parents[1]


def _epoch_ms(local_iso: str) -> int:
    local = dt.datetime.fromisoformat(local_iso).replace(tzinfo=ZoneInfo("America/New_York"))
    return int(local.timestamp() * 1000)


def _raw(trade_time, *, side="ASK", strike=6500.0, premium=300000.0, size=100):
    return {
        "id": f"row-{trade_time}-{side}",
        "ticker": "SPX",
        "contractType": "CALL",
        "expirationDate": "2026-09-09",
        "strikePrice": strike,
        "premium": premium,
        "size": size,
        "optionPrice": 30.0,
        "stockPrice": 6501.0,
        "tradeSideCode": side,
        "tradeConsolidationType": "SWEEP",
        "tradeTime": trade_time,
    }


def test_quantdata_epoch_millisecond_trade_time_normalizes_to_et():
    tape = build_flow_tape([_raw(_epoch_ms("2026-09-09T10:01:12"))], ["SPX"])
    assert tape["status"] == "OK"
    assert tape["rows"][0]["time_et"] == "10:01:12"
    diag = tape["normalization_diagnostics"]
    assert diag["raw_rows"] == 1
    assert diag["normalized_rows"] == 1
    assert diag["invalid_trade_time"] == 0
    assert diag["trade_time_contract"] == "QUANTDATA_EPOCH_MILLISECONDS_TO_ET"


def test_invalid_provider_time_is_not_replaced_with_current_clock():
    tape = build_flow_tape([_raw("not-a-time")], ["SPX"])
    assert tape["rows"][0]["time_et"] is None
    assert tape["normalization_diagnostics"]["invalid_trade_time"] == 1
    events = classify_flow_events(tape["rows"])["events"]
    assert events[0]["timestamp"] is None
    assert any("Unparseable timestamp" in w for w in events[0]["warnings"])


def test_current_quantdata_trade_side_vocabulary_is_classified_without_alias_dependency():
    for side, expected_aggression in [("ASK", "BUY"), ("BID", "SELL"), ("MID_MARKET", "PASSIVE_MID")]:
        tape = build_flow_tape([_raw(_epoch_ms("2026-09-09T10:01:12"), side=side)], ["SPX"])
        event = classify_flow_events(tape["rows"])["events"][0]
        assert event["execution_aggression"] == expected_aggression


def test_epoch_ms_rows_reach_canonical_source_clusters():
    raw = [
        _raw(_epoch_ms("2026-09-09T10:01:12"), strike=6500.0),
        _raw(_epoch_ms("2026-09-09T10:01:13"), strike=6500.0),
    ]

    def tape_provider(tickers, min_premium):
        return build_flow_tape(raw, tickers, min_premium=min_premium)

    out = run_flow_pl(
        tickers=["SPX"],
        flow_tape_provider=tape_provider,
        chain_fetcher=None,
        last_result_provider=lambda: {"market_state": {"price": 6501.0}},
        default_ticker="SPX",
        track=False,
        attach_excursions=False,
    )
    assert out["available"] is True
    assert len(out["source_clusters"]) >= 1
    diag = out["source_diagnostics"]
    assert diag["raw_rows"] == 2
    assert diag["normalized_rows"] == 2
    assert diag["classified_events"] == 2
    assert diag["unclusterable"] == 0
    assert diag["reason"] == "SOURCE_CLUSTERS_AVAILABLE"


def test_release_truth_and_guardrails_69_10_2():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == manifest["semantic_version"] == manifest["application_version"] == "69.10.2"
    assert manifest["build_name"] == "Canonical Live Flow Cluster Production Closure"
    g = manifest["guardrails"]
    assert g["quantdata_order_flow_epoch_ms_normalized_to_et"] is True
    assert g["invalid_flow_trade_time_replaced_with_current_clock"] is False
    assert g["current_quantdata_trade_side_vocabulary_supported"] is True
    assert g["live_flow_source_cluster_stage_diagnostics"] is True
    assert g["synthetic_cluster_time_created"] is False
    assert g["flow_cluster_qualification_relaxed"] is False
    assert g["automatic_calibration_activation"] is False
    assert g["execution_authority"] is False
    assert g["behavioral_authority"] is False


def test_scanner_runtime_exposes_cluster_stage_diagnostics():
    src = (ROOT / "app.py").read_text()
    for key in ["raw_flow_rows", "normalized_flow_rows", "classified_flow_events",
                "unclusterable_flow_events", "invalid_trade_time", "last_source_diagnostics"]:
        assert f'"{key}"' in src
    for state in ["NO_NORMALIZED_FLOW_ROWS", "ALL_EVENTS_UNCLUSTERABLE", "NO_CLUSTER_OUTPUT",
                  "NO_CLASSIFIED_EVENTS", "NO_SOURCE_CLUSTERS"]:
        assert state in src
    assert "defer_excursion_capture=False" in src
