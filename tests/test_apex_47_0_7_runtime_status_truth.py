"""APEX 47.0.7 regression tests for backend release authority and status truth."""
import datetime as dt
import os
import pathlib
import re

from engine.release_manager import APP_VERSION, RELEASE_MANIFEST, release_metadata


def _resolver():
    source = pathlib.Path(__file__).resolve().parents[1].joinpath("app.py").read_text()
    match = re.search(r"def _resolve_health_state\(.*?\n(?=\n@app\.route)", source, re.S)
    namespace = {"os": os}
    exec("import datetime\n" + match.group(0), namespace)
    return namespace["_resolve_health_state"]


def test_canonical_manifest_controls_backend_version():
    assert RELEASE_MANIFEST["apex_version"] == "47.0.7"
    assert APP_VERSION == "47.0.7"
    payload = release_metadata()
    assert payload["apex_version"] == "47.0.7"
    assert payload["application_version"] == "47.0.7"
    assert payload["version_source"] == "config/apex_release_manifest.json"
    assert payload["legacy_application_version"] == "25.1.1_DECISION_QUALITY"


def test_closed_scanner_is_scheduled_idle_not_degraded():
    resolve = _resolver()
    now = dt.datetime(2026, 7, 26, 18, 0, tzinfo=dt.timezone.utc)
    result = resolve(
        session="CLOSED",
        scan_in_progress=False,
        updated_at=None,
        last_scan_duration=None,
        scanner_started=False,
        now=now,
    )
    assert result["state"] == "CLOSED"
    assert result["scanner_expected"] is False
    assert result["scanner_state"] == "SCHEDULED_IDLE"


def test_live_missing_scanner_remains_degraded():
    resolve = _resolver()
    now = dt.datetime(2026, 7, 27, 14, 0, tzinfo=dt.timezone.utc)
    result = resolve(
        session="MARKET_OPEN",
        scan_in_progress=False,
        updated_at=None,
        last_scan_duration=None,
        scanner_started=False,
        now=now,
    )
    assert result["state"] == "DEGRADED"
    assert result["scanner_expected"] is True
    assert result["scanner_state"] == "NOT_STARTED"
