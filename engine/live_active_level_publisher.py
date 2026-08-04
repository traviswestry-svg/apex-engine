"""APEX 66.1 — lightweight live publication into the 66.0 active-level registry.

This module intentionally does not generate a Morning Brief and does not own a
second level engine. It reuses the existing Daily Key Levels deterministic
adapters, extracts only mutable intraday kinds, and publishes them through the
66.0 canonical registry boundary.
"""
from __future__ import annotations

import datetime as dt
import time
import threading
from typing import Any, Dict, Mapping, Optional
from zoneinfo import ZoneInfo

from .canonical_session_context import LIVE_MUTABLE_LEVEL_KINDS, normalize_level_kind, publish_live_levels
from .daily_key_levels_adapters import build_daily_key_levels, intraday_time_to_close_frac

VERSION = "66.1.2_DYNAMIC_LEVEL_IDENTITY"
_ET = ZoneInfo("America/New_York")

PROFILE_KINDS = {"developing_poc", "vah", "val", "hvn", "lvn"}
LIQUIDITY_KINDS = {"swing_high", "swing_low", "fair_value_gap", "buyside_liquidity", "sellside_liquidity", "unfilled_gap"}
OPENING_KINDS = {"or5_high", "or5_low", "or15_high", "or15_low", "initial_balance_high", "initial_balance_low", "ib_extension"}
GAMMA_KINDS = {"gamma_flip", "zero_gamma", "call_wall", "put_wall", "high_gamma_strike", "low_gamma_strike", "volatility_trigger", "large_option_strike", "dealer_hedge_zone"}


class LiveActiveLevelPublisher:
    def __init__(self, app_module: Any, *, symbol: str = "SPX", interval_seconds: int = 60):
        self.app = app_module
        self.symbol = symbol.upper()
        self.interval_seconds = max(30, int(interval_seconds))
        self.last_run_monotonic = 0.0
        self.last_result: Dict[str, Any] = {}
        self.last_error: Optional[str] = None
        self.runs = 0
        self.successes = 0
        self.skips = 0
        self._daily_cache = {"at": 0.0, "rows": []}
        self._stop_event = threading.Event()
        self._thread = None
        self._run_lock = threading.Lock()


    def start(self) -> dict:
        if self._thread and self._thread.is_alive():
            return {"ok": True, "state": "ALREADY_RUNNING", "version": VERSION}
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="live-active-level-publisher", daemon=True)
        self._thread.start()
        return {"ok": True, "state": "STARTED", "version": VERSION}

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        # Publish immediately, then sleep in short increments so shutdown remains
        # responsive and scanner heartbeat supervision is never blocked.
        while not self._stop_event.is_set():
            self.publish_if_due(force=(self.runs == 0))
            self._stop_event.wait(5.0)

    def diagnostics(self) -> dict:
        return {
            "version": VERSION,
            "symbol": self.symbol,
            "interval_seconds": self.interval_seconds,
            "runs": self.runs,
            "successes": self.successes,
            "skips": self.skips,
            "last_error": self.last_error,
            "last_result": dict(self.last_result or {}),
            "thread_alive": bool(self._thread and self._thread.is_alive()),
        }

    def due(self) -> bool:
        return (time.monotonic() - self.last_run_monotonic) >= self.interval_seconds

    def _daily_bars(self):
        now = time.monotonic()
        if self._daily_cache["rows"] and now - float(self._daily_cache["at"] or 0.0) < 900:
            return list(self._daily_cache["rows"])
        rows = self.app.get_daily_bars(self.symbol, 260) or []
        self._daily_cache = {"at": now, "rows": list(rows)}
        return list(rows)

    def publish_if_due(self, *, force: bool = False) -> dict:
        if not force and not self.due():
            self.skips += 1
            return {"ok": True, "state": "NOT_DUE", "version": VERSION}
        return self.publish()

    def publish(self) -> dict:
        if not self._run_lock.acquire(blocking=False):
            return {"ok": True, "state": "PUBLISH_ALREADY_IN_PROGRESS", "version": VERSION}
        try:
            return self._publish_once()
        finally:
            self._run_lock.release()

    def _publish_once(self) -> dict:
        self.last_run_monotonic = time.monotonic()
        self.runs += 1
        now_et = dt.datetime.now(_ET)
        target_session = now_et.date().isoformat()
        try:
            # Intraday publication is intentionally bounded to the cash session.
            # Morning/overnight publications remain owned by the canonical brief.
            if now_et.weekday() >= 5 or not (dt.time(9, 30) <= now_et.time() <= dt.time(16, 5)):
                self.skips += 1
                self.last_result = {"ok": True, "state": "OUTSIDE_RTH", "target_session_date": target_session, "version": VERSION}
                return dict(self.last_result)

            flow = self.app.quantdata_flow_snapshot(self.symbol) or {}
            intraday = self.app.get_intraday_bars(self.symbol, multiplier=1, limit_days=1) or []
            volume = self.app._volume_profile_bundle(self.symbol, 1, 5) or {}
            canonical = self.app._morning_brief_market_state(flow, volume) or {}
            daily = self._daily_bars()

            live_profile_levels = ((volume.get("profile") or {}).get("levels") or {})
            vp_extra = dict(live_profile_levels)

            dkl = build_daily_key_levels(
                canonical_ms=canonical,
                flow_snapshot=flow,
                daily_bars=daily,
                intraday_1m_bars=intraday,
                overnight_bars=None,
                es_daily_bars=None,
                es_spot=None,
                straddle=None,
                iv=None,
                time_to_close_frac=intraday_time_to_close_frac(now_et),
                atr_val=self.app.atr(daily) if daily else None,
                adr_val=None,
                vp_extra=vp_extra,
            )
            payload = dkl.to_dict()
            levels = []
            for row in (payload.get("levels") or []):
                if not isinstance(row, Mapping):
                    continue
                if normalize_level_kind(row.get("kind")) in LIVE_MUTABLE_LEVEL_KINDS:
                    levels.append(row)

            published_kind_set = {normalize_level_kind(row.get("kind")) for row in levels}
            authoritative_kinds = set()
            if intraday:
                authoritative_kinds |= OPENING_KINDS | LIQUIDITY_KINDS
            if live_profile_levels:
                authoritative_kinds |= PROFILE_KINDS
            # Gamma providers can be partially populated. Only replace a gamma
            # kind when a real current value is present; absence is treated as
            # unavailable, not as proof that the level ceased to exist.
            authoritative_kinds |= (GAMMA_KINDS & published_kind_set)

            result = publish_live_levels(
                levels,
                symbol=self.symbol,
                target_session_date=target_session,
                observed_at=now_et.isoformat(),
                reference_spot=payload.get("spot"),
                mutable_kinds=LIVE_MUTABLE_LEVEL_KINDS,
                authoritative_kinds=authoritative_kinds,
                source="scanner_live_active_level_publisher",
                component_version=VERSION,
            )
            result["input_level_count"] = len(levels)
            result["provider_state"] = {
                "flow": bool(flow),
                "intraday_bars": len(intraday),
                "daily_bars": len(daily),
                "volume_profile": bool(volume),
            }
            self.last_result = dict(result)
            self.last_error = None if result.get("ok") else str(result.get("state") or "PUBLISH_FAILED")
            if result.get("ok"):
                self.successes += 1
            return result
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.last_result = {
                "ok": False,
                "state": "LIVE_LEVEL_PUBLICATION_ERROR",
                "error": self.last_error,
                "target_session_date": target_session,
                "version": VERSION,
            }
            return dict(self.last_result)
