import json
from pathlib import Path

from engine.live_active_level_publisher import (
    LiveActiveLevelPublisher,
    build_learning_replay_snapshot,
)
from engine.feature_store import frames_from_replay, resolve_frame_at_or_before


def test_release_truth_and_replay_guardrails():
    manifest = json.loads(Path("config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == manifest["semantic_version"] == manifest["application_version"] == "69.10.17"
    assert manifest["build_name"] == "Canonical Feature-to-Excursion Settlement Identity Closure"
    g = manifest["guardrails"]
    assert g["spx_learning_replay_frame_producer_enabled"] is True
    assert g["spx_learning_replay_reuses_live_active_level_provider_inputs"] is True
    assert g["spx_learning_replay_adds_provider_path"] is False
    assert g["spx_learning_replay_forward_only"] is True
    assert g["spx_learning_replay_future_frame_allowed"] is False
    assert g["spx_learning_replay_stale_frame_tolerance_relaxed"] is False
    assert g["spx_learning_replay_synthetic_context_allowed"] is False
    assert g["canonical_feature_persistence_requires_prior_replay_frame"] is True
    assert g["replay_frame_availability_changes_trade_decisions"] is False
    assert g["replay_frame_availability_changes_execution_authority"] is False

    registry = Path("config/apex_capability_registry.yaml").read_text()
    assert "apex_version: 69.10.17" in registry
    assert "decision_time_replay_frame_availability_closure:" in registry
    assert "no_future_frame_join" in registry
    assert "no_staleness_relaxation" in registry


def test_learning_replay_snapshot_reuses_observed_state_without_inference():
    snap = build_learning_replay_snapshot(
        canonical={"price": 6501.25, "poc": 6498.0, "gamma_regime": "POSITIVE", "vwap": None},
        flow={"stock_price": 6500.0, "call_wall": 6550.0, "put_wall": 6450.0, "bias": "BULLISH"},
        volume={"profile": {"levels": {"vah": 6510.0, "val": 6485.0}}},
    )
    assert snap["stock_price"] == 6501.25
    assert snap["poc"] == 6498.0
    assert snap["vah"] == 6510.0
    assert snap["val"] == 6485.0
    assert snap["call_wall"] == 6550.0
    assert snap["put_wall"] == 6450.0
    assert snap["flow_bias"] == "BULLISH"
    assert "vwap" not in snap
    assert "decision_state" not in snap  # never inferred from unavailable context


def test_publisher_records_forward_only_spx_learning_frame():
    class FakeApp:
        def __init__(self):
            self.calls = []
        def _record_replay_frame(self, ticker, snapshot):
            self.calls.append((ticker, dict(snapshot)))

    app = FakeApp()
    pub = LiveActiveLevelPublisher(app, symbol="SPX")
    out = pub._record_learning_replay_frame(
        canonical={"price": 6501.0, "gamma_regime": "POSITIVE"},
        flow={"call_wall": 6550.0}, volume={},
        observed_at="2026-09-11T15:27:00-04:00",
    )
    assert out["ok"] is True
    assert out["state"] == "RECORDED"
    assert app.calls[0][0] == "SPX"
    assert app.calls[0][1]["stock_price"] == 6501.0
    assert pub.learning_replay_frames_published == 1
    assert pub.last_learning_replay_frame_state == "RECORDED"


def test_empty_observed_context_fails_closed_without_frame():
    class FakeApp:
        def __init__(self): self.calls = []
        def _record_replay_frame(self, ticker, snapshot): self.calls.append((ticker, snapshot))

    app = FakeApp()
    pub = LiveActiveLevelPublisher(app, symbol="SPX")
    out = pub._record_learning_replay_frame(
        canonical={}, flow={}, volume={}, observed_at="2026-09-11T15:27:00-04:00")
    assert out["ok"] is False
    assert out["state"] == "NO_OBSERVED_CONTEXT"
    assert app.calls == []


def test_prior_frame_resolves_but_future_frame_is_rejected():
    frames = frames_from_replay([
        {"session_date": "2026-09-11", "frame_time": "15:18:30", "ticker": "SPX", "snapshot": {"stock_price": 6500}},
        {"session_date": "2026-09-11", "frame_time": "15:20:30", "ticker": "SPX", "snapshot": {"stock_price": 6502}},
    ])
    got = resolve_frame_at_or_before(
        frames, "2026-09-11T15:19:43", max_staleness_seconds=600)
    assert got is not None
    assert got["frame_time"] == "15:18:30"
    assert got["snapshot"]["stock_price"] == 6500


def test_app_runtime_exposes_replay_availability_without_relaxing_gate():
    src = Path("app.py").read_text()
    assert '"version": "69.10.6"' in src
    assert '"replay_frames_available": 0' in src
    assert '"last_replay_frame_at": None' in src
    assert '"PRE_PERSIST_REPLAY_FRAME_GATED"' in src
    writer = Path("engine/feature_store_writer.py").read_text()
    assert 'FEATURE_MAX_FRAME_STALENESS_S' in writer
    assert 'resolve_frame_at_or_before(' in writer
    assert 'built from stale or future state' in writer
