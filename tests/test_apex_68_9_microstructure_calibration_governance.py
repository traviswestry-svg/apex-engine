from datetime import datetime, timezone

from engine.market_microstructure_ingest import ingest
from engine.market_microstructure_store import MicrostructureStore
from engine.market_microstructure_calibration import calibration_report, integrity_report, promotion_readiness, shadow_confirmation


def _payload(ts, seq, *, bid_size=150, ask_size=50, buy=30, sell=5, price_change=0.5):
    return {
        "instrument": "ES", "source": "TEST_LICENSED_DEPTH", "feed_quality": "L2",
        "observed_at": ts, "sequence_id": str(seq), "tick_size": 0.25, "price_change": price_change,
        "book": {"bids": [[6499.75, bid_size], [6499.50, 50]], "asks": [[6500.0, ask_size], [6500.25, 50]]},
        "trades": [{"price": 6500.0, "size": buy, "aggressor_side": "BUY"}, {"price": 6499.75, "size": sell, "aggressor_side": "SELL"}],
    }


def test_outcome_calibration_uses_explicit_labels_only(tmp_path):
    store=MicrostructureStore(str(tmp_path/'m.sqlite3'),max_snapshots=100,max_age_minutes=100000)
    r=ingest(_payload("2026-08-23T13:30:00+00:00",1),store)
    assert calibration_report(store)["labeled_samples"] == 0
    store.record_outcome(r["persistence"]["row_id"], horizon_seconds=30, forward_move_ticks=4)
    out=calibration_report(store)
    assert out["labeled_samples"] == 1
    assert out["metrics"]["delta_direction"]["accuracy_pct"] == 100.0
    assert out["metrics"]["depth_imbalance_direction"]["accuracy_pct"] == 100.0


def test_integrity_detects_sequence_continuity(tmp_path):
    store=MicrostructureStore(str(tmp_path/'m.sqlite3'),max_snapshots=100,max_age_minutes=100000)
    ingest(_payload("2026-08-23T13:30:00+00:00",10),store)
    ingest(_payload("2026-08-23T13:30:01+00:00",11),store)
    out=integrity_report(store,max_age_seconds=999999999)
    assert out["timestamp_monotonic"] is True
    assert out["sequence"]["authoritative"] is True
    assert out["true_delta_coverage_pct"] == 100.0


def test_integrity_reports_sequence_gap_without_fabricating_authority(tmp_path):
    store=MicrostructureStore(str(tmp_path/'m.sqlite3'),max_snapshots=100,max_age_minutes=100000)
    ingest(_payload("2026-08-23T13:30:00+00:00",10),store)
    ingest(_payload("2026-08-23T13:30:01+00:00",13),store)
    out=integrity_report(store,max_age_seconds=999999999)
    assert out["sequence"]["authoritative"] is False
    assert out["sequence"]["gaps"] == 2


def test_promotion_readiness_never_applies_production_effect(tmp_path):
    store=MicrostructureStore(str(tmp_path/'m.sqlite3'),max_snapshots=100,max_age_minutes=100000)
    ids=[]
    for i in range(5):
        r=ingest(_payload(f"2026-08-23T13:30:0{i}+00:00",i+1),store); ids.append(r["persistence"]["row_id"])
    for row_id in ids:
        store.record_outcome(row_id,horizon_seconds=30,forward_move_ticks=4)
    out=promotion_readiness(store,min_labeled=5,min_accuracy_pct=55,min_coverage_pct=95)
    assert out["eligible_for_human_review"] is True
    assert out["production_promotion_applied"] is False
    assert out["governance"]["production_effect"] == "NONE"
    assert out["governance"]["influences_decision"] is False


def test_shadow_confirmation_is_never_live_decision_authority(tmp_path):
    store=MicrostructureStore(str(tmp_path/'m.sqlite3'),max_snapshots=100,max_age_minutes=100000)
    ingest(_payload("2026-08-23T13:30:00+00:00",1),store)
    out=shadow_confirmation(store.latest_analysis("ES"), calibration_report(store))
    assert out["eligible"] is True
    assert out["direction"] == "BULLISH"
    assert out["calibrated_for_production"] is False
    assert out["governance"]["influences_decision"] is False
