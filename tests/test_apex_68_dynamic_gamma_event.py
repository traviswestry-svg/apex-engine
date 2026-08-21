from datetime import datetime
from zoneinfo import ZoneInfo

from engine.event_calendar import event_phase_at
from engine.flow_excitation import build_flow_excitation
from engine.gamma import _build_gamma_path, _build_gamma_term_structure

ET = ZoneInfo("America/New_York")


def test_event_phase_segments_release_lifecycle():
    pre = event_phase_at(datetime(2026, 9, 16, 13, 57, tzinfo=ET))
    release = event_phase_at(datetime(2026, 9, 16, 14, 0, 30, tzinfo=ET))
    post = event_phase_at(datetime(2026, 9, 16, 14, 10, tzinfo=ET))
    assert pre["phase"] == "RELEASE"
    assert release["phase"] == "RELEASE"
    assert post["phase"] == "PRICE_DISCOVERY"
    assert pre["boundary_id"] == post["boundary_id"]


def test_flow_burst_is_split_across_event_release_boundary():
    rows = [
        {"ticker":"SPX", "side":"BUY", "option_type":"CALL", "strike":7500,
         "timestamp":"2026-09-16T13:59:00-04:00"},
        {"ticker":"SPX", "side":"BUY", "option_type":"CALL", "strike":7500,
         "timestamp":"2026-09-16T14:03:00-04:00"},
    ]
    out = build_flow_excitation(rows, now=datetime(2026, 9, 16, 14, 3, tzinfo=ET), burst_gap_seconds=600)
    assert out["burst_count"] == 2
    assert out["independent_evidence_factor"] == 1.0


def test_gamma_path_has_version_and_snapshot_metadata():
    curve = {7400:{"net":-5}, 7450:{"net":10}, 7500:{"net":20}}
    out = _build_gamma_path(curve, 7440, active_flip=7450, call_wall=7500,
                            put_wall=7400, high_gamma=7500, low_gamma=7400)
    assert out["path_version"]
    assert out["level_version"]
    assert out["generated_at"] == out["source_snapshot_at"]


def test_gamma_term_structure_detects_forward_divergence():
    curves = {
        "2026-08-21": {7400:{"call":10,"put":0,"net":10}},
        "2026-08-24": {7400:{"call":0,"put":-10,"net":-10}},
    }
    out = _build_gamma_term_structure(curves, 7400, as_of=datetime(2026,8,21).date())
    assert out["zero_dte_dominance"] is True
    assert out["term_divergence"] is True
    assert out["near_term_fragility"] is True
