"""Dedicated scanner process for APEX 24.2.1.

Runs beside Gunicorn in the same Render service so both processes share the
mounted /data volume while the web process remains free of import-time jobs.

APEX 65.7.3: HLCE remains scanner-owned. Lifecycle supervision and provider fallbacks
ensure the scanner cannot appear healthy while calibration ingestion is dead. The
provider no longer depends on
the web-only ``STATE['last_result']`` bus.  The provider prefers a valid local
canonical snapshot, then falls back to the durable morning/session level
context plus a lightweight live SPX index snapshot.  This closes the
cross-process ingestion gap without enabling a duplicate full IOS composition.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo
import os
import signal
import time
from typing import Any, Dict, Mapping, Optional

os.environ["RUN_SCANNER_ON_IMPORT"] = "false"
# Mark this interpreter before app.py is imported. APEX 65.7.5 uses app.py as
# the unavoidable production bootstrap boundary; this marker prevents recursive
# scanner spawning when the dedicated scanner imports the legacy application.
os.environ["APEX_SCANNER_PROCESS"] = "true"

from engine.operational_runtime import write_scanner_heartbeat  # noqa: E402
from engine.pre23_hardening import acquire_scanner_lease  # noqa: E402
from engine.silent_degradation_observability import record_degradation  # noqa: E402

# APEX 65.7.3: take the process lease *before* importing the large application.
# This prevents duplicate scanner/HLCE owners even if both start_render.sh and
# a direct-Gunicorn WSGI fallback are accidentally active during deployment.
_PROCESS_LEASE = acquire_scanner_lease()
_APEX_IMPORT_ERROR = None
if _PROCESS_LEASE.get("acquired"):
    try:
        write_scanner_heartbeat({
            "scanner_started": False,
            "phase": "IMPORTING_APP",
            "bootstrap_source": os.getenv("APEX_SCANNER_BOOTSTRAP_SOURCE", "start_render"),
            "scanner_lease": _PROCESS_LEASE,
        })
    except Exception:
        pass
    try:
        import app as apex_app  # noqa: E402
    except Exception as exc:  # make import-time scanner failures observable
        _APEX_IMPORT_ERROR = exc
        try:
            write_scanner_heartbeat({
                "scanner_started": False,
                "phase": "APP_IMPORT_FAILED",
                "bootstrap_source": os.getenv("APEX_SCANNER_BOOTSTRAP_SOURCE", "start_render"),
                "startup_error": f"{type(exc).__name__}: {exc}",
            })
        finally:
            raise
else:
    apex_app = None  # type: ignore[assignment]

from engine.historical_level_calibration import (  # noqa: E402
    extract_context as hlce_extract_context,
    get_service as get_hlce_service,
)
from engine.canonical_session_context import latest as latest_canonical_context, active_levels as canonical_active_levels  # noqa: E402
from engine.live_active_level_publisher import LiveActiveLevelPublisher  # noqa: E402
from engine.historical_evidence_lifecycle import (  # noqa: E402
    sample_price as evidence_sample_price,
    grade as evidence_grade,
    runtime_status as evidence_runtime_status,
)

_RUNNING = True
_HLCE_PROVIDER_CACHE: Dict[str, Any] = {"at": 0.0, "snapshot": {}}
_HLCE_RUNTIME: Dict[str, Any] = {"provider_ok": False, "provider_error": None, "restart_count": 0, "last_tick": None}
_EVIDENCE_RUNTIME: Dict[str, Any] = {"last_grade_monotonic": 0.0, "last_price_result": None, "last_grade_result": None}
_LIVE_LEVEL_PUBLISHER = LiveActiveLevelPublisher(
    apex_app,
    symbol=getattr(apex_app, "ASSISTANT_TICKER", "SPX"),
    interval_seconds=int(os.getenv("APEX_LIVE_LEVEL_PUBLISH_SECONDS", "60")),
) if apex_app is not None else None


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
    """Return a current SPX value using two already-supported Polygon paths.

    65.7.1 used only the generic v3 snapshot endpoint.  Some Polygon plans can
    return an empty/partial index snapshot even while aggregate bars are live.
    Fall back to APEX's proven I:SPX intraday aggregate path before declaring
    the provider unavailable.  No synthetic/proxy price is fabricated.
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

    # Proven fallback: the dashboard/chart stack already consumes this exact
    # aggregate family for live SPX cash bars.  Keep the request bounded.
    try:
        bars = apex_app.get_intraday_bars(apex_app.ASSISTANT_TICKER, multiplier=1, limit_days=1)
        if bars:
            price = _safe_positive((bars[-1] or {}).get("c"))
            if price is not None:
                return price
    except Exception as exc:
        print(f"[HLCE] SPX aggregate fallback failed (non-fatal): {exc}", flush=True)
    return None


def _canonical_level_snapshot(spot: float) -> Dict[str, Any]:
    target_session = dt.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    ctx = latest_canonical_context(apex_app.ASSISTANT_TICKER, target_session_date=target_session) or {}
    registry_rows = canonical_active_levels(apex_app.ASSISTANT_TICKER, target_session_date=target_session)
    levels = []
    for row in registry_rows:
        levels.append({
            "canonical_level_id": row.get("canonical_level_id"),
            "kind": row.get("kind"),
            "price": row.get("price"),
            "source": row.get("source"),
            "instrument": row.get("instrument"),
            "normalized": bool(row.get("normalized")),
            "revision": row.get("revision"),
            "observed_at": row.get("observed_at"),
            "active": True,
        })
    if not levels:
        levels = ctx.get("levels") if isinstance(ctx.get("levels"), list) else []
    snapshot: Dict[str, Any] = {
        "ticker": apex_app.ASSISTANT_TICKER,
        "symbol": apex_app.ASSISTANT_TICKER,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "spot": spot,
        "market_state": {"price": spot},
        "canonical_levels": levels,
        "hlce_source": "scanner_durable_context_plus_live_spot",
        "canonical_context_target_session": ctx.get("target_session_date") or target_session,
        "canonical_context_generated_at": ctx.get("generated_at"),
        "active_level_registry_count": len(levels),
        "active_level_registry_source": "canonical_active_levels" if registry_rows else "canonical_session_context_fallback",
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
    except Exception as _collector_state_err:
        record_degradation(
            component="hlce_scanner_collector",
            operation="collector_state_update",
            exc=_collector_state_err,
            fallback="CONTINUE_WITH_PRIOR_COLLECTOR_STATE",
            decision_authority_suppressed=False,
            source="scanner_worker.py",
        )

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
        _HLCE_RUNTIME.update({"provider_ok": False, "provider_error": "LIVE_SPX_UNAVAILABLE"})
        return {}
    snapshot = _canonical_level_snapshot(spot)
    _HLCE_PROVIDER_CACHE.update({"at": now, "snapshot": dict(snapshot)})
    _HLCE_RUNTIME.update({"provider_ok": True, "provider_error": None})
    return snapshot


def _ensure_hlce_running() -> None:
    """Start/restart the scanner-owned collector and verify the provider once."""
    service = get_hlce_service()
    if service.collector_running():
        return
    result = service.start(_hlce_snapshot_provider) or {}
    if not service.collector_running():
        raise RuntimeError(f"HLCE collector failed to start: {result}")
    _HLCE_RUNTIME["restart_count"] = int(_HLCE_RUNTIME.get("restart_count") or 0) + 1

    # Run one synchronous evidence cycle at startup/recovery. This makes a
    # disconnected provider visible immediately instead of waiting for thread
    # cadence while still using the exact same Collector.observe path.
    snap = _hlce_snapshot_provider()
    if snap:
        tick = service.tick(snap)
        _HLCE_RUNTIME["last_tick"] = tick


def main() -> int:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    if not _PROCESS_LEASE.get("acquired"):
        # Another process is already the canonical scanner owner. Exiting here
        # is safe and avoids starting a second HLCE collector. Do not overwrite
        # the owner's heartbeat.
        print(
            f"APEX scanner standby: process lease unavailable ({_PROCESS_LEASE.get('reason')}); exiting duplicate worker.",
            flush=True,
        )
        return 0

    write_scanner_heartbeat({
        "scanner_started": False,
        "phase": "STARTING",
        "bootstrap_source": os.getenv("APEX_SCANNER_BOOTSTRAP_SOURCE", "start_render"),
        "scanner_lease": _PROCESS_LEASE,
    })
    apex_app.start_background_scanner()
    try:
        _ensure_hlce_running()
        if _LIVE_LEVEL_PUBLISHER is not None:
            _LIVE_LEVEL_PUBLISHER.start()
    except Exception as exc:
        # Lifecycle failure is fatal for the dedicated scanner process.
        # start_render.sh supervises this process and will restart the service
        # instead of allowing a web-only zombie deployment.
        print(f"[HLCE] scanner-owned collector startup failed: {exc}", flush=True)
        return 2

    while _RUNNING:
        try:
            _ensure_hlce_running()
        except Exception as exc:
            print(f"[HLCE] collector recovery failed: {exc}", flush=True)
            return 3

        # APEX 69.0 — feed the canonical decision evidence ledger from the same
        # real SPX observation source already trusted by HLCE. No proxy/synthetic
        # price is permitted. Grade matured rows on a bounded cadence.
        try:
            _evidence_snap = _hlce_snapshot_provider() or {}
            _evidence_spot = _safe_positive(
                _evidence_snap.get("spot")
                or (_evidence_snap.get("market_state") or {}).get("price")
            )
            if _evidence_spot is not None:
                _EVIDENCE_RUNTIME["last_price_result"] = evidence_sample_price(
                    getattr(apex_app, "ASSISTANT_TICKER", "SPX"), _evidence_spot
                )
            _grade_every = max(30, int(os.getenv("APEX_EVIDENCE_GRADER_SECONDS", "60")))
            _mono = time.monotonic()
            if _mono - float(_EVIDENCE_RUNTIME.get("last_grade_monotonic") or 0.0) >= _grade_every:
                _EVIDENCE_RUNTIME["last_grade_result"] = evidence_grade()
                _EVIDENCE_RUNTIME["last_grade_monotonic"] = _mono
        except Exception as exc:
            record_degradation(
                component="historical_evidence_lifecycle",
                operation="sample_and_grade", exc=exc,
                fallback="CONTINUE_SCANNER_WITHOUT_EVIDENCE_TICK",
                decision_authority_suppressed=False, source="scanner_worker.py",
            )

        service = get_hlce_service()
        db = service.status().get("database") or {}
        write_scanner_heartbeat({
            "scanner_started": bool(apex_app.SCANNER_STARTED),
            "phase": "RUNNING",
            "bootstrap_source": os.getenv("APEX_SCANNER_BOOTSTRAP_SOURCE", "start_render"),
            "scanner_lease": _PROCESS_LEASE,
            "thread_alive": bool(apex_app.STATE.get("scanner_thread_alive", False)),
            "last_scan_at": apex_app.SCANNER_STATE.get("updated_at") or apex_app.STATE.get("updated_at"),
            "last_error": apex_app.STATE.get("last_error"),
            "hlce_collector_running": bool(service.collector_running()),
            "hlce_provider_ok": bool(_HLCE_RUNTIME.get("provider_ok")),
            "hlce_provider_error": _HLCE_RUNTIME.get("provider_error"),
            "hlce_provider_source": (_HLCE_PROVIDER_CACHE.get("snapshot") or {}).get("hlce_source"),
            "hlce_db_path": str(service.path),
            "hlce_counts": db.get("counts") or {},
            "hlce_collector_stats": dict(service.collector.stats),
            "hlce_interaction_diagnostics": service.collector.interaction_diagnostics(),
            "hlce_last_event": service.collector.last_event,
            "hlce_last_database_write": service.collector.last_write_ts,
            "hlce_restart_count": int(_HLCE_RUNTIME.get("restart_count") or 0),
            "live_active_level_publisher": _LIVE_LEVEL_PUBLISHER.diagnostics() if _LIVE_LEVEL_PUBLISHER is not None else {"state": "UNAVAILABLE"},
            "historical_evidence_lifecycle": evidence_runtime_status(),
            "feature_label_settlement": getattr(apex_app, "_LAST_LABEL_SETTLE_RESULT", None),
        })
        time.sleep(max(5, int(os.getenv("APEX_SCANNER_PROCESS_HEARTBEAT_SECONDS", "15"))))
    if _LIVE_LEVEL_PUBLISHER is not None:
        _LIVE_LEVEL_PUBLISHER.stop()
    get_hlce_service().stop()
    write_scanner_heartbeat({"scanner_started": False, "stopped": True, "hlce_collector_running": False})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
