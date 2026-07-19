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
