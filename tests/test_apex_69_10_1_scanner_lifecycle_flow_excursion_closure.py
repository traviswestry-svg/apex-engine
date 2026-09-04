import json
from pathlib import Path

from engine.scanner_runtime_truth import resolve_scanner_runtime

ROOT = Path(__file__).resolve().parents[1]


def test_version_truth_and_release_guardrails():
    manifest = json.loads((ROOT / "config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == "69.10.1"
    assert manifest["semantic_version"] == "69.10.1"
    assert manifest["application_version"] == "69.10.1"
    assert manifest["build_name"] == "Scanner Lifecycle & Flow Excursion Capture Closure"
    g = manifest["guardrails"]
    assert g["scanner_health_prefers_fresh_cross_process_heartbeat"] is True
    assert g["flow_excursion_capture_forward_only"] is True
    assert g["flow_excursion_historical_backfill_from_coarse_cluster_envelope"] is False
    assert g["flow_excursion_capture_creates_synthetic_evidence"] is False
    assert g["execution_authority"] is False
    assert g["behavioral_authority"] is False
    assert g["automatic_calibration_activation"] is False


def test_fresh_dedicated_scanner_heartbeat_is_authoritative():
    out = resolve_scanner_runtime(
        local_started=False, local_thread_alive=False,
        heartbeat={"available": True, "age_seconds": 4.0, "scanner_started": True,
                   "thread_alive": True, "phase": "RUNNING", "last_scan_at": "2026-09-04T15:23:11+00:00",
                   "updated_at": "2026-09-04T15:23:20+00:00"},
    )
    assert out["heartbeat_fresh"] is True
    assert out["effective_started"] is True
    assert out["effective_thread_alive"] is True
    assert out["source"] == "SCANNER_PROCESS_HEARTBEAT"
    assert out["process_last_scan_at"] is not None
    assert out["behavioral_authority"] is False
    assert out["execution_authority"] is False


def test_stale_heartbeat_fails_closed():
    out = resolve_scanner_runtime(
        local_started=False, local_thread_alive=False,
        heartbeat={"available": True, "age_seconds": 999.0, "scanner_started": True,
                   "thread_alive": True, "phase": "RUNNING"},
        stale_after_seconds=45,
    )
    assert out["heartbeat_fresh"] is False
    assert out["effective_started"] is False
    assert out["effective_thread_alive"] is False
    assert out["process_last_scan_at"] is None


def test_app_health_uses_effective_cross_process_state_by_construction():
    src = (ROOT / "app.py").read_text()
    assert "from engine.scanner_runtime_truth import resolve_scanner_runtime" in src
    assert 'scanner_started=bool(_scanner_runtime.get("effective_started"))' in src
    assert '"scanner_started": bool(_scanner_runtime.get("effective_started"))' in src
    assert '"scanner_state_source": _scanner_runtime.get("source")' in src
    assert 'or _scanner_runtime.get("process_last_scan_at")' in src
    assert 'else _scanner_runtime.get("heartbeat")' in src


def test_flow_learning_runtime_is_published_and_zero_attempt_is_explained():
    app_src = (ROOT / "app.py").read_text()
    worker_src = (ROOT / "scanner_worker.py").read_text()
    assert 'def flow_learning_runtime_status()' in app_src
    assert '"flow_learning_runtime": apex_app.flow_learning_runtime_status()' in worker_src
    for state in ["NO_SOURCE_CLUSTERS", "SESSION_GATED", "UNAVAILABLE",
                  "FEATURE_WRITER_UNAVAILABLE", "CAPTURE_ATTEMPTED", "WRITER_NO_CAPTURE_TARGET"]:
        assert state in app_src
    assert "defer_excursion_capture=False" in app_src


def test_no_historical_coarse_cluster_backfill_path_added():
    # flow_pl_cluster_tracking is session-wide and may contain observations that
    # predate a sample decision. It must remain lineage/diagnostic evidence only.
    store_src = (ROOT / "engine/flow_pl_store.py").read_text()
    assert "flow_pl_cluster_tracking" in store_src
    app_src = (ROOT / "app.py").read_text()
    scanner_slice = app_src[app_src.index("def scanner_loop"):app_src.index("def start_background_scanner")]
    assert "get_cluster_excursions" not in scanner_slice


def test_scanner_worker_publishes_real_scanner_and_flow_capture_state():
    src = (ROOT / "scanner_worker.py").read_text()
    assert '"scanner_started": bool(apex_app.SCANNER_STARTED)' in src
    assert '"thread_alive": bool(apex_app.STATE.get("scanner_thread_alive", False))' in src
    assert '"last_scan_at": apex_app.SCANNER_STATE.get("updated_at") or apex_app.STATE.get("updated_at")' in src
    assert '"flow_excursion_capture": _flow_pl_store.sample_excursion_health()' in src
