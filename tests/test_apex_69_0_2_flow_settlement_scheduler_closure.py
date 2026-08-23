import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from engine.flow_settlement_scheduler import FlowSettlementScheduler
from engine import flow_settlement_scheduler as S
from engine import historical_evidence_lifecycle as H

ET = ZoneInfo("America/New_York")


def test_release_identity_69_0_2():
    manifest = json.loads(Path("config/apex_release_manifest.json").read_text())
    assert tuple(map(int, manifest["apex_version"].split("."))) >= (69, 0, 2)
    assert isinstance(manifest.get("build_name"), str) and manifest["build_name"].strip()
    assert tuple(map(int, H.VERSION.split("."))) >= (69, 0, 2)
    assert H.SCHEMA_VERSION.startswith("apex.historical_evidence_lifecycle.v1.")
    assert "apex_version: 69." in Path("config/apex_capability_registry.yaml").read_text()


def test_scheduler_runs_immediately_and_exposes_reason_counts(monkeypatch):
    calls = []
    monkeypatch.setattr(S.feature_store_writer, "settle_pending_labels", lambda **kw: calls.append(kw) or {
        "state": "UNLABELLED_REMAINS", "sessions_checked": 20,
        "sessions_with_unlabelled": 20, "pending": 47, "labelled": 0,
        "missing_excursion_row": 47, "missing_mfe": 0, "write_failures": 0,
    })
    sched = FlowSettlementScheduler(interval_seconds=300, enabled=True)
    out = sched.run_if_due(now=dt.datetime(2026, 8, 23, 11, 30, tzinfo=ET), monotonic_now=100.0)
    assert len(calls) == 1
    assert calls[0]["before_session_date"] == "2026-08-23"
    assert out["runs"] == 1
    assert out["state"] == "COMPLETED"
    assert out["settlement_scope"] == "PRIOR_SESSIONS_ONLY"
    assert out["last_result"]["pending"] == 47
    assert out["last_result"]["missing_excursion_row"] == 47


def test_scheduler_cadence_prevents_duplicate_runs(monkeypatch):
    calls = []
    monkeypatch.setattr(S.feature_store_writer, "settle_pending_labels", lambda **kw: calls.append(kw) or {"state": "NO_PRIOR_UNLABELLED_SESSIONS", "labelled": 0})
    sched = FlowSettlementScheduler(interval_seconds=300, enabled=True)
    sched.run_if_due(now=dt.datetime(2026, 8, 23, 11, 30, tzinfo=ET), monotonic_now=100.0)
    out = sched.run_if_due(now=dt.datetime(2026, 8, 23, 11, 31, tzinfo=ET), monotonic_now=150.0)
    assert len(calls) == 1
    assert out["runs"] == 1
    assert out["cadence_skips"] == 1


def test_scheduler_includes_current_session_only_post_close(monkeypatch):
    calls = []
    monkeypatch.setattr(S.feature_store_writer, "settle_pending_labels", lambda **kw: calls.append(kw) or {"state": "NO_PRIOR_UNLABELLED_SESSIONS", "labelled": 0})
    sched = FlowSettlementScheduler(interval_seconds=300, enabled=True)
    out = sched.run_if_due(force=True, now=dt.datetime(2026, 8, 24, 16, 6, tzinfo=ET), monotonic_now=100.0)
    assert calls[0]["before_session_date"] == "2026-08-25"
    assert out["settlement_scope"] == "CURRENT_AND_PRIOR_POST_CLOSE"


def test_scanner_heartbeat_uses_scheduler_diagnostics_not_legacy_app_global():
    src = Path("scanner_worker.py").read_text()
    assert "FlowSettlementScheduler" in src
    assert "_FLOW_SETTLEMENT_SCHEDULER.run_if_due()" in src
    assert '"feature_label_settlement": _FLOW_SETTLEMENT_SCHEDULER.status()' in src
    assert 'getattr(apex_app, "_LAST_LABEL_SETTLE_RESULT", None)' not in src


def test_legacy_scanner_settlement_is_disabled_when_scheduler_enabled():
    src = Path("app.py").read_text()
    assert 'APEX_FLOW_SETTLEMENT_SCHEDULER_ENABLED' in src
    assert 'not in {"1", "true", "yes", "on"}' in src
