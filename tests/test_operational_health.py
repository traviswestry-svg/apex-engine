import datetime as dt

import app as apex_app


def test_health_timestamp_is_never_null(monkeypatch):
    monkeypatch.setattr(apex_app, "SCANNER_STARTED", True)
    with apex_app.STATE_LOCK:
        apex_app.STATE["updated_at"] = None
        apex_app.STATE["last_scan_duration_seconds"] = None
        apex_app.STATE["scanner_heartbeat_at"] = None
        apex_app.STATE["data_sources"] = {"polygon": True, "quantdata": False}
    body = apex_app.app.test_client().get("/health").get_json()
    assert body["updated_at"]
    assert body["updated_at_basis"] == "status_generated_at"
    assert body["status_generated_at"] == body["updated_at"]
    assert body["health_age_seconds"] == 0.0


def test_health_exposes_release_and_runtime_metadata(monkeypatch):
    monkeypatch.setenv("APEX_BUILD_ID", "build-health-test")
    monkeypatch.setenv("APEX_GIT_COMMIT", "abc123")
    monkeypatch.setenv("APEX_DEPLOYED_AT", "2026-07-19T12:00:00Z")
    body = apex_app.app.test_client().get("/health").get_json()
    assert body["deployment"]["build"] == "build-health-test"
    assert body["deployment"]["git_sha"] == "abc123"
    assert body["deployment"]["deployed_at"] == "2026-07-19T12:00:00Z"
    assert body["process_started_at"]
    assert body["process_uptime_seconds"] >= 0


def test_health_includes_memory_pressure(monkeypatch):
    pressure = {"severity": "NORMAL", "read_only": True}
    monkeypatch.setattr(apex_app, "memory_pressure_status", lambda: pressure)
    body = apex_app.app.test_client().get("/health").get_json()
    assert body["memory_pressure"] == pressure


def test_health_memory_diagnostics_report_prior_response(monkeypatch):
    attribution = apex_app.health_memory_attribution
    with attribution._LOCK:
        attribution._EVENTS.clear()
    phase = {"processes": []}
    monkeypatch.setattr(apex_app, "scanner_settlement_phase_memory_inspect", lambda: phase)
    monkeypatch.setattr(apex_app, "container_memory_limit_event_observe",
                        lambda **kwargs: {"phase_summary": kwargs["phase_summary"]})
    client = apex_app.app.test_client()
    first = client.get("/health").get_json()
    second = client.get("/health").get_json()
    assert first["health_response_memory_attribution"]["status"] == "NO_PRIOR_COMPLETED_REQUEST"
    assert second["health_response_memory_attribution"]["last_completed"]["response_bytes"] > 0
    assert first["container_memory_limit_event_investigation"]["phase_summary"] == phase
    assert "runtime_memory_investigation" in first


def test_health_memory_diagnostics_fail_open(monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(apex_app, "runtime_memory_investigation", unavailable)
    monkeypatch.setattr(apex_app, "scanner_settlement_phase_memory_inspect", unavailable)
    monkeypatch.setattr(apex_app, "container_memory_limit_event_observe", unavailable)
    monkeypatch.setattr(apex_app.health_memory_attribution, "begin", unavailable)
    response = apex_app.app.test_client().get("/health")
    assert response.status_code == 200
    body = response.get_json()
    for key in ("runtime_memory_investigation", "scanner_settlement_phase_memory_attribution",
                "container_memory_limit_event_investigation"):
        assert body[key]["status"] == "DIAGNOSTIC_UNAVAILABLE"


def test_health_memory_attribution_reports_previous_response(tmp_path, monkeypatch):
    from engine import health_response_memory_attribution as attribution

    monkeypatch.setenv("APEX_MEMORY_PAIR_PATH", str(tmp_path / "missing.jsonl"))
    with attribution._LOCK:
        attribution._EVENTS.clear()
    client = apex_app.app.test_client()
    first = client.get("/health")
    second = client.get("/health")
    assert first.status_code == second.status_code == 200
    assert first.get_json()["health_response_memory_attribution"]["last_completed"] is None
    body = second.get_json()
    assert body["health_response_memory_attribution"]["last_completed"]["response_bytes"] == len(first.data)
    assert body["runtime_memory_investigation"]["read_only"]
    assert body["scanner_settlement_phase_memory_attribution"]["status"] == "PHASE_TRACE_UNAVAILABLE"


def test_source_health_does_not_invent_latency():
    observed = apex_app._source_observability(
        {
            "polygon": True,
            "quantdata": {
                "available": True,
                "latency_ms": 84,
                "last_success_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            },
        },
        "2026-07-19T12:00:00+00:00",
    )
    assert observed["polygon"]["available"] is True
    assert observed["polygon"]["latency_ms"] is None
    assert observed["quantdata"]["latency_ms"] == 84
    assert observed["quantdata"]["last_success_age_seconds"] is not None


def test_last_scan_age_and_heartbeat_are_separate(monkeypatch):
    now = dt.datetime.now(dt.timezone.utc)
    scan_at = (now - dt.timedelta(seconds=45)).isoformat()
    heartbeat_at = (now - dt.timedelta(seconds=5)).isoformat()
    monkeypatch.setattr(apex_app, "SCANNER_STARTED", True)
    with apex_app.STATE_LOCK:
        apex_app.STATE["updated_at"] = scan_at
        apex_app.STATE["last_scan_duration_seconds"] = 2.5
        apex_app.STATE["scanner_heartbeat_at"] = heartbeat_at
        apex_app.STATE["scanner_thread_alive"] = True
    body = apex_app.app.test_client().get("/health").get_json()
    assert body["updated_at_basis"] == "last_completed_scan"
    assert body["last_scan_at"] == scan_at
    assert 40 <= body["last_scan_age_seconds"] <= 55
    assert 0 <= body["scanner_heartbeat_age_seconds"] <= 15
    assert body["scanner_thread_alive"] is True
