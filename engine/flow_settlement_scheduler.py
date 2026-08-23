"""APEX 69.0.2 — scanner-owned flow label settlement scheduler.

Makes feature-label settlement an explicit, bounded responsibility of the
dedicated scanner process.  It creates no evidence, relaxes no label rule, and
has no decision or execution authority; it only retries settlement from already
persisted feature vectors and already persisted excursion evidence.
"""
from __future__ import annotations

import datetime as dt
import os
import threading
import time
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from . import feature_store_writer

VERSION = "69.0.2"
SCHEMA_VERSION = "apex.flow_settlement_scheduler.v1"
_ET = ZoneInfo("America/New_York")

_TRUE = {"1", "true", "yes", "on"}


class FlowSettlementScheduler:
    def __init__(self, *, ticker: str = "SPX", interval_seconds: Optional[int] = None,
                 max_sessions: Optional[int] = None, enabled: Optional[bool] = None) -> None:
        self.ticker = str(ticker or "SPX").upper()
        self.interval_seconds = max(60, int(interval_seconds or os.getenv("APEX_FLOW_SETTLEMENT_SECONDS", "300")))
        self.max_sessions = max(1, int(max_sessions or os.getenv("APEX_FLOW_SETTLEMENT_MAX_SESSIONS", "30")))
        if enabled is None:
            enabled = str(os.getenv("APEX_FLOW_SETTLEMENT_SCHEDULER_ENABLED", "true")).lower() in _TRUE
        self.enabled = bool(enabled)
        self._lock = threading.RLock()
        self._last_run_monotonic = 0.0
        self._status: Dict[str, Any] = {
            "ok": True,
            "version": VERSION,
            "schema_version": SCHEMA_VERSION,
            "state": "READY" if self.enabled else "DISABLED",
            "enabled": self.enabled,
            "owner": "scanner_process",
            "ticker": self.ticker,
            "interval_seconds": self.interval_seconds,
            "max_sessions": self.max_sessions,
            "runs": 0,
            "errors": 0,
            "cadence_skips": 0,
            "last_attempt_at": None,
            "last_success_at": None,
            "last_error": None,
            "last_result": None,
            "execution_authority": False,
            "changes_trade_decisions": False,
            "creates_synthetic_evidence": False,
            "relaxes_label_requirements": False,
        }

    @staticmethod
    def _cutoff(now_et: dt.datetime) -> tuple[str, str]:
        """Return exclusive session cutoff and scope.

        Before 16:05 ET (and on weekends), only sessions strictly before today
        are eligible.  After 16:05 ET on a weekday, today's session may also be
        retried by using tomorrow as the exclusive cutoff.  Settlement itself
        still refuses rows without persisted excursion evidence.
        """
        current = now_et.date()
        after_close = now_et.weekday() < 5 and (now_et.hour, now_et.minute) >= (16, 5)
        if after_close:
            return (current + dt.timedelta(days=1)).isoformat(), "CURRENT_AND_PRIOR_POST_CLOSE"
        return current.isoformat(), "PRIOR_SESSIONS_ONLY"

    def run_if_due(self, *, force: bool = False, now: Optional[dt.datetime] = None,
                   monotonic_now: Optional[float] = None) -> Dict[str, Any]:
        if not self.enabled:
            with self._lock:
                return dict(self._status)

        mono = time.monotonic() if monotonic_now is None else float(monotonic_now)
        with self._lock:
            if not force and self._last_run_monotonic and mono - self._last_run_monotonic < self.interval_seconds:
                self._status["cadence_skips"] = int(self._status.get("cadence_skips") or 0) + 1
                return dict(self._status)
            # Claim the cadence slot before I/O so concurrent callers cannot duplicate it.
            self._last_run_monotonic = mono
            self._status["runs"] = int(self._status.get("runs") or 0) + 1
            self._status["last_attempt_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            self._status["state"] = "RUNNING"

        local_now = now.astimezone(_ET) if now is not None and now.tzinfo else (now.replace(tzinfo=_ET) if now is not None else dt.datetime.now(_ET))
        cutoff, scope = self._cutoff(local_now)
        try:
            result = feature_store_writer.settle_pending_labels(
                before_session_date=cutoff,
                ticker=self.ticker,
                max_sessions=self.max_sessions,
            )
            with self._lock:
                self._status.update({
                    "ok": bool(result.get("state") != "ERROR"),
                    "state": "COMPLETED" if result.get("state") != "ERROR" else "ERROR",
                    "last_success_at": dt.datetime.now(dt.timezone.utc).isoformat() if result.get("state") != "ERROR" else self._status.get("last_success_at"),
                    "last_error": result.get("error"),
                    "last_result": result,
                    "settlement_scope": scope,
                    "eligible_session_cutoff_exclusive": cutoff,
                    "local_time_et": local_now.isoformat(),
                })
                if result.get("state") == "ERROR":
                    self._status["errors"] = int(self._status.get("errors") or 0) + 1
                return dict(self._status)
        except Exception as exc:  # defensive boundary; scanner must remain alive
            with self._lock:
                self._status["ok"] = False
                self._status["state"] = "ERROR"
                self._status["errors"] = int(self._status.get("errors") or 0) + 1
                self._status["last_error"] = f"{type(exc).__name__}: {exc}"
                self._status["settlement_scope"] = scope
                self._status["eligible_session_cutoff_exclusive"] = cutoff
                self._status["local_time_et"] = local_now.isoformat()
                return dict(self._status)

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._status)
