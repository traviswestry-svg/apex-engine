"""Dedicated scanner process for APEX 24.2.1.

Runs beside Gunicorn in the same Render service so both processes share the
mounted /data volume while the web process remains free of import-time jobs.

APEX 65.7.1: HLCE remains scanner-owned, but its provider no longer depends on
the web-only ``STATE['last_result']`` bus.  The provider prefers a valid local
canonical snapshot, then falls back to the durable morning/session level
context plus a lightweight live SPX index snapshot.  This closes the
cross-process ingestion gap without enabling a duplicate full IOS composition.
"""
from __future__ import annotations

import datetime as dt
import os
import signal
import time
from typing import Any, Dict, Mapping, Optional

os.environ["RUN_SCANNER_ON_IMPORT"] = "false"

import app as apex_app  # noqa: E402
from engine.operational_runtime import write_scanner_heartbeat  # noqa: E402
from engine.historical_level_calibration import (  # noqa: E402
    extract_context as hlce_extract_context,
    get_service as get_hlce_service,
)
from engine.canonical_session_context import latest as latest_canonical_context  # noqa: E402

_RUNNING = True
_HLCE_PROVIDER_CACHE: Dict[str, Any] = {"at": 0.0, "snapshot": {}}


def _stop(_signum, _frame):
    global _RUNNING
    _RUNNING = False


def _safe_positive(value: Any) -> Optional[float]:
    try:
        x = float(value)
        return x if x > 0 else None
    except (TypeError, ValueError):
        return None


def _live_spx_snapshot_price() -> Optional[float]:
    """Return a lightweight current SPX value from the existing Polygon client.

    Uses the same v3 indices snapshot family already used by APEX for VIX.  No
    execution or decision state is mutated here.  Returning ``None`` is safe:
    HLCE will truthfully drop the observation rather than fabricate a spot.
    """
    data = apex_app.safe_get_json(
        "https://api.polygon.io/v3/snapshot?ticker.any_of=I:SPX", timeout=10
    )
    for row in (data or {}).get("results") or []:
        session = row.get("session") if isinstance(row.get("session"), Mapping) else {}
        last_quote = row.get("last_quote") if isinstance(row.get("last_quote"), Mapping) else {}
        value = (
            session.get("close")
            or session.get("value")
            or row.get("value")
            or last_quote.get("price")
        )
        price = _safe_positive(value)
        if price is not None:
            return price
    return None


def _canonical_level_snapshot(spot: float) -> Dict[str, Any]:
    ctx = latest_canonical_context(apex_app.ASSISTANT_TICKER) or {}
    levels = ctx.get("levels") if isinstance(ctx.get("levels"), list) else []
    snapshot: Dict[str, Any] = {
        "ticker": apex_app.ASSISTANT_TICKER,
        "symbol": apex_app.ASSISTANT_TICKER,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "spot": spot,
        "market_state": {"price": spot},
        "canonical_levels": levels,
        "hlce_source": "scanner_durable_context_plus_live_spot",
        "canonical_context_target_session": ctx.get("target_session_date"),
        "canonical_context_generated_at": ctx.get("generated_at"),
    }
    # Promote common level kinds into the legacy fields as well. This keeps all
    # existing HLCE extractors/backward-compatible consumers working unchanged.
    for row in levels:
        if not isinstance(row, Mapping):
            continue
        kind = str(row.get("kind") or "").strip().lower()
        price = _safe_positive(row.get("price"))
        if price is None:
            continue
        if kind in {"expected_move_high", "expected_move_upper", "em_high"}:
            snapshot["expected_move_high"] = price
        elif kind in {"expected_move_low", "expected_move_lower", "em_low"}:
            snapshot["expected_move_low"] = price
    return snapshot


def _hlce_snapshot_provider() -> Dict[str, Any]:
    """Provide HLCE a real scanner-process snapshot without web-memory coupling."""
    local = dict(apex_app.STATE.get("last_result") or {})
    try:
        if hlce_extract_context(local).spot is not None:
            local["hlce_source"] = "scanner_local_canonical_snapshot"
            return local
    except Exception:
        pass

    # Keep provider traffic bounded if the collector cadence is configured below
    # 15 seconds. A cached snapshot is still a real observation; HLCE's own price
    # sample interval and timestamps govern persistence.
    now = time.monotonic()
    cache_seconds = max(5.0, float(os.getenv("APEX_HLCE_SPOT_CACHE_SECONDS", "10")))
    cached = _HLCE_PROVIDER_CACHE.get("snapshot") or {}
    if cached and now - float(_HLCE_PROVIDER_CACHE.get("at") or 0.0) < cache_seconds:
        return dict(cached)

    spot = _live_spx_snapshot_price()
    if spot is None:
        return {}
    snapshot = _canonical_level_snapshot(spot)
    _HLCE_PROVIDER_CACHE.update({"at": now, "snapshot": dict(snapshot)})
    return snapshot


def main() -> int:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    apex_app.start_background_scanner()
    # APEX 65.7/65.7.1: the dedicated scanner process is the single owner of
    # HLCE. Web/Gunicorn route registration never starts recurring collectors.
    try:
        get_hlce_service().start(_hlce_snapshot_provider)
    except Exception as exc:
        print(f"[HLCE] scanner-owned collector start failed (non-fatal): {exc}", flush=True)
    while _RUNNING:
        write_scanner_heartbeat({
            "scanner_started": bool(apex_app.SCANNER_STARTED),
            "thread_alive": bool(apex_app.STATE.get("scanner_thread_alive", False)),
            "last_scan_at": apex_app.SCANNER_STATE.get("updated_at"),
            "last_error": apex_app.STATE.get("last_error"),
            "hlce_collector_running": bool(get_hlce_service().collector_running()),
            "hlce_provider_source": (_HLCE_PROVIDER_CACHE.get("snapshot") or {}).get("hlce_source"),
            "hlce_db_path": str(get_hlce_service().path),
        })
        time.sleep(max(5, int(os.getenv("APEX_SCANNER_PROCESS_HEARTBEAT_SECONDS", "15"))))
    get_hlce_service().stop()
    write_scanner_heartbeat({"scanner_started": False, "stopped": True})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
