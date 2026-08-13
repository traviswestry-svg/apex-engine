"""Tests for the runtime health-state resolver (Tier 1, item 4)."""
import datetime as dt
import os, re, pathlib

# Extract the pure resolver from app.py without importing the whole Flask app.
_SRC = pathlib.Path(__file__).resolve().parents[1].joinpath("app.py").read_text()
_M = re.search(r'def _resolve_health_state\(.*?\n(?=\n@app\.route)', _SRC, re.S)
_NS = {"os": os}
exec("import datetime\n" + _M.group(0), _NS)
resolve = _NS["_resolve_health_state"]

NOW = dt.datetime(2026, 7, 12, 12, 0, 0, tzinfo=dt.timezone.utc)
RECENT = (NOW - dt.timedelta(seconds=30)).isoformat()
OLD = (NOW - dt.timedelta(seconds=600)).isoformat()


def _r(**kw):
    return resolve(now=NOW, **kw)["state"]


def test_closed_with_prior_scan_is_closed():
    assert _r(session="OVERNIGHT", scan_in_progress=False, updated_at=OLD,
              last_scan_duration=3.0, scanner_started=True) == "CLOSED"


def test_live_fresh_is_healthy():
    assert _r(session="MARKET_OPEN", scan_in_progress=False, updated_at=RECENT,
              last_scan_duration=3.0, scanner_started=True) == "HEALTHY"


def test_live_stale_is_stale():
    assert _r(session="MARKET_OPEN", scan_in_progress=False, updated_at=OLD,
              last_scan_duration=3.0, scanner_started=True) == "STALE"


def test_live_no_scan_yet_is_warming():
    assert _r(session="MARKET_OPEN", scan_in_progress=True, updated_at=None,
              last_scan_duration=None, scanner_started=True) == "WARMING"


def test_scanner_not_started_is_degraded():
    assert _r(session="MARKET_OPEN", scan_in_progress=False, updated_at=None,
              last_scan_duration=None, scanner_started=False) == "DEGRADED"


def test_closed_cold_start_is_closed_not_warming():
    assert _r(session="OVERNIGHT", scan_in_progress=False, updated_at=None,
              last_scan_duration=None, scanner_started=True) == "CLOSED"
