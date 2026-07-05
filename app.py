from __future__ import annotations

import datetime as dt
import os
import time
import threading
import sqlite3
import statistics
import json
import math
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, jsonify, render_template, request, redirect

# APEX Institutional OS 6.0.1 modular engines
try:
    from engine.gamma import build_gamma_from_quantdata_response, normalize_index_level_v6
    from engine.data_bus import build_market_state as build_market_state_v6
    from engine.volume_profile import build_volume_profile
    from engine.auction import build_auction_state
    APEX_OS_601_AVAILABLE = True
except Exception as _apex601_import_error:
    build_gamma_from_quantdata_response = None
    normalize_index_level_v6 = None
    build_market_state_v6 = None
    build_volume_profile = None
    build_auction_state = None
    APEX_OS_601_AVAILABLE = False
    print(f"APEX 6.0.1 engines unavailable: {_apex601_import_error}", flush=True)

# APEX 6.3.2 — Flow Tape Engine
try:
    from engine.flow_tape import build_flow_tape
    FLOW_TAPE_AVAILABLE = True
except Exception as _ft_err:
    build_flow_tape = None  # type: ignore[assignment]
    FLOW_TAPE_AVAILABLE = False
    print(f"APEX 6.3.2 flow tape engine unavailable: {_ft_err}", flush=True)

# APEX 6.3.4 / 6.3.5 — Story Engine 3.0, Trade Coach 3.0
try:
    from engine.story import build_story_v3
    from engine.trade_coach import build_trade_coach_v3
    STORY_COACH_V3_AVAILABLE = True
except Exception as _sc_err:
    build_story_v3 = None  # type: ignore[assignment]
    build_trade_coach_v3 = None  # type: ignore[assignment]
    STORY_COACH_V3_AVAILABLE = False
    print(f"APEX 6.3.4/6.3.5 story/coach v3 unavailable: {_sc_err}", flush=True)

# APEX 6.4.1 — Canonical Market State
try:
    from engine.market_state import build_canonical_market_state
    CANONICAL_MARKET_STATE_AVAILABLE = True
except Exception as _cms_err:
    build_canonical_market_state = None  # type: ignore[assignment]
    CANONICAL_MARKET_STATE_AVAILABLE = False
    print(f"APEX 6.4.1 canonical market state unavailable: {_cms_err}", flush=True)

# APEX Overnight Game Plan Engine
try:
    from engine.overnight import build_overnight_game_plan
    OVERNIGHT_ENGINE_AVAILABLE = True
except Exception as _on_err:
    build_overnight_game_plan = None  # type: ignore[assignment]
    OVERNIGHT_ENGINE_AVAILABLE = False
    print(f"APEX overnight engine unavailable: {_on_err}", flush=True)

# APEX Auction Intelligence Suite
try:
    from engine.auction_intelligence import build_auction_intelligence
    AUCTION_INTEL_AVAILABLE = True
except Exception as _ai_err:
    build_auction_intelligence = None  # type: ignore[assignment]
    AUCTION_INTEL_AVAILABLE = False
    print(f"APEX auction intelligence unavailable: {_ai_err}", flush=True)

# APEX 6.5 — Dealer Positioning Engine
try:
    from engine.dealer_positioning import build_dealer_positioning
    DEALER_POSITIONING_AVAILABLE = True
except Exception as _dp_err:
    build_dealer_positioning = None  # type: ignore[assignment]
    DEALER_POSITIONING_AVAILABLE = False
    print(f"APEX dealer positioning unavailable: {_dp_err}", flush=True)

# APEX 6.5 — Flow Intelligence 2.0
try:
    from engine.flow_intelligence import build_flow_intelligence_2
    FLOW_INTEL_2_AVAILABLE = True
except Exception as _fi2_err:
    build_flow_intelligence_2 = None  # type: ignore[assignment]
    FLOW_INTEL_2_AVAILABLE = False
    print(f"APEX flow intelligence 2.0 unavailable: {_fi2_err}", flush=True)

# APEX 6.5 — Institutional Playbook
try:
    from engine.playbook import build_institutional_playbook
    PLAYBOOK_AVAILABLE = True
except Exception as _pb_err:
    build_institutional_playbook = None  # type: ignore[assignment]
    PLAYBOOK_AVAILABLE = False
    print(f"APEX institutional playbook unavailable: {_pb_err}", flush=True)

# APEX 6.5 — Options Chain Intelligence
try:
    from engine.options_chain import build_options_chain_intelligence
    OPTIONS_CHAIN_AVAILABLE = True
except Exception as _oc_err:
    build_options_chain_intelligence = None  # type: ignore[assignment]
    OPTIONS_CHAIN_AVAILABLE = False
    print(f"APEX options chain unavailable: {_oc_err}", flush=True)

# APEX 6.5 — Volatility Intelligence
try:
    from engine.volatility import build_volatility_intelligence
    VOLATILITY_AVAILABLE = True
except Exception as _vi_err:
    build_volatility_intelligence = None  # type: ignore[assignment]
    VOLATILITY_AVAILABLE = False
    print(f"APEX volatility intelligence unavailable: {_vi_err}", flush=True)

# APEX 6.5 — Market Rotation Engine
try:
    from engine.rotation import build_rotation_intelligence
    ROTATION_AVAILABLE = True
except Exception as _rot_err:
    build_rotation_intelligence = None  # type: ignore[assignment]
    ROTATION_AVAILABLE = False
    print(f"APEX rotation engine unavailable: {_rot_err}", flush=True)

# APEX 6.5 — Institutional Intelligence (canonical master object)
try:
    from engine.institutional_intelligence import build_institutional_intelligence
    INST_INTEL_AVAILABLE = True
except Exception as _ii_err:
    build_institutional_intelligence = None  # type: ignore[assignment]
    INST_INTEL_AVAILABLE = False
    print(f"APEX institutional intelligence unavailable: {_ii_err}", flush=True)

# APEX 8.0 — Execution Intelligence Engine
try:
    from engine.execution_intelligence import build_execution_intelligence
    EIE_AVAILABLE = True
except Exception as _eie_err:
    build_execution_intelligence = None  # type: ignore[assignment]
    EIE_AVAILABLE = False
    print(f"APEX execution intelligence unavailable: {_eie_err}", flush=True)

# APEX 7.0 — Market Drivers Engine
try:
    from engine.market_drivers import build_market_drivers
    MARKET_DRIVERS_AVAILABLE = True
except Exception as _md_err:
    build_market_drivers = None  # type: ignore[assignment]
    MARKET_DRIVERS_AVAILABLE = False
    print(f"APEX market drivers unavailable: {_md_err}", flush=True)

# APEX 7.0 — Strike Magnet Engine
try:
    from engine.strike_magnet import build_strike_magnets
    STRIKE_MAGNET_AVAILABLE = True
except Exception as _sm_err:
    build_strike_magnets = None  # type: ignore[assignment]
    STRIKE_MAGNET_AVAILABLE = False
    print(f"APEX strike magnets unavailable: {_sm_err}", flush=True)

# APEX 4.5 nine-engine decision support system
try:
    from apex_engines import build_institutional_decision as _build_institutional_decision
    APEX_ENGINES_AVAILABLE = True
except ImportError:
    _build_institutional_decision = None
    APEX_ENGINES_AVAILABLE = False
    print("apex_engines.py not found — nine-engine pipeline disabled. Deploy apex_engines.py alongside app.py.", flush=True)

# APEX 8.0 — Active Trade Director (continuous state-aware trade management)
try:
    from engine.director.routes import register_director_routes
    from engine.director import DIRECTOR_VERSION
    ACTIVE_TRADE_DIRECTOR_AVAILABLE = True
except Exception as _atd_err:
    register_director_routes = None  # type: ignore[assignment]
    DIRECTOR_VERSION = "unavailable"
    ACTIVE_TRADE_DIRECTOR_AVAILABLE = False
    print(f"APEX Active Trade Director unavailable (non-fatal): {_atd_err}", flush=True)

VERSION = "7.0.1_APEX_EIGHT_FOUNDATION"
EASTERN = ZoneInfo("America/New_York")

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "").strip()
QUANTDATA_API_KEY = os.getenv("QUANTDATA_API_KEY", "").strip()
QUANTDATA_BASE_URL = os.getenv("QUANTDATA_BASE_URL", "https://api.quantdata.us/v1").rstrip("/")
BENZINGA_API_KEY = os.getenv("BENZINGA_API_KEY", "").strip()
# If Benzinga is subscribed through Massive/Polygon, do not call api.benzinga.com directly.
# Valid values: "massive"/"polygon" or "direct". Default keeps production quiet.
BENZINGA_SOURCE = os.getenv("BENZINGA_SOURCE", "massive").strip().lower()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "tv_institutional_signal").strip()
SIGNAL_TTL_SECONDS = int(os.getenv("SIGNAL_TTL_SECONDS", "360"))
ASSISTANT_TICKER = os.getenv("ASSISTANT_TICKER", "SPX").strip().upper()
ASSISTANT_SIGNAL_VALID_SECONDS = int(os.getenv("ASSISTANT_SIGNAL_VALID_SECONDS", str(SIGNAL_TTL_SECONDS)))
ASSISTANT_DEFAULT_RISK_POINTS = float(os.getenv("ASSISTANT_DEFAULT_RISK_POINTS", "6"))
ASSISTANT_TARGET1_R_MULT = float(os.getenv("ASSISTANT_TARGET1_R_MULT", "1.2"))
ASSISTANT_TARGET2_R_MULT = float(os.getenv("ASSISTANT_TARGET2_R_MULT", "2.0"))
ASSISTANT_STRIKE_STEP_SPX = int(os.getenv("ASSISTANT_STRIKE_STEP_SPX", "5"))
ASSISTANT_STRIKE_STEP_ETF = int(os.getenv("ASSISTANT_STRIKE_STEP_ETF", "1"))

ACCOUNT_SIZE = float(os.getenv("ACCOUNT_SIZE", "60000"))
MAX_RISK_PER_TRADE = float(os.getenv("MAX_RISK_PER_TRADE", "750"))
SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))
MIN_FINAL_SCORE = float(os.getenv("MIN_FINAL_SCORE", "78"))
MIN_ALERT_SCORE = float(os.getenv("MIN_ALERT_SCORE", "85"))
PREBREAKOUT_DISTANCE_PCT = float(os.getenv("PREBREAKOUT_DISTANCE_PCT", "2.0"))
MIN_ACCUMULATION_SCORE = float(os.getenv("MIN_ACCUMULATION_SCORE", "68"))
DARK_POOL_ENDPOINT_ENABLED = os.getenv("DARK_POOL_ENDPOINT_ENABLED", "true").lower() == "true"
ORDER_FLOW_ENABLED = os.getenv("ORDER_FLOW_ENABLED", "true").lower() == "true"
DARK_POOL_LEVELS_ENABLED = os.getenv("DARK_POOL_LEVELS_ENABLED", "true").lower() == "true"
DARK_POOL_LEVELS_LOOKBACK_DAYS = int(os.getenv("DARK_POOL_LEVELS_LOOKBACK_DAYS", "10"))
QUANTDATA_NEWS_ENABLED = os.getenv("QUANTDATA_NEWS_ENABLED", "true").lower() == "true"
FLOW_DASHBOARD_TICKERS = [x.strip().upper() for x in os.getenv("FLOW_DASHBOARD_TICKERS", "SPY,QQQ,SPX").split(",") if x.strip()]
GEX_ENABLED = os.getenv("GEX_ENABLED", "true").lower() == "true"
MASSIVE_API_KEY = os.getenv("MASSIVE_API_KEY", POLYGON_API_KEY).strip()
MASSIVE_BASE_URL = os.getenv("MASSIVE_BASE_URL", "https://api.polygon.io").rstrip("/")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "15"))
SEND_TELEGRAM = os.getenv("SEND_TELEGRAM", "true").lower() == "true"
RUN_SCANNER_ON_IMPORT = os.getenv("RUN_SCANNER_ON_IMPORT", "false").lower() == "true"
SCAN_WORKERS = int(os.getenv("SCAN_WORKERS", "8"))
BREAKER_MAX_FAILURES = int(os.getenv("BREAKER_MAX_FAILURES", "3"))
DB_PATH = os.getenv("DB_PATH", "apex_tracking.db")  # set to /data/apex_tracking.db on Render with a mounted disk
TRACKING_ENABLED = os.getenv("TRACKING_ENABLED", "true").lower() == "true"
TRACK_MAX_HOLD_DAYS = int(os.getenv("TRACK_MAX_HOLD_DAYS", "30"))  # mark unresolved trades EXPIRED after this many trading days
TRACK_MIN_SAMPLE = int(os.getenv("TRACK_MIN_SAMPLE", "10"))  # minimum resolved trades in a bucket before stats are shown

CORE_TICKERS = [
    "SPY", "QQQ", "NVDA", "TSLA", "META", "MSFT", "AAPL", "AMZN", "COIN", "AMD",
    "NFLX", "PLTR", "SMH", "QCOM", "AVGO", "MU", "CRM", "SHOP", "SNOW", "ARM", "ANET", "NET"
]
STATIC_TICKERS_EXTRA = [x.strip().upper() for x in os.getenv("STATIC_TICKERS_EXTRA", "").split(",") if x.strip()]
DYNAMIC_TICKERS_ENABLED = os.getenv("DYNAMIC_TICKERS_ENABLED", "true").lower() == "true"
MAX_DYNAMIC_TICKERS = int(os.getenv("MAX_DYNAMIC_TICKERS", "25"))

app = Flask(__name__)

@app.after_request
def add_no_cache_headers(response):
    """Keep Render/browser from serving stale dashboard JS/HTML during rapid APEX releases."""
    try:
        path = request.path or ""
        if path.startswith(("/api/", "/apex_os", "/chart", "/scanner", "/health")) or path == "/":
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
    except Exception:
        pass
    return response
SENT_ALERTS: set[str] = set()
SENT_ALERTS_LOCK = threading.Lock()
STATE_LOCK = threading.RLock()
SCAN_LOCK = threading.Lock()
SCANNER_START_LOCK = threading.Lock()
SCANNER_STARTED = False
TRADE_ASSISTANT_LOCK = threading.RLock()

# SCANNER_STATE: persists auction intelligence context across scan cycles.
# Tracks POC history, bar-level acceptance counters, signal log, and
# last valid ICI for carry-forward during early-session warm-up.
SCANNER_STATE: Dict[str, Any] = {
    "updated_at":             None,
    "last_scan_duration_seconds": None,
    "scan_in_progress":       False,
    "signal_log":             [],
    "last_valid_ici":         {},
    "bars_above_vah":         0,
    "bars_below_val":         0,
    "bars_above_poc":         0,
    "bars_below_poc":         0,
    "_bar_day":               None,
    # EIE history buffers (rolling 10-cycle window)
    "flow_history":           [],   # net_premium per scan cycle
    "delta_score_history":    [],   # ICI score per scan cycle
    "exec_score_history":     [],   # execution probability per cycle
}

TRADE_ASSISTANT_STATE: Dict[str, Any] = {
    "state": "WAITING",
    "message": "Waiting for Flow/GEX snapshot and Pine trigger",
    "last_signal": None,
    "last_decision": None,
    "updated_at": None,
    "updated_at_et": None,
}

# ---------------------------------------------------------------------------
# APEX 6.1.1 server-side confidence timeline
# Keeps an intraday memory of ICI/decision snapshots for replay/review.
# ---------------------------------------------------------------------------
CONFIDENCE_TIMELINE_LOCK = threading.RLock()
CONFIDENCE_TIMELINE_MAX_POINTS = int(os.getenv("CONFIDENCE_TIMELINE_MAX_POINTS", "240"))
CONFIDENCE_TIMELINE: Dict[str, List[Dict[str, Any]]] = {}


def _safe_confidence_value(result: Dict[str, Any]) -> float:
    ici_obj = result.get("ici") if isinstance(result.get("ici"), dict) else {}
    return round(safe_float(ici_obj.get("ici") or result.get("confidence") or result.get("confidence_pct"), 0.0), 1)


def _record_confidence_timeline_point(ticker: str, result: Dict[str, Any]) -> None:
    """Record a compact confidence/decision snapshot.

    This is intentionally server-side so the timeline survives page refreshes
    and can become the source for replay/review without relying on browser state.
    Duplicate consecutive points are skipped unless confidence, decision, price,
    or flow materially changes.
    """
    if not isinstance(result, dict):
        return
    t = (ticker or result.get("ticker") or ASSISTANT_TICKER or "SPX").upper()
    now_utc = dt.datetime.now(dt.timezone.utc)
    now_local = now_et()
    ribbon = result.get("ribbon") if isinstance(result.get("ribbon"), dict) else {}
    flow = result.get("flow") if isinstance(result.get("flow"), dict) else {}
    gamma = result.get("gamma_regime") if isinstance(result.get("gamma_regime"), dict) else {}
    ici_obj = result.get("ici") if isinstance(result.get("ici"), dict) else {}
    consensus = result.get("consensus") if isinstance(result.get("consensus"), dict) else {}
    execution = result.get("execution") if isinstance(result.get("execution"), dict) else {}
    point = {
        "ticker": t,
        "time": now_local.strftime("%H:%M:%S"),
        "time_et": now_local.strftime("%Y-%m-%d %H:%M:%S ET"),
        "timestamp": now_utc.isoformat(),
        "ici": _safe_confidence_value(result),
        "grade": result.get("grade"),
        "state": result.get("decision_state") or (result.get("decision") or {}).get("state") or result.get("recommendation") or "NO_TRADE",
        "recommendation": result.get("recommendation"),
        "readiness": result.get("readiness"),
        "price": ribbon.get("spx_price") or flow.get("stock_price"),
        "net_flow": ribbon.get("net_flow") or flow.get("net_premium"),
        "flow_momentum": ribbon.get("flow_momentum") or flow.get("flow_momentum"),
        "gamma_regime": gamma.get("regime_display") or gamma.get("regime_label"),
        "zero_gamma": ribbon.get("zero_gamma") or gamma.get("zero_gamma"),
        "consensus_direction": consensus.get("consensus_direction"),
        "signal_fresh": execution.get("signal_fresh"),
        "session": (result.get("session") or {}).get("session_state") or session_status(),
    }
    with CONFIDENCE_TIMELINE_LOCK:
        rows = CONFIDENCE_TIMELINE.setdefault(t, [])
        last = rows[-1] if rows else None
        if last:
            same_state = last.get("state") == point.get("state")
            same_ici = abs(safe_float(last.get("ici"), 0) - safe_float(point.get("ici"), 0)) < 0.2
            same_price = abs(safe_float(last.get("price"), 0) - safe_float(point.get("price"), 0)) < 0.05
            same_flow = abs(safe_float(last.get("net_flow"), 0) - safe_float(point.get("net_flow"), 0)) < 1000
            if same_state and same_ici and same_price and same_flow:
                return
        rows.append(point)
        if len(rows) > CONFIDENCE_TIMELINE_MAX_POINTS:
            del rows[:-CONFIDENCE_TIMELINE_MAX_POINTS]


def _confidence_timeline_payload(ticker: str) -> Dict[str, Any]:
    t = (ticker or ASSISTANT_TICKER or "SPX").upper()
    with CONFIDENCE_TIMELINE_LOCK:
        points = list(CONFIDENCE_TIMELINE.get(t, []))
    return {
        "ok": True,
        "version": VERSION,
        "ticker": t,
        "count": len(points),
        "points": points,
        "latest": points[-1] if points else None,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "updated_at_et": now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
    }


class CircuitBreaker:
    """Per-endpoint failure tracking so one dead/slow API can't stall an entire scan.

    Resets at the start of every scan cycle (transient outages get retried next
    cycle), but once an endpoint fails BREAKER_MAX_FAILURES times within the
    current cycle, further calls to it are skipped instantly (return neutral
    defaults) instead of burning a full network timeout per remaining ticker.
    """

    def __init__(self, max_failures: int = 3):
        self._lock = threading.Lock()
        self._max_failures = max_failures
        self._failures: Dict[str, int] = {}
        self._skipped: Dict[str, int] = {}

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()
            self._skipped.clear()

    def is_open(self, name: str) -> bool:
        with self._lock:
            return self._failures.get(name, 0) >= self._max_failures

    def record_failure(self, name: str) -> None:
        with self._lock:
            self._failures[name] = self._failures.get(name, 0) + 1

    def record_success(self, name: str) -> None:
        with self._lock:
            self._failures[name] = 0

    def record_skip(self, name: str) -> None:
        with self._lock:
            self._skipped[name] = self._skipped.get(name, 0) + 1

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "open_circuits": [n for n, c in self._failures.items() if c >= self._max_failures],
                "failure_counts": dict(self._failures),
                "skipped_calls": dict(self._skipped),
            }


BREAKER = CircuitBreaker(max_failures=BREAKER_MAX_FAILURES)

STATE: Dict[str, Any] = {
    "mode": VERSION,
    "updated_at": None,
    "updated_at_et": None,
    "session": "STARTING",
    "ideas": [],
    "scan_debug": [],
    "last_scan_status": f"Starting APEX {VERSION} scanner...",
    "last_error": None,
    "scan_in_progress": False,
    "scan_started_at": None,
    "last_scan_duration_seconds": None,
    "circuit_breaker": {"open_circuits": [], "failure_counts": {}, "skipped_calls": {}},
    "data_sources": {
        "polygon": bool(POLYGON_API_KEY),
        "quantdata": bool(QUANTDATA_API_KEY),
        "benzinga": bool(BENZINGA_API_KEY),
        "telegram": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
    },
}


def now_et() -> dt.datetime:
    return dt.datetime.now(EASTERN)


# NYSE/Nasdaq full-day closures. Equity options (SPX/SPXW) do not trade on these
# days, so there is no live options flow — the dashboard must read CLOSED, not
# AFTER_HOURS. Keyed by ISO date. Update annually.
US_MARKET_HOLIDAYS = frozenset({
    # 2026
    "2026-01-01",  # New Year's Day
    "2026-01-19",  # Martin Luther King Jr. Day
    "2026-02-16",  # Washington's Birthday (Presidents' Day)
    "2026-04-03",  # Good Friday
    "2026-05-25",  # Memorial Day
    "2026-06-19",  # Juneteenth
    "2026-07-03",  # Independence Day (observed — July 4 is a Saturday)
    "2026-09-07",  # Labor Day
    "2026-11-26",  # Thanksgiving Day
    "2026-12-25",  # Christmas Day
    # 2027
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
    "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
})


def is_market_holiday(n: Optional[dt.datetime] = None) -> bool:
    """True if the given ET datetime falls on a full-day US equity market holiday."""
    n = n or now_et()
    return n.strftime("%Y-%m-%d") in US_MARKET_HOLIDAYS


def session_status() -> str:
    """Returns the current market session state string.

    States:
      MARKET_OPEN     — RTH 9:30–16:00 ET, Mon–Fri (non-holiday)
      PREMARKET       — 4:00–9:30 ET, Mon–Fri (non-holiday)
      AFTER_HOURS     — 16:00–18:00 ET, Mon–Fri (ES still trading)
      OVERNIGHT       — 18:00 ET Mon–Fri through 4:00 ET next day, or Sun 18:00+
      CLOSED          — Saturday, Sunday before 18:00 ET, or a market holiday
    """
    n = now_et()
    wd = n.weekday()       # 0=Mon … 6=Sun
    minutes = n.hour * 60 + n.minute

    # Full-day market holiday — no equity/options session regardless of weekday
    if is_market_holiday(n):
        return "CLOSED"

    # Saturday — fully closed
    if wd == 5:
        return "CLOSED"

    # Sunday — ES opens at 18:00 ET
    if wd == 6:
        return "OVERNIGHT" if minutes >= 18 * 60 else "CLOSED"

    # Weekdays
    if 9 * 60 + 30 <= minutes < 16 * 60:
        return "MARKET_OPEN"
    if 4 * 60 <= minutes < 9 * 60 + 30:
        return "PREMARKET"
    if 16 * 60 <= minutes < 18 * 60:
        return "AFTER_HOURS"
    # 18:00 ET through midnight / 00:00–04:00 ET next day
    return "OVERNIGHT"


def _next_rth_open() -> str:
    """Return the next RTH open time as a human-readable string."""
    n = now_et()
    wd = n.weekday()
    minutes = n.hour * 60 + n.minute
    open_min = 9 * 60 + 30

    # If today is a weekday and we haven't opened yet
    if wd < 5 and minutes < open_min:
        mins_left = open_min - minutes
        if mins_left < 60:
            return f"Today 9:30 AM ET (~{mins_left}m)"
        return f"Today 9:30 AM ET (~{mins_left // 60}h {mins_left % 60}m)"

    # Find next weekday
    days_ahead = 1
    while True:
        next_wd = (wd + days_ahead) % 7
        if next_wd < 5:  # Mon–Fri
            if days_ahead == 1:
                return "Tomorrow 9:30 AM ET"
            day_name = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][next_wd]
            return f"{day_name} 9:30 AM ET"
        days_ahead += 1
        if days_ahead > 7:
            return "Monday 9:30 AM ET"


def system_mode(session: Optional[str] = None) -> Dict[str, Any]:
    """Canonical operator-facing system mode.

    Collapses the internal session states into four labels a trader can trust at
    a glance, each with a plain-English message and whether live SPX options flow
    is expected. This is the single source of truth for the header pill and the
    server-rendered status banner (so the first paint is meaningful before JS).

      LIVE      — RTH open. Live SPX options flow.
      PRE-RTH   — Pre-market on a trading day. Building next-session game plan.
      OVERNIGHT — Post-close / futures session. Cash closed, ES trading.
      CLOSED    — Weekend or market holiday. No session imminent.
    """
    session = session or session_status()
    next_open = _next_rth_open()

    if session == "MARKET_OPEN":
        mode, flow_live = "LIVE", True
        title = "LIVE — RTH SESSION"
        message = "Live SPX options flow. Real-time institutional read."
    elif session == "PREMARKET":
        mode, flow_live = "PRE-RTH", False
        title = "PRE-RTH — PRE-MARKET"
        message = ("Pre-market. Building the next-session game plan. "
                   "No live SPX options flow yet.")
    elif session in ("AFTER_HOURS", "OVERNIGHT"):
        mode, flow_live = "OVERNIGHT", False
        title = "OVERNIGHT — REVIEW MODE"
        message = ("Cash market closed, ES futures trading. No live SPX options "
                   "flow. Showing last profile and next-session game plan.")
    else:  # CLOSED
        mode, flow_live = "CLOSED", False
        holiday = is_market_holiday()
        title = "CLOSED — MARKET HOLIDAY" if holiday else "CLOSED — WEEKEND"
        message = ("Market closed" + (" for the holiday" if holiday else "") +
                   ". No live SPX options flow. Showing last profile and "
                   "next-session game plan.")

    return {
        "mode":       mode,               # LIVE | PRE-RTH | OVERNIGHT | CLOSED
        "session":    session,            # underlying internal session state
        "flow_live":  flow_live,          # is live SPX options flow expected?
        "title":      title,
        "message":    message,
        "next_rth":   next_open,
        "pill_class": "sess-open" if mode == "LIVE" else (
                      "sess-closed" if mode == "CLOSED" else "sess-pre"),
        "is_holiday": is_market_holiday(),
    }


def _build_market_status_panel(session: str) -> Dict[str, Any]:
    """Build the market status panel dict for the API and UI banner."""
    n = now_et()
    minutes = n.hour * 60 + n.minute
    wd = n.weekday()

    # ES futures: open Sun 18:00 – Fri 17:00 ET (with brief maintenance)
    es_open = session in ("MARKET_OPEN", "PREMARKET", "AFTER_HOURS", "OVERNIGHT")

    # SPX cash: RTH only
    spx_open = session == "MARKET_OPEN"

    # Options flow: available during RTH and shortly after
    flow_status = (
        "LIVE"     if spx_open else
        "LIMITED"  if session in ("PREMARKET", "AFTER_HOURS") else
        "OVERNIGHT" if session == "OVERNIGHT" else
        "CLOSED"
    )

    # Scanner mode
    scanner_mode = (
        "Live Scan"        if spx_open else
        "Pre-Session Prep" if session == "PREMARKET" else
        "Overnight Monitor" if session == "OVERNIGHT" else
        "Historical Mode"
    )

    # Story engine mode
    story_mode = (
        "Live Analysis"        if spx_open else
        "Pre-Session Analysis" if session in ("PREMARKET", "OVERNIGHT") else
        "Post-Session Review"  if session == "AFTER_HOURS" else
        "Closed"
    )

    next_open = _next_rth_open()

    status_items = [
        {
            "label": "ES Futures",
            "status": "OPEN" if es_open else "CLOSED",
            "detail": "Active overnight session" if session == "OVERNIGHT" else ("Live" if es_open else "Closed"),
            "color":  "green" if es_open else "red",
        },
        {
            "label": "SPX Cash",
            "status": "OPEN" if spx_open else "CLOSED",
            "detail": "9:30–16:00 ET" if spx_open else f"Opens: {next_open}",
            "color":  "green" if spx_open else "red",
        },
        {
            "label": "Options Flow",
            "status": flow_status,
            "detail": "QuantData live" if spx_open else ("Low volume pre-market" if session == "PREMARKET" else "Cash market closed"),
            "color":  "green" if spx_open else "amber" if flow_status in ("LIMITED", "OVERNIGHT") else "red",
        },
        {
            "label": "Scanner",
            "status": scanner_mode,
            "detail": "Scanning for live setups" if spx_open else "Historical analysis mode",
            "color":  "green" if spx_open else "amber",
        },
        {
            "label": "Story Engine",
            "status": story_mode,
            "detail": "Real-time institutional read" if spx_open else "Pre-session game plan",
            "color":  "green" if spx_open else "amber",
        },
    ]

    # Overall banner level
    if spx_open:
        level = "GREEN"
        title = "MARKET OPEN — LIVE MODE"
        message = "All engines active. Entries require flow alignment and Pine confirmation."
    elif session == "PREMARKET":
        mins_left = max(0, (9 * 60 + 30) - minutes)
        level = "AMBER"
        title = "PRE-MARKET — GAME PLAN MODE"
        message = f"Cash market opens in ~{mins_left}m. Use ES and overnight data to build your opening bias. No entries until RTH open and Pine confirmation."
    elif session == "OVERNIGHT":
        level = "AMBER"
        title = "OVERNIGHT SESSION — MONITOR MODE"
        message = f"ES futures active. Monitoring overnight structure relative to Friday's levels. Next RTH open: {next_open}."
    elif session == "AFTER_HOURS":
        level = "AMBER"
        title = "AFTER HOURS — REVIEW MODE"
        message = "Cash market closed. Reviewing today's session. ES still trading — monitoring for overnight positioning."
    else:
        level = "RED"
        title = "MARKET CLOSED"
        message = f"All cash markets closed. ES opens Sunday 18:00 ET. Next RTH: {next_open}."

    return {
        "session":      session,
        "level":        level,
        "title":        title,
        "message":      message,
        "next_rth":     next_open,
        "es_open":      es_open,
        "spx_open":     spx_open,
        "flow_status":  flow_status,
        "scanner_mode": scanner_mode,
        "story_mode":   story_mode,
        "items":        status_items,
        "updated_at":   n.strftime("%H:%M:%S ET"),
    }


def market_session_context() -> Dict[str, Any]:
    """Session-aware guidance for the Trade Assistant and Story Engine."""
    status = session_status()
    n = now_et()
    minutes = n.hour * 60 + n.minute
    open_minutes = 9 * 60 + 30
    panel = _build_market_status_panel(status)

    base = {
        "session_state":       status,
        "is_tradeable_session": status == "MARKET_OPEN",
        "market_status":       panel,
    }

    if status == "MARKET_OPEN":
        return {**base,
            "banner_level": "GREEN",
            "banner_title": panel["title"],
            "banner_message": panel["message"],
            "assistant_mode": "LIVE_TRADE_ASSISTANT",
        }
    if status == "PREMARKET":
        mins_to_open = max(0, open_minutes - minutes)
        return {**base,
            "minutes_to_open": mins_to_open,
            "banner_level": "YELLOW",
            "banner_title": panel["title"],
            "banner_message": panel["message"],
            "assistant_mode": "GAME_PLAN",
        }
    if status == "OVERNIGHT":
        return {**base,
            "banner_level": "YELLOW",
            "banner_title": panel["title"],
            "banner_message": panel["message"],
            "assistant_mode": "OVERNIGHT_MONITOR",
        }
    if status == "AFTER_HOURS":
        return {**base,
            "banner_level": "YELLOW",
            "banner_title": panel["title"],
            "banner_message": panel["message"],
            "assistant_mode": "REVIEW_PREP",
        }
    return {**base,
        "banner_level": "RED",
        "banner_title": panel["title"],
        "banner_message": panel["message"],
        "assistant_mode": "CLOSED_GAME_PLAN",
    }


def last_market_date(max_lookback: int = 8) -> dt.date:
    d = now_et().date()
    if session_status() in {"PREMARKET", "AFTER_HOURS", "CLOSED"}:
        d -= dt.timedelta(days=1)
    for _ in range(max_lookback):
        if d.weekday() < 5:
            return d
        d -= dt.timedelta(days=1)
    return now_et().date()


def safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


# _sf: short alias for safe_float, used throughout engine injection blocks
_sf = safe_float

def safe_get_json(url: str, params: Optional[dict] = None, headers: Optional[dict] = None, timeout: Optional[int] = None) -> Optional[dict]:
    params = dict(params or {})
    if "polygon.io" in url and POLYGON_API_KEY:
        params["apiKey"] = POLYGON_API_KEY
    try:
        r = requests.get(url, params=params, headers=headers or {}, timeout=timeout or REQUEST_TIMEOUT)
        if r.status_code != 200:
            print(f"GET {url} failed HTTP {r.status_code}: {r.text[:180]}", flush=True)
            return None
        return r.json()
    except Exception as e:
        print(f"GET {url} exception: {e}", flush=True)
        return None


def safe_post_json(url: str, payload: dict, headers: Optional[dict] = None, timeout: Optional[int] = None) -> Optional[dict]:
    try:
        r = requests.post(url, json=payload, headers=headers or {}, timeout=timeout or REQUEST_TIMEOUT)
        if r.status_code != 200:
            print(f"POST {url} failed HTTP {r.status_code}: {r.text[:180]}", flush=True)
            return None
        return r.json()
    except Exception as e:
        print(f"POST {url} exception: {e}", flush=True)
        return None



def normalize_index_level(value: Any, reference_price: Optional[float], ticker: str = "SPX") -> Optional[float]:
    """Backward-compatible wrapper around APEX 6.0.1 index normalizer."""
    if normalize_index_level_v6 is not None:
        return normalize_index_level_v6(value, ticker=ticker, reference_price=reference_price)
    v = safe_float(value, 0.0)
    ref = safe_float(reference_price, 0.0)
    if v <= 0:
        return None
    t = (ticker or "").upper()
    index_like = t in {"SPX", "SPXW", "I:SPX", "$SPX", "ES", "ES1!", "/ES"} or ref >= 1000
    if not index_like:
        return round(v, 2)
    if ref >= 1000:
        for _ in range(6):
            if v >= ref * 0.45:
                break
            v *= 10.0
        for _ in range(6):
            if v <= ref * 2.20:
                break
            v /= 10.0
        return round(v, 2)
    if v < 100:
        v *= 100.0
    elif v < 1000:
        v *= 10.0
    return round(v, 2)

def normalize_gamma_levels(levels: Dict[str, Any], reference_price: Optional[float], ticker: str = "SPX") -> Dict[str, Any]:
    """Return gamma levels normalized to the displayed instrument price scale."""
    out = dict(levels or {})
    ref = safe_float(reference_price or out.get("stock_price"), 0.0)
    for key in ("stock_price", "call_wall", "put_wall", "zero_gamma", "gammaFlip", "callWall", "putWall"):
        if key in out and out.get(key) is not None:
            nv = normalize_index_level(out.get(key), ref or reference_price, ticker)
            if nv is not None:
                out[key] = nv
    out["gamma_scale_diagnostics"] = {
        "reference_price": ref or reference_price,
        "ticker": ticker,
        "normalization": "power_of_10_only",
    }
    return out

def ema(values: List[float], period: int) -> Optional[float]:
    vals = [safe_float(v) for v in values if v is not None]
    if len(vals) < period:
        return None
    k = 2 / (period + 1)
    e = sum(vals[:period]) / period
    for v in vals[period:]:
        e = v * k + e * (1 - k)
    return e


def rsi(values: List[float], period: int = 14) -> Optional[float]:
    if len(values) <= period:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def rel_volume(volumes: List[float], period: int = 20) -> float:
    if len(volumes) < period + 1:
        return 1.0
    avg = sum(volumes[-period - 1:-1]) / period
    return volumes[-1] / avg if avg else 1.0


def atr(bars: List[dict], period: int = 14) -> Optional[float]:
    if len(bars) < period + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        h = safe_float(bars[i].get("h"))
        l = safe_float(bars[i].get("l"))
        pc = safe_float(bars[i - 1].get("c"))
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-period:]) / period




def polygon_bar_ticker(ticker: str) -> str:
    """Return the Polygon ticker used for historical bars.

    SPX cash index must be requested as I:SPX on Polygon. Keeping this
    mapping centralized prevents the OS engines from getting empty bars while
    the chart endpoint has valid SPX candles.
    """
    t = (ticker or "").upper().strip()
    if t in {"SPX", "$SPX", "SPXW"}:
        return "I:SPX"
    return ticker

def get_daily_bars(ticker: str, days: int = 320) -> List[dict]:
    end = now_et().date()
    start = end - dt.timedelta(days=days * 2)
    polygon_ticker = polygon_bar_ticker(ticker)
    url = f"https://api.polygon.io/v2/aggs/ticker/{polygon_ticker}/range/1/day/{start}/{end}"
    data = safe_get_json(url, params={"adjusted": "true", "sort": "asc", "limit": 5000}, timeout=20)
    return data.get("results", []) if data else []


def get_intraday_bars(ticker: str, multiplier: int = 5, limit_days: int = 3) -> List[dict]:
    today = now_et().date()
    end   = today + dt.timedelta(days=7)   # future end so closed-market sessions are included
    start = today - dt.timedelta(days=max(limit_days * 3, 10))
    polygon_ticker = polygon_bar_ticker(ticker)
    url = f"https://api.polygon.io/v2/aggs/ticker/{polygon_ticker}/range/{multiplier}/minute/{start}/{end}"
    data = safe_get_json(url, params={"adjusted": "true", "sort": "asc", "limit": 5000}, timeout=15)
    return data.get("results", []) if data else []


def get_vix_price() -> Optional[float]:
    """Fetch the current VIX level. Uses the Polygon indices snapshot."""
    # Indices snapshot — works on Indices Advanced plan
    data = safe_get_json("https://api.polygon.io/v3/snapshot?ticker.any_of=I:VIX", timeout=10)
    if data:
        results = data.get("results") or []
        for r in results:
            val = safe_float((r.get("session") or {}).get("close") or
                             (r.get("session") or {}).get("previous_close"), 0.0)
            if val > 0:
                return val
    # Fallback: VIXY ETF daily snapshot
    data = safe_get_json(
        "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/VIXY", timeout=10)
    if data and "ticker" in data:
        day = data["ticker"].get("day") or {}
        val = safe_float(day.get("c") or day.get("vw"), 0.0)
        if val > 0:
            return val
    return None


def get_breadth_score() -> Optional[float]:
    """
    Approximate breadth score from SPY vs IWM relative performance.
    IWM/SPY ratio above 20-day average = broad participation (score > 50).
    Not a real TICK/VOLD feed — an honest proxy from daily bars.
    """
    try:
        spy = get_daily_bars("SPY", days=30)
        iwm = get_daily_bars("IWM", days=30)
        if len(spy) < 22 or len(iwm) < 22:
            return None
        spy_closes = [safe_float(b.get("c")) for b in spy]
        iwm_closes = [safe_float(b.get("c")) for b in iwm]
        # Current ratio vs 20-day average ratio
        current_ratio = iwm_closes[-1] / spy_closes[-1] if spy_closes[-1] else 1.0
        past_ratios = [iwm_closes[i] / spy_closes[i] for i in range(-21, -1) if spy_closes[i] > 0]
        avg_ratio = sum(past_ratios) / len(past_ratios) if past_ratios else current_ratio
        # Score 0-100: 50 = ratio at average, 100 = IWM strongly outperforming
        score = 50.0 + (current_ratio - avg_ratio) / avg_ratio * 200
        return round(max(0.0, min(100.0, score)), 1)
    except Exception:
        return None


def get_dynamic_tickers() -> List[str]:
    """Build a liquid, optionable universe without blindly chasing yesterday's largest movers."""
    base = list(dict.fromkeys(CORE_TICKERS + STATIC_TICKERS_EXTRA))
    if not DYNAMIC_TICKERS_ENABLED:
        return base
    date_to_use = last_market_date()
    url = f"https://api.polygon.io/v2/aggs/grouped/locale/us/market/stocks/{date_to_use}"
    data = safe_get_json(url, params={"adjusted": "true"}, timeout=25)
    if not data or "results" not in data:
        return base
    blocked = {"VXX", "UVXY", "SQQQ", "TQQQ", "SOXL", "SOXS", "SPXL", "SPXS"}
    candidates: List[Tuple[float, str]] = []
    for row in data.get("results", []):
        t = str(row.get("T", "")).upper().strip()
        if not t or "." in t or "-" in t or len(t) > 5 or t in blocked:
            continue
        o, c, h, l, v = [safe_float(row.get(k)) for k in ["o", "c", "h", "l", "v"]]
        if c < 20 or v < 3_000_000 or o <= 0:
            continue
        signed_change_pct = (c - o) / o
        abs_change_pct = abs(signed_change_pct)
        range_pct = (h - l) / c if c else 0
        dollar_volume = c * v
        # Avoid names that already made an extreme completed-session move. They can still qualify
        # through CORE_TICKERS, but the dynamic add-on should be earlier-watchlist oriented.
        if abs_change_pct > 0.075:
            continue
        if dollar_volume < 1_000_000_000 and range_pct < 0.018:
            continue
        liquidity_score = min(dollar_volume / 1_000_000_000, 12) * 2.0
        range_score = min(range_pct * 100, 6) * 1.5
        constructive_momentum = max(signed_change_pct, 0) * 45
        chase_penalty = max(abs_change_pct - 0.035, 0) * 120
        rank = liquidity_score + range_score + constructive_momentum - chase_penalty
        candidates.append((rank, t))
    candidates.sort(reverse=True)
    dynamic = [t for _, t in candidates[:MAX_DYNAMIC_TICKERS]]
    return list(dict.fromkeys(base + dynamic))


def technical_layer(ticker: str, daily: List[dict], intraday: List[dict]) -> Optional[Dict[str, Any]]:
    if len(daily) < 60:
        return None
    closes = [safe_float(x.get("c")) for x in daily]
    volumes = [safe_float(x.get("v")) for x in daily]
    price = closes[-1]
    prev_close = closes[-2] if len(closes) > 1 else price
    e8, e21, e50 = ema(closes, 8), ema(closes, 21), ema(closes, 50)
    e200 = ema(closes, 200) or e50
    current_rsi = rsi(closes, 14)
    current_atr = atr(daily, 14) or 0.0
    rv = rel_volume(volumes, 20)
    if not all([price, e8, e21, e50, e200, current_rsi]):
        return None

    bullish = price > e50 and e50 >= e200
    bearish = price < e50 and e50 <= e200
    direction = "CALL" if bullish else "PUT" if bearish else "NEUTRAL"

    score = 50.0
    notes: List[str] = []
    if bullish or bearish:
        score += 14
        notes.append("Trend stack aligned")
    if direction == "CALL" and price > e21:
        score += 8
        notes.append("Above EMA21")
    if direction == "PUT" and price < e21:
        score += 8
        notes.append("Below EMA21")
    if 45 <= current_rsi <= 68 and direction == "CALL":
        score += 8
        notes.append("RSI in bullish continuation range")
    elif 32 <= current_rsi <= 55 and direction == "PUT":
        score += 8
        notes.append("RSI in bearish continuation range")
    if rv >= 1.25:
        score += 10
        notes.append("Relative volume expansion")
    elif rv >= 1.05:
        score += 5
    if intraday:
        ic = [safe_float(x.get("c")) for x in intraday]
        ie8 = ema(ic, 8)
        ie21 = ema(ic, 21)
        if ie8 and ie21 and ((direction == "CALL" and ic[-1] > ie8 > ie21) or (direction == "PUT" and ic[-1] < ie8 < ie21)):
            score += 8
            notes.append("Intraday timing confirms")

    buy_low = e21 - max(current_atr * 0.25, price * 0.005)
    buy_high = e21 + max(current_atr * 0.35, price * 0.01)
    if direction == "PUT":
        buy_low = e21 - max(current_atr * 0.35, price * 0.01)
        buy_high = e21 + max(current_atr * 0.25, price * 0.005)
    if buy_low <= price <= buy_high:
        zone_status = "INSIDE BUY ZONE"
        distance_pct = 0.0
        score += 8
    elif direction == "CALL" and price < buy_low:
        distance_pct = (buy_low - price) / price * 100
        zone_status = f"BELOW BUY ZONE BY {distance_pct:.2f}%"
    elif direction == "CALL":
        distance_pct = (price - buy_high) / price * 100
        zone_status = f"ABOVE BUY ZONE BY {distance_pct:.2f}%"
        if distance_pct > 3:
            score -= 8
            notes.append("Extended above buy zone")
    elif direction == "PUT" and price > buy_high:
        distance_pct = (price - buy_high) / price * 100
        zone_status = f"ABOVE PUT ZONE BY {distance_pct:.2f}%"
    else:
        distance_pct = (buy_low - price) / price * 100
        zone_status = f"BELOW PUT ZONE BY {abs(distance_pct):.2f}%"
        if abs(distance_pct) > 3:
            score -= 8

    return {
        "price": round(price, 2), "prev_close": round(prev_close, 2), "ema8": round(e8, 2),
        "ema21": round(e21, 2), "ema50": round(e50, 2), "ema200": round(e200, 2),
        "rsi": round(current_rsi, 1), "atr": round(current_atr, 2), "rel_volume": round(rv, 2),
        "direction": direction, "technical_score": round(max(0, min(score, 100)), 1),
        "buy_zone_low": round(buy_low, 2), "buy_zone_high": round(buy_high, 2),
        "buy_zone_status": zone_status, "distance_to_buy_zone_pct": round(abs(distance_pct), 2),
        "technical_notes": notes,
    }


def rows_from_tool_response(data: Any) -> List[dict]:
    """Normalize tool responses into a list of row dictionaries."""
    if data is None:
        return []
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("results", "items", "rows", "articles", "news"):
        val = data.get(key)
        if isinstance(val, list):
            return [r for r in val if isinstance(r, dict)]
        if isinstance(val, dict):
            return [r for r in val.values() if isinstance(r, dict)]
    val = data.get("data")
    if isinstance(val, list):
        return [r for r in val if isinstance(r, dict)]
    if isinstance(val, dict):
        for key in ("items", "rows", "results"):
            nested = val.get(key)
            if isinstance(nested, list):
                return [r for r in nested if isinstance(r, dict)]
        return [r for r in val.values() if isinstance(r, dict)]
    return []


def quantdata_flow_layer(ticker: str) -> Dict[str, Any]:
    """QuantData options net-flow layer using /v1/options/tool/net-flow."""
    if not QUANTDATA_API_KEY:
        return {"flow_score": 50.0, "flow_status": "NEUTRAL - QUANTDATA NOT CONFIGURED", "flow_notes": ["Set QUANTDATA_API_KEY to enable live net-flow."], "call_premium": 0, "put_premium": 0, "call_ratio_pct": None}
    if BREAKER.is_open("quantdata_net_flow"):
        BREAKER.record_skip("quantdata_net_flow")
        return {"flow_score": 50.0, "flow_status": "NEUTRAL - CIRCUIT OPEN (repeated failures this scan)", "flow_notes": ["quantdata_net_flow skipped after repeated failures this scan cycle."], "call_premium": 0, "put_premium": 0, "call_ratio_pct": None}
    headers = {"Authorization": f"Bearer {QUANTDATA_API_KEY}", "Content-Type": "application/json"}
    # Deliberately omit sessionDate: our own last_market_date() is calendar-correct
    # but can land on a session QuantData hasn't finished finalizing yet (e.g. a
    # weekend request for Friday). QuantData's documented default for an omitted
    # sessionDate is "the latest completed trading session" -- let them resolve it.
    payload = {"dataMode": "NET_PREMIUM", "filter": {"ticker": ticker}}
    data = safe_post_json(f"{QUANTDATA_BASE_URL}/options/tool/net-flow", payload, headers=headers, timeout=20)
    BREAKER.record_failure("quantdata_net_flow") if data is None else BREAKER.record_success("quantdata_net_flow")
    rows = rows_from_tool_response(data)
    call_sum = put_sum = 0.0
    for row in rows:
        call_sum += safe_float(row.get("callSum") or row.get("call_sum") or row.get("callPremium") or row.get("netCallPremium"))
        put_sum += abs(safe_float(row.get("putSum") or row.get("put_sum") or row.get("putPremium") or row.get("netPutPremium")))
    # QuantData's NET_PREMIUM dataMode returns callSum/putSum in cents, not dollars.
    call_sum /= 100.0
    put_sum /= 100.0
    total = abs(call_sum) + abs(put_sum)
    if total <= 0:
        return {"flow_score": 50.0, "flow_status": "NEUTRAL - NO FLOW RETURNED", "flow_notes": ["QuantData net-flow returned no usable rows."], "call_premium": 0, "put_premium": 0, "call_ratio_pct": None}
    call_ratio = abs(call_sum) / total * 100
    bullish_score = max(0, min(100, 50 + (call_ratio - 50) * 1.2 + min(total / 5_000_000, 20)))
    notes = [f"QuantData net-flow call ratio {call_ratio:.0f}%", f"Net-flow total ${total:,.0f}", f"Rows analyzed: {len(rows)}"]
    status = "BULLISH NET FLOW" if bullish_score >= 65 else "BEARISH/PUT NET FLOW" if bullish_score <= 40 else "MIXED NET FLOW"
    return {"flow_score": round(bullish_score, 1), "flow_status": status, "flow_notes": notes, "call_premium": round(call_sum, 0), "put_premium": round(put_sum, 0), "call_ratio_pct": round(call_ratio, 1)}


def quantdata_order_flow_layer(ticker: str) -> Dict[str, Any]:
    """QuantData consolidated order-flow layer using /v1/options/tool/order-flow/consolidated."""
    if not QUANTDATA_API_KEY or not ORDER_FLOW_ENABLED:
        return {"order_flow_score": 50.0, "order_flow_status": "NEUTRAL - ORDER FLOW NOT CONFIGURED", "order_flow_notes": ["Set QUANTDATA_API_KEY and ORDER_FLOW_ENABLED=true to enable consolidated order flow."], "sweep_count": 0, "large_trade_premium": 0}
    if BREAKER.is_open("quantdata_order_flow"):
        BREAKER.record_skip("quantdata_order_flow")
        return {"order_flow_score": 50.0, "order_flow_status": "NEUTRAL - CIRCUIT OPEN (repeated failures this scan)", "order_flow_notes": ["quantdata_order_flow skipped after repeated failures this scan cycle."], "sweep_count": 0, "large_trade_premium": 0}
    headers = {"Authorization": f"Bearer {QUANTDATA_API_KEY}", "Content-Type": "application/json"}
    payload = {"filter": {"ticker": ticker}, "size": 75, "sort": {"field": "tradeTime", "direction": "DESCENDING"}}
    data = safe_post_json(f"{QUANTDATA_BASE_URL}/options/tool/order-flow/consolidated", payload, headers=headers, timeout=20)
    BREAKER.record_failure("quantdata_order_flow") if data is None else BREAKER.record_success("quantdata_order_flow")
    rows = rows_from_tool_response(data)
    if not rows:
        return {"order_flow_score": 50.0, "order_flow_status": "NEUTRAL - NO ORDER FLOW ROWS", "order_flow_notes": ["QuantData consolidated order-flow returned no rows."], "sweep_count": 0, "large_trade_premium": 0}
    bull_premium = bear_premium = total_premium = 0.0
    sweep_count = block_count = 0
    for row in rows:
        premium = safe_float(row.get("premium") or row.get("notional") or row.get("totalPremium") or row.get("tradePremium") or row.get("value"))
        if premium <= 0:
            price = safe_float(row.get("price") or row.get("optionPrice") or row.get("tradePrice"))
            size = safe_float(row.get("size") or row.get("quantity") or row.get("contracts"))
            premium = price * size * 100 if price and size else 0.0
        total_premium += premium
        # Real QuantData fields (per /api/docs/endpoints/order-flow-consolidated):
        # tradeSideCode (e.g. ABOVE_ASK / AT_ASK / AT_BID / BELOW_BID), tradeConsolidationType
        # (SWEEP / BLOCK / SPLIT), contractType (CALL / PUT). The old code searched for
        # "side"/"sentiment"/"tradeSide"/"type" keys that don't exist on this endpoint, so
        # sweep/block counts were always 0 and direction silently fell back to contractType only.
        trade_side = str(row.get("tradeSideCode") or "").upper()
        consolidation_type = str(row.get("tradeConsolidationType") or "").upper()
        contract_type = str(row.get("contractType") or row.get("contract_type") or row.get("optionType") or "").upper()
        if consolidation_type == "SWEEP":
            sweep_count += 1
        if consolidation_type in ("BLOCK", "SPLIT"):
            block_count += 1
        bullish_side = trade_side in ("ABOVE_ASK", "AT_ASK")
        bearish_side = trade_side in ("BELOW_BID", "AT_BID")
        if bullish_side or (not bearish_side and contract_type == "CALL"):
            bull_premium += premium
        elif bearish_side or contract_type == "PUT":
            bear_premium += premium
    if total_premium <= 0:
        score = 50.0
    else:
        directional = ((bull_premium - bear_premium) / total_premium) * 25
        size_boost = min(total_premium / 3_000_000, 18)
        sweep_boost = min(sweep_count * 1.5 + block_count, 12)
        score = max(0, min(100, 50 + directional + size_boost + sweep_boost))
    status = "BULLISH ORDER FLOW" if score >= 65 else "BEARISH ORDER FLOW" if score <= 40 else "MIXED ORDER FLOW"
    notes = [f"Consolidated premium ${total_premium:,.0f}", f"Sweeps {sweep_count}, blocks/splits {block_count}", f"Rows analyzed: {len(rows)}"]
    return {"order_flow_score": round(score, 1), "order_flow_status": status, "order_flow_notes": notes, "sweep_count": sweep_count, "large_trade_premium": round(total_premium, 0)}



def quantdata_gex_layer(ticker: str) -> Dict[str, Any]:
    """APEX 6.0.1 QuantData gamma layer with raw → normalized → engine diagnostics."""
    empty = {
        "gex_score": 50.0,
        "gex_status": "NEUTRAL - GEX NOT CONFIGURED",
        "call_wall": None,
        "put_wall": None,
        "zero_gamma": None,
        "stock_price": None,
        "quality_flags": ["QUANTDATA_NOT_CONFIGURED"],
        "gex_notes": ["Set QUANTDATA_API_KEY and GEX_ENABLED=true to enable gamma exposure."],
        "diagnostics": None,
    }
    if not QUANTDATA_API_KEY or not GEX_ENABLED:
        return empty
    if BREAKER.is_open("quantdata_gex"):
        BREAKER.record_skip("quantdata_gex")
        return {**empty, "gex_status": "NEUTRAL - CIRCUIT OPEN", "quality_flags": ["QUANTDATA_GEX_CIRCUIT_OPEN"], "gex_notes": ["quantdata_gex skipped after repeated failures this scan cycle."]}

    headers = {"Authorization": f"Bearer {QUANTDATA_API_KEY}", "Content-Type": "application/json"}
    # SPXW maps to the same index options complex for dashboard purposes.
    qd_ticker = "SPX" if ticker.upper() in {"SPXW", "$SPX", "I:SPX"} else ticker.upper()
    payload = {"greekMode": "GAMMA", "representationMode": "RAW", "filter": {"ticker": qd_ticker}}
    data = safe_post_json(f"{QUANTDATA_BASE_URL}/options/tool/exposure-by-strike", payload, headers=headers, timeout=20)
    BREAKER.record_failure("quantdata_gex") if data is None else BREAKER.record_success("quantdata_gex")
    if data is None:
        return {**empty, "gex_status": "NEUTRAL - NO GEX RETURNED", "quality_flags": ["NO_GEX_RESPONSE"], "gex_notes": ["QuantData exposure-by-strike returned no usable response."]}

    if build_gamma_from_quantdata_response is not None:
        return build_gamma_from_quantdata_response(data, qd_ticker)

    # Defensive fallback if the modular package did not import.
    return {**empty, "gex_status": "NEUTRAL - GAMMA ENGINE UNAVAILABLE", "quality_flags": ["APEX_601_ENGINE_IMPORT_FAILED"], "gex_notes": ["APEX 6.0.1 gamma module was not importable."]}

def flow_decision_gate(bias: str, net_premium: float, flow_score: float, order_flow_score: float, gex_score: float) -> Dict[str, Any]:
    """Fast traffic-light decision gate for the Flow/GEX dashboard.

    This does not create a trade by itself. It approves or blocks the Pine signal side.
    Green = only trade the approved side. Yellow = reduce size / wait. Red = skip.
    """
    reasons: List[str] = []
    call_approved = (bias == "BULLISH" and net_premium > 0 and flow_score >= 70 and order_flow_score >= 65)
    put_approved = (bias == "BEARISH" and net_premium < 0 and flow_score <= 30 and order_flow_score >= 65)

    if call_approved:
        decision = "TRADE APPROVED - CALL"
        color = "GREEN"
        side = "CALL"
        reasons += ["Bullish flow bias", "Positive net premium", "Flow score >= 70", "Order flow confirms"]
    elif put_approved:
        decision = "TRADE APPROVED - PUT"
        color = "GREEN"
        side = "PUT"
        reasons += ["Bearish flow bias", "Negative net premium", "Put-side flow confirmed", "Order flow confirms"]
    else:
        # Caution only when the picture is close but incomplete. Mixed/negative with no approved side is a no-trade for speed.
        close_to_call = bias == "BULLISH" and net_premium > 0 and flow_score >= 60
        close_to_put = bias == "BEARISH" and net_premium < 0 and flow_score <= 40
        strong_order_only = order_flow_score >= 70 and bias != "MIXED"
        if close_to_call or close_to_put or strong_order_only:
            decision = "CAUTION"
            color = "YELLOW"
            side = "WAIT"
            reasons.append("Some alignment present, but not enough for a green approval")
        else:
            decision = "NO TRADE"
            color = "RED"
            side = "NONE"
            reasons.append("Institutional alignment is not strong enough")

        if bias == "MIXED":
            reasons.append("Bias is mixed")
        if flow_score < 70 and bias == "BULLISH":
            reasons.append("Flow score below CALL approval threshold")
        if flow_score > 30 and bias == "BEARISH":
            reasons.append("Put-side flow is not strong enough")
        if net_premium <= 0 and bias != "BEARISH":
            reasons.append("Net premium is not supportive for calls")
        if net_premium >= 0 and bias == "BEARISH":
            reasons.append("Net premium is not supportive for puts")
        if order_flow_score < 65:
            reasons.append("Order flow score below confirmation threshold")

    # Simple 0-100 institutional alignment readout for faster visual decisions.
    if side == "CALL":
        alignment = min(100, max(0, flow_score * 0.55 + order_flow_score * 0.25 + (20 if net_premium > 0 else 0)))
    elif side == "PUT":
        put_flow_score = 100 - flow_score
        alignment = min(100, max(0, put_flow_score * 0.55 + order_flow_score * 0.25 + (20 if net_premium < 0 else 0)))
    else:
        directional_component = flow_score if net_premium > 0 else (100 - flow_score if net_premium < 0 else 50)
        alignment = min(100, max(0, directional_component * 0.45 + order_flow_score * 0.25 + gex_score * 0.10))

    return {
        "decision": decision,
        "decision_color": color,
        "approved_side": side,
        "institutional_alignment": round(alignment, 1),
        "decision_reasons": reasons[:6],
    }




def normalize_signal_ticker(ticker: str) -> str:
    t = (ticker or "").upper()
    if "SPX" in t:
        return "SPX"
    if "SPY" in t:
        return "SPY"
    if "QQQ" in t:
        return "QQQ"
    return t.split(":")[-1]


def signal_is_fresh(sig: Optional[Dict[str, Any]]) -> bool:
    if not sig:
        return False
    try:
        ts = dt.datetime.fromisoformat(sig.get("received_at", ""))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        return (dt.datetime.now(dt.timezone.utc) - ts).total_seconds() <= SIGNAL_TTL_SECONDS
    except Exception:
        return False


def signal_age_seconds(sig: Optional[Dict[str, Any]]) -> Optional[int]:
    """Age of latest Pine/TradingView signal in seconds."""
    if not sig:
        return None
    try:
        ts = dt.datetime.fromisoformat(sig.get("received_at", ""))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        return max(0, int((dt.datetime.now(dt.timezone.utc) - ts).total_seconds()))
    except Exception:
        return None


def signal_seconds_remaining(sig: Optional[Dict[str, Any]]) -> int:
    age = signal_age_seconds(sig)
    if age is None:
        return 0
    return max(0, ASSISTANT_SIGNAL_VALID_SECONDS - age)


def assistant_price_from_signal_or_flow(flow_item: Dict[str, Any], signal: Optional[Dict[str, Any]]) -> float:
    for obj in (signal or {}, flow_item or {}):
        for key in ("close", "price", "underlying_price", "last", "spot"):
            v = safe_float(obj.get(key), 0.0)
            if v > 0:
                return v
    zg = safe_float((flow_item or {}).get("zero_gamma"), 0.0)
    cw = safe_float((flow_item or {}).get("call_wall"), 0.0)
    pw = safe_float((flow_item or {}).get("put_wall"), 0.0)
    if zg > 0:
        return zg
    vals = [x for x in [cw, pw] if x > 0]
    return sum(vals) / len(vals) if vals else 0.0


def round_to_strike(price: float, side: str, ticker: str) -> Optional[float]:
    if price <= 0:
        return None
    step = ASSISTANT_STRIKE_STEP_SPX if "SPX" in ticker.upper() else ASSISTANT_STRIKE_STEP_ETF
    if side == "CALL":
        return float(((int(price // step) + 1) * step))
    if side == "PUT":
        return float((int(price // step) * step))
    return float(round(price / step) * step)


def build_assistant_trade_plan(flow_item: Dict[str, Any], signal: Optional[Dict[str, Any]], side: str, state: str) -> Dict[str, Any]:
    """Turn institutional bias + Pine trigger into an execution plan.

    This is intentionally a planner, not a broker order. It gives a strike,
    entry zone, stop, targets, risk notes, and a countdown so stale signals are
    not chased.
    """
    ticker = normalize_signal_ticker((flow_item.get("ticker") or (signal or {}).get("ticker") or ASSISTANT_TICKER))
    px = assistant_price_from_signal_or_flow(flow_item, signal)
    side = (side or "NONE").upper()
    risk_pts = ASSISTANT_DEFAULT_RISK_POINTS
    if ticker in {"SPY", "QQQ"}:
        risk_pts = max(0.55, ASSISTANT_DEFAULT_RISK_POINTS / 10.0)
    # If zero gamma / walls are nearby, use that to avoid oversized stops.
    zero_gamma = safe_float(flow_item.get("zero_gamma"), 0.0)
    call_wall = safe_float(flow_item.get("call_wall"), 0.0)
    put_wall = safe_float(flow_item.get("put_wall"), 0.0)
    if px > 0 and zero_gamma > 0:
        risk_pts = max(risk_pts, min(abs(px - zero_gamma) * 0.55, risk_pts * 1.8))
    if side == "CALL" and px > 0:
        entry_low, entry_high = px - risk_pts * 0.18, px + risk_pts * 0.18
        stop = px - risk_pts
        target1 = px + risk_pts * ASSISTANT_TARGET1_R_MULT
        target2 = px + risk_pts * ASSISTANT_TARGET2_R_MULT
    elif side == "PUT" and px > 0:
        entry_low, entry_high = px - risk_pts * 0.18, px + risk_pts * 0.18
        stop = px + risk_pts
        target1 = px - risk_pts * ASSISTANT_TARGET1_R_MULT
        target2 = px - risk_pts * ASSISTANT_TARGET2_R_MULT
    else:
        entry_low = entry_high = stop = target1 = target2 = None
    strike = round_to_strike(px, side, ticker) if side in {"CALL", "PUT"} else None
    if strike is not None:
        suffix = "C" if side == "CALL" else "P"
        contract_hint = f"{ticker} 0DTE {int(strike) if strike.is_integer() else strike:g}{suffix}"
    else:
        contract_hint = "Wait for price/contract selection"
    remaining = signal_seconds_remaining(signal)
    expired = bool(signal) and remaining <= 0
    session_ctx = market_session_context()
    checklist = [
        {"label": "Market open", "ok": session_ctx.get("is_tradeable_session")},
        {"label": "Institutional side agrees", "ok": side in {"CALL", "PUT"} and flow_item.get("approved_side") == side},
        {"label": "Alignment >= 70", "ok": safe_float(flow_item.get("institutional_alignment"), 0) >= 70},
        {"label": "Flow score >= 70", "ok": safe_float(flow_item.get("flow_score"), 0) >= 70},
        {"label": "Order flow confirms", "ok": safe_float(flow_item.get("order_flow_score"), 0) >= 70},
        {"label": "Fresh Pine trigger", "ok": bool(signal) and not expired},
        {"label": "No stale chase", "ok": not expired},
    ]
    plan = {
        "ticker": ticker,
        "side": side,
        "spot_price": round(px, 2) if px else None,
        "recommended_contract": contract_hint,
        "recommended_strike": strike,
        "entry_zone": f"{entry_low:.2f} - {entry_high:.2f}" if entry_low is not None else "Waiting for live price",
        "stop_price": round(stop, 2) if stop is not None else None,
        "target_1": round(target1, 2) if target1 is not None else None,
        "target_2": round(target2, 2) if target2 is not None else None,
        "risk_points": round(risk_pts, 2),
        "rr_to_t1": round(ASSISTANT_TARGET1_R_MULT, 2),
        "rr_to_t2": round(ASSISTANT_TARGET2_R_MULT, 2),
        "signal_seconds_remaining": remaining,
        "signal_ttl_seconds": ASSISTANT_SIGNAL_VALID_SECONDS,
        "signal_expired": expired,
        "checklist": checklist,
        "exit_rules": [
            "Take partials into Target 1 or +20% to +30% option gain.",
            "Move stop near breakeven after fast profit.",
            "Exit immediately if Flow/GEX flips against the trade.",
            "Do not enter after countdown expires; wait for the next Pine trigger.",
        ],
        "walls": {"call_wall": call_wall or None, "zero_gamma": zero_gamma or None, "put_wall": put_wall or None},
        "session_context": session_ctx,
    }
    if not session_ctx.get("is_tradeable_session"):
        if side in {"CALL", "PUT"}:
            plan["execution_summary"] = f"{session_ctx.get('banner_title')}: bias is {side}, but entries are disabled until market open plus a fresh Pine trigger."
        else:
            plan["execution_summary"] = f"{session_ctx.get('banner_title')}: no executable trade plan until the next live session."
    elif state.startswith("ENTER_") and not expired:
        plan["execution_summary"] = f"{side} setup active: {contract_hint}, entry {plan['entry_zone']}, stop {plan['stop_price']}, targets {plan['target_1']} / {plan['target_2']}."
    elif expired:
        plan["execution_summary"] = "Signal expired. Do not chase; wait for next Pine trigger."
    elif side in {"CALL", "PUT"}:
        plan["execution_summary"] = f"Bias is {side}. Wait for fresh Pine trigger before entry."
    else:
        plan["execution_summary"] = "No trade plan until institutional side is clean."
    return plan


def build_trade_assistant_decision(flow_item: Dict[str, Any], signal: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Combine Flow/GEX institutional filter with the latest Pine webhook signal.

    Flow approves a side. Pine provides the actual entry trigger.
    This function turns those two pieces into a state-machine decision.
    """
    approved_side = (flow_item.get("approved_side") or "NONE").upper()
    decision_color = flow_item.get("decision_color") or "YELLOW"
    alignment = safe_float(flow_item.get("institutional_alignment"), 0.0)
    flow_decision = flow_item.get("decision") or "NO TRADE"
    fresh = signal_is_fresh(signal)
    sig_side = ((signal or {}).get("signal") or (signal or {}).get("side") or "NONE").upper()
    sig_score = safe_float((signal or {}).get("score"), 0.0)
    sig_ticker = normalize_signal_ticker((signal or {}).get("ticker", ""))
    ticker = flow_item.get("ticker") or ASSISTANT_TICKER

    if decision_color == "GREEN" and approved_side in {"CALL", "PUT"}:
        base_state = f"WATCHING_{approved_side}S"
        base_message = f"Institutional filter approves {approved_side}. Waiting for Pine {approved_side} trigger."
        base_action = f"Only take {approved_side} setups. Ignore the opposite side unless Flow/GEX flips."
    elif decision_color == "YELLOW":
        base_state = "CAUTION"
        base_message = "Flow/GEX is not clean enough for full-size entries. Wait or reduce size."
        base_action = "Do not chase. Require a very clean Pine trigger and smaller size."
    else:
        base_state = "NO_TRADE"
        base_message = "Institutional filter is blocking new trades."
        base_action = "Skip new entries until the dashboard turns green."

    state = base_state
    message = base_message
    action = base_action
    priority = "INFO"
    alert = False
    reason = []

    session_ctx = market_session_context()

    if fresh and not session_ctx.get("is_tradeable_session"):
        reason.append(f"Fresh Pine signal received outside market hours: {sig_side} score {sig_score:g} on {sig_ticker or 'unknown'}")
        state = "MARKET_CLOSED_SIGNAL_IGNORED" if session_ctx.get("session") == "CLOSED" else "OUTSIDE_LIVE_SESSION"
        message = session_ctx.get("banner_message")
        action = "Do not enter. Treat the signal as stale planning information and wait for the next market-open trigger."
        priority = "WARNING"
    elif fresh:
        reason.append(f"Fresh Pine signal: {sig_side} score {sig_score:g} on {sig_ticker or 'unknown'}")
        if sig_ticker and sig_ticker != ticker:
            state = "SIGNAL_TICKER_MISMATCH"
            message = f"Pine signal was for {sig_ticker}, but assistant is viewing {ticker}."
            action = "Check the chart/ticker before acting."
            priority = "WARNING"
        elif decision_color == "GREEN" and sig_side == approved_side and sig_side in {"CALL", "PUT"}:
            state = f"ENTER_{approved_side}_NOW"
            message = f"Pine {approved_side} trigger confirmed by Flow/GEX."
            action = f"ENTER {approved_side} only if spread/liquidity is acceptable. Scale at +30%, move stop to breakeven, exit on EMA21/VWAP failure."
            priority = "URGENT"
            alert = True
            reason.append("Pine side matches approved institutional side")
        elif decision_color == "GREEN" and sig_side in {"CALL", "PUT"} and sig_side != approved_side:
            state = "REJECTED_SIGNAL"
            message = f"Pine fired {sig_side}, but Flow/GEX only approves {approved_side}."
            action = "Skip this signal. Do not trade against the institutional filter."
            priority = "BLOCKED"
            reason.append("Signal conflicts with Flow/GEX approved side")
        elif sig_side in {"CALL", "PUT"}:
            state = "REJECTED_SIGNAL"
            message = f"Pine fired {sig_side}, but Flow/GEX is not green."
            action = "Skip or wait for Flow/GEX to improve."
            priority = "BLOCKED"
            reason.append("Flow/GEX did not approve the trade")

    if fresh and signal_seconds_remaining(signal) <= 0:
        state = "SIGNAL_EXPIRED"
        message = "The last Pine trigger is stale."
        action = "Do not chase. Wait for the next trigger."
        priority = "WARNING"
        alert = False
        reason.append("Signal countdown expired")

    reason += (flow_item.get("decision_reasons") or flow_item.get("notes") or [])[:4]
    plan_side = approved_side if approved_side in {"CALL", "PUT"} else sig_side
    trade_plan = build_assistant_trade_plan(flow_item, signal, plan_side, state)
    return {
        "state": state,
        "priority": priority,
        "message": message,
        "action": action,
        "approved_side": approved_side,
        "flow_decision": flow_decision,
        "session_context": session_ctx,
        "institutional_alignment": round(alignment, 1),
        "fresh_signal": fresh,
        "last_signal": signal,
        "alert": alert,
        "reasons": reason[:8],
        "trade_plan": trade_plan,
        "checklist": trade_plan.get("checklist", []),
        "signal_seconds_remaining": trade_plan.get("signal_seconds_remaining", 0),
        "signal_ttl_seconds": trade_plan.get("signal_ttl_seconds", ASSISTANT_SIGNAL_VALID_SECONDS),
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "updated_at_et": now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
    }
def quantdata_flow_snapshot(ticker: str) -> Dict[str, Any]:
    """One ticker snapshot for the /flow dashboard."""
    flow = quantdata_flow_layer(ticker)
    order = quantdata_order_flow_layer(ticker)
    gex = quantdata_gex_layer(ticker)
    call_premium = safe_float(flow.get("call_premium"))
    put_premium = safe_float(flow.get("put_premium"))
    net_premium = call_premium - put_premium
    total = call_premium + put_premium
    flow_ratio = round(call_premium / put_premium, 2) if put_premium > 0 else None
    flow_score_val = safe_float(flow.get("flow_score"), 50.0)
    order_score_val = safe_float(order.get("order_flow_score"), 50.0)
    gex_score_val = safe_float(gex.get("gex_score"), 50.0)
    if net_premium > 0 and flow_score_val >= 60:
        bias = "BULLISH"
    elif net_premium < 0 and flow_score_val <= 40:
        bias = "BEARISH"
    else:
        bias = "MIXED"
    decision = flow_decision_gate(bias, net_premium, flow_score_val, order_score_val, gex_score_val)
    return {
        "ticker": ticker,
        "bias": bias,
        **decision,
        "flow_score": flow.get("flow_score"),
        "flow_status": flow.get("flow_status"),
        "call_premium": round(call_premium, 0),
        "put_premium": round(put_premium, 0),
        "net_premium": round(net_premium, 0),
        "total_premium": round(total, 0),
        "flow_ratio": flow_ratio,
        "call_ratio_pct": flow.get("call_ratio_pct"),
        "order_flow_score": order.get("order_flow_score"),
        "order_flow_status": order.get("order_flow_status"),
        "sweep_count": order.get("sweep_count"),
        "large_trade_premium": order.get("large_trade_premium"),
        "gex_score": gex.get("gex_score"),
        "gex_status": gex.get("gex_status"),
        "call_wall": gex.get("call_wall"),
        "put_wall": gex.get("put_wall"),
        "zero_gamma": gex.get("zero_gamma"),
        "active_gamma_flip": gex.get("active_gamma_flip"),
        "raw_zero_gamma": gex.get("raw_zero_gamma"),
        "zero_gamma_method": gex.get("zero_gamma_method"),
        "zero_gamma_confidence": gex.get("zero_gamma_confidence"),
        "stock_price": gex.get("stock_price"),
        "raw_stock_price": gex.get("raw_stock_price"),
        "quality_flags": gex.get("quality_flags", []),
        "gamma_diagnostics": gex.get("diagnostics"),
        "notes": (decision.get("decision_reasons") or []) + (flow.get("flow_notes") or []) + (order.get("order_flow_notes") or []) + (gex.get("gex_notes") or []),
    }

def quantdata_news_rows(ticker: str) -> List[dict]:
    if not QUANTDATA_API_KEY or not QUANTDATA_NEWS_ENABLED:
        return []
    if BREAKER.is_open("quantdata_news"):
        BREAKER.record_skip("quantdata_news")
        return []
    headers = {"Authorization": f"Bearer {QUANTDATA_API_KEY}", "Content-Type": "application/json"}
    payload = {"filter": {"ticker": ticker}, "size": 10}
    data = safe_post_json(f"{QUANTDATA_BASE_URL}/news/tool/articles", payload, headers=headers, timeout=15)
    BREAKER.record_failure("quantdata_news") if data is None else BREAKER.record_success("quantdata_news")
    return rows_from_tool_response(data)


def massive_benzinga_news_rows(ticker: str) -> List[dict]:
    """Massive/Polygon Benzinga news route; falls back to Polygon reference news."""
    if not MASSIVE_API_KEY:
        return []
    if not BREAKER.is_open("massive_benzinga_news"):
        # Per Massive's docs (massive.com/docs/rest/partners/benzinga/news) the filter
        # param is the plural "tickers", not "ticker" -- the singular param was likely
        # silently ignored or matched nothing, which would explain catalyst_score being
        # pinned at the neutral 50.0 baseline for every ticker.
        data = safe_get_json(f"{MASSIVE_BASE_URL}/benzinga/v2/news", params={"tickers": ticker, "limit": 10}, timeout=15)
        BREAKER.record_failure("massive_benzinga_news") if data is None else BREAKER.record_success("massive_benzinga_news")
        rows = rows_from_tool_response(data)
        if rows:
            return rows
    else:
        BREAKER.record_skip("massive_benzinga_news")
    if BREAKER.is_open("polygon_reference_news"):
        BREAKER.record_skip("polygon_reference_news")
        return []
    data = safe_get_json("https://api.polygon.io/v2/reference/news", params={"ticker": ticker, "limit": 10, "order": "desc", "sort": "published_utc"}, timeout=15)
    BREAKER.record_failure("polygon_reference_news") if data is None else BREAKER.record_success("polygon_reference_news")
    return rows_from_tool_response(data)


def catalyst_layer(ticker: str) -> Dict[str, Any]:
    """Catalyst/news scoring with correct source routing for Massive/Benzinga and QuantData news."""
    score = 50.0
    notes: List[str] = []
    rows: List[dict] = []
    if BENZINGA_SOURCE == "direct" and BENZINGA_API_KEY and not BREAKER.is_open("benzinga_direct"):
        data = safe_get_json("https://api.benzinga.com/api/v2/news", params={"token": BENZINGA_API_KEY, "tickers": ticker, "pagesize": 10, "displayOutput": "full"}, timeout=15)
        BREAKER.record_failure("benzinga_direct") if data is None else BREAKER.record_success("benzinga_direct")
        rows = rows_from_tool_response(data)
        if rows:
            notes.append(f"{len(rows[:10])} recent direct Benzinga headlines")
    else:
        rows = massive_benzinga_news_rows(ticker)
        if rows:
            notes.append(f"{len(rows[:10])} Massive/Benzinga or Polygon news headlines")
        else:
            rows = quantdata_news_rows(ticker)
            if rows:
                notes.append(f"{len(rows[:10])} QuantData news articles")
    if not rows:
        notes.append("No catalyst rows returned; catalyst kept neutral")
    text_bits = []
    for r in rows[:10]:
        text_bits.append(str(r.get("title") or r.get("headline") or r.get("name") or ""))
        text_bits.append(str(r.get("summary") or r.get("description") or r.get("teaser") or ""))
    text = " ".join(text_bits).lower()
    if rows:
        score += 6
    positive_words = ["upgrade", "raises", "beat", "beats", "guidance", "contract", "approval", "launch", "partnership", "record", "growth", "buy rating", "price target raised"]
    negative_words = ["downgrade", "cuts", "miss", "probe", "lawsuit", "warning", "recall", "investigation", "delay", "price target cut", "sell rating"]
    score += sum(5 for w in positive_words if w in text)
    score -= sum(6 for w in negative_words if w in text)
    score = max(0, min(score, 100))
    status = "POSITIVE CATALYST" if score >= 65 else "NEGATIVE CATALYST" if score <= 40 else "NO MAJOR CATALYST"
    return {"catalyst_score": round(score, 1), "catalyst_status": status, "catalyst_notes": notes[:4]}


def quantdata_dark_pool_layer(ticker: str) -> Dict[str, Any]:
    """QuantData dark-flow layer using /v1/equities/tool/dark-flow."""
    if not QUANTDATA_API_KEY or not DARK_POOL_ENDPOINT_ENABLED:
        return {"dark_pool_score": 50.0, "dark_pool_status": "NEUTRAL - DARK FLOW NOT CONFIGURED", "dark_pool_notional": 0, "dark_pool_notes": ["Set QUANTDATA_API_KEY and DARK_POOL_ENDPOINT_ENABLED=true to activate QuantData dark-flow."]}
    if BREAKER.is_open("quantdata_dark_flow"):
        BREAKER.record_skip("quantdata_dark_flow")
        return {"dark_pool_score": 50.0, "dark_pool_status": "NEUTRAL - CIRCUIT OPEN (repeated failures this scan)", "dark_pool_notional": 0, "dark_pool_notes": ["quantdata_dark_flow skipped after repeated failures this scan cycle."]}
    headers = {"Authorization": f"Bearer {QUANTDATA_API_KEY}", "Content-Type": "application/json"}
    payload = {"filter": {"ticker": ticker}}
    data = safe_post_json(f"{QUANTDATA_BASE_URL}/equities/tool/dark-flow", payload, headers=headers, timeout=18)
    BREAKER.record_failure("quantdata_dark_flow") if data is None else BREAKER.record_success("quantdata_dark_flow")
    rows = rows_from_tool_response(data)
    if not rows:
        return {"dark_pool_score": 50.0, "dark_pool_status": "NEUTRAL - NO DARK FLOW ROWS", "dark_pool_notional": 0, "dark_pool_notes": ["QuantData dark-flow returned no rows or is unavailable for this ticker/session."]}
    total_notional = 0.0
    trade_count = 0.0
    for row in rows:
        notional = safe_float(row.get("notionalValue") or row.get("notional") or row.get("value") or row.get("amount"))
        price = safe_float(row.get("stockPrice") or row.get("price") or row.get("avgPrice"))
        size = safe_float(row.get("size") or row.get("shares") or row.get("volume"))
        if notional <= 0 and price > 0 and size > 0:
            notional = price * size
        total_notional += notional
        trade_count += safe_float(row.get("tradeCount") or row.get("trades") or 0)
    score = max(0, min(100, 50 + min(total_notional / 10_000_000, 28) + min(trade_count / 50, 7))) if total_notional > 0 else 50.0
    status = "DARK FLOW ACCUMULATION" if score >= 65 else "LOW DARK FLOW" if score <= 45 else "MIXED/NEUTRAL DARK FLOW"
    return {"dark_pool_score": round(score, 1), "dark_pool_status": status, "dark_pool_notional": round(total_notional, 0), "dark_pool_notes": [f"QuantData dark-flow notional ${total_notional:,.0f}", f"Rows analyzed: {len(rows)}", f"Trade count: {trade_count:.0f}"]}


def quantdata_dark_pool_levels_layer(ticker: str, price: float) -> Dict[str, Any]:
    """QuantData dark-pool levels layer using /v1/equities/tool/dark-pool-levels.

    Per QuantData's docs (api/docs/endpoints/dark-pool-levels), this endpoint:
      - requires a top-level `sessionDateRange.startDate` (NOT `sessionDate` --
        sending `sessionDate` here returns HTTP 400 ValidationFailure every time).
      - returns `data` as an object keyed by price-level string (e.g. "215.00"),
        not a list of rows with a `price`/`level` field. The level itself is the
        dict key, so it has to be parsed out explicitly rather than read off a row.
    """
    if not QUANTDATA_API_KEY or not DARK_POOL_LEVELS_ENABLED:
        return {"dark_pool_levels_score": 50.0, "dark_pool_levels_status": "NEUTRAL - LEVELS NOT CONFIGURED", "nearest_dark_pool_level": None, "dark_pool_levels_notes": ["Set DARK_POOL_LEVELS_ENABLED=true and QUANTDATA_API_KEY to activate dark-pool levels."]}
    if BREAKER.is_open("quantdata_dark_pool_levels"):
        BREAKER.record_skip("quantdata_dark_pool_levels")
        return {"dark_pool_levels_score": 50.0, "dark_pool_levels_status": "NEUTRAL - CIRCUIT OPEN (repeated failures this scan)", "nearest_dark_pool_level": None, "dark_pool_levels_notes": ["quantdata_dark_pool_levels skipped after repeated failures this scan cycle."]}
    headers = {"Authorization": f"Bearer {QUANTDATA_API_KEY}", "Content-Type": "application/json"}
    start_date = (last_market_date() - dt.timedelta(days=DARK_POOL_LEVELS_LOOKBACK_DAYS)).isoformat()
    payload = {"sessionDateRange": {"startDate": start_date}, "filter": {"ticker": ticker}}
    data = safe_post_json(f"{QUANTDATA_BASE_URL}/equities/tool/dark-pool-levels", payload, headers=headers, timeout=18)
    BREAKER.record_failure("quantdata_dark_pool_levels") if data is None else BREAKER.record_success("quantdata_dark_pool_levels")
    level_map = (data or {}).get("data") if isinstance(data, dict) else None
    levels = []
    if isinstance(level_map, dict):
        for level_key, stats in level_map.items():
            level = safe_float(level_key)
            notional = safe_float((stats or {}).get("notionalValue")) if isinstance(stats, dict) else 0.0
            if level > 0:
                levels.append((level, notional))
    if not levels or price <= 0:
        return {"dark_pool_levels_score": 50.0, "dark_pool_levels_status": "NEUTRAL - NO LEVELS", "nearest_dark_pool_level": None, "dark_pool_levels_notes": ["QuantData dark-pool levels returned no usable rows."]}
    nearest = min(levels, key=lambda x: abs(x[0] - price))
    distance_pct = abs(nearest[0] - price) / price * 100
    score = max(0, min(100, 50 + max(0, 20 - distance_pct * 6) + (min(nearest[1] / 5_000_000, 10) if nearest[1] else 0)))
    status = "NEAR INSTITUTIONAL LEVEL" if score >= 65 else "NO NEARBY LEVEL" if score <= 45 else "MODERATE LEVEL PROXIMITY"
    return {"dark_pool_levels_score": round(score, 1), "dark_pool_levels_status": status, "nearest_dark_pool_level": round(nearest[0], 2), "dark_pool_levels_notes": [f"Nearest dark-pool level {nearest[0]:.2f}", f"Distance {distance_pct:.2f}%", f"Levels analyzed: {len(levels)}"]}


def institutional_accumulation_layer(direction: str, flow: Dict[str, Any], order: Dict[str, Any], dark: Dict[str, Any], levels: Dict[str, Any], cat: Dict[str, Any], rs: Dict[str, Any], tech: Dict[str, Any]) -> Dict[str, Any]:
    """APEX 3.2.2 institutional accumulation score.

    35% net-flow, 15% consolidated order-flow, 10% dark-flow, 10% dark-pool
    levels, 15% catalyst, 10% relative strength, 5% technical structure.
    """
    directional_flow = safe_float(flow.get("flow_score"), 50.0)
    order_score = safe_float(order.get("order_flow_score"), 50.0)
    if direction == "PUT":
        directional_flow = 100 - directional_flow
        order_score = 100 - order_score
    dark_score = safe_float(dark.get("dark_pool_score"), 50.0)
    levels_score = safe_float(levels.get("dark_pool_levels_score"), 50.0)
    catalyst = safe_float(cat.get("catalyst_score"), 50.0)
    rel_strength = safe_float(rs.get("relative_strength_score"), 50.0)
    technical = safe_float(tech.get("technical_score"), 50.0)
    score = directional_flow * 0.35 + order_score * 0.15 + dark_score * 0.10 + levels_score * 0.10 + catalyst * 0.15 + rel_strength * 0.10 + technical * 0.05
    score = round(max(0, min(score, 100)), 1)
    if score >= 78:
        status = "SMART MONEY ACCUMULATING"
    elif score >= MIN_ACCUMULATION_SCORE:
        status = "ACCUMULATION WATCH"
    elif score <= 40:
        status = "DISTRIBUTION / PRESSURE"
    else:
        status = "NO CLEAR ACCUMULATION"
    notes = [f"Net-flow contribution: {directional_flow:.1f}", f"Order-flow contribution: {order_score:.1f}", f"Dark-flow contribution: {dark_score:.1f}", f"Dark-pool-levels contribution: {levels_score:.1f}", f"Catalyst contribution: {catalyst:.1f}"]
    breakout = max(0, min(100, score * 0.68 + technical * 0.18 + rel_strength * 0.09 + catalyst * 0.05))
    label = "HIGH" if breakout >= 80 else "ELEVATED" if breakout >= 68 else "MODERATE" if breakout >= 55 else "LOW"
    return {"accumulation_score": score, "accumulation_status": status, "accumulation_notes": notes, "breakout_probability": round(breakout, 0), "breakout_probability_label": label}



def market_regime_layer() -> Dict[str, Any]:
    """Market regime filter using SPY, QQQ, and SMH daily trend structure."""
    scores: List[float] = []
    notes: List[str] = []
    spy_20d_return = 0.0

    for ticker in ["SPY", "QQQ", "SMH"]:
        bars = get_daily_bars(ticker, days=260)
        if len(bars) < 60:
            notes.append(f"{ticker} regime unavailable")
            continue

        closes = [safe_float(x.get("c")) for x in bars]
        price = closes[-1]
        e21 = ema(closes, 21)
        e50 = ema(closes, 50)
        e200 = ema(closes, 200) or e50

        if ticker == "SPY" and len(closes) >= 22 and closes[-21]:
            spy_20d_return = (closes[-1] - closes[-21]) / closes[-21] * 100

        if not all([price, e21, e50, e200]):
            notes.append(f"{ticker} regime incomplete")
            continue

        score = 50.0
        if price > e21:
            score += 12
        else:
            score -= 10
        if price > e50:
            score += 12
        else:
            score -= 14
        if e50 >= e200:
            score += 14
        else:
            score -= 10

        score = max(0, min(score, 100))
        scores.append(score)
        notes.append(f"{ticker} regime {score:.0f}")

    market_score = sum(scores) / len(scores) if scores else 50.0
    market_regime = "RISK ON" if market_score >= 70 else "DEFENSIVE" if market_score <= 45 else "NEUTRAL"

    return {
        "market_regime_score": round(market_score, 1),
        "market_regime": market_regime,
        "market_notes": notes,
        "spy_20d_return": round(spy_20d_return, 2),
    }


def relative_strength_score(ticker: str, daily: List[dict], spy_20d_return: float = 0.0) -> Dict[str, Any]:
    """20-day relative strength versus SPY, cached from the market-regime layer."""
    if len(daily) < 22:
        return {"relative_strength_score": 50.0, "relative_strength_notes": ["Not enough daily bars for relative strength."]}

    closes = [safe_float(x.get("c")) for x in daily]
    if closes[-21] <= 0:
        return {"relative_strength_score": 50.0, "relative_strength_notes": ["Invalid 20-day reference price."]}

    stock_20d_return = (closes[-1] - closes[-21]) / closes[-21] * 100
    spread = stock_20d_return - spy_20d_return
    score = max(0, min(100, 50 + spread * 2.5))

    return {
        "relative_strength_score": round(score, 1),
        "relative_strength_notes": [f"20D relative performance vs SPY: {spread:.1f}%"],
    }


def final_grade(score: float) -> str:
    if score >= 92:
        return "A+"
    if score >= 86:
        return "A"
    if score >= 80:
        return "B+"
    if score >= 74:
        return "B"
    return "WATCH"


def _polygon_next_page(url: Optional[str]) -> Optional[dict]:
    """Fetch a Polygon next_url page. safe_get_json adds apiKey automatically."""
    if not url:
        return None
    return safe_get_json(url, timeout=20)


def breakout_probability_layer(idea: Dict[str, Any]) -> Dict[str, Any]:
    """Forecast breakout probability from final score, accumulation, regime, distance, and volume."""
    existing = idea.get("breakout_probability")
    if existing is not None:
        try:
            existing_value = float(existing)
            existing_label = idea.get("breakout_probability_label")
            if existing_label:
                return {"breakout_probability": round(existing_value, 1), "breakout_probability_label": existing_label}
        except Exception:
            pass

    distance = safe_float(idea.get("distance_to_buy_zone_pct"), 10.0)
    final_score = safe_float(idea.get("final_score"), 50.0)
    accumulation = safe_float(idea.get("accumulation_score"), 50.0)
    rel_volume_value = safe_float(idea.get("rel_volume"), 1.0)
    regime = safe_float(idea.get("market_regime_score"), 50.0)

    distance_boost = max(0, 18 - distance * 5)
    rvol_boost = min(max(rel_volume_value - 1.0, 0) * 8, 10)
    probability = final_score * 0.42 + accumulation * 0.33 + regime * 0.10 + distance_boost + rvol_boost - 18
    probability = round(max(1, min(probability, 99)), 1)
    label = "HIGH" if probability >= 75 else "MODERATE" if probability >= 60 else "LOW"

    return {"breakout_probability": probability, "breakout_probability_label": label}

def pick_option_contract(ticker: str, direction: str, trader_type: str, price: float) -> Optional[dict]:
    contract_type = "call" if direction == "CALL" else "put"
    min_dte, max_dte = (0, 2) if trader_type == "0DTE" else (7, 45) if trader_type == "SWING" else (90, 365)
    today = now_et().date()
    exp_gte = (today + dt.timedelta(days=min_dte)).isoformat()
    exp_lte = (today + dt.timedelta(days=max_dte)).isoformat()
    url = f"https://api.polygon.io/v3/snapshot/options/{ticker}"
    params = {
        "contract_type": contract_type,
        "expiration_date.gte": exp_gte,
        "expiration_date.lte": exp_lte,
        "limit": 250,
        "sort": "expiration_date",
        "order": "asc",
    }
    data = safe_get_json(url, params=params, timeout=20)
    candidates = []
    pages_seen = 0
    while data and pages_seen < 8:
        pages_seen += 1
        for item in data.get("results", []):
            details = item.get("details", {})
            exp, strike, opt_ticker = details.get("expiration_date"), details.get("strike_price"), details.get("ticker")
            if not exp or strike is None or not opt_ticker:
                continue
            try:
                dte = (dt.date.fromisoformat(exp) - today).days
            except Exception:
                continue
            if dte < min_dte or dte > max_dte:
                continue
            quote = item.get("last_quote") or {}
            bid, ask = safe_float(quote.get("bid")), safe_float(quote.get("ask"))
            day = item.get("day") or {}
            last_trade = item.get("last_trade") or {}
            fallback = safe_float(last_trade.get("price") or day.get("close"))
            # Quote staleness: prefer the live quote's own nanosecond timestamp; if we had
            # to fall back to last trade/day close instead, use whichever of those has a
            # timestamp so an "estimated" price still gets an honest age instead of none.
            quote_ts_ns = quote.get("last_updated") or last_trade.get("sip_timestamp") or day.get("last_updated")
            quote_timeframe = quote.get("timeframe")  # Polygon flags "REAL-TIME" vs delayed plans here
            if bid <= 0 or ask <= 0:
                if fallback <= 0:
                    continue
                mid, bid, ask = fallback, fallback * 0.95, fallback * 1.05
                quote_source = "estimated"  # no live NBBO -- synthesized a +/-5% spread around last trade/close
            else:
                mid = (bid + ask) / 2
                quote_source = "live"
            spread_pct = (ask - bid) / mid if mid else 9
            if spread_pct > 0.30:
                continue
            oi = safe_float(item.get("open_interest"))
            vol = safe_float(day.get("volume"))
            strike_dist = abs(safe_float(strike) - price) / price
            # Favor near-the-money, liquid, tighter-spread contracts inside the intended DTE window.
            rank = strike_dist * 10 + spread_pct * 4 - min(oi, 2000) / 10000 - min(vol, 1000) / 10000 + abs(dte - ((min_dte + max_dte) / 2)) / 100
            greeks = item.get("greeks") or {}
            greeks_source = "live" if greeks.get("delta") is not None else "estimated"  # defaulted to 0.50 delta below if missing
            delta = abs(safe_float(greeks.get("delta"), 0.50))
            gamma = max(0.0, safe_float(greeks.get("gamma"), 0.0))
            iv = safe_float(item.get("implied_volatility"), 0.0)
            candidates.append({"ticker": opt_ticker, "label": f"{opt_ticker} {exp} {float(strike):g} {direction}", "expiration": exp, "strike": float(strike), "dte": dte, "bid": round(bid, 2), "ask": round(ask, 2), "mid": round(mid, 2), "spread_pct": round(spread_pct, 3), "open_interest": int(oi), "volume": int(vol), "delta": round(delta, 3), "gamma": round(gamma, 5), "iv": round(iv, 3), "rank": rank, "quote_source": quote_source, "greeks_source": greeks_source, "quote_timestamp_ns": int(quote_ts_ns) if quote_ts_ns else None, "quote_timeframe": quote_timeframe})
        next_url = data.get("next_url")
        data = _polygon_next_page(next_url) if next_url else None
    if not candidates:
        return None
    candidates.sort(key=lambda x: x["rank"])
    best = candidates[0]
    best["contracts_evaluated"] = len(candidates)
    return best


def confidence_size_pct(score: float) -> int:
    if score >= 92: return 100
    if score >= 86: return 70
    return 50


def estimate_option_stop_pct(option: Dict[str, Any], underlying_price: float, stock_stop: float) -> float:
    """Estimate option loss at the stock stop using snapshot Greeks when available.

    This avoids the old flat 20%-30% premium stop assumption. It uses delta/gamma
    to approximate the premium loss from the actual underlying stop distance, then
    adds a liquidity/IV cushion. The floor is intentionally low so tight, liquid
    setups are not all forced into the same 20% bucket.
    """
    option_price = safe_float(option.get("ask") or option.get("mid"))
    if option_price <= 0 or underlying_price <= 0 or stock_stop <= 0:
        return 0.0
    underlying_move = abs(underlying_price - stock_stop)
    delta = abs(safe_float(option.get("delta"), 0.50)) or 0.50
    gamma = max(0.0, safe_float(option.get("gamma"), 0.0))
    iv = max(0.0, safe_float(option.get("iv"), 0.0))
    spread_pct = max(0.0, safe_float(option.get("spread_pct"), 0.0))

    greek_loss_dollars = delta * underlying_move + 0.5 * gamma * (underlying_move ** 2)
    greek_loss_pct = greek_loss_dollars / option_price
    cushion = max(spread_pct * 1.25, min(iv * 0.04, 0.08))
    return round(max(0.08, min(0.75, greek_loss_pct + cushion)), 4)


def position_contracts(option_price: float, score: float, estimated_option_stop_pct: float) -> int:
    if option_price <= 0 or estimated_option_stop_pct <= 0:
        return 0
    allowed = MAX_RISK_PER_TRADE * (confidence_size_pct(score) / 100)
    risk_per_contract = option_price * 100 * estimated_option_stop_pct
    return max(0, int(allowed // risk_per_contract)) if risk_per_contract else 0


## ---------------------------------------------------------------------------
## Backtest tracking (Phase 1 of the historical-timing project)
##
## Forward-collection approach: every qualified idea this engine actually
## produces gets logged once (deduped against an already-open position for the
## same ticker+direction), then a daily resolution pass walks forward through
## real daily bars to see which level -- T1, T2, or stop -- got hit first, and
## how many trading days it took. Once enough resolved trades accumulate in a
## given score/direction bucket, /api/backtest_stats can report real median
## time-to-target and win rate instead of the ATR ballpark. This intentionally
## does NOT attempt to reconstruct history retroactively -- see README for why.
## ---------------------------------------------------------------------------

TRACKING_LOCK = threading.Lock()
TRACKING_AVAILABLE = False  # flipped true only after init_tracking_db() succeeds


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_tracking_db() -> None:
    """Sets up the tracking DB if possible. This must NEVER raise -- a missing/
    unmounted disk, a read-only filesystem, or any other storage problem should
    disable tracking gracefully (TRACKING_AVAILABLE stays False) rather than
    prevent the whole Flask app from booting. Backtest tracking is a nice-to-have
    layered on top of the scanner; it must never be a single point of failure for
    the scanner itself."""
    global TRACKING_AVAILABLE
    if not TRACKING_ENABLED:
        TRACKING_AVAILABLE = False
        return
    with TRACKING_LOCK:
        try:
            db_dir = os.path.dirname(DB_PATH)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
            conn = get_db_connection()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS tracked_ideas (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ticker TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        status TEXT,
                        final_score REAL,
                        technical_score REAL,
                        flow_score REAL,
                        order_flow_score REAL,
                        dark_pool_score REAL,
                        catalyst_score REAL,
                        relative_strength_score REAL,
                        accumulation_score REAL,
                        breakout_probability REAL,
                        market_regime TEXT,
                        entry_price REAL,
                        target_1_price REAL,
                        target_2_price REAL,
                        stock_stop REAL,
                        option_contract TEXT,
                        option_entry_limit REAL,
                        opened_at TEXT NOT NULL,
                        resolved_at TEXT,
                        outcome TEXT,
                        trading_days_to_resolution REAL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_tracked_open ON tracked_ideas (ticker, direction, outcome)")
                conn.commit()
            finally:
                conn.close()
            TRACKING_AVAILABLE = True
        except Exception as e:
            TRACKING_AVAILABLE = False
            print(
                f"Backtest tracking DISABLED -- could not initialize DB at '{DB_PATH}': {e}. "
                f"The rest of the app continues normally. If you intended to use a Render disk, "
                f"confirm it's mounted in the dashboard and DB_PATH matches the mount path exactly.",
                flush=True,
            )


def record_idea_if_new(idea: Dict[str, Any]) -> None:
    """Log a tracked_ideas row the first time a ticker+direction setup qualifies.
    Skips it if there's already an unresolved (OPEN) row for the same ticker+direction,
    so a setup that keeps qualifying scan after scan doesn't spawn duplicate trades."""
    if not TRACKING_ENABLED or not TRACKING_AVAILABLE or idea.get("price") is None:
        return
    with TRACKING_LOCK:
        conn = get_db_connection()
        try:
            existing = conn.execute(
                "SELECT id FROM tracked_ideas WHERE ticker=? AND direction=? AND outcome IS NULL",
                (idea["ticker"], idea["direction"]),
            ).fetchone()
            if existing:
                return
            conn.execute(
                """INSERT INTO tracked_ideas (
                    ticker, direction, status, final_score, technical_score, flow_score,
                    order_flow_score, dark_pool_score, catalyst_score, relative_strength_score,
                    accumulation_score, breakout_probability, market_regime, entry_price,
                    target_1_price, target_2_price, stock_stop, option_contract,
                    option_entry_limit, opened_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    idea["ticker"], idea["direction"], idea.get("status"), idea.get("final_score"),
                    idea.get("technical_score"), idea.get("flow_score_directional"),
                    idea.get("order_flow_score_directional"), idea.get("dark_pool_score"),
                    idea.get("catalyst_score"), idea.get("relative_strength_score"),
                    idea.get("accumulation_score"), idea.get("breakout_probability"),
                    idea.get("market_regime"), idea.get("price"), idea.get("target_1_price"),
                    idea.get("target_2_price"), idea.get("stock_stop"), idea.get("option_contract"),
                    idea.get("option_entry_limit"), dt.datetime.now(dt.timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        except Exception as e:
            print(f"record_idea_if_new error for {idea.get('ticker')}: {e}", flush=True)
        finally:
            conn.close()


def resolve_open_trades() -> int:
    """Daily pass: for every still-open tracked idea, walk forward through real
    daily bars since it was opened and check whether T1, T2, or the stop was hit
    first. Resolves the row in place. Returns how many rows were resolved."""
    if not TRACKING_ENABLED or not TRACKING_AVAILABLE:
        return 0
    resolved_count = 0
    with TRACKING_LOCK:
        conn = get_db_connection()
        try:
            open_rows = conn.execute("SELECT * FROM tracked_ideas WHERE outcome IS NULL").fetchall()
        finally:
            conn.close()

    for row in open_rows:
        try:
            opened_date = dt.datetime.fromisoformat(row["opened_at"]).date()
        except Exception:
            continue
        bars = [b for b in get_daily_bars(row["ticker"], days=TRACK_MAX_HOLD_DAYS + 10) if _bar_date(b) and _bar_date(b) > opened_date]
        bars.sort(key=lambda b: _bar_date(b))
        outcome, resolved_on, days_held = None, None, None
        for i, bar in enumerate(bars[:TRACK_MAX_HOLD_DAYS]):
            high, low = safe_float(bar.get("h")), safe_float(bar.get("l"))
            if row["direction"] == "CALL":
                hit_stop = low <= row["stock_stop"]
                hit_t2 = high >= row["target_2_price"]
                hit_t1 = high >= row["target_1_price"]
            else:
                hit_stop = high >= row["stock_stop"]
                hit_t2 = low <= row["target_2_price"]
                hit_t1 = low <= row["target_1_price"]
            # If both a target and the stop print on the same daily bar we can't tell
            # which came first intraday from daily OHLC alone -- conservatively count
            # that as the stop, since protecting against overstating win rate matters
            # more here than flattering it.
            if hit_stop:
                outcome, resolved_on, days_held = "STOP", _bar_date(bar), i + 1
                break
            if hit_t2:
                outcome, resolved_on, days_held = "T2", _bar_date(bar), i + 1
                break
            if hit_t1:
                outcome, resolved_on, days_held = "T1", _bar_date(bar), i + 1
                break
        if outcome is None and len(bars) >= TRACK_MAX_HOLD_DAYS:
            outcome, resolved_on, days_held = "EXPIRED", _bar_date(bars[TRACK_MAX_HOLD_DAYS - 1]), TRACK_MAX_HOLD_DAYS
        if outcome:
            with TRACKING_LOCK:
                conn = get_db_connection()
                try:
                    conn.execute(
                        "UPDATE tracked_ideas SET outcome=?, resolved_at=?, trading_days_to_resolution=? WHERE id=?",
                        (outcome, resolved_on.isoformat() if resolved_on else None, days_held, row["id"]),
                    )
                    conn.commit()
                finally:
                    conn.close()
            resolved_count += 1
    return resolved_count


# ═══════════════════════════════════════════════════════════════════════════════
# APEX SIGNAL-OUTCOME SPINE  (Piece Two)
# ───────────────────────────────────────────────────────────────────────────────
# Logs every actionable APEX decision with its full entry context, then samples
# price on each scan to track MFE / MAE and resolve WIN / LOSS / EXPIRED intraday.
# This is the measurement foundation for calibrated conviction and pattern memory
# — every number it produces comes from a realized outcome, never an estimate.
#
# Independent of tracked_ideas (daily swing) and trade_reviews (manual journal).
# Non-fatal by construction: any storage problem disables the spine and leaves the
# scanner untouched (SPINE_AVAILABLE stays False).
# ═══════════════════════════════════════════════════════════════════════════════
SPINE_ENABLED         = os.getenv("SPINE_ENABLED", "true").lower() == "true"
SPINE_DB_PATH         = os.getenv("SPINE_DB_PATH", DB_PATH)
SPINE_LOG_WHEN_CLOSED = os.getenv("SPINE_LOG_WHEN_CLOSED", "false").lower() == "true"
SPINE_MIN_STAGE       = os.getenv("SPINE_MIN_STAGE", "PREPARE").upper()
SPINE_MAX_HOLD_MIN    = int(os.getenv("SPINE_MAX_HOLD_MIN", "120"))   # EXPIRE after this many minutes open
SPINE_LOCK            = threading.Lock()
SPINE_AVAILABLE       = False

# Stage ordering — a signal is logged once it reaches at least SPINE_MIN_STAGE.
_SPINE_STAGE_RANK = {"WATCH": 0, "PREPARE": 1, "ARMED": 2, "EXECUTE": 3}


def _spine_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(SPINE_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_signal_spine() -> None:
    """Create the apex_signals table. Must NEVER raise — mirrors init_tracking_db."""
    global SPINE_AVAILABLE
    if not SPINE_ENABLED:
        SPINE_AVAILABLE = False
        return
    with SPINE_LOCK:
        try:
            db_dir = os.path.dirname(SPINE_DB_PATH)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
            conn = _spine_conn()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS apex_signals (
                        id            INTEGER PRIMARY KEY AUTOINCREMENT,
                        signal_id     TEXT UNIQUE,
                        ticker        TEXT NOT NULL,
                        direction     TEXT NOT NULL,
                        session_date  TEXT NOT NULL,
                        created_at    TEXT NOT NULL,
                        entry_price   REAL,
                        entry_low     REAL,
                        entry_high    REAL,
                        stop          REAL,
                        target1       REAL,
                        target2       REAL,
                        risk_points   REAL,
                        contract      TEXT,
                        stage         TEXT,
                        pine_confirmed INTEGER DEFAULT 0,
                        ici           REAL,
                        flow_score    REAL,
                        conviction    REAL,
                        context_json  TEXT,
                        status        TEXT DEFAULT 'OPEN',
                        mfe           REAL DEFAULT 0,
                        mae           REAL DEFAULT 0,
                        mfe_r         REAL DEFAULT 0,
                        mae_r         REAL DEFAULT 0,
                        last_price    REAL,
                        samples       INTEGER DEFAULT 0,
                        exit_price    REAL,
                        exit_at       TEXT,
                        exit_reason   TEXT,
                        hold_seconds  INTEGER,
                        outcome_r     REAL,
                        updated_at    TEXT
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_spine_open ON apex_signals (ticker, status)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_spine_date ON apex_signals (session_date)")
                conn.commit()
            finally:
                conn.close()
            SPINE_AVAILABLE = True
        except Exception as e:
            SPINE_AVAILABLE = False
            print(f"APEX signal spine DISABLED — could not init DB at '{SPINE_DB_PATH}': {e}. "
                  f"Scanner continues normally.", flush=True)


def _spine_num(v):
    try:
        if v is None:
            return None
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return None


def _spine_extract(ticker, result):
    """Pull the entry context out of a scan result, or None if not actionable."""
    risk = result.get("risk") or {}
    eie  = result.get("execution_intelligence") or {}
    decision = result.get("decision") or {}

    direction = str(risk.get("approved_side") or decision.get("approved_side") or "").upper()
    if direction in ("CALL", "LONG", "BULLISH"):
        direction = "CALL"
    elif direction in ("PUT", "SHORT", "BEARISH"):
        direction = "PUT"
    else:
        return None

    entry_price = _spine_num((result.get("market_state") or {}).get("price")) or _spine_num(risk.get("price"))
    stop    = _spine_num(risk.get("stop"))
    target1 = _spine_num(risk.get("target1"))
    target2 = _spine_num(risk.get("target2"))
    if entry_price is None or stop is None or target1 is None:
        return None

    stage = str(eie.get("stage") or "WATCH").upper()
    if _SPINE_STAGE_RANK.get(stage, 0) < _SPINE_STAGE_RANK.get(SPINE_MIN_STAGE, 1):
        return None

    risk_pts = _spine_num(risk.get("risk_points")) or abs(entry_price - stop)
    if not risk_pts or risk_pts <= 0:
        return None

    ici = _spine_num((result.get("ici") or {}).get("ici")) or _spine_num(result.get("confidence"))
    flow_score = _spine_num((result.get("flow") or {}).get("flow_score")) or \
                 _spine_num((result.get("flow_intelligence") or {}).get("flow_score"))
    conviction = _spine_num((result.get("consensus") or {}).get("leading_conviction")) or \
                 _spine_num(result.get("confidence"))

    ctx = {
        "gamma_regime": (result.get("gamma_regime") or {}).get("regime_label"),
        "auction_state": ((result.get("auction_intelligence") or {}).get("auction_state") or {}).get("state"),
        "session_type": ((result.get("institutional_intelligence") or {}).get("playbook") or {}).get("session_type_label"),
        "grade": result.get("grade"),
        "poc_migration": (result.get("market_state") or {}).get("poc_migration"),
        "vix": (result.get("volatility") or {}).get("vix"),
    }

    return {
        "ticker": ticker, "direction": direction, "entry_price": entry_price,
        "entry_low": _spine_num(risk.get("entry_low")), "entry_high": _spine_num(risk.get("entry_high")),
        "stop": stop, "target1": target1, "target2": target2, "risk_points": risk_pts,
        "contract": risk.get("contract_hint"), "stage": stage,
        "pine_confirmed": 1 if eie.get("pine_confirmed") else 0,
        "ici": ici, "flow_score": flow_score, "conviction": conviction,
        "context_json": json.dumps(ctx, default=str),
    }


def log_apex_signal(ticker, result, session_state):
    """Log a new signal the first time a ticker+direction setup becomes actionable.
    De-dupes against an existing OPEN row for the same ticker+direction. Returns id or None."""
    if not SPINE_AVAILABLE:
        return None
    if session_state != "MARKET_OPEN" and not SPINE_LOG_WHEN_CLOSED:
        return None
    ctx = _spine_extract(ticker, result)
    if not ctx:
        return None
    now = now_et()
    signal_id = f"{ticker}:{ctx['direction']}:{now.strftime('%Y%m%dT%H%M%S')}"
    with SPINE_LOCK:
        conn = _spine_conn()
        try:
            dup = conn.execute(
                "SELECT id FROM apex_signals WHERE ticker=? AND direction=? AND status='OPEN'",
                (ticker, ctx["direction"]),
            ).fetchone()
            if dup:
                return None
            conn.execute("""
                INSERT INTO apex_signals (
                    signal_id, ticker, direction, session_date, created_at,
                    entry_price, entry_low, entry_high, stop, target1, target2,
                    risk_points, contract, stage, pine_confirmed, ici, flow_score,
                    conviction, context_json, status, last_price, samples, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'OPEN', ?, 0, ?)
            """, (
                signal_id, ticker, ctx["direction"], now.strftime("%Y-%m-%d"), now.isoformat(),
                ctx["entry_price"], ctx["entry_low"], ctx["entry_high"], ctx["stop"],
                ctx["target1"], ctx["target2"], ctx["risk_points"], ctx["contract"],
                ctx["stage"], ctx["pine_confirmed"], ctx["ici"], ctx["flow_score"],
                ctx["conviction"], ctx["context_json"], ctx["entry_price"], now.isoformat(),
            ))
            conn.commit()
            return signal_id
        except Exception as e:
            print(f"log_apex_signal error ({ticker}): {e}", flush=True)
            return None
        finally:
            conn.close()


def update_open_signals(ticker, price, session_state):
    """Sample price for every OPEN signal on this ticker: update MFE/MAE and resolve
    WIN / LOSS / EXPIRED. Sampled resolution — if a target and the stop are both crossed
    between samples we count the stop (never overstate win rate). Returns resolved count."""
    if not SPINE_AVAILABLE:
        return 0
    price = _spine_num(price)
    resolved = 0
    now = now_et()
    with SPINE_LOCK:
        conn = _spine_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM apex_signals WHERE ticker=? AND status='OPEN'", (ticker,)
            ).fetchall()
            for row in rows:
                entry = row["entry_price"]; stop = row["stop"]
                t1 = row["target1"]; t2 = row["target2"]
                risk = row["risk_points"] or abs((entry or 0) - (stop or 0)) or 1.0
                is_call = row["direction"] == "CALL"

                fav = (price - entry) if (is_call and price is not None) else (entry - price) if price is not None else None
                mfe = row["mfe"] or 0.0
                mae = row["mae"] or 0.0
                if fav is not None:
                    if fav > mfe: mfe = fav
                    if -fav > mae: mae = -fav

                status, exit_price, exit_reason = "OPEN", None, None
                if price is not None:
                    if is_call:
                        hit_stop = price <= stop
                        hit_t2   = t2 is not None and price >= t2
                        hit_t1   = price >= t1
                    else:
                        hit_stop = price >= stop
                        hit_t2   = t2 is not None and price <= t2
                        hit_t1   = price <= t1
                    if hit_stop:
                        status, exit_price, exit_reason = "LOSS", stop, "STOP"
                    elif hit_t2:
                        status, exit_price, exit_reason = "WIN", t2, "T2"
                    elif hit_t1:
                        status, exit_price, exit_reason = "WIN", t1, "T1"

                try:
                    opened = dt.datetime.fromisoformat(row["created_at"])
                    held_s = int((now - opened).total_seconds())
                except Exception:
                    held_s = None
                session_over = session_state != "MARKET_OPEN"
                too_long = held_s is not None and held_s > SPINE_MAX_HOLD_MIN * 60
                if status == "OPEN" and (session_over or too_long):
                    status = "EXPIRED"
                    exit_price = price if price is not None else row["last_price"]
                    exit_reason = "SESSION_END" if session_over else "MAX_HOLD"

                if status == "OPEN":
                    conn.execute(
                        "UPDATE apex_signals SET mfe=?, mae=?, mfe_r=?, mae_r=?, last_price=?, "
                        "samples=samples+1, updated_at=? WHERE id=?",
                        (mfe, mae, mfe / risk, mae / risk, price, now.isoformat(), row["id"]),
                    )
                else:
                    ex = exit_price if exit_price is not None else (price if price is not None else entry)
                    signed = (ex - entry) if is_call else (entry - ex)
                    conn.execute(
                        "UPDATE apex_signals SET status=?, mfe=?, mae=?, mfe_r=?, mae_r=?, "
                        "last_price=?, samples=samples+1, exit_price=?, exit_at=?, exit_reason=?, "
                        "hold_seconds=?, outcome_r=?, updated_at=? WHERE id=?",
                        (status, mfe, mae, mfe / risk, mae / risk, price, ex, now.isoformat(),
                         exit_reason, held_s, signed / risk, now.isoformat(), row["id"]),
                    )
                    resolved += 1
            conn.commit()
        except Exception as e:
            print(f"update_open_signals error ({ticker}): {e}", flush=True)
        finally:
            conn.close()
    return resolved


def _spine_ingest(ticker, result):
    """Non-fatal per-scan hook: update open signals first (freeing a resolved slot),
    then log a fresh signal if the current read is actionable."""
    if not SPINE_AVAILABLE:
        return
    try:
        ms = result.get("market_state") or {}
        price = ms.get("price")
        session_state = (result.get("session") or {}).get("session_state") or ms.get("session_state") or session_status()
        update_open_signals(ticker, price, session_state)
        log_apex_signal(ticker, result, session_state)
    except Exception as e:
        print(f"_spine_ingest error ({ticker}): {e}", flush=True)


def signal_spine_stats(direction=None):
    """Aggregate edge statistics over resolved signals. Every figure is measured from
    realized outcomes. win_rate is over decided trades (WIN+LOSS), excluding EXPIRED."""
    empty = {
        "available": SPINE_AVAILABLE, "ready": False, "n_total": 0, "n_open": 0,
        "n_resolved": 0, "wins": 0, "losses": 0, "expired": 0, "win_rate": None,
        "avg_outcome_r": None, "avg_hold_min": None, "avg_mfe_r": None,
        "avg_mae_r": None, "min_sample_for_confidence": 20,
    }
    if not SPINE_AVAILABLE:
        return empty
    with SPINE_LOCK:
        conn = _spine_conn()
        try:
            where = "" if not direction else f" AND direction='{direction.upper()}'"
            rows = conn.execute(
                f"SELECT status, outcome_r, hold_seconds, mfe_r, mae_r FROM apex_signals WHERE 1=1{where}"
            ).fetchall()
        except Exception as e:
            print(f"signal_spine_stats error: {e}", flush=True)
            return empty
        finally:
            conn.close()

    n_open = sum(1 for r in rows if r["status"] == "OPEN")
    wins   = [r for r in rows if r["status"] == "WIN"]
    losses = [r for r in rows if r["status"] == "LOSS"]
    expired = [r for r in rows if r["status"] == "EXPIRED"]
    decided = wins + losses
    resolved = decided + expired

    def _avg(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    avg_hold_s = _avg([r["hold_seconds"] for r in resolved])
    return {
        "available": True,
        "ready": len(resolved) > 0,
        "n_total": len(rows),
        "n_open": n_open,
        "n_resolved": len(resolved),
        "wins": len(wins),
        "losses": len(losses),
        "expired": len(expired),
        "win_rate": round(100 * len(wins) / len(decided), 1) if decided else None,
        "avg_outcome_r": _avg([r["outcome_r"] for r in resolved]),
        "avg_hold_min": round(avg_hold_s / 60, 1) if avg_hold_s is not None else None,
        "avg_mfe_r": _avg([r["mfe_r"] for r in resolved]),
        "avg_mae_r": _avg([r["mae_r"] for r in resolved]),
        "min_sample_for_confidence": 20,
    }


def get_apex_signals(limit=50, status=None):
    """Return recent signals (newest first) as plain dicts for the API / Signal Log."""
    if not SPINE_AVAILABLE:
        return []
    with SPINE_LOCK:
        conn = _spine_conn()
        try:
            q = "SELECT * FROM apex_signals"
            params = ()
            if status:
                q += " WHERE status=?"; params = (status.upper(),)
            q += " ORDER BY id DESC LIMIT ?"
            params = params + (int(limit),)
            rows = conn.execute(q, params).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"get_apex_signals error: {e}", flush=True)
            return []
        finally:
            conn.close()


def _bar_date(bar: dict) -> Optional[dt.date]:
    ts = bar.get("t")
    if not ts:
        return None
    try:
        return dt.datetime.fromtimestamp(ts / 1000, tz=dt.timezone.utc).date()
    except Exception:
        return None


def score_bucket(score: float) -> str:
    if score >= 90:
        return "90-100"
    if score >= 85:
        return "85-89"
    if score >= 78:
        return "78-84"
    return "<78"


def backtest_stats() -> Dict[str, Any]:
    if not TRACKING_ENABLED or not TRACKING_AVAILABLE:
        return {"enabled": False, "buckets": []}
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM tracked_ideas WHERE outcome IS NOT NULL AND outcome != 'EXPIRED'").fetchall()
        total_open = conn.execute("SELECT COUNT(*) AS c FROM tracked_ideas WHERE outcome IS NULL").fetchone()["c"]
        total_expired = conn.execute("SELECT COUNT(*) AS c FROM tracked_ideas WHERE outcome = 'EXPIRED'").fetchone()["c"]
    finally:
        conn.close()

    grouped: Dict[Tuple[str, str], List[sqlite3.Row]] = {}
    for r in rows:
        key = (score_bucket(r["final_score"] or 0), r["direction"])
        grouped.setdefault(key, []).append(r)

    buckets = []
    for (bucket, direction), group in sorted(grouped.items()):
        n = len(group)
        wins = [r for r in group if r["outcome"] in ("T1", "T2")]
        win_rate = round(len(wins) / n * 100, 1) if n else None
        days_to_win = [r["trading_days_to_resolution"] for r in wins if r["trading_days_to_resolution"] is not None]
        days_to_stop = [r["trading_days_to_resolution"] for r in group if r["outcome"] == "STOP" and r["trading_days_to_resolution"] is not None]
        buckets.append({
            "score_bucket": bucket,
            "direction": direction,
            "n": n,
            "sufficient_sample": n >= TRACK_MIN_SAMPLE,
            "win_rate_pct": win_rate,
            "median_days_to_win": round(statistics.median(days_to_win), 1) if days_to_win else None,
            "median_days_to_stop": round(statistics.median(days_to_stop), 1) if days_to_stop else None,
        })
    return {
        "enabled": True,
        "min_sample_for_display": TRACK_MIN_SAMPLE,
        "open_positions": total_open,
        "expired_positions": total_expired,
        "buckets": buckets,
    }


def trade_plan(idea: Dict[str, Any]) -> Dict[str, Any]:
    trader_type, direction, score, price, atr_value = idea["trader_type"], idea["direction"], idea["final_score"], idea["price"], idea["atr"]
    if direction == "CALL":
        stock_stop = price - max(atr_value * 0.8, price * 0.015)
        t1 = price + max(atr_value * 1.0, price * 0.02)
        t2 = price + max(atr_value * 1.8, price * 0.035)
    else:
        stock_stop = price + max(atr_value * 0.8, price * 0.015)
        t1 = price - max(atr_value * 1.0, price * 0.02)
        t2 = price - max(atr_value * 1.8, price * 0.035)

    # Rough, explicitly approximate timing estimate: trading days = price distance /
    # daily ATR. This assumes an average-volatility day in a straight line toward the
    # target, which real breakouts/accumulation moves rarely do -- it's a scale-of-patience
    # ballpark (e.g. "expect low single-digit days"), not a forecast of when it'll trigger
    # or how long to hold. There is no model here for *when* the trigger condition fires.
    atr_days_t1 = round(abs(t1 - price) / atr_value, 1) if atr_value > 0 else None
    atr_days_t2 = round(abs(t2 - price) / atr_value, 1) if atr_value > 0 else None
    atr_days_stop = round(abs(price - stock_stop) / atr_value, 1) if atr_value > 0 else None

    return {
        "confirmation_trigger": "Enter only after 5-min reclaim/rejection of VWAP/EMA8 with volume expansion; no chase outside the zone.",
        "entry_range": f"{idea['buy_zone_low']:.2f} - {idea['buy_zone_high']:.2f}",
        "stock_stop": round(stock_stop, 2),
        "target_1_price": round(t1, 2),
        "target_2_price": round(t2, 2),
        "targets": ["Fast profit: +20% option gain", "Target 1: +30% to +40% option gain", "Target 2: +60% to +100% option gain if trend holds"],
        "stop_loss": "Option hard stop -25% to -35%, or stock invalidates the listed stock stop.",
        "time_stop": "Swing: reduce/exit if no follow-through in 2-3 sessions. 0DTE: hard exit by 3:30 PM ET.",
        "position_plan": "Scale size by conviction; protect gains fast, leave runner only while EMA/VWAP trend holds.",
        "atr_days_to_t1": atr_days_t1,
        "atr_days_to_t2": atr_days_t2,
        "atr_days_to_stop": atr_days_stop,
    }


def analyze_ticker(ticker: str, regime: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    daily = get_daily_bars(ticker)
    intraday = get_intraday_bars(ticker, 5, 3)
    tech = technical_layer(ticker, daily, intraday)
    if not tech or tech["direction"] == "NEUTRAL":
        return None, {"ticker": ticker, "direction": (tech or {}).get("direction", "NEUTRAL"), "excluded_reason": "No directional technical setup (NEUTRAL or insufficient bars)."}
    flow = quantdata_flow_layer(ticker)
    order = quantdata_order_flow_layer(ticker)
    dark = quantdata_dark_pool_layer(ticker)
    levels = quantdata_dark_pool_levels_layer(ticker, tech["price"])
    cat = catalyst_layer(ticker)
    rs = relative_strength_score(ticker, daily, safe_float(regime.get("spy_20d_return")))
    accumulation = institutional_accumulation_layer(tech["direction"], flow, order, dark, levels, cat, rs, tech)

    # Direction-aware flow: a low call ratio can support put ideas.
    flow_score = flow["flow_score"]
    if tech["direction"] == "PUT":
        flow_score = 100 - flow_score

    order_score = safe_float(order.get("order_flow_score"), 50.0)
    if tech["direction"] == "PUT":
        order_score = 100 - order_score
    final = (
        tech["technical_score"] * 0.20 +
        flow_score * 0.28 +
        order_score * 0.12 +
        cat["catalyst_score"] * 0.13 +
        rs["relative_strength_score"] * 0.10 +
        regime["market_regime_score"] * 0.07 +
        accumulation["accumulation_score"] * 0.10
    )
    if regime["market_regime"] == "DEFENSIVE" and tech["direction"] == "CALL":
        final -= 5
    final = round(max(0, min(final, 100)), 1)
    debug = {
        "ticker": ticker,
        "direction": tech["direction"],
        "final_score": final,
        "technical_score": tech["technical_score"],
        "flow_score": round(flow_score, 1),
        "order_flow_score": round(order_score, 1),
        "dark_pool_score": dark.get("dark_pool_score"),
        "dark_pool_levels_score": levels.get("dark_pool_levels_score"),
        "catalyst_score": cat["catalyst_score"],
        "relative_strength_score": rs["relative_strength_score"],
        "accumulation_score": accumulation["accumulation_score"],
        "buy_zone_status": tech.get("buy_zone_status"),
        "distance_to_buy_zone_pct": tech.get("distance_to_buy_zone_pct"),
    }
    if final < MIN_FINAL_SCORE:
        debug["excluded_reason"] = f"final_score {final} below MIN_FINAL_SCORE {MIN_FINAL_SCORE}"
        return None, debug
    debug["excluded_reason"] = None

    approaching = tech["distance_to_buy_zone_pct"] <= PREBREAKOUT_DISTANCE_PCT and "INSIDE" not in tech["buy_zone_status"] and (final >= MIN_ALERT_SCORE - 5 or accumulation["accumulation_score"] >= MIN_ACCUMULATION_SCORE)
    ready = "INSIDE BUY ZONE" in tech["buy_zone_status"] and final >= MIN_ALERT_SCORE
    status = "READY - IN BUY ZONE" if ready else "PRE-BREAKOUT WATCHLIST" if approaching else "ACCUMULATION WATCHLIST" if accumulation["accumulation_score"] >= MIN_ACCUMULATION_SCORE else "WATCHLIST - WAIT FOR ZONE"
    trade_permission = "TRUE" if ready and session_status() == "MARKET_OPEN" else "DO NOT TRADE"
    trader_type = "0DTE" if ticker in {"SPY", "QQQ"} and session_status() == "MARKET_OPEN" else "SWING"
    if ticker not in {"SPY", "QQQ"} and final >= 88 and tech["price"] > tech["ema200"]:
        trader_type = "SWING/LEAP CANDIDATE"

    idea = {**tech, **flow, **order, **dark, **levels, **cat, **rs, **regime, **accumulation}
    idea.update({
        "ticker": ticker,
        "grade": final_grade(final),
        "final_score": final,
        "conviction_score": final,
        "flow_score_directional": round(flow_score, 1),
        "order_flow_score_directional": round(order_score, 1),
        "status": status,
        "trade_permission": trade_permission,
        "trader_type": trader_type,
        "strategy": "APEX 3.4.2 institutional forecast + Greek-aware risk engine",
        "no_trade_reason": "Waiting for buy-zone confirmation." if trade_permission != "TRUE" else "",
        "notes": tech["technical_notes"] + flow.get("flow_notes", []) + order.get("order_flow_notes", []) + dark.get("dark_pool_notes", []) + levels.get("dark_pool_levels_notes", []) + cat.get("catalyst_notes", []) + rs.get("relative_strength_notes", []) + accumulation.get("accumulation_notes", []),
    })
    idea.update(trade_plan(idea))
    idea.update(breakout_probability_layer(idea))

    option = pick_option_contract(ticker, tech["direction"], "SWING" if "SWING" in trader_type else "LEAP", tech["price"])
    if option:
        stop_distance_pct = abs(idea["price"] - idea["stock_stop"]) / idea["price"] if idea.get("price") else 0.0
        option_stop_pct = estimate_option_stop_pct(option, idea["price"], idea["stock_stop"])
        contracts = position_contracts(option.get("ask") or option.get("mid") or 0, final, option_stop_pct)
        idea.update({"option_contract": option["label"], "option_ticker": option["ticker"], "estimated_option_entry": option["mid"], "recommended_contracts": contracts, "confidence_size_pct": confidence_size_pct(final), "option_liquidity": f"Spread {option['spread_pct']:.1%}, OI {option['open_interest']}, Vol {option['volume']}, Delta {option.get('delta', 0):.2f}, IV {option.get('iv', 0):.1%}, evaluated {option.get('contracts_evaluated', 0)} contracts", "estimated_option_stop_pct": round(option_stop_pct * 100, 1), "sizing_basis": f"Greek-aware sizing: stock stop {stop_distance_pct:.1%} implies approx {option_stop_pct:.1%} option risk."})

        # Exact, fillable execution numbers for the option leg. This is a single-leg
        # long call/put (never a multi-leg spread), so the trade is always a DEBIT --
        # premium paid up front, max loss capped at that debit (before the stop is hit).
        entry_limit = round(option["mid"], 2)
        bid, ask = option.get("bid", 0.0), option.get("ask", 0.0)
        stop_price = round(entry_limit * (1 - option_stop_pct), 2)
        exit_fast = round(entry_limit * 1.20, 2)
        exit_t1 = round(entry_limit * 1.35, 2)
        exit_t2 = round(entry_limit * 1.80, 2)
        per_contract_debit = round(entry_limit * 100, 2)
        total_debit = round(per_contract_debit * max(contracts, 1), 2)
        quote_ts_ns = option.get("quote_timestamp_ns")
        quote_updated_at = None
        if quote_ts_ns:
            try:
                quote_updated_at = dt.datetime.fromtimestamp(quote_ts_ns / 1e9, tz=dt.timezone.utc).isoformat()
            except Exception:
                quote_updated_at = None
        idea.update({
            "trade_side": "DEBIT",
            "option_entry_limit": entry_limit,
            "option_bid": round(bid, 2),
            "option_ask": round(ask, 2),
            "option_bid_ask_spread": round(ask - bid, 2),
            "option_spread_pct": option.get("spread_pct"),
            "option_stop_price": stop_price,
            "option_exit_fast": exit_fast,
            "option_exit_target_1": exit_t1,
            "option_exit_target_2": exit_t2,
            "per_contract_debit": per_contract_debit,
            "total_debit": total_debit,
            "quote_source": option.get("quote_source", "estimated"),
            "greeks_source": option.get("greeks_source", "estimated"),
            "option_quote_updated_at": quote_updated_at,
            "option_quote_timeframe": option.get("quote_timeframe"),
        })
    else:
        idea.update({"option_contract": "No clean contract found yet", "option_ticker": None, "estimated_option_entry": None, "recommended_contracts": 0, "confidence_size_pct": confidence_size_pct(final), "option_liquidity": "Wait for liquid contract selection.", "trade_side": None, "option_entry_limit": None, "option_stop_price": None, "option_exit_fast": None, "option_exit_target_1": None, "option_exit_target_2": None, "per_contract_debit": None, "total_debit": None, "quote_source": None, "greeks_source": None, "option_quote_updated_at": None, "option_quote_timeframe": None})
    return idea, debug


def send_telegram(text: str) -> bool:
    if not SEND_TELEGRAM or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"Telegram failed: {e}", flush=True)
        return False


def maybe_alert(idea: Dict[str, Any]) -> None:
    if idea.get("final_score", 0) < MIN_ALERT_SCORE:
        return
    if not (idea.get("status") in {"READY - IN BUY ZONE", "PRE-BREAKOUT WATCHLIST", "ACCUMULATION WATCHLIST"}):
        return
    key = f"{now_et().date()}-{idea['ticker']}-{idea['direction']}-{idea['status']}"
    with SENT_ALERTS_LOCK:
        if key in SENT_ALERTS:
            return
        SENT_ALERTS.add(key)
    text = (
        f"🚨 APEX 3.3 {idea['status']}\n\n"
        f"Ticker: {idea['ticker']} | {idea['direction']} | Grade: {idea['grade']}\n"
        f"Final Score: {idea['final_score']} | Accumulation: {idea.get('accumulation_score')} | Breakout Prob: {idea.get('breakout_probability')}%\n"
        f"Flow: {idea['flow_score_directional']} | Dark: {idea.get('dark_pool_score')} | Catalyst: {idea['catalyst_score']}\n"
        f"Buy Zone: {idea['entry_range']} | Price: {idea['price']}\n"
        f"Regime: {idea['market_regime']} | Contract: {idea['option_contract']}\n"
        f"Trigger: {idea['confirmation_trigger']}\nStop: {idea['stop_loss']}"
    )
    if not send_telegram(text):
        # Sending failed -- allow a retry on a later scan instead of permanently
        # treating this idea/status as already-alerted.
        with SENT_ALERTS_LOCK:
            SENT_ALERTS.discard(key)


def run_scan_once(force: bool = False) -> bool:
    if not SCAN_LOCK.acquire(blocking=False):
        with STATE_LOCK:
            STATE["last_scan_status"] = "Scan already running; skipped duplicate request."
        return False
    scan_start = time.monotonic()
    try:
        print(f"🔥 APEX ENGINE {VERSION} SCAN START 🔥", flush=True)
        BREAKER.reset()
        with STATE_LOCK:
            STATE["last_scan_status"] = "Scan running..."
            STATE["last_error"] = None
            STATE["scan_in_progress"] = True
            STATE["scan_started_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        regime = market_regime_layer()
        universe = get_dynamic_tickers()
        ideas: List[Dict[str, Any]] = []
        debug_records: List[Dict[str, Any]] = []
        completed = 0
        with ThreadPoolExecutor(max_workers=max(1, SCAN_WORKERS), thread_name_prefix="apex-ticker") as pool:
            futures = {pool.submit(analyze_ticker, ticker, regime): ticker for ticker in universe}
            for future in as_completed(futures):
                ticker = futures[future]
                completed += 1
                try:
                    idea, debug = future.result()
                    debug_records.append(debug)
                    if idea:
                        ideas.append(idea)
                        maybe_alert(idea)
                        record_idea_if_new(idea)
                except Exception as e:
                    debug_records.append({"ticker": ticker, "excluded_reason": f"Exception during analysis: {e}"})
                    print(f"Error scanning {ticker}: {e}", flush=True)
                if completed % 10 == 0 or completed == len(universe):
                    with STATE_LOCK:
                        STATE["last_scan_status"] = f"Scan running... {completed}/{len(universe)} tickers analyzed"
        ideas.sort(key=lambda x: (x.get("status") == "READY - IN BUY ZONE", x.get("status") == "PRE-BREAKOUT WATCHLIST", x.get("status") == "ACCUMULATION WATCHLIST", x.get("breakout_probability", 0), x.get("final_score", 0)), reverse=True)
        # Closest-to-qualifying tickers, even when nothing actually qualified -- sorted
        # by final_score descending so you can see how close the scan got to MIN_FINAL_SCORE.
        near_misses = sorted(
            [d for d in debug_records if d.get("final_score") is not None],
            key=lambda d: d.get("final_score", 0), reverse=True,
        )[:10]
        duration = round(time.monotonic() - scan_start, 1)
        with STATE_LOCK:
            STATE.update({
                "mode": VERSION,
                "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "updated_at_et": now_et().strftime("%Y-%m-%d %I:%M:%S %p ET"),
                "session": session_status(),
                "ticker_universe": universe,
                "ticker_count": len(universe),
                "market_regime": regime,
                "ideas": ideas,
                "scan_debug": near_misses,
                "last_scan_status": f"Scan complete in {duration}s. Qualified ideas: {len(ideas)}",
                "last_error": None,
                "scanner_started": SCANNER_STARTED,
                "scan_in_progress": False,
                "last_scan_duration_seconds": duration,
                "circuit_breaker": BREAKER.snapshot(),
                # last_result is populated by /api/institutional_os, not the scanner
            })
            status = STATE["last_scan_status"]
        print(status, flush=True)
        return True
    except Exception as e:
        with STATE_LOCK:
            STATE["last_error"] = str(e)
            STATE["last_scan_status"] = "Scan failed"
            STATE["scan_in_progress"] = False
        print(f"Fatal scan error: {e}", flush=True)
        return False
    finally:
        SCAN_LOCK.release()


def scanner_loop() -> None:
    with STATE_LOCK:
        STATE["scanner_heartbeat_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        STATE["scanner_thread_alive"] = True
    init_tracking_db()
    last_resolution_date: Optional[dt.date] = None
    time.sleep(2)
    while True:
        with STATE_LOCK:
            STATE["scanner_heartbeat_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            run_scan_once()
        except Exception as e:
            # run_scan_once() already catches its own exceptions internally. This is a
            # last-resort backstop: if something still slips through (or raises outside
            # that try, e.g. during lock acquisition), it must not be allowed to kill
            # this thread silently. Without this, a dead thread looks identical to a
            # slow one -- STATE just freezes on "first scan pending" forever with no
            # last_error to explain why.
            with STATE_LOCK:
                STATE["last_error"] = f"Scanner thread error (recovered): {e}"
                STATE["last_scan_status"] = "Scanner hit an unexpected error; will retry next cycle."
                STATE["scan_in_progress"] = False
            print(f"Scanner loop exception (recovered, thread continues): {e}", flush=True)
        today = now_et().date()
        if TRACKING_ENABLED and today != last_resolution_date:
            try:
                resolved = resolve_open_trades()
                last_resolution_date = today
                if resolved:
                    print(f"Backtest tracking: resolved {resolved} trade(s) today.", flush=True)
            except Exception as e:
                print(f"resolve_open_trades error (recovered): {e}", flush=True)
        time.sleep(SCAN_INTERVAL_SECONDS)


def start_background_scanner() -> None:
    global SCANNER_STARTED
    if os.getenv("DISABLE_BACKGROUND_SCANNER", "false").lower() == "true":
        return
    with SCANNER_START_LOCK:
        if SCANNER_STARTED:
            return
        SCANNER_STARTED = True
        with STATE_LOCK:
            STATE["scanner_started"] = True
            STATE["scanner_thread_alive"] = False
            STATE["scanner_heartbeat_at"] = None
            STATE["last_scan_status"] = "Background scanner started; first scan pending..."
        threading.Thread(target=scanner_loop, name="apex-scanner", daemon=True).start()


# =============================================================================
# APEX 4.5 INSTITUTIONAL OS — NEW ENGINES
# Additive layer on top of 3.5.1. All existing functions preserved above.
# =============================================================================

VERSION_45 = VERSION
STATIC_ASSET_VERSION = VERSION.replace(".", "_")

# ---------------------------------------------------------------------------
# New env vars for v4.5 features
# ---------------------------------------------------------------------------
STORY_ENABLED = os.getenv("STORY_ENABLED", "true").lower() == "true"
HEATMAP_TICKERS = [x.strip().upper() for x in os.getenv("HEATMAP_TICKERS", "SPX,SPY,QQQ,NVDA,TSLA,IWM").split(",") if x.strip()]
POSITION_MONITOR_ENABLED = os.getenv("POSITION_MONITOR_ENABLED", "true").lower() == "true"
GAMEPLAN_TICKERS = [x.strip().upper() for x in os.getenv("GAMEPLAN_TICKERS", "SPX,SPY,QQQ").split(",") if x.strip()]

# In-memory store for the position monitor (does not need persistence across restarts)
ACTIVE_POSITION: Dict[str, Any] = {}
ACTIVE_POSITION_LOCK = threading.RLock()

# In-memory store for the daily game plan (refreshed each premarket)
DAILY_GAMEPLAN: Dict[str, Any] = {}
DAILY_GAMEPLAN_LOCK = threading.RLock()

# ---------------------------------------------------------------------------
# Confidence Decay Engine
# Scores decay over time after a signal. Returned by /api/assistant already
# via signal_seconds_remaining; this adds a richer decay curve.
# ---------------------------------------------------------------------------

def confidence_decay(base_confidence: float, signal_age_secs: int, ttl_secs: int) -> Dict[str, Any]:
    """
    Applies exponential-style decay to a base confidence score.
    Returns current confidence, % remaining, and a decay status label.
    """
    if ttl_secs <= 0 or signal_age_secs < 0:
        return {
            "base_confidence": round(base_confidence, 1),
            "current_confidence": round(base_confidence, 1),
            "decay_pct": 100.0,
            "time_remaining_secs": 0,
            "decay_status": "NO_SIGNAL",
        }
    elapsed_ratio = min(1.0, signal_age_secs / ttl_secs)
    # Non-linear decay: fast initial drop, slower toward expiry
    # At 0% elapsed → 100% confidence, at 50% elapsed → ~75%, at 100% → 0%
    decay_factor = 1.0 - (elapsed_ratio ** 0.6)
    current = round(base_confidence * decay_factor, 1)
    time_remaining = max(0, ttl_secs - signal_age_secs)
    if elapsed_ratio >= 1.0:
        status = "EXPIRED"
    elif elapsed_ratio >= 0.75:
        status = "FADING"
    elif elapsed_ratio >= 0.50:
        status = "WEAKENING"
    elif elapsed_ratio >= 0.25:
        status = "ACTIVE"
    else:
        status = "FRESH"
    return {
        "base_confidence": round(base_confidence, 1),
        "current_confidence": current,
        "decay_pct": round(decay_factor * 100, 1),
        "time_remaining_secs": time_remaining,
        "decay_status": status,
        "elapsed_ratio": round(elapsed_ratio, 3),
    }


# ---------------------------------------------------------------------------
# Institutional Story Engine
# The killer feature: turns raw data into a timestamped narrative.
# ---------------------------------------------------------------------------

def build_institutional_story(ticker: str, flow_item: Dict[str, Any], signal: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Builds a timestamped institutional narrative from flow/gex/order data.
    Instead of showing numbers, it tells the story of what institutions are doing.
    Each chapter has a timestamp (wall-clock ET), a short description, a color
    (green=bullish, blue=informational, amber=caution, red=bearish), and a
    significance weight.
    """
    now = now_et()
    story_chapters: List[Dict[str, Any]] = []
    narrative_lines: List[str] = []
    bias = (flow_item.get("bias") or "MIXED").upper()
    approved_side = (flow_item.get("approved_side") or "NONE").upper()
    alignment = safe_float(flow_item.get("institutional_alignment"), 0.0)
    flow_score = safe_float(flow_item.get("flow_score"), 50.0)
    order_score = safe_float(flow_item.get("order_flow_score"), 50.0)
    gex_score = safe_float(flow_item.get("gex_score"), 50.0)
    net_premium = safe_float(flow_item.get("net_premium"), 0.0)
    sweep_count = safe_float(flow_item.get("sweep_count"), 0)
    call_wall = flow_item.get("call_wall")
    put_wall = flow_item.get("put_wall")
    zero_gamma = flow_item.get("zero_gamma")
    stock_price = flow_item.get("stock_price")

    # Chapter 1: Opening institutional position
    if net_premium != 0:
        side_word = "accumulating" if net_premium > 0 else "distributing"
        premium_abs = abs(net_premium)
        size_label = "aggressively" if premium_abs > 10_000_000 else "steadily" if premium_abs > 2_000_000 else "quietly"
        color = "#0ca30c" if net_premium > 0 else "#e34948"
        story_chapters.append({
            "time": now.strftime("%H:%M"),
            "chapter": "Net flow",
            "text": f"Institutions {size_label} {side_word} on {ticker}. Net premium {'+' if net_premium > 0 else ''}{net_premium:,.0f}.",
            "color": color,
            "significance": min(abs(net_premium) / 5_000_000, 3.0),
        })
        narrative_lines.append(f"Institutions are {side_word} at a net {'+' if net_premium > 0 else ''}{net_premium / 1_000_000:.1f}M premium level.")

    # Chapter 2: GEX / dealer positioning
    if gex_score >= 60:
        gex_narrative = f"Dealers are long gamma, creating a magnetic pin effect near {zero_gamma or stock_price}."
        color = "#2a78d6"
        story_chapters.append({
            "time": now.strftime("%H:%M"),
            "chapter": "Gamma positioning",
            "text": gex_narrative,
            "color": color,
            "significance": 2.0,
        })
        narrative_lines.append(gex_narrative)
    elif gex_score <= 40:
        gex_narrative = f"Dealers are short gamma — price can trend more freely. Expect larger intraday swings."
        story_chapters.append({
            "time": now.strftime("%H:%M"),
            "chapter": "Gamma positioning",
            "text": gex_narrative,
            "color": "#fab219",
            "significance": 2.0,
        })
        narrative_lines.append(gex_narrative)

    # Chapter 3: Call/Put walls as context
    if call_wall and put_wall and stock_price:
        dist_to_call = round(abs(call_wall - stock_price), 2)
        dist_to_put = round(abs(stock_price - put_wall), 2)
        wall_text = f"Call wall at {call_wall} (+{dist_to_call} pts). Put wall at {put_wall} (-{dist_to_put} pts)."
        story_chapters.append({
            "time": now.strftime("%H:%M"),
            "chapter": "Key levels",
            "text": wall_text,
            "color": "#2a78d6",
            "significance": 1.5,
        })
        narrative_lines.append(f"Price is range-bound between the put wall ({put_wall}) and call wall ({call_wall}).")

    # Chapter 4: Order flow (sweeps, large prints)
    if order_score >= 70:
        sweep_text = f"Order flow is directionally bullish." if bias == "BULLISH" else "Order flow is directionally bearish."
        if sweep_count >= 5:
            sweep_text += f" {int(sweep_count)} sweeps detected — aggressive institutional urgency."
        story_chapters.append({
            "time": now.strftime("%H:%M"),
            "chapter": "Order flow",
            "text": sweep_text,
            "color": "#0ca30c" if bias == "BULLISH" else "#e34948",
            "significance": 2.5,
        })
        narrative_lines.append(sweep_text)
    elif order_score <= 35:
        story_chapters.append({
            "time": now.strftime("%H:%M"),
            "chapter": "Order flow",
            "text": "Order flow is weak or opposing. Institutional confirmation is absent.",
            "color": "#e34948",
            "significance": 1.5,
        })

    # Chapter 5: Fresh Pine trigger (if signal present)
    if signal and signal_is_fresh(signal):
        sig_side = (signal.get("signal") or signal.get("side") or "NONE").upper()
        sig_score = safe_float(signal.get("score"), 0.0)
        remaining = signal_seconds_remaining(signal)
        if sig_side in ("CALL", "PUT") and approved_side == sig_side:
            story_chapters.append({
                "time": signal.get("received_at_et", now.strftime("%H:%M:%S ET")).split(" ")[1][:5] if signal.get("received_at_et") else now.strftime("%H:%M"),
                "chapter": "Pine trigger",
                "text": f"Pine fired a {sig_side} signal (score {sig_score:g}). Institutional side agrees. Countdown: {remaining}s.",
                "color": "#0ca30c",
                "significance": 3.0,
            })
            narrative_lines.append(f"Pine trigger confirmed on the {sig_side} side with {remaining}s remaining.")
        elif sig_side in ("CALL", "PUT") and approved_side != sig_side:
            story_chapters.append({
                "time": signal.get("received_at_et", now.strftime("%H:%M:%S ET")).split(" ")[1][:5] if signal.get("received_at_et") else now.strftime("%H:%M"),
                "chapter": "Pine trigger — REJECTED",
                "text": f"Pine fired {sig_side} but institutions approve {approved_side}. Signal rejected.",
                "color": "#e34948",
                "significance": 3.0,
            })
            narrative_lines.append(f"Pine {sig_side} signal was rejected — institutional flow demands {approved_side}.")

    # Chapter 6: Overall institutional verdict
    if approved_side in ("CALL", "PUT"):
        verdict_text = f"Institutional verdict: {approved_side}S. Alignment score {alignment:.0f}/100. Wait for Pine confirmation."
        verdict_color = "#0ca30c" if alignment >= 70 else "#fab219"
    else:
        verdict_text = f"Institutional verdict: NO TRADE. Mixed or insufficient institutional conviction ({alignment:.0f}/100)."
        verdict_color = "#e34948" if alignment < 40 else "#fab219"

    story_chapters.append({
        "time": now.strftime("%H:%M"),
        "chapter": "Verdict",
        "text": verdict_text,
        "color": verdict_color,
        "significance": 3.0,
    })
    narrative_lines.append(verdict_text)

    # Sort chapters by significance (most important last, for narrative flow)
    story_chapters.sort(key=lambda c: c["significance"])

    # Build the full prose narrative paragraph
    full_narrative = " ".join(narrative_lines)

    return {
        "ticker": ticker,
        "chapters": story_chapters,
        "full_narrative": full_narrative,
        "approved_side": approved_side,
        "alignment": round(alignment, 1),
        "bias": bias,
        "chapter_count": len(story_chapters),
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S ET"),
        "generated_at_iso": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Institutional Heat Map Engine
# Scores multiple tickers quickly for a side-by-side comparison.
# ---------------------------------------------------------------------------

def _heatmap_quick_score(ticker: str) -> Dict[str, Any]:
    """
    Quick institutional score for one ticker — optimized for parallel heatmap calls.
    Lighter than the full scanner; only calls Flow/GEX, not dark-pool levels or catalyst.
    """
    try:
        flow_item = quantdata_flow_snapshot(ticker)
        alignment = safe_float(flow_item.get("institutional_alignment"), 0.0)
        approved_side = flow_item.get("approved_side") or "NONE"
        decision_color = flow_item.get("decision_color") or "RED"
        bias = flow_item.get("bias") or "MIXED"
        if decision_color == "GREEN" and alignment >= 80:
            action = "ENTER"
            action_class = "enter"
        elif decision_color == "GREEN" or alignment >= 65:
            action = "WATCH"
            action_class = "watch"
        elif decision_color == "YELLOW" or alignment >= 45:
            action = "WAIT"
            action_class = "wait"
        else:
            action = "NO TRADE"
            action_class = "no"
        return {
            "ticker": ticker,
            "score": round(alignment, 0),
            "approved_side": approved_side,
            "action": action,
            "action_class": action_class,
            "bias": bias,
            "decision_color": decision_color,
            "flow_score": flow_item.get("flow_score"),
            "gex_score": flow_item.get("gex_score"),
            "call_wall": flow_item.get("call_wall"),
            "put_wall": flow_item.get("put_wall"),
            "error": None,
        }
    except Exception as e:
        return {
            "ticker": ticker, "score": 0, "approved_side": "NONE",
            "action": "ERROR", "action_class": "no", "bias": "MIXED",
            "decision_color": "RED", "flow_score": None, "gex_score": None,
            "call_wall": None, "put_wall": None, "error": str(e),
        }


def build_institutional_heatmap(tickers: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Parallel heatmap scan across multiple tickers.
    Returns sorted list (best score first) with action labels.
    """
    target_tickers = tickers or HEATMAP_TICKERS
    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(len(target_tickers), 6), thread_name_prefix="apex-heatmap") as pool:
        futures = {pool.submit(_heatmap_quick_score, t): t for t in target_tickers}
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                results.append({"ticker": futures[future], "score": 0, "action": "ERROR", "error": str(e)})
    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    best = results[0] if results else {}
    return {
        "tickers": results,
        "best_ticker": best.get("ticker"),
        "best_score": best.get("score"),
        "best_action": best.get("action"),
        "generated_at": now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
        "generated_at_iso": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Daily Game Plan Engine
# Pre-market or early session bias summary for the day.
# ---------------------------------------------------------------------------

def build_daily_gameplan(tickers: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Generates the daily institutional game plan before or at open.
    Aggregates Flow/GEX for primary tickers and produces:
    - Today's bias (BULLISH / BEARISH / MIXED)
    - Key levels to watch
    - Best window estimate (based on session position)
    - Expected volatility label (from GEX scores)
    - Watchlist for the day
    """
    target = tickers or GAMEPLAN_TICKERS
    session_ctx = market_session_context()
    heatmap = build_institutional_heatmap(target)
    items = heatmap.get("tickers", [])

    # Aggregate bias
    bullish_count = sum(1 for i in items if i.get("approved_side") == "CALL")
    bearish_count = sum(1 for i in items if i.get("approved_side") == "PUT")
    total = len(items) or 1
    if bullish_count / total >= 0.60:
        today_bias = "BULLISH"
        bias_color = "#0ca30c"
    elif bearish_count / total >= 0.60:
        today_bias = "BEARISH"
        bias_color = "#e34948"
    else:
        today_bias = "MIXED"
        bias_color = "#fab219"

    # Aggregate GEX for expected volatility
    gex_scores = [safe_float(i.get("gex_score"), 50.0) for i in items]
    avg_gex = sum(gex_scores) / len(gex_scores) if gex_scores else 50.0
    if avg_gex >= 65:
        expected_vol = "LOW — Dealers long gamma, expect chop/pin"
    elif avg_gex <= 35:
        expected_vol = "HIGH — Dealers short gamma, expect trend moves"
    else:
        expected_vol = "MEDIUM — Mixed gamma, moderate expected range"

    # Best window: use session context
    n = now_et()
    hour = n.hour
    if hour < 10:
        best_window = "9:45 – 10:30 (first hour momentum)"
    elif hour < 12:
        best_window = "Current: midmorning. Best remaining: 11:00 – 11:45"
    elif hour < 14:
        best_window = "Midday chop zone. Wait for 2:00 PM ET re-acceleration"
    else:
        best_window = "2:00 – 3:30 PM ET power hour"

    # Key levels from primary ticker (first in list)
    primary = items[0] if items else {}
    key_levels = []
    if primary.get("call_wall"):
        key_levels.append({"label": "Call wall", "value": primary["call_wall"], "ticker": primary.get("ticker", "")})
    if primary.get("put_wall"):
        key_levels.append({"label": "Put wall", "value": primary["put_wall"], "ticker": primary.get("ticker", "")})

    # Watchlist: tickers with ENTER or WATCH action
    watchlist = [i for i in items if i.get("action") in ("ENTER", "WATCH")]

    plan = {
        "date": now_et().strftime("%Y-%m-%d"),
        "generated_at": now_et().strftime("%H:%M ET"),
        "session": session_ctx.get("session"),
        "today_bias": today_bias,
        "bias_color": bias_color,
        "expected_volatility": expected_vol,
        "best_window": best_window,
        "key_levels": key_levels,
        "watchlist": watchlist,
        "tickers_analyzed": len(items),
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "avg_gex_score": round(avg_gex, 1),
        "heatmap": items,
    }

    with DAILY_GAMEPLAN_LOCK:
        DAILY_GAMEPLAN.update(plan)

    return plan


# ---------------------------------------------------------------------------
# Position Monitor Engine
# After entry, monitors the open position against live flow and GEX.
# ---------------------------------------------------------------------------

def set_active_position(ticker: str, side: str, entry_price: float, stop: float, target1: float, target2: float) -> Dict[str, Any]:
    """Record an open position for monitoring."""
    pos = {
        "ticker": ticker.upper(),
        "side": side.upper(),
        "entry_price": entry_price,
        "stop": stop,
        "target1": target1,
        "target2": target2,
        "entered_at": now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
        "entered_at_iso": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "OPEN",
        "last_checked_at": None,
        "last_recommendation": None,
    }
    with ACTIVE_POSITION_LOCK:
        ACTIVE_POSITION.update(pos)
    return pos


def monitor_active_position() -> Dict[str, Any]:
    """
    Checks the currently tracked position against live Flow/GEX.
    Returns: HOLD, TAKE_PARTIAL, EXIT, or NO_POSITION.
    """
    with ACTIVE_POSITION_LOCK:
        pos = dict(ACTIVE_POSITION)

    if not pos or pos.get("status") != "OPEN":
        return {"status": "NO_POSITION", "recommendation": "No active position being tracked."}

    ticker = pos["ticker"]
    side = pos["side"]
    entry = safe_float(pos.get("entry_price"), 0.0)
    stop = safe_float(pos.get("stop"), 0.0)
    t1 = safe_float(pos.get("target1"), 0.0)
    t2 = safe_float(pos.get("target2"), 0.0)

    flow_item = quantdata_flow_snapshot(ticker)
    current_price = safe_float(flow_item.get("stock_price") or flow_item.get("zero_gamma"), 0.0)
    approved_side = (flow_item.get("approved_side") or "NONE").upper()
    alignment = safe_float(flow_item.get("institutional_alignment"), 0.0)
    gex_score = safe_float(flow_item.get("gex_score"), 50.0)

    reasons = []
    recommendation = "HOLD"
    priority = "INFO"

    # Check if flow has flipped against us
    if approved_side != side and approved_side in ("CALL", "PUT"):
        reasons.append(f"Flow/GEX now approves {approved_side}, opposing our {side} position.")
        recommendation = "EXIT"
        priority = "URGENT"

    # Check alignment drop
    if alignment < 45:
        reasons.append(f"Institutional alignment dropped to {alignment:.0f}/100 — conviction is fading.")
        recommendation = "TAKE_PARTIAL" if recommendation == "HOLD" else recommendation
        priority = "WARNING" if priority == "INFO" else priority

    # Check GEX flip risk
    if gex_score <= 35 and side == "CALL":
        reasons.append("Dealers are now short gamma — directional protection is weakening.")
        recommendation = "TAKE_PARTIAL" if recommendation == "HOLD" else recommendation

    # Price target checks (if we have current price)
    if current_price > 0 and entry > 0:
        if side == "CALL":
            if current_price >= t2:
                reasons.append(f"Price {current_price:.2f} has reached Target 2 ({t2:.2f}).")
                recommendation = "EXIT"
                priority = "URGENT"
            elif current_price >= t1:
                reasons.append(f"Price {current_price:.2f} has reached Target 1 ({t1:.2f}). Consider partials.")
                recommendation = "TAKE_PARTIAL" if recommendation == "HOLD" else recommendation
            elif current_price <= stop:
                reasons.append(f"Price {current_price:.2f} has hit stop ({stop:.2f}).")
                recommendation = "EXIT"
                priority = "URGENT"
        elif side == "PUT":
            if current_price <= t2:
                reasons.append(f"Price {current_price:.2f} has reached Target 2 ({t2:.2f}).")
                recommendation = "EXIT"
                priority = "URGENT"
            elif current_price <= t1:
                reasons.append(f"Price {current_price:.2f} has reached Target 1 ({t1:.2f}). Consider partials.")
                recommendation = "TAKE_PARTIAL" if recommendation == "HOLD" else recommendation
            elif current_price >= stop:
                reasons.append(f"Price {current_price:.2f} has hit stop ({stop:.2f}).")
                recommendation = "EXIT"
                priority = "URGENT"

    if not reasons:
        reasons.append("Flow/GEX remains aligned. Institutional support intact. Hold.")

    result = {
        "status": "MONITORING",
        "position": pos,
        "current_price": current_price,
        "approved_side": approved_side,
        "alignment": alignment,
        "gex_score": gex_score,
        "recommendation": recommendation,
        "priority": priority,
        "reasons": reasons,
        "checked_at": now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
        "flow_snapshot": {
            "bias": flow_item.get("bias"),
            "decision_color": flow_item.get("decision_color"),
            "flow_score": flow_item.get("flow_score"),
            "order_flow_score": flow_item.get("order_flow_score"),
        },
    }

    with ACTIVE_POSITION_LOCK:
        ACTIVE_POSITION["last_checked_at"] = result["checked_at"]
        ACTIVE_POSITION["last_recommendation"] = recommendation

    return result


# ---------------------------------------------------------------------------
# Performance Dashboard Engine (pulls from tracking DB)
# ---------------------------------------------------------------------------

def build_performance_dashboard() -> Dict[str, Any]:
    """
    Builds a comprehensive performance summary from the tracking DB.
    Returns win rate, average hold, best setup, PnL estimates.
    This is the /api/performance endpoint response.
    """
    if not TRACKING_ENABLED or not TRACKING_AVAILABLE:
        return {
            "enabled": False,
            "message": "Tracking not enabled or DB unavailable.",
            "summary": {},
            "monthly": [],
            "best_setup": None,
        }
    try:
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT * FROM tracked_ideas WHERE outcome IS NOT NULL"
        ).fetchall()
        open_count = conn.execute(
            "SELECT COUNT(*) AS c FROM tracked_ideas WHERE outcome IS NULL"
        ).fetchone()["c"]
        conn.close()
    except Exception as e:
        return {"enabled": True, "error": str(e), "summary": {}, "monthly": [], "best_setup": None}

    if not rows:
        return {
            "enabled": True,
            "message": "No resolved trades yet. Performance data accumulates as trades close.",
            "open_positions": open_count,
            "summary": {},
            "monthly": {},
            "best_setup": None,
        }

    total = len(rows)
    wins = [r for r in rows if r["outcome"] in ("T1", "T2")]
    stops = [r for r in rows if r["outcome"] == "STOP"]
    expired = [r for r in rows if r["outcome"] == "EXPIRED"]
    win_rate = round(len(wins) / (total - len(expired)) * 100, 1) if (total - len(expired)) > 0 else 0.0

    win_days = [r["trading_days_to_resolution"] for r in wins if r["trading_days_to_resolution"]]
    stop_days = [r["trading_days_to_resolution"] for r in stops if r["trading_days_to_resolution"]]
    avg_win_hold = round(statistics.mean(win_days), 1) if win_days else None
    avg_stop_hold = round(statistics.mean(stop_days), 1) if stop_days else None

    # Best setup by win rate (bucket + direction with >= 3 trades)
    from collections import defaultdict
    bucket_stats: Dict[str, Dict] = defaultdict(lambda: {"wins": 0, "total": 0, "label": ""})
    for r in rows:
        if r["outcome"] == "EXPIRED":
            continue
        key = f"{score_bucket(r['final_score'] or 0)} {r['direction']}"
        bucket_stats[key]["wins"] += 1 if r["outcome"] in ("T1", "T2") else 0
        bucket_stats[key]["total"] += 1
        bucket_stats[key]["label"] = key
    best_setup = None
    best_wr = 0.0
    for key, s in bucket_stats.items():
        if s["total"] >= 3:
            wr = s["wins"] / s["total"]
            if wr > best_wr:
                best_wr = wr
                best_setup = {"setup": key, "win_rate_pct": round(wr * 100, 1), "sample": s["total"]}

    # Monthly summary
    monthly: Dict[str, Dict] = {}
    for r in rows:
        try:
            month = dt.datetime.fromisoformat(r["opened_at"]).strftime("%Y-%m")
        except Exception:
            month = "unknown"
        m = monthly.setdefault(month, {"wins": 0, "stops": 0, "expired": 0, "total": 0})
        m["total"] += 1
        if r["outcome"] in ("T1", "T2"):
            m["wins"] += 1
        elif r["outcome"] == "STOP":
            m["stops"] += 1
        else:
            m["expired"] += 1

    return {
        "enabled": True,
        "summary": {
            "total_trades": total,
            "wins": len(wins),
            "stops": len(stops),
            "expired": len(expired),
            "win_rate_pct": win_rate,
            "avg_hold_win_days": avg_win_hold,
            "avg_hold_stop_days": avg_stop_hold,
            "open_positions": open_count,
        },
        "best_setup": best_setup,
        "monthly": [{"month": k, **v} for k, v in sorted(monthly.items())],
        "generated_at": now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
    }


# ---------------------------------------------------------------------------
# Institutional OS Master Endpoint
# Single call that returns everything the APEX Institutional OS dashboard needs.
# ---------------------------------------------------------------------------

def build_institutional_os(ticker: str, include_heatmap: bool = True) -> Dict[str, Any]:
    """
    Master endpoint data for the APEX Institutional OS dashboard.
    Calls Flow/GEX, builds Story, applies Decay, optionally runs Heatmap.
    All in one shot for the dashboard's polling loop.
    """
    with TRADE_ASSISTANT_LOCK:
        last_signal = TRADE_ASSISTANT_STATE.get("last_signal")

    # Core flow/gex snapshot
    flow_item = quantdata_flow_snapshot(ticker)

    # Build assistant decision (same as /api/assistant)
    assistant = build_trade_assistant_decision(flow_item, last_signal)

    # Confidence decay
    alignment = safe_float(flow_item.get("institutional_alignment"), 50.0)
    age_secs = signal_age_seconds(last_signal) or 0
    decay = confidence_decay(alignment, age_secs, ASSISTANT_SIGNAL_VALID_SECONDS)

    # Institutional story
    story = build_institutional_story(ticker, flow_item, last_signal)

    # Heat map (parallel, can be disabled per-call)
    heatmap_data = build_institutional_heatmap() if include_heatmap else None

    # Session context
    session_ctx = market_session_context()

    # Position monitor
    position_status = monitor_active_position() if POSITION_MONITOR_ENABLED else {"status": "DISABLED"}

    return {
        "version": VERSION_45,
        "ticker": ticker,
        "updated_at": now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
        "updated_at_iso": dt.datetime.now(dt.timezone.utc).isoformat(),
        "session": session_ctx,
        "decision": {
            "state": assistant.get("state"),
            "priority": assistant.get("priority"),
            "message": assistant.get("message"),
            "action": assistant.get("action"),
            "approved_side": assistant.get("approved_side"),
            "institutional_alignment": assistant.get("institutional_alignment"),
            "fresh_signal": assistant.get("fresh_signal"),
            "signal_seconds_remaining": assistant.get("signal_seconds_remaining"),
            "signal_ttl_seconds": assistant.get("signal_ttl_seconds"),
            "checklist": assistant.get("checklist"),
            "trade_plan": assistant.get("trade_plan"),
        },
        "confidence_decay": decay,
        "flow": {
            "ticker": ticker,
            "bias": flow_item.get("bias"),
            "decision_color": flow_item.get("decision_color"),
            "flow_score": flow_item.get("flow_score"),
            "order_flow_score": flow_item.get("order_flow_score"),
            "net_premium": flow_item.get("net_premium"),
            "sweep_count": flow_item.get("sweep_count"),
            "gex_score": flow_item.get("gex_score"),
            "call_wall": flow_item.get("call_wall"),
            "put_wall": flow_item.get("put_wall"),
            "zero_gamma": flow_item.get("zero_gamma"),
            "stock_price": flow_item.get("stock_price"),
            "notes": flow_item.get("notes", [])[:6],
        },
        "story": story,
        "heatmap": heatmap_data,
        "position_monitor": position_status,
        "last_signal": last_signal,
    }


# ---------------------------------------------------------------------------
# New v4.5 HTML Template for the APEX Institutional OS Dashboard
# Replaces ASSISTANT_HTML with the full OS experience.
# ---------------------------------------------------------------------------

# APEX_OS_HTML migrated to templates/apex_os.html

# HTML migrated to templates/dashboard.html




# FLOW_HTML migrated to templates/flow.html


# ASSISTANT_HTML migrated to templates/assistant.html

@app.route("/assistant")
def assistant_dashboard():
    return render_template("assistant.html", version=VERSION, asset_version=STATIC_ASSET_VERSION)


@app.route("/api/session")
def api_session():
    return jsonify(market_session_context())

@app.route("/api/assistant")
def api_assistant():
    ticker = request.args.get("ticker", ASSISTANT_TICKER).upper()
    flow_item = quantdata_flow_snapshot(ticker)
    with TRADE_ASSISTANT_LOCK:
        sig = TRADE_ASSISTANT_STATE.get("last_signal")
    assistant = build_trade_assistant_decision(flow_item, sig)
    with TRADE_ASSISTANT_LOCK:
        TRADE_ASSISTANT_STATE.update(assistant)
        TRADE_ASSISTANT_STATE["last_decision"] = assistant
    return jsonify({"ok": True, "version": VERSION, "ticker": ticker, "flow": flow_item, "assistant": assistant})

@app.route("/tv_signal", methods=["POST"])
def tv_signal():
    payload = request.get_json(silent=True) or {}
    secret = str(payload.get("secret", ""))
    if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
        return jsonify({"ok": False, "error": "bad secret"}), 403

    ticker = normalize_signal_ticker(str(payload.get("ticker", ASSISTANT_TICKER)))
    side   = str(payload.get("signal", payload.get("side", "NONE"))).upper()

    # Full signal enriched with Pine v6 context fields
    signal = {
        "ticker":       ticker,
        "signal":       side,
        "direction":    str(payload.get("direction", "")),
        "price":        payload.get("price"),
        "score":        payload.get("score"),
        "close":        payload.get("close") or payload.get("price"),
        "timeframe":    payload.get("timeframe"),
        "system":       payload.get("source", payload.get("system", "APEX_PRO")),
        # APEX context from Pine inputs
        "apex_decision":      payload.get("apex_decision"),
        "apex_auction":       payload.get("apex_auction"),
        "apex_poc_migration": payload.get("apex_poc_migration"),
        "apex_acceptance":    payload.get("apex_acceptance"),
        "apex_ici":           payload.get("apex_ici"),
        "poc":                payload.get("poc"),
        "vah":                payload.get("vah"),
        "val":                payload.get("val"),
        # Chart confirmation from Pine
        "ema8":           payload.get("ema8"),
        "ema21":          payload.get("ema21"),
        "vwap":           payload.get("vwap"),
        "vix":            payload.get("vix"),
        "orb_high":       payload.get("orb_high"),
        "orb_low":        payload.get("orb_low"),
        "intern_score":   payload.get("intern_score"),
        "signal_num":     payload.get("signal_num"),
        "bar_time":       payload.get("bar_time"),
        # Outcome tracking — filled in later via /api/signal_outcome
        "outcome":        None,
        "outcome_pnl":    None,
        "outcome_notes":  None,
        "received_at":    dt.datetime.now(dt.timezone.utc).isoformat(),
        "received_at_et": now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
    }

    # Persist signal in SCANNER_STATE signal log (last 50)
    with STATE_LOCK:
        log = SCANNER_STATE.setdefault("signal_log", [])
        log.insert(0, signal)
        SCANNER_STATE["signal_log"] = log[:50]

    flow_item = quantdata_flow_snapshot(ticker)
    assistant = build_trade_assistant_decision(flow_item, signal)
    with TRADE_ASSISTANT_LOCK:
        TRADE_ASSISTANT_STATE.update(assistant)
        TRADE_ASSISTANT_STATE["last_signal"]   = signal
        TRADE_ASSISTANT_STATE["last_decision"] = assistant

    if assistant.get("alert"):
        send_telegram(
            f"🚨 APEX ENTER {side}\n"
            f"Ticker: {ticker} · Price: {signal.get('price')}\n"
            f"Auction: {signal.get('apex_auction','--')} · ICI: {signal.get('apex_ici','--')}\n"
            f"POC: {signal.get('poc','--')} · Bar: {signal.get('bar_time','--')}\n"
            f"Internals: {signal.get('intern_score','--')}/3 · Signal #{signal.get('signal_num','--')}"
        )

    return jsonify({"ok": True, "version": VERSION, "signal": signal, "flow": flow_item, "assistant": assistant})

@app.route("/api/signal_log")
def api_signal_log():
    """GET /api/signal_log — last 50 Pine signals received at /tv_signal."""
    with STATE_LOCK:
        log = SCANNER_STATE.get("signal_log", [])
    return jsonify({"ok": True, "count": len(log), "signals": log})


@app.route("/api/apex_signals")
def api_apex_signals():
    """GET /api/apex_signals — APEX signal-outcome spine (Piece Two).

    Every actionable APEX decision logged with entry context, plus the tracked
    outcome (MFE/MAE/WIN/LOSS/EXPIRED). Query params:
      ?limit=N        (default 50)
      ?status=OPEN|WIN|LOSS|EXPIRED
    Returns the log AND measured edge statistics (never estimated).
    """
    try:
        limit = max(1, min(500, int(request.args.get("limit", 50))))
    except Exception:
        limit = 50
    status = request.args.get("status")
    signals = get_apex_signals(limit=limit, status=status)
    return jsonify({
        "ok": True,
        "version": VERSION,
        "available": SPINE_AVAILABLE,
        "count": len(signals),
        "signals": signals,
        "stats": signal_spine_stats(),
    })


@app.route("/api/edge_stats")
def api_edge_stats():
    """GET /api/edge_stats — measured edge statistics from realized outcomes.
    Consumed by the Execution tab's Edge Statistics block. ?direction=CALL|PUT
    to filter. `ready:false` means not enough resolved trades yet — show pending,
    never a fabricated number."""
    direction = request.args.get("direction")
    return jsonify({
        "ok": True,
        "version": VERSION,
        "available": SPINE_AVAILABLE,
        "stats": signal_spine_stats(direction=direction),
        "by_direction": {
            "CALL": signal_spine_stats(direction="CALL"),
            "PUT": signal_spine_stats(direction="PUT"),
        },
    })


@app.route("/api/signal_outcome", methods=["POST"])
def api_signal_outcome():
    """POST /api/signal_outcome — mark the outcome of a received signal.

    Body: { "received_at": "<iso>", "outcome": "WIN|LOSS|SCRATCH", "pnl": 0.0, "notes": "..." }
    """
    body = request.get_json(silent=True) or {}
    received_at = body.get("received_at")
    if not received_at:
        return jsonify({"ok": False, "error": "received_at required"}), 400
    with STATE_LOCK:
        log = SCANNER_STATE.get("signal_log", [])
        matched = False
        for sig in log:
            if sig.get("received_at") == received_at:
                sig["outcome"]       = body.get("outcome")
                sig["outcome_pnl"]   = body.get("pnl")
                sig["outcome_notes"] = body.get("notes")
                matched = True
                break
    return jsonify({"ok": matched, "updated": matched})


@app.route("/flow")
def flow_dashboard():
    return render_template("flow.html", version=VERSION, asset_version=STATIC_ASSET_VERSION)

@app.route("/api/flow")
def api_flow():
    tickers_raw = request.args.get("tickers", "")
    tickers = [x.strip().upper() for x in tickers_raw.split(",") if x.strip()] or FLOW_DASHBOARD_TICKERS
    items = []
    for ticker in tickers[:10]:
        items.append(quantdata_flow_snapshot(ticker))
    return jsonify({
        "ok": True,
        "version": VERSION,
        "quantdata_configured": bool(QUANTDATA_API_KEY),
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "updated_at_et": now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
        "tickers": tickers[:10],
        "items": items,
    })

@app.route("/api/flow/<ticker>")
def api_flow_ticker(ticker: str):
    return jsonify(quantdata_flow_snapshot(ticker.upper()))

@app.route("/scanner")
def scanner_dashboard():
    """Legacy scanner dashboard with manual scan button and current scanner STATE.

    The dashboard.html template expects a `data` object for its initial JSON
    payload. Rendering it without that object can raise a template/tojson error
    and produce a 500 page. Always pass a STATE snapshot.
    """
    with STATE_LOCK:
        data = dict(STATE)
    return render_template("dashboard.html", data=data)

@app.route("/")
def dashboard():
    return redirect("/apex_os", code=302)

@app.route("/dashboard.json")
def dashboard_json():
    with STATE_LOCK:
        return jsonify(dict(STATE))

@app.route("/api/status")
def api_status():
    with STATE_LOCK:
        payload = dict(STATE)
    payload["version"] = VERSION
    _mode = system_mode()
    payload["system_mode"] = _mode["mode"]
    payload["system_mode_detail"] = _mode
    return jsonify(payload)


@app.route("/api/scanner_ideas")
def api_scanner_ideas():
    """Compact scanner results for the Institutional OS panel."""
    with STATE_LOCK:
        ideas = list(STATE.get("ideas", []))
        return jsonify({
            "ok": True,
            "version": VERSION,
            "session": STATE.get("session"),
            "updated_at": STATE.get("updated_at"),
            "updated_at_et": STATE.get("updated_at_et"),
            "scan_in_progress": STATE.get("scan_in_progress"),
            "last_scan_status": STATE.get("last_scan_status"),
            "last_error": STATE.get("last_error"),
            "idea_count": len(ideas),
            "ideas": ideas,
        })


@app.route("/api/run", methods=["GET", "POST"])
def api_run():
    ran = run_scan_once(force=True)
    with STATE_LOCK:
        return jsonify({"ok": ran, "status": STATE.get("last_scan_status"), "ideas": len(STATE.get("ideas", []))})


@app.route("/api/backtest_stats")
def api_backtest_stats():
    try:
        return jsonify(backtest_stats())
    except Exception as e:
        return jsonify({"enabled": TRACKING_ENABLED, "error": str(e), "buckets": []}), 500

@app.route("/api/diagnostics")
def api_diagnostics():
    with STATE_LOCK:
        ideas = list(STATE.get("ideas", []))
        return jsonify({
            "ok": True,
            "mode": VERSION,
            "scanner_started": SCANNER_STARTED,
            "scan_in_progress": STATE.get("scan_in_progress"),
            "scan_started_at": STATE.get("scan_started_at"),
            "last_scan_duration_seconds": STATE.get("last_scan_duration_seconds"),
            "scan_workers": SCAN_WORKERS,
            "tracking_enabled": TRACKING_ENABLED,
            "tracking_available": TRACKING_AVAILABLE,
            "db_path": DB_PATH,
            "updated_at": STATE.get("updated_at"),
            "last_error": STATE.get("last_error"),
            "last_scan_status": STATE.get("last_scan_status"),
            "circuit_breaker": STATE.get("circuit_breaker"),
            "data_sources": {
                "polygon": bool(POLYGON_API_KEY),
                "quantdata": bool(QUANTDATA_API_KEY),
                "benzinga_direct_key": bool(BENZINGA_API_KEY),
                "benzinga_source": BENZINGA_SOURCE,
                "massive": bool(MASSIVE_API_KEY),
                "telegram": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
            },
            "market_regime": STATE.get("market_regime"),
            "ticker_count": STATE.get("ticker_count"),
            "ideas": len(ideas),
            "min_final_score": MIN_FINAL_SCORE,
            "min_alert_score": MIN_ALERT_SCORE,
            "closest_to_qualifying": STATE.get("scan_debug", []),
        })

@app.route("/api/auction_intelligence")
def api_auction_intelligence():
    """GET /api/auction_intelligence?ticker=SPX — full auction intelligence read."""
    ticker = request.args.get("ticker", "SPX").upper()
    if not AUCTION_INTEL_AVAILABLE or build_auction_intelligence is None:
        return jsonify({"ok": False, "error": "Auction intelligence engine not available."}), 503
    try:
        volume_bundle = _volume_profile_bundle(ticker=ticker, days=1, multiplier=5)
        vp_cur   = volume_bundle.get("profile") or {}
        vp_pri   = volume_bundle.get("prior_profile") or {}
        flow_snap= quantdata_flow_snapshot(ticker)
        price    = _sf((vp_cur.get("levels") or {}).get("poc")) or _sf(flow_snap.get("stock_price"))
        intel    = build_auction_intelligence(
            current_profile=vp_cur, prior_profile=vp_pri, earlier_poc=None,
            current_price=price or 0.0,
            flow_bias=flow_snap.get("bias", "MIXED"),
            flow_momentum="STABLE", sweep_count=0,
            gamma_regime="MIXED",
            call_wall=_sf(flow_snap.get("call_wall")),
            put_wall=_sf(flow_snap.get("put_wall")),
        )
        intel["ok"] = True
        intel["ticker"] = ticker
        intel["version"] = VERSION
        intel["updated_at_et"] = now_et().strftime("%Y-%m-%d %H:%M:%S ET")
        return jsonify(intel)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/market_status")
def api_market_status():
    """GET /api/market_status — current session state and per-component status panel."""
    session = session_status()
    panel   = _build_market_status_panel(session)
    _mode   = system_mode(session)
    return jsonify({
        "ok": True, "version": VERSION,
        "system_mode": _mode["mode"],
        "system_mode_detail": _mode,
        **panel,
    })


@app.route("/health")
def health():
    with STATE_LOCK:
        s_updated  = SCANNER_STATE.get("updated_at") or STATE.get("updated_at")
        s_duration = SCANNER_STATE.get("last_scan_duration_seconds") or STATE.get("last_scan_duration_seconds")
        s_sources  = SCANNER_STATE.get("data_sources") or STATE.get("data_sources")
        s_session  = session_status()
        _mode = system_mode(s_session)
        return jsonify({
            "ok":                         True,
            "version":                    VERSION,
            "mode":                       VERSION,   # legacy alias — kept for back-compat
            "system_mode":                _mode["mode"],
            "system_mode_detail":         _mode,
            "session":                    s_session,
            "updated_at":                 s_updated,
            "scanner_started":            SCANNER_STARTED,
            "scan_in_progress":           SCANNER_STATE.get("scan_in_progress") or STATE.get("scan_in_progress"),
            "last_scan_duration_seconds": s_duration,
            "sources":                    s_sources,
            "is_tradeable":               s_session == "MARKET_OPEN",
        })

# =============================================================================
# APEX 4.5 NEW API ROUTES
# =============================================================================

@app.route("/apex_os")
def apex_os_dashboard():
    mode = system_mode()
    return render_template(
        "apex_os.html",
        version=VERSION,
        asset_version=STATIC_ASSET_VERSION,
        mode=mode,
    )


# ── Institutional OS response cache ──────────────────────────────────────────
# Per-ticker cache to return stale data instantly when a refresh is in progress
# or when the last response was < CACHE_TTL seconds ago.
_IOS_CACHE: Dict[str, Any] = {}          # {ticker: {data, ts, in_progress}}
_IOS_CACHE_LOCK = threading.Lock()
_IOS_CACHE_TTL  = float(os.getenv("IOS_CACHE_TTL_SECONDS", "8"))
_FETCH_TIMEOUT  = float(os.getenv("IOS_FETCH_TIMEOUT_SECONDS", "3"))


def _ios_cached(ticker: str) -> Optional[Dict[str, Any]]:
    with _IOS_CACHE_LOCK:
        entry = _IOS_CACHE.get(ticker)
    if not entry:
        return None
    age = time.monotonic() - entry["ts"]
    if age < _IOS_CACHE_TTL or entry.get("in_progress"):
        return entry.get("data")
    return None


def _ios_set_cache(ticker: str, data: Dict[str, Any]) -> None:
    with _IOS_CACHE_LOCK:
        _IOS_CACHE[ticker] = {"data": data, "ts": time.monotonic(), "in_progress": False}


def _ios_mark_in_progress(ticker: str, flag: bool) -> None:
    with _IOS_CACHE_LOCK:
        if ticker not in _IOS_CACHE:
            _IOS_CACHE[ticker] = {"data": None, "ts": 0.0, "in_progress": flag}
        else:
            _IOS_CACHE[ticker]["in_progress"] = flag


def _safe_result(future, label: str, default: Any, timeout: float = _FETCH_TIMEOUT) -> Tuple[Any, Optional[str]]:
    """Resolve a future with timeout; return (value, timed_out_label_or_None)."""
    try:
        return future.result(timeout=timeout), None
    except Exception as e:
        print(f"[IOS] {label} timed out / failed ({type(e).__name__}: {e})", flush=True)
        return default, label


@app.route("/api/institutional_os")
def api_institutional_os():
    """
    Master endpoint for the APEX Institutional OS dashboard.
    Improvements (v7.0.1):
      - Per-ticker response cache with configurable TTL
      - Returns stale data immediately when a refresh is in-progress
      - Per-component timeouts — partial data instead of full failure
      - Response timing metadata: response_ms, partial, stale, timed_out_components
    """
    t_start = time.monotonic()
    ticker = request.args.get("ticker", ASSISTANT_TICKER).upper()
    include_heatmap = request.args.get("heatmap", "0") == "1"   # default OFF — loaded lazily
    force = request.args.get("force", "0") == "1"

    # ── Return cached data immediately if a refresh is already running ──────
    if not force:
        cached = _ios_cached(ticker)
        if cached is not None and _IOS_CACHE.get(ticker, {}).get("in_progress"):
            payload = dict(cached)
            payload.update({"stale": True, "status": "refresh_in_progress",
                             "response_ms": round((time.monotonic()-t_start)*1000, 1)})
            return jsonify(payload)

    _ios_mark_in_progress(ticker, True)

    if APEX_ENGINES_AVAILABLE and _build_institutional_decision is not None:
        try:
            with TRADE_ASSISTANT_LOCK:
                last_signal = TRADE_ASSISTANT_STATE.get("last_signal")
            session_ctx = market_session_context()
            timed_out: List[str] = []

            # Fetch all data inputs in parallel with per-component timeouts
            with ThreadPoolExecutor(max_workers=6, thread_name_prefix="apex-os-fetch") as pool:
                f_flow    = pool.submit(quantdata_flow_snapshot, ticker)
                f_spy     = pool.submit(get_daily_bars, "SPY", 260)
                f_qqq     = pool.submit(get_daily_bars, "QQQ", 260)
                f_daily   = pool.submit(get_daily_bars, ticker, 260)
                f_intra   = pool.submit(get_intraday_bars, ticker, 5, 3)
                f_vix     = pool.submit(get_vix_price)

            flow_snapshot, to1 = _safe_result(f_flow,  "flow_snapshot",  {})
            spy_bars,      to2 = _safe_result(f_spy,   "spy_bars",       [])
            qqq_bars,      to3 = _safe_result(f_qqq,   "qqq_bars",       [])
            daily_bars,    to4 = _safe_result(f_daily, "daily_bars",     [])
            intraday_bars, to5 = _safe_result(f_intra, "intraday_bars",  [])
            vix_price,     to6 = _safe_result(f_vix,   "vix_price",      None)
            for t in [to1,to2,to3,to4,to5,to6]:
                if t: timed_out.append(t)

            # Volume profile with its own timeout protection
            try:
                volume_bundle = _volume_profile_bundle(ticker=ticker, days=1, multiplier=5)
            except Exception as vp_err:
                print(f"[IOS] volume_profile failed: {vp_err}", flush=True)
                volume_bundle = {}
                timed_out.append("volume_profile")

            # Run nine-engine pipeline
            result = _build_institutional_decision(
                ticker=ticker,
                flow_snapshot=flow_snapshot,
                spy_bars=spy_bars,
                qqq_bars=qqq_bars,
                daily_bars=daily_bars,
                intraday_bars=intraday_bars,
                signal=last_signal,
                vix_price=vix_price,
                breadth_score=None,  # Optional; add get_breadth_score() call if desired
                overnight_bars=None,
                default_risk_points=ASSISTANT_DEFAULT_RISK_POINTS,
                target1_r_mult=ASSISTANT_TARGET1_R_MULT,
                target2_r_mult=ASSISTANT_TARGET2_R_MULT,
                strike_step_spx=ASSISTANT_STRIKE_STEP_SPX,
                strike_step_etf=ASSISTANT_STRIKE_STEP_ETF,
                signal_ttl_seconds=ASSISTANT_SIGNAL_VALID_SECONDS,
                session_is_tradeable=session_ctx.get("is_tradeable_session", False),
            )

            # Attach heatmap and session context (not part of nine-engine core)
            if include_heatmap:
                try:
                    result["heatmap"] = build_institutional_heatmap()
                except Exception:
                    result["heatmap"] = None
            result["session"] = session_ctx
            result["market_status"] = session_ctx.get("market_status") or _build_market_status_panel(session_ctx.get("session_state", "CLOSED"))
            result["volume_profile"] = volume_bundle.get("profile")
            result["auction"] = volume_bundle.get("auction")
            # Make POC/VAH/VAL available to Ribbon/Story/Trade Coach without duplicating calculations.
            vp_levels = ((volume_bundle.get("profile") or {}).get("levels") or {})
            if isinstance(result.get("structure"), dict):
                result["structure"]["session_poc"] = result["structure"].get("session_poc") or vp_levels.get("poc")
                result["structure"]["session_vah"] = result["structure"].get("session_vah") or vp_levels.get("vah")
                result["structure"]["session_val"] = result["structure"].get("session_val") or vp_levels.get("val")
                result["structure"]["auction_state"] = (volume_bundle.get("auction") or {}).get("auction_state")
            if isinstance(result.get("ribbon"), dict):
                result["ribbon"]["poc"] = result["ribbon"].get("poc") or vp_levels.get("poc")
                result["ribbon"]["vah"] = vp_levels.get("vah")
                result["ribbon"]["val"] = vp_levels.get("val")
                result["ribbon"]["auction_state"] = (volume_bundle.get("auction") or {}).get("auction_state")
                result["ribbon"]["poc_migration"] = (volume_bundle.get("auction") or {}).get("poc_migration")
            result["engine_mode"] = "NINE_ENGINE_PIPELINE"
            result["version"] = VERSION

            # ── 6.5 engine output vars — declared here so they're always in
            # scope even if the engine blocks below don't execute (e.g. because
            # AUCTION_INTEL_AVAILABLE is False). Story Engine 3.1 references
            # auction_intel before the auction block runs.
            auction_intel:        Dict[str, Any] = {}
            dealer_pos:           Dict[str, Any] = {}
            flow_intel_2:         Dict[str, Any] = {}
            options_chain_intel:  Dict[str, Any] = {}
            vol_intel:            Dict[str, Any] = {}
            rotation_intel:       Dict[str, Any] = {}

            # APEX 5.1 dashboard compatibility contract. The engine returns the
            # institutional OS fields directly; this normalizes them into the
            # older dashboard sections without discarding the new ribbon/ICI fields.
            flow_intel = result.get("flow_intelligence", {}) or {}
            gamma = result.get("gamma_regime", {}) or {}
            structure = result.get("structure", {}) or {}
            risk = result.get("risk", {}) or {}
            if (risk.get("price") is None or risk.get("error") == "No price available") and safe_float(flow_snapshot.get("stock_price"), 0) > 0:
                risk["price"] = flow_snapshot.get("stock_price")
                risk["error"] = None
                if risk.get("contract_hint") == "Waiting for price data":
                    risk["contract_hint"] = "Waiting for directional consensus"
                result["risk"] = risk
            consensus = result.get("consensus", {}) or {}
            ribbon = result.get("ribbon", {}) or {}
            ici = result.get("ici", {}) or {}

            # ── ICI carry-forward: if current ICI is 0 and we have a recent
            # valid value in SCANNER_STATE, carry it forward so the dashboard
            # doesn't show 0 during the first few minutes of the session
            # (volume profile still building, engines not yet warmed up).
            _cur_ici = safe_float(ici.get("ici"), 0.0)
            if _cur_ici <= 0:
                with STATE_LOCK:
                    _last_valid_ici = SCANNER_STATE.get("last_valid_ici") or {}
                if _last_valid_ici and safe_float(_last_valid_ici.get("ici"), 0.0) > 0:
                    ici = dict(_last_valid_ici)
                    ici["stale"] = True
                    ici["stale_note"] = "Carried from last valid scan — engines warming up."
                    result["ici"] = ici
            else:
                # Save this as the last valid ICI
                with STATE_LOCK:
                    SCANNER_STATE["last_valid_ici"] = dict(ici)

            result.setdefault("flow", {
                "ticker": ticker,
                "bias": "CALL" if consensus.get("consensus_direction") == "BULLISH" else "PUT" if consensus.get("consensus_direction") == "BEARISH" else "NEUTRAL",
                "decision_color": "GREEN" if result.get("decision_state") in ("READY", "ENTER_CALL", "ENTER_PUT") else "YELLOW" if str(result.get("decision_state", "")).startswith("WATCH") else "RED",
                "flow_score": flow_intel.get("flow_score"),
                "order_flow_score": flow_intel.get("order_flow_score"),
                "net_premium": ribbon.get("net_flow") or safe_float(flow_snapshot.get("net_premium")),
                "call_premium": ribbon.get("call_flow") or safe_float(flow_snapshot.get("call_premium")),
                "put_premium": ribbon.get("put_flow") or safe_float(flow_snapshot.get("put_premium")),
                "sweep_count": flow_intel.get("sweep_count"),
                "flow_momentum": flow_intel.get("flow_momentum"),
                "gex_score": gamma.get("gex_score"),
                "gamma_regime": gamma.get("regime_label"),
                "call_wall": gamma.get("call_wall"),
                "put_wall": gamma.get("put_wall"),
                "zero_gamma": gamma.get("zero_gamma"),
                "stock_price": ribbon.get("spx_price") or structure.get("current_price"),
                "vwap": structure.get("vwap"),
                "poc": structure.get("session_poc"),
                "institutional_alignment": result.get("confidence"),
                "approved_side": risk.get("approved_side"),
                "notes": flow_intel.get("notes", [])[:6],
            })
            result["decision"] = {
                **(result.get("decision") or {}),
                "state": result.get("decision_state"),
                "priority": ici.get("ici_color"),
                "message": result.get("executive_summary"),
                "action": consensus.get("action"),
                "approved_side": risk.get("approved_side"),
                "institutional_alignment": result.get("confidence"),
                "confidence": result.get("confidence"),
                "grade": result.get("grade"),
                "readiness": result.get("readiness"),
                "fresh_signal": (result.get("execution") or {}).get("signal_fresh"),
                "signal_seconds_remaining": (result.get("execution") or {}).get("signal_seconds_remaining"),
                "signal_ttl_seconds": ASSISTANT_SIGNAL_VALID_SECONDS,
                "checklist": [
                    {"label": "ICI >= 70", "ok": safe_float(result.get("confidence"), 0) >= 70},
                    {"label": "Consensus directional", "ok": consensus.get("consensus_direction") in ("BULLISH", "BEARISH")},
                    {"label": "Fresh Pine confirmation", "ok": (result.get("execution") or {}).get("signal_matches_flow") is True},
                    {"label": "No A+ divergence block", "ok": flow_intel.get("divergence_type") != "A_PLUS"},
                ],
                "trade_plan": {
                    "recommended_contract": risk.get("contract_hint"),
                    "entry_zone": risk.get("entry_zone"),
                    "stop_price": risk.get("stop"),
                    "target_1": risk.get("target1"),
                    "target_2": risk.get("target2"),
                    "rr_to_t1": risk.get("rr_to_t1"),
                    "execution_summary": consensus.get("action"),
                },
            }

            # ── APEX 6.3.2 — Flow tape summary ──
            tape_summary: Dict[str, Any] = {}
            if FLOW_TAPE_AVAILABLE and build_flow_tape is not None and QUANTDATA_API_KEY and ORDER_FLOW_ENABLED:
                try:
                    _tape_tickers = ["SPY", "QQQ", "SPX"]
                    _tape_rows = _fetch_flow_tape_rows(_tape_tickers, size_per_ticker=30)
                    _tape_result = build_flow_tape(_tape_rows, _tape_tickers, min_premium=250_000)
                    tape_summary = _tape_result.get("summary") or {}
                    result["flow_tape_summary"] = tape_summary
                    result["flow_tape_rows_preview"] = (_tape_result.get("rows") or [])[:5]
                except Exception:
                    pass

            # ── APEX 6.4.1 — Canonical Market State ──
            canonical_ms: Dict[str, Any] = {}
            if CANONICAL_MARKET_STATE_AVAILABLE and build_canonical_market_state is not None:
                try:
                    canonical_ms = build_canonical_market_state(
                        flow_snapshot=flow_snapshot,
                        volume_bundle=volume_bundle,
                        result=result,
                        tape_summary=tape_summary,
                        session_ctx=session_ctx,
                    )
                    result["market_state"] = canonical_ms
                except Exception as _cms_err:
                    print(f"Canonical market state error (non-fatal): {_cms_err}", flush=True)

            # ── APEX 6.3.4 / 6.4.1 — Story Engine 3.1 ──
            _session_state_for_story = session_ctx.get("session_state", "MARKET_OPEN")
            if STORY_COACH_V3_AVAILABLE and build_story_v3 is not None:
                try:
                    story_v3 = build_story_v3(
                        ticker=ticker,
                        market_regime=result.get("market_regime") or {},
                        gamma_regime=result.get("gamma_regime") or {},
                        flow=result.get("flow_intelligence") or {},
                        structure=result.get("structure") or {},
                        trend=result.get("trend") or {},
                        execution=result.get("execution") or {},
                        consensus=result.get("consensus") or {},
                        risk=result.get("risk") or {},
                        auction=volume_bundle.get("auction"),
                        volume_profile=volume_bundle.get("profile"),
                        flow_tape_summary=tape_summary,
                        session_state=_session_state_for_story,
                        market_state=canonical_ms or None,
                        auction_intel=auction_intel if isinstance(auction_intel, dict) else None,
                        institutional_intelligence=result.get("institutional_intelligence") if isinstance(result.get("institutional_intelligence"), dict) else None,
                    )
                    result["story"] = story_v3
                    result["executive_summary"] = story_v3.get("executive_summary", result.get("executive_summary", ""))
                except Exception as _sv3_err:
                    print(f"Story v3 error (using v2 fallback): {_sv3_err}", flush=True)

            # ── APEX 6.3.5 / 6.4.1 — Trade Coach 3.1 ──
            if STORY_COACH_V3_AVAILABLE and build_trade_coach_v3 is not None:
                try:
                    from engine.trade_coach import build_trade_coach_v3 as _btcv3
                    coach_v3 = _btcv3(
                        decision_state=result.get("decision_state", "NO_TRADE"),
                        consensus=result.get("consensus") or {},
                        execution=result.get("execution") or {},
                        risk=result.get("risk") or {},
                        gamma_regime=result.get("gamma_regime") or {},
                        flow=result.get("flow_intelligence") or {},
                        structure=result.get("structure") or {},
                        ici=result.get("ici") or {},
                        auction=volume_bundle.get("auction"),
                        volume_profile=volume_bundle.get("profile"),
                        flow_tape_summary=tape_summary,
                        market_state=canonical_ms or None,
                    )
                    result["trade_coach"] = coach_v3
                except Exception as _cv3_err:
                    print(f"Trade coach v3 error (using v2 fallback): {_cv3_err}", flush=True)

            # ── APEX 6.4.1 — Enriched replay frame ──
            try:
                story_snap = result.get("story") or {}
                coach_snap = result.get("trade_coach") or {}
                _replay_snap = {
                    # Decision
                    "decision_state":    result.get("decision_state"),
                    "ici":               result.get("confidence"),
                    "grade":             result.get("grade"),
                    "approved_side":     (result.get("risk") or {}).get("approved_side"),
                    # Price / structure
                    "stock_price":       canonical_ms.get("price") or (result.get("flow") or {}).get("stock_price"),
                    "vwap":              canonical_ms.get("vwap"),
                    "poc":               canonical_ms.get("poc"),
                    "vah":               canonical_ms.get("vah"),
                    "val":               canonical_ms.get("val"),
                    "poc_migration":     canonical_ms.get("poc_migration"),
                    "price_vs_poc":      canonical_ms.get("price_vs_poc"),
                    "price_vs_va":       canonical_ms.get("price_vs_va"),
                    "poc_vwap_confluent":canonical_ms.get("poc_vwap_confluent"),
                    # Auction
                    "auction_state":     canonical_ms.get("auction_state"),
                    # Gamma
                    "gamma_regime":      canonical_ms.get("gamma_regime"),
                    "call_wall":         canonical_ms.get("call_wall"),
                    "put_wall":          canonical_ms.get("put_wall"),
                    "flip_risk":         canonical_ms.get("flip_risk"),
                    # Flow / tape
                    "flow_bias":         canonical_ms.get("flow_bias"),
                    "tape_bias":         canonical_ms.get("tape_bias"),
                    "tape_sweeps":       canonical_ms.get("tape_sweeps"),
                    # Pine
                    "pine_state":        canonical_ms.get("pine_state"),
                    "signal_secs":       canonical_ms.get("signal_secs"),
                    # Story snapshot (the key addition for replay quality)
                    "executive_summary": story_snap.get("executive_summary", ""),
                    "coach_action":      coach_snap.get("action", ""),
                    "coach_entry":       coach_snap.get("entry_zone"),
                    "coach_stop":        coach_snap.get("stop"),
                    "coach_t1":          coach_snap.get("target1"),
                    "coach_t2":          coach_snap.get("target2"),
                    "recommendation":    result.get("recommendation"),
                }
                _record_replay_frame(ticker, _replay_snap)
            except Exception:
                pass

            # ── APEX Auction Intelligence ──
            if AUCTION_INTEL_AVAILABLE and build_auction_intelligence is not None:
                try:
                    _vp_cur  = volume_bundle.get("profile") or {}
                    _vp_pri  = volume_bundle.get("prior_profile") or {}
                    _vp_lvls = (_vp_cur.get("levels") or {})
                    _au_obj  = volume_bundle.get("auction") or {}
                    _fl_obj  = result.get("flow_intelligence") or {}
                    _gm_obj  = result.get("gamma_regime") or {}
                    _cur_price = canonical_ms.get("price") or _sf((flow_snapshot or {}).get("stock_price"))
                    _minutes_o = canonical_ms.get("minutes_open", 0) or 0

                    # Track POC history in the STATE_STORE across calls
                    _poc_key = f"poc_history_{ticker}"
                    with STATE_LOCK:
                        _poc_hist = SCANNER_STATE.get(_poc_key) or []
                    _cur_poc = _sf(_vp_lvls.get("poc"))
                    _prior_poc_ai = _sf((_vp_pri.get("levels") or {}).get("poc"))
                    _earlier_poc  = _poc_hist[-1] if len(_poc_hist) >= 1 else None
                    if _cur_poc > 0:
                        with STATE_LOCK:
                            _poc_hist.append(_cur_poc)
                            SCANNER_STATE[_poc_key] = _poc_hist[-20:]  # keep last 20

                    auction_intel = build_auction_intelligence(
                        current_profile  = _vp_cur,
                        prior_profile    = _vp_pri,
                        earlier_poc      = _earlier_poc,
                        current_price    = _cur_price or 0.0,
                        flow_bias        = _fl_obj.get("bias", "MIXED"),
                        flow_momentum    = _fl_obj.get("flow_momentum", "STABLE"),
                        sweep_count      = int(_sf(_fl_obj.get("sweep_count"))),
                        gamma_regime     = canonical_ms.get("gamma_regime", "MIXED"),
                        call_wall        = _sf(canonical_ms.get("call_wall")),
                        put_wall         = _sf(canonical_ms.get("put_wall")),
                        prev_day_poc     = _sf(_au_obj.get("previous_day_poc")),
                        prev_day_vah     = 0.0,
                        prev_day_val     = 0.0,
                        minutes_open     = _minutes_o,
                        bars_above_vah   = int(SCANNER_STATE.get("bars_above_vah", 0)),
                        bars_below_val   = int(SCANNER_STATE.get("bars_below_val", 0)),
                        bars_above_poc   = int(SCANNER_STATE.get("bars_above_poc", 0)),
                        bars_below_poc   = int(SCANNER_STATE.get("bars_below_poc", 0)),
                    )
                    result["auction_intelligence"] = auction_intel

                    # ── Update bar-level acceptance counters ──
                    # These persist across scan cycles to track acceptance duration
                    _vah = _sf(_vp_lvls.get("vah"))
                    _val = _sf(_vp_lvls.get("val"))
                    _poc = _sf(_vp_lvls.get("poc"))
                    _px  = _cur_price or 0.0
                    if _px > 0 and _vah > 0 and _val > 0:
                        _new_day = SCANNER_STATE.get("_bar_day") != now_et().strftime("%Y-%m-%d")
                        if _new_day:
                            SCANNER_STATE["bars_above_vah"] = 0
                            SCANNER_STATE["bars_below_val"] = 0
                            SCANNER_STATE["bars_above_poc"] = 0
                            SCANNER_STATE["bars_below_poc"] = 0
                            SCANNER_STATE["_bar_day"] = now_et().strftime("%Y-%m-%d")
                        if _px > _vah:
                            SCANNER_STATE["bars_above_vah"] = SCANNER_STATE.get("bars_above_vah", 0) + 1
                            SCANNER_STATE["bars_below_val"] = 0
                        elif _px < _val:
                            SCANNER_STATE["bars_below_val"] = SCANNER_STATE.get("bars_below_val", 0) + 1
                            SCANNER_STATE["bars_above_vah"] = 0
                        else:
                            SCANNER_STATE["bars_above_vah"] = 0
                            SCANNER_STATE["bars_below_val"] = 0
                        if _poc > 0:
                            if _px > _poc:
                                SCANNER_STATE["bars_above_poc"] = SCANNER_STATE.get("bars_above_poc", 0) + 1
                                SCANNER_STATE["bars_below_poc"] = 0
                            else:
                                SCANNER_STATE["bars_below_poc"] = SCANNER_STATE.get("bars_below_poc", 0) + 1
                                SCANNER_STATE["bars_above_poc"] = 0
                except Exception as _ai_err2:
                    print(f"Auction intelligence error (non-fatal): {_ai_err2}", flush=True)

            # ── APEX 6.5 Dealer Positioning Engine ──
            dealer_pos: Dict[str, Any] = {}
            if DEALER_POSITIONING_AVAILABLE and build_dealer_positioning is not None:
                try:
                    dealer_pos = build_dealer_positioning(
                        gamma_regime  = result.get("gamma_regime") or {},
                        flow_snapshot = flow_snapshot,
                        auction_state = auction_intel.get("auction_state") or {},
                        market_state  = canonical_ms or {},
                        dte           = 0.0,
                    )
                    result["dealer_positioning"] = dealer_pos
                except Exception as _dp2:
                    print(f"Dealer positioning error (non-fatal): {_dp2}", flush=True)

            # ── APEX 6.5 Flow Intelligence 2.0 ──
            flow_intel_2: Dict[str, Any] = {}
            if FLOW_INTEL_2_AVAILABLE and build_flow_intelligence_2 is not None:
                try:
                    _fi2_rows = (result.get("flow_tape") or {}).get("rows") or []
                    _fi2_sum  = (result.get("flow_tape") or {}).get("summary") or {}
                    flow_intel_2 = build_flow_intelligence_2(
                        flow_snapshot = flow_snapshot,
                        tape_rows     = _fi2_rows,
                        tape_summary  = _fi2_sum,
                        dealer_delta  = dealer_pos.get("delta"),
                        dealer_gamma  = dealer_pos.get("gamma"),
                    )
                    result["flow_intelligence_2"] = flow_intel_2
                except Exception as _fi2_2:
                    print(f"Flow Intelligence 2.0 error (non-fatal): {_fi2_2}", flush=True)

            _session_state_now = session_ctx.get("session_state", "MARKET_OPEN")

            # ── APEX 6.5 Institutional Playbook ──
            if PLAYBOOK_AVAILABLE and build_institutional_playbook is not None:
                try:
                    _pb_auction = auction_intel if isinstance(auction_intel, dict) else {}
                    _pb_flow2   = flow_intel_2  if isinstance(flow_intel_2,  dict) else {}
                    playbook = build_institutional_playbook(
                        dealer_positioning = dealer_pos if isinstance(dealer_pos, dict) else {},
                        auction_intel      = _pb_auction,
                        flow_intel_2       = _pb_flow2,
                        market_state       = canonical_ms or {},
                        overnight_plan     = result.get("overnight_game_plan") if _session_state_now in ("OVERNIGHT","PREMARKET") else None,
                        session_state      = _session_state_now,
                    )
                    result["playbook"] = playbook
                except Exception as _pb2:
                    print(f"Playbook error (non-fatal): {_pb2}", flush=True)

            # ── APEX 7.0 Market Drivers Engine ──
            market_drivers_intel: Dict[str, Any] = {}
            if MARKET_DRIVERS_AVAILABLE and build_market_drivers is not None:
                try:
                    # Build snapshot dict from heat_map scores
                    _heat_items  = (result.get("heat_map") or {}).get("items") or []
                    _hm_scores   = {str(it.get("ticker","")):_sf(it.get("score"),50.0) for it in _heat_items}
                    _flow_biases = {str(it.get("ticker","")):"BULLISH" if _sf(it.get("score"),50.0)>=70 else "BEARISH" if _sf(it.get("score"),50.0)<=35 else "MIXED" for it in _heat_items}
                    # Polygon daily bars snapshot for change_pct
                    _md_snap: Dict[str, Any] = {}
                    if POLYGON_API_KEY:
                        try:
                            from engine.market_drivers import SPX_CONSTITUENTS
                            _md_tickers = [c["ticker"].replace(".", "/") for c in SPX_CONSTITUENTS]
                            _md_url = f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers"
                            _md_data = safe_get_json(_md_url, params={"tickers": ",".join(_md_tickers)}, timeout=12)
                            if _md_data and "tickers" in _md_data:
                                for t in _md_data["tickers"]:
                                    tkr  = str(t.get("ticker","")).upper()
                                    chg  = _sf((t.get("todaysChangePerc") or t.get("day", {}).get("c", 0)))
                                    vol  = _sf(t.get("day", {}).get("v", 0))
                                    avol = _sf(t.get("prevDay", {}).get("v", 1) or 1)
                                    _md_snap[tkr] = {"change_pct": chg, "volume_relative": vol/avol if avol else 1.0}
                        except Exception:
                            pass
                    market_drivers_intel = build_market_drivers(
                        snapshot_data   = _md_snap,
                        heat_map_scores = _hm_scores,
                        flow_biases     = _flow_biases,
                    )
                    result["market_drivers"] = market_drivers_intel
                except Exception as _md2:
                    print(f"Market drivers error (non-fatal): {_md2}", flush=True)

            # ── APEX 7.0 Strike Magnet Engine ──
            strike_magnets_intel: Dict[str, Any] = {}
            if STRIKE_MAGNET_AVAILABLE and build_strike_magnets is not None:
                try:
                    strike_magnets_intel = build_strike_magnets(
                        gamma_regime  = result.get("gamma_regime") or {},
                        market_state  = canonical_ms or {},
                        auction_intel = auction_intel if isinstance(auction_intel, dict) else None,
                        dte           = 0.0,
                        minutes_open  = int(_sf((canonical_ms or {}).get("minutes_open"))),
                    )
                    result["strike_magnets"] = strike_magnets_intel
                except Exception as _sm2:
                    print(f"Strike magnets error (non-fatal): {_sm2}", flush=True)

            # ── APEX 6.5 Options Chain Intelligence ──
            options_chain_intel: Dict[str, Any] = {}
            if OPTIONS_CHAIN_AVAILABLE and build_options_chain_intelligence is not None:
                try:
                    options_chain_intel = build_options_chain_intelligence(
                        gamma_regime  = result.get("gamma_regime") or {},
                        flow_snapshot = flow_snapshot,
                        market_state  = canonical_ms or {},
                    )
                    result["options_chain"] = options_chain_intel
                except Exception as _oc2:
                    print(f"Options chain error (non-fatal): {_oc2}", flush=True)

            # ── APEX 6.5 Volatility Intelligence ──
            vol_intel: Dict[str, Any] = {}
            if VOLATILITY_AVAILABLE and build_volatility_intelligence is not None:
                try:
                    _vix_cur  = _sf(canonical_ms.get("vix") or vix_price or 0.0)
                    vol_intel = build_volatility_intelligence(
                        vix                 = _vix_cur,
                        vix_prev            = 0.0,
                        gex_score           = _sf((result.get("gamma_regime") or {}).get("gex_score")),
                        dealer_gamma_regime = dealer_pos.get("gamma", {}).get("regime", "NEUTRAL_GAMMA"),
                        call_premium        = _sf(flow_snapshot.get("call_premium")),
                        put_premium         = _sf(flow_snapshot.get("put_premium")),
                        flow_momentum       = str((result.get("flow_intelligence") or {}).get("flow_momentum","STABLE")),
                        minutes_open        = int(_sf(canonical_ms.get("minutes_open"))),
                        session_state       = _session_state_now,
                    )
                    result["volatility"] = vol_intel
                except Exception as _vi2:
                    print(f"Volatility intelligence error (non-fatal): {_vi2}", flush=True)

            # ── APEX 6.5 Market Rotation ──
            rotation_intel: Dict[str, Any] = {}
            if ROTATION_AVAILABLE and build_rotation_intelligence is not None:
                try:
                    _heat = result.get("heat_map") or {}
                    rotation_intel = build_rotation_intelligence(
                        heat_map       = _heat,
                        flow_snapshot  = flow_snapshot,
                        market_state   = canonical_ms or {},
                        breadth_score  = canonical_ms.get("breadth_score"),
                        spx_flow_score = _sf((result.get("flow_intelligence") or {}).get("flow_score"), 50.0),
                    )
                    result["rotation"] = rotation_intel
                except Exception as _rot2:
                    print(f"Rotation intelligence error (non-fatal): {_rot2}", flush=True)

            # ── APEX 6.5 Institutional Intelligence (canonical master object) ──
            if INST_INTEL_AVAILABLE and build_institutional_intelligence is not None:
                try:
                    inst_intel = build_institutional_intelligence(
                        auction_intel      = auction_intel if isinstance(auction_intel, dict) else {},
                        market_state       = canonical_ms if isinstance(canonical_ms, dict) else {},
                        rotation           = rotation_intel if isinstance(rotation_intel, dict) else None,
                        volume_profile     = volume_bundle.get("profile"),
                        dealer_positioning = dealer_pos if isinstance(dealer_pos, dict) else {},
                        options_chain      = options_chain_intel if isinstance(options_chain_intel, dict) else None,
                        volatility         = vol_intel if isinstance(vol_intel, dict) else None,
                        strike_magnets     = strike_magnets_intel if isinstance(strike_magnets_intel, dict) else None,
                        flow_intel_2       = flow_intel_2 if isinstance(flow_intel_2, dict) else {},
                        market_drivers     = market_drivers_intel if isinstance(market_drivers_intel, dict) else None,
                        story              = result.get("story") if isinstance(result.get("story"), dict) else None,
                        trade_coach        = result.get("trade_coach") if isinstance(result.get("trade_coach"), dict) else None,
                        risk               = result.get("risk") if isinstance(result.get("risk"), dict) else None,
                        ici                = result.get("ici") or {},
                        consensus          = result.get("consensus") or {},
                        decision_state     = str(result.get("decision_state") or "NO_TRADE"),
                        playbook           = result.get("playbook") if isinstance(result.get("playbook"), dict) else None,
                        session_state      = str(_session_state_now),
                    )
                    result["institutional_intelligence"] = inst_intel
                except Exception as _ii2:
                    print(f"Institutional intelligence error (non-fatal): {_ii2}", flush=True)

            # ── APEX 8.0 Execution Intelligence Engine ──────────────────────
            if EIE_AVAILABLE and build_execution_intelligence is not None:
                try:
                    # Update rolling history buffers (max 12 cycles)
                    with STATE_LOCK:
                        _net_p = _sf(flow_snapshot.get("net_premium"))
                        _ici_s = _sf((result.get("ici") or {}).get("ici"), 0.0)
                        _fh = SCANNER_STATE.get("flow_history", [])
                        _dh = SCANNER_STATE.get("delta_score_history", [])
                        _fh.append(_net_p); SCANNER_STATE["flow_history"]        = _fh[-12:]
                        _dh.append(_ici_s); SCANNER_STATE["delta_score_history"] = _dh[-12:]
                        _flow_hist  = list(SCANNER_STATE["flow_history"])
                        _delta_hist = list(SCANNER_STATE["delta_score_history"])

                    eie = build_execution_intelligence(
                        institutional_intelligence = result.get("institutional_intelligence") or {},
                        auction_intel              = auction_intel if isinstance(auction_intel, dict) else {},
                        dealer_positioning         = dealer_pos   if isinstance(dealer_pos, dict)   else {},
                        flow_snapshot              = flow_snapshot,
                        market_state               = canonical_ms or {},
                        flow_history               = _flow_hist,
                        delta_score_history        = _delta_hist,
                        session_state              = _session_state_now,
                    )
                    result["execution_intelligence"] = eie

                    # Update exec score history
                    with STATE_LOCK:
                        _eh = SCANNER_STATE.get("exec_score_history", [])
                        _eh.append(_sf(eie.get("exec_probability")))
                        SCANNER_STATE["exec_score_history"] = _eh[-12:]
                except Exception as _eie2:
                    print(f"Execution intelligence error (non-fatal): {_eie2}", flush=True)
            if _session_state_now in ("OVERNIGHT", "PREMARKET") and OVERNIGHT_ENGINE_AVAILABLE and build_overnight_game_plan is not None:
                try:
                    # Fetch ES overnight bars if not already in volume_bundle
                    _es_bars = _futures_fetch_bars(_resolve_polygon_futures_ticker("ES"), days=1, multiplier=5)
                    _es_price = _sf(canonical_ms.get("price") or 0.0)
                    _prior_poc  = _sf(vp_levels.get("poc"))
                    _prior_vah  = _sf(vp_levels.get("vah"))
                    _prior_val  = _sf(vp_levels.get("val"))
                    # Approximate prior close from structure
                    _prior_close = _sf((result.get("structure") or {}).get("prev_close") or 0.0)
                    _on_plan = build_overnight_game_plan(
                        es_price=_es_price,
                        es_bars=_es_bars,
                        prior_poc=_prior_poc if _prior_poc else None,
                        prior_vah=_prior_vah if _prior_vah else None,
                        prior_val=_prior_val if _prior_val else None,
                        prior_close=_prior_close if _prior_close else None,
                        call_wall=canonical_ms.get("call_wall"),
                        put_wall=canonical_ms.get("put_wall"),
                        zero_gamma=canonical_ms.get("zero_gamma"),
                        session_state=_session_state_now,
                        next_rth=session_ctx.get("market_status", {}).get("next_rth", "9:30 AM ET"),
                    )
                    result["overnight_game_plan"] = _on_plan
                    # Override executive summary with overnight read when not in RTH
                    if _on_plan.get("executive_summary"):
                        result["executive_summary"] = _on_plan["executive_summary"]
                except Exception as _on_err:
                    print(f"Overnight game plan error (non-fatal): {_on_err}", flush=True)
            recommendation = result.get("recommendation", "")
            if "ENTER" in recommendation and "NOW" in recommendation:
                story = result.get("story", {})
                summary = story.get("executive_summary", "")
                consensus_label = result.get("consensus_label", "")
                send_telegram(
                    f"🚨 APEX {VERSION} {recommendation}\n"
                    f"Ticker: {ticker}\n"
                    f"Consensus: {consensus_label}\n"
                    f"Summary: {summary}\n"
                    f"Contract: {result.get('risk', {}).get('contract_hint', '--')}\n"
                    f"Entry: {result.get('risk', {}).get('entry_zone', '--')}\n"
                    f"Stop: {result.get('risk', {}).get('stop', '--')}\n"
                    f"Targets: {result.get('risk', {}).get('target1', '--')} / {result.get('risk', {}).get('target2', '--')}"
                )

            _record_confidence_timeline_point(ticker, result)
            # APEX signal-outcome spine (Piece Two): log actionable signals and
            # sample price to resolve open ones. Non-fatal by construction.
            try:
                _spine_ingest(ticker, result)
            except Exception as _spine_err:
                print(f"spine ingest error (non-fatal): {_spine_err}", flush=True)
            # Cache the result for stale-data fallback and sub-endpoints
            with STATE_LOCK:
                STATE["last_result"] = result
            result_payload = {
                "ok": True,
                "stale": False,
                "partial": len(timed_out) > 0,
                "timed_out_components": timed_out,
                "response_ms": round((time.monotonic() - t_start) * 1000, 1),
                **result,
            }
            _ios_set_cache(ticker, result_payload)
            _ios_mark_in_progress(ticker, False)
            return jsonify(result_payload)

        except Exception as e:
            # Nine-engine pipeline failed — fall back to 4.5 build_institutional_os
            _ios_mark_in_progress(ticker, False)
            print(f"Nine-engine pipeline error (falling back): {e}", flush=True)
            try:
                data = build_institutional_os(ticker, include_heatmap=include_heatmap)
                data["engine_mode"] = "FALLBACK_45"
                data["pipeline_error"] = str(e)
                _record_confidence_timeline_point(ticker, data)
                return jsonify({"ok": True, **data})
            except Exception as e2:
                return jsonify({"ok": False, "error": str(e2), "version": VERSION_45}), 500

    # apex_engines.py not available — use 4.5 build_institutional_os
    try:
        data = build_institutional_os(ticker, include_heatmap=include_heatmap)
        data["engine_mode"] = "STANDARD_45"
        return jsonify({"ok": True, **data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "version": VERSION_45}), 500


@app.route("/api/story")
def api_story():
    """Institutional Story Engine — narrative for one ticker."""
    ticker = request.args.get("ticker", ASSISTANT_TICKER).upper()
    try:
        with TRADE_ASSISTANT_LOCK:
            last_signal = TRADE_ASSISTANT_STATE.get("last_signal")
        flow_item = quantdata_flow_snapshot(ticker)
        story = build_institutional_story(ticker, flow_item, last_signal)
        return jsonify({"ok": True, "ticker": ticker, "story": story})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/heatmap")
def api_heatmap():
    """Institutional Heat Map — quick score for multiple tickers."""
    tickers_raw = request.args.get("tickers", "")
    tickers = [x.strip().upper() for x in tickers_raw.split(",") if x.strip()] or None
    try:
        heatmap = build_institutional_heatmap(tickers)
        return jsonify({"ok": True, "version": VERSION_45, **heatmap})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/gameplan")
def api_gameplan():
    """Daily game plan — pre-market bias summary."""
    tickers_raw = request.args.get("tickers", "")
    tickers = [x.strip().upper() for x in tickers_raw.split(",") if x.strip()] or None
    try:
        plan = build_daily_gameplan(tickers)
        return jsonify({"ok": True, "version": VERSION_45, "gameplan": plan})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/position", methods=["GET", "POST"])
def api_position():
    """
    GET  — monitor the current active position.
    POST — set a new active position to monitor.
         JSON body: {ticker, side, entry_price, stop, target1, target2}
    """
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        ticker = str(body.get("ticker", ASSISTANT_TICKER)).upper()
        side = str(body.get("side", "NONE")).upper()
        entry = safe_float(body.get("entry_price"), 0.0)
        stop = safe_float(body.get("stop"), 0.0)
        t1 = safe_float(body.get("target1"), 0.0)
        t2 = safe_float(body.get("target2"), 0.0)
        if not ticker or side not in ("CALL", "PUT"):
            return jsonify({"ok": False, "error": "side must be CALL or PUT"}), 400
        pos = set_active_position(ticker, side, entry, stop, t1, t2)
        return jsonify({"ok": True, "position": pos})
    try:
        result = monitor_active_position()
        return jsonify({"ok": True, "version": VERSION_45, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/position/clear", methods=["POST"])
def api_position_clear():
    """Clear the active position monitor."""
    with ACTIVE_POSITION_LOCK:
        ACTIVE_POSITION.clear()
    return jsonify({"ok": True, "message": "Active position cleared."})


@app.route("/api/performance")
def api_performance():
    """Performance dashboard — win rate, hold time, best setup from tracking DB."""
    try:
        return jsonify({"ok": True, "version": VERSION_45, **build_performance_dashboard()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/decay")
def api_decay():
    """Confidence decay for the current signal."""
    with TRADE_ASSISTANT_LOCK:
        last_signal = TRADE_ASSISTANT_STATE.get("last_signal")
    alignment = safe_float(
        (TRADE_ASSISTANT_STATE.get("last_decision") or {}).get("institutional_alignment") or
        TRADE_ASSISTANT_STATE.get("institutional_alignment"), 50.0
    )
    age = signal_age_seconds(last_signal) or 0
    decay = confidence_decay(alignment, age, ASSISTANT_SIGNAL_VALID_SECONDS)
    return jsonify({"ok": True, "version": VERSION_45, "decay": decay,
                    "last_signal": last_signal, "ttl_seconds": ASSISTANT_SIGNAL_VALID_SECONDS})


@app.route("/api/nine_engines")
def api_nine_engines():
    """
    Raw nine-engine pipeline output — faster than /api/institutional_os
    because it skips the heatmap. Designed for high-frequency dashboard polling.
    Returns all nine engine outputs plus consensus and story.
    Requires apex_engines.py to be deployed alongside app.py.
    """
    if not APEX_ENGINES_AVAILABLE:
        return jsonify({
            "ok": False,
            "error": "apex_engines.py not found. Deploy it alongside app.py.",
            "apex_engines_available": False,
        }), 503

    ticker = request.args.get("ticker", ASSISTANT_TICKER).upper()
    try:
        with TRADE_ASSISTANT_LOCK:
            last_signal = TRADE_ASSISTANT_STATE.get("last_signal")
        session_ctx = market_session_context()

        with ThreadPoolExecutor(max_workers=6, thread_name_prefix="apex-9e-fetch") as pool:
            f_flow  = pool.submit(quantdata_flow_snapshot, ticker)
            f_spy   = pool.submit(get_daily_bars, "SPY", 260)
            f_qqq   = pool.submit(get_daily_bars, "QQQ", 260)
            f_daily = pool.submit(get_daily_bars, ticker, 260)
            f_intra = pool.submit(get_intraday_bars, ticker, 5, 3)
            f_vix   = pool.submit(get_vix_price)

        _fb_flow,  _ = _safe_result(f_flow,  "fb_flow",  {})
        _fb_spy,   _ = _safe_result(f_spy,   "fb_spy",   [])
        _fb_qqq,   _ = _safe_result(f_qqq,   "fb_qqq",   [])
        _fb_daily, _ = _safe_result(f_daily, "fb_daily", [])
        _fb_intra, _ = _safe_result(f_intra, "fb_intra", [])
        _fb_vix,   _ = _safe_result(f_vix,   "fb_vix",   None)

        result = _build_institutional_decision(
            ticker=ticker,
            flow_snapshot=_fb_flow,
            spy_bars=_fb_spy,
            qqq_bars=_fb_qqq,
            daily_bars=_fb_daily,
            intraday_bars=_fb_intra,
            signal=last_signal,
            vix_price=_fb_vix,
            default_risk_points=ASSISTANT_DEFAULT_RISK_POINTS,
            target1_r_mult=ASSISTANT_TARGET1_R_MULT,
            target2_r_mult=ASSISTANT_TARGET2_R_MULT,
            strike_step_spx=ASSISTANT_STRIKE_STEP_SPX,
            strike_step_etf=ASSISTANT_STRIKE_STEP_ETF,
            signal_ttl_seconds=ASSISTANT_SIGNAL_VALID_SECONDS,
            session_is_tradeable=session_ctx.get("is_tradeable_session", False),
        )
        result["session"] = session_ctx
        result["version"] = VERSION_45
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/v45/status")
def api_v45_status():
    """v4.5 feature availability status."""
    return jsonify({
        "ok": True,
        "version": VERSION_45,
        "base_version": VERSION,
        "apex_engines_available": APEX_ENGINES_AVAILABLE,
        "features": {
            "nine_engine_pipeline": APEX_ENGINES_AVAILABLE,
            "institutional_os": True,
            "story_engine": STORY_ENABLED,
            "heatmap": True,
            "daily_gameplan": True,
            "confidence_decay": True,
            "position_monitor": POSITION_MONITOR_ENABLED,
            "performance_dashboard": TRACKING_AVAILABLE,
            "backtest_tracking": TRACKING_ENABLED,
            "vix_fetch": True,
            "breadth_score": True,
            "flow_divergence": APEX_ENGINES_AVAILABLE,
            "gamma_regime": APEX_ENGINES_AVAILABLE,
            "market_structure_poc": APEX_ENGINES_AVAILABLE,
            "adaptive_weights": APEX_ENGINES_AVAILABLE,
            "consensus_engine": APEX_ENGINES_AVAILABLE,
        },
        "config": {
            "assistant_ticker": ASSISTANT_TICKER,
            "heatmap_tickers": HEATMAP_TICKERS,
            "gameplan_tickers": GAMEPLAN_TICKERS,
            "signal_ttl_seconds": ASSISTANT_SIGNAL_VALID_SECONDS,
            "default_risk_points": ASSISTANT_DEFAULT_RISK_POINTS,
            "strike_step_spx": ASSISTANT_STRIKE_STEP_SPX,
        },
        "active_position": bool(ACTIVE_POSITION),
        "updated_at": now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
    })


# =============================================================================
# APEX 5.0 — MARKET INTELLIGENCE TERMINAL
# Live ES and SPX side-by-side candlestick charts with EMA 8/21, VWAP,
# HVBO zone, gamma levels, and key price levels sidebar.
# Data source: Polygon.io (already configured in APEX).
# Routes: GET /chart  →  dashboard HTML
#         GET /api/chart_data?ticker=ES1!&days=3  →  JSON payload
# =============================================================================

def _chart_ema(values: List[float], period: int) -> List[Optional[float]]:
    """EMA returning a value for every bar (None for warm-up bars)."""
    if not values or len(values) < period:
        return [None] * len(values)
    k = 2.0 / (period + 1)
    out: List[Optional[float]] = [None] * (period - 1)
    e = sum(values[:period]) / period
    out.append(round(e, 4))
    for v in values[period:]:
        e = v * k + e * (1 - k)
        out.append(round(e, 4))
    return out


def _chart_vwap_multiday(bars: List[dict]) -> List[float]:
    """VWAP that resets each calendar day (matches original dashboard logic)."""
    out: List[float] = []
    cpv = cv = 0.0
    current_day: Optional[str] = None
    for b in bars:
        ts = safe_float(b.get("t"), 0.0)
        day_key = dt.datetime.utcfromtimestamp(ts / 1000).strftime("%Y-%m-%d") if ts else None
        if day_key != current_day:
            cpv = cv = 0.0
            current_day = day_key
        tp = (safe_float(b.get("h")) + safe_float(b.get("l")) + safe_float(b.get("c"))) / 3
        vol = safe_float(b.get("v"), 0.0)
        cpv += tp * vol
        cv += vol
        out.append(round(cpv / cv if cv > 0 else safe_float(b.get("c")), 4))
    return out


def _resolve_polygon_futures_ticker(symbol: str) -> str:
    """
    Resolve a futures symbol to the correct Polygon.io ticker format.

    Polygon futures use specific contract month codes, e.g. ESU26 = ES September 2026.
    Month codes: F=Jan G=Feb H=Mar J=Apr K=May M=Jun N=Jul Q=Aug U=Sep V=Oct X=Nov Z=Dec

    ES rolls quarterly (Mar/Jun/Sep/Dec). We compute the current active front-month.
    Returns the front-month contract ticker (e.g. ESU26).
    """
    MONTH_CODES = {3:'H', 6:'M', 9:'U', 12:'Z'}
    BASE_MAP = {
        "ES": "ES", "ES1!": "ES", "/ES": "ES",
        "NQ": "NQ", "NQ1!": "NQ", "/NQ": "NQ",
        "MES": "MES", "MNQ": "MNQ",
    }
    upper = symbol.upper().strip()
    base = BASE_MAP.get(upper)
    if not base:
        return upper

    now = now_et()
    m = now.month
    y = now.year

    quarterly = [3, 6, 9, 12]
    exp_month = None
    exp_year = y
    for qm in quarterly:
        if m <= qm:
            exp_month = qm
            exp_year = y
            break
    if exp_month is None:
        exp_month = 3
        exp_year = y + 1

    from calendar import monthcalendar
    cal = monthcalendar(exp_year, exp_month)
    fridays = [week[4] for week in cal if week[4] != 0]
    third_friday = fridays[2] if len(fridays) >= 3 else fridays[-1]
    roll_date = dt.date(exp_year, exp_month, third_friday) - dt.timedelta(days=14)
    if now.date() >= roll_date:
        qidx = quarterly.index(exp_month)
        if qidx < 3:
            exp_month = quarterly[qidx + 1]
        else:
            exp_month = quarterly[0]
            exp_year += 1

    code = MONTH_CODES.get(exp_month, 'U')
    year1 = str(exp_year)[-1:]   # Single digit: ESU6 not ESU26 (per Massive docs format)
    return f"{base}{code}{year1}"  # e.g. ESU6, ESZ6, ESH7


def _futures_fetch_bars(ticker: str, days: int, multiplier: int) -> List[dict]:
    """
    Fetch intraday bars from the Massive/Polygon Futures API.

    Endpoint: GET https://api.polygon.io/futures/v1/aggs/{ticker}

    Per Massive docs (https://massive.com/docs/rest/futures/aggregates):
      resolution: number + unit with no space — e.g. "5min", "1min", "15min"
                  NOT "5", NOT "minute", NOT "5 min"
      window_start: YYYY-MM-DD date string OR nanosecond Unix timestamp

    Plan notes:
      Futures Basic (free): 8-hour historical delay, 2 years history.
      Data will be empty if called during or within 8 hours of the session.
      Futures Starter+: 10-min delayed or real-time.

    Response fields: open/high/low/close/volume/window_start (nanoseconds).
    Response key: "results"
    """
    if not POLYGON_API_KEY:
        return []

    today = now_et().date()
    day_buffer = max(days * 4, 20) if multiplier >= 5 else max(days * 3, 10)
    start_date = today - dt.timedelta(days=day_buffer)
    end_date   = today + dt.timedelta(days=1)

    url = f"https://api.polygon.io/futures/v1/aggs/{ticker}"
    params = {
        # Correct format per Massive docs: number+unit, no space
        "resolution":       f"{multiplier}min",
        "window_start.gte": str(start_date),
        "window_start.lte": str(end_date),
        "limit":            50000,
        "sort":             "window_start.asc",
    }
    data = safe_get_json(url, params=params, timeout=20)
    if not data:
        return []

    raw_results = data.get("results") or data.get("data") or []
    if not isinstance(raw_results, list):
        raw_results = []

    if not raw_results:
        status = data.get("status", "")
        error  = data.get("error", "") or data.get("message", "")
        print(
            f"[futures] {ticker} returned 0 bars. "
            f"status={status!r} error={error!r} keys={list(data.keys())} "
            f"(Futures Basic has 8-hour delay — no intraday data during market hours)",
            flush=True,
        )
        return []

    bars = []
    for r in raw_results:
        ws = r.get("window_start")
        if not ws:
            continue
        try:
            t_ms = int(ws) // 1_000_000
        except (TypeError, ValueError):
            continue
        bars.append({
            "t": t_ms,
            "o": r.get("open"),
            "h": r.get("high"),
            "l": r.get("low"),
            "c": r.get("close"),
            "v": r.get("volume", 0),
        })
    return bars


def _resolve_es_bars_with_probe(days: int, multiplier: int) -> tuple:
    """
    Fetch ES futures bars using the correct Polygon Futures API endpoint,
    with fallback to SPX cash if the futures API returns nothing.

    Polygon/Massive Futures Basic plan ($0/m) uses:
      GET /futures/v1/aggs/{ticker}?resolution=5min&window_start.gte=...
    NOT the stocks /v2/aggs endpoint — that endpoint returns empty for futures tickers.

    Returns (bars, ticker_used, display_name, is_futures, is_fallback)
    """
    front_month = _resolve_polygon_futures_ticker("ES")  # e.g. ESU26
    mes_front   = "MES" + front_month[2:]               # e.g. MESU26

    # Try front-month ES via the futures-specific API
    bars = _futures_fetch_bars(front_month, days=days, multiplier=multiplier)
    if bars:
        return bars, front_month, f"ES Futures ({front_month})", True, False

    # Try MES micro via the futures API (same price scale as ES)
    bars = _futures_fetch_bars(mes_front, days=days, multiplier=multiplier)
    if bars:
        return bars, mes_front, f"MES Micro Futures ({mes_front})", True, False

    # Futures API returned nothing — fall back to SPX cash index
    spx_bars = _chart_fetch_bars("I:SPX", days=days, multiplier=multiplier)
    if spx_bars:
        return spx_bars, "I:SPX", "ES panel — SPX Cash (futures API returned no data)", False, True

    return [], front_month, f"ES Futures unavailable ({front_month})", False, True


def _chart_fetch_bars(polygon_ticker: str, days: int = 3, multiplier: int = 15) -> List[dict]:
    """
    Fetch bars for the last N trading days via Polygon.io.
    Supports 1-min, 5-min, and 15-min bars via the multiplier param.

    Important: end date is set to today + 7 days so that when the market is
    closed (weekends, after hours, holidays) Polygon still returns the most
    recent completed session rather than an empty result. Polygon's intraday
    aggregate endpoint treats the end date as exclusive, so a future end date
    simply means "give me everything up to now."
    """
    today = now_et().date()
    end   = today + dt.timedelta(days=7)   # always ahead of today — captures last closed session
    day_buffer = max(days * 4, 20) if multiplier >= 5 else max(days * 3, 10)
    start = today - dt.timedelta(days=day_buffer)
    url = (f"https://api.polygon.io/v2/aggs/ticker/{polygon_ticker}/range/"
           f"{multiplier}/minute/{start}/{end}")
    data = safe_get_json(url, params={"adjusted": "true", "sort": "asc", "limit": 50000}, timeout=20)
    return (data or {}).get("results", [])


def build_chart_data(symbol: str, days: int = 3, multiplier: int = 15) -> dict:
    """
    Build the full Market Intelligence Terminal payload for one symbol.

    Ported from the original training dashboard's build_market_intelligence()
    and fetch_multi_day_bars(). Data comes from Polygon.io, which is already
    configured in APEX.

    SPX is proxied via SPY (10× scale labels shown in UI).
    ES uses ES1! futures ticker.
    multiplier: bar size in minutes — 1, 5, or 15.
    """
    # Clamp multiplier to supported values
    multiplier = multiplier if multiplier in (1, 5, 15) else 15

    symbol_upper = symbol.upper().strip()
    if symbol_upper in ("SPX", "$SPX"):
        polygon_ticker = "I:SPX"   # Polygon cash index — real SPX prices
        display_name = "SPX (Cash Index)"
        is_futures = False
        spx_proxy = False
        raw_bars = _chart_fetch_bars(polygon_ticker, days=days, multiplier=multiplier)
    elif symbol_upper == "SPY":
        polygon_ticker = "SPY"
        display_name = "SPY"
        is_futures = False
        spx_proxy = True
        raw_bars = _chart_fetch_bars(polygon_ticker, days=days, multiplier=multiplier)
    elif symbol_upper in ("ES", "ES1!", "/ES"):
        # Use the probe chain — tries ESU26, ES1!, MESU26, then I:SPX in order
        raw_bars, polygon_ticker, display_name, is_futures, spx_proxy = \
            _resolve_es_bars_with_probe(days, multiplier)
    else:
        polygon_ticker = symbol_upper
        display_name = symbol_upper
        is_futures = False
        spx_proxy = False
        raw_bars = _chart_fetch_bars(polygon_ticker, days=days, multiplier=multiplier)

    # Final fallback to SPY if I:SPX also fails (non-ES path)
    if not raw_bars and not is_futures and polygon_ticker == "I:SPX":
        polygon_ticker = "SPY"
        display_name = display_name.replace("SPX proxy", "SPY proxy")
        raw_bars = _chart_fetch_bars(polygon_ticker, days=days, multiplier=multiplier)
    if not raw_bars:
        return {"error": f"No data returned for {polygon_ticker}", "symbol": symbol}

    # Group bars by trading day, keep last N days
    from collections import defaultdict
    days_map: dict = defaultdict(list)
    for b in raw_bars:
        ts = safe_float(b.get("t"), 0.0)
        if ts:
            # Use ET date so overnight futures bars (e.g. 00:00 UTC = 20:00 ET prev day)
            # group with the correct trading session rather than rolling to tomorrow UTC
            try:
                dt_et = dt.datetime.fromtimestamp(ts / 1000, tz=EASTERN)
                day_key = dt_et.strftime("%Y-%m-%d")
            except Exception:
                day_key = dt.datetime.utcfromtimestamp(ts / 1000).strftime("%Y-%m-%d")
        else:
            day_key = "unknown"
        days_map[day_key].append(b)

    sorted_days = sorted(days_map.keys())[-days:]
    bars: List[dict] = []
    for d in sorted_days:
        bars.extend(days_map[d])

    if not bars:
        return {"error": "No bars after day filtering", "symbol": symbol}

    # Compute indicators
    closes  = [safe_float(b.get("c")) for b in bars]
    highs   = [safe_float(b.get("h")) for b in bars]
    lows    = [safe_float(b.get("l")) for b in bars]
    volumes = [safe_float(b.get("v"), 0.0) for b in bars]

    ema8v  = _chart_ema(closes, 8)
    ema21v = _chart_ema(closes, 21)
    vwapv  = _chart_vwap_multiday(bars)
    avg_vol = sum(volumes) / max(len(volumes), 1)

    # Build chart array (matches original dashboard shape)
    chart = []
    for i, b in enumerate(bars):
        ts = safe_float(b.get("t"), 0.0)
        dt_utc = dt.datetime.utcfromtimestamp(ts / 1000) if ts else dt.datetime.utcnow()

        # Convert to ET for display label
        try:
            import zoneinfo
            tz_et = zoneinfo.ZoneInfo("America/New_York")
            dt_et = dt.datetime.fromtimestamp(ts / 1000, tz=tz_et)
        except Exception:
            # Fallback: manual EDT offset (UTC-4)
            dt_et = dt_utc - dt.timedelta(hours=4)

        try:
            label = dt_et.strftime("%-I:%M %p")
        except ValueError:
            label = dt_et.strftime("%I:%M %p").lstrip("0")
        day_label = dt_et.strftime("%b %d")

        # ts_et: Unix seconds shifted to ET so Lightweight Charts x-axis renders ET times.
        # Lightweight Charts treats the time field as UTC seconds for display — by shifting
        # the timestamp to ET we make it render the correct local session time on the axis.
        ts_et_sec = int(dt_et.replace(tzinfo=None).timestamp()) if hasattr(dt_et, 'replace') else int(ts / 1000) - 14400

        chart.append({
            "ts":     int(ts),
            "ts_et":  ts_et_sec,
            "time":   f"{day_label} {label}",
            "day":    day_label,
            "open":   round(safe_float(b.get("o")), 2),
            "high":   round(safe_float(b.get("h")), 2),
            "low":    round(safe_float(b.get("l")), 2),
            "close":  round(safe_float(b.get("c")), 2),
            "volume": round(volumes[i], 0),
            "ema8":   ema8v[i],
            "ema21":  ema21v[i],
            "vwap":   round(vwapv[i], 2),
            "relVol": round(volumes[i] / avg_vol, 2) if avg_vol > 0 else 1.0,
        })

    if not chart:
        return {"error": "Chart array empty after processing", "symbol": symbol}

    current_close = closes[-1]
    recent_high   = max(highs)
    recent_low    = min(lows)

    # HVBO zone — bars where volume ≥ 1.5× average
    hv_bars = [chart[i] for i, v in enumerate(volumes) if v >= avg_vol * 1.5]
    if hv_bars:
        hv_prices = [b["close"] for b in hv_bars]
        hvbo_low  = round(min(hv_prices), 2)
        hvbo_high = round(max(hv_prices), 2)
    else:
        hvbo_low  = round(current_close - 1.0, 2)
        hvbo_high = round(current_close + 1.0, 2)

    # Gamma levels — estimated from price structure
    # (Real GEX comes from QuantData; these are the same approximations the original uses)
    gamma_flip   = round((recent_high + current_close) / 2, 2)
    step = 5 if is_futures else 1  # SPY $1 steps, ES 5-point steps
    call_wall    = round(round(current_close / step) * step + step, 2)
    put_wall     = round(round(current_close / step) * step - step, 2)

    # Try to get real gamma levels from QuantData if available
    gamma_diagnostics = {}
    try:
        # SPX and ES panels should both use SPX/SPXW gamma because the active
        # 0DTE options book is SPX. Do not request ES gamma for the ES panel.
        gex_ticker = "SPX" if symbol_upper in ("SPX", "$SPX", "SPY", "ES", "ES1!", "/ES") else symbol_upper
        flow_snap  = quantdata_flow_snapshot(gex_ticker)
        normalized = normalize_gamma_levels({
            "callWall": flow_snap.get("call_wall"),
            "putWall": flow_snap.get("put_wall"),
            "gammaFlip": flow_snap.get("zero_gamma"),
            "stock_price": flow_snap.get("stock_price"),
        }, current_close, gex_ticker)
        if normalized.get("callWall"):
            call_wall  = safe_float(normalized["callWall"], call_wall)
        if normalized.get("putWall"):
            put_wall   = safe_float(normalized["putWall"], put_wall)
        if normalized.get("gammaFlip"):
            gamma_flip = safe_float(normalized["gammaFlip"], gamma_flip)
        gamma_diagnostics = {
            "gexTicker": gex_ticker,
            "raw": {
                "callWall": flow_snap.get("call_wall"),
                "putWall": flow_snap.get("put_wall"),
                "zeroGamma": flow_snap.get("zero_gamma"),
                "activeGammaFlip": flow_snap.get("active_gamma_flip"),
                "rawZeroGamma": flow_snap.get("raw_zero_gamma"),
                "zeroGammaMethod": flow_snap.get("zero_gamma_method"),
                "zeroGammaConfidence": flow_snap.get("zero_gamma_confidence"),
                "stockPrice": flow_snap.get("stock_price"),
            },
            "normalized": {
                "callWall": call_wall,
                "putWall": put_wall,
                "zeroGamma": gamma_flip,
                "rawZeroGamma": flow_snap.get("raw_zero_gamma"),
                "activeGammaFlip": flow_snap.get("active_gamma_flip"),
                "zeroGammaMethod": flow_snap.get("zero_gamma_method"),
                "zeroGammaConfidence": flow_snap.get("zero_gamma_confidence"),
                "referencePrice": current_close,
            },
        }
    except Exception as gamma_exc:
        gamma_diagnostics = {"error": str(gamma_exc)}

    major_support     = round(recent_low, 2)
    secondary_support = round(recent_low - (step * 3), 2)
    resistance        = round(recent_high, 2)

    # Regime detection
    last = chart[-1]
    above_vwap  = current_close > last["vwap"]
    trend_ok    = (last["ema8"] or 0) > (last["ema21"] or 0) and current_close > (last["ema8"] or 0)
    below_gamma = current_close < gamma_flip

    if trend_ok and above_vwap:
        regime = "Bullish Continuation"
        regime_color = "bullish"
    elif trend_ok and not above_vwap:
        regime = "Bullish — Momentum Fading"
        regime_color = "caution"
    elif not above_vwap and not trend_ok:
        regime = "Bearish / Weak Structure"
        regime_color = "bearish"
    elif below_gamma:
        regime = "Below Gamma Flip — Cautious"
        regime_color = "caution"
    else:
        regime = "Balanced / Range"
        regime_color = "neutral"

    strength = sum([trend_ok, above_vwap, not below_gamma,
                    current_close > major_support, current_close > secondary_support])
    strength_label = (
        "Very Strong" if strength == 5 else
        "Strong"      if strength >= 4 else
        "Moderate"    if strength >= 3 else
        "Weak"        if strength >= 2 else "Very Weak"
    )

    return {
        "symbol":          display_name,
        "rawSymbol":       symbol_upper,
        "polygonTicker":   polygon_ticker,
        "isFutures":       is_futures,
        "spxProxy":        spx_proxy,
        "tradingDays":     sorted_days,
        "barInterval":     f"{multiplier}-min",
        "currentClose":    round(current_close, 2),
        "recentHigh":      round(recent_high, 2),
        "recentLow":       round(recent_low, 2),
        "gammaFlip":       gamma_flip,
        "callWall":        call_wall,
        "putWall":         put_wall,
        "hvboLow":         hvbo_low,
        "hvboHigh":        hvbo_high,
        "majorSupport":    major_support,
        "secondarySupport":secondary_support,
        "resistance":      resistance,
        "regime":          regime,
        "regimeColor":     regime_color,
        "strength":        strength,
        "strengthLabel":   strength_label,
        "chart":           chart,
        "barsCount":       len(chart),
        # Tight y-axis bounds: 0.3% padding around the actual price range
        "yMin":            round(recent_low  * 0.997, 2),
        "yMax":            round(recent_high * 1.003, 2),
        "updatedAt":       now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
        "gammaDiagnostics": gamma_diagnostics,
    }


@app.route("/api/chart_data")
def api_chart_data():
    """
    Market Intelligence Terminal data endpoint.
    GET /api/chart_data?ticker=SPX&days=3&tf=15
    GET /api/chart_data?ticker=ES&days=1&tf=1
    tf = timeframe in minutes: 1, 5, or 15 (default 15)
    """
    ticker     = request.args.get("ticker", "SPX").strip().upper()
    days       = max(1, min(int(request.args.get("days", "3")), 5))
    multiplier = int(request.args.get("tf", "15"))
    multiplier = multiplier if multiplier in (1, 5, 15) else 15
    try:
        data = build_chart_data(ticker, days=days, multiplier=multiplier)
        if "error" in data:
            return jsonify({"ok": False, **data}), 500
        return jsonify({"ok": True, **data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "ticker": ticker}), 500


@app.route("/api/market_state")
def api_market_state():
    """APEX 6.0.1 unified Data Bus endpoint.

    Returns one validated market_state object separating ES futures from SPX cash,
    anchoring gamma to SPX, and exposing diagnostics for raw→normalized→display values.
    """
    days = max(1, min(int(request.args.get("days", "1")), 5))
    multiplier = int(request.args.get("tf", "5"))
    multiplier = multiplier if multiplier in (1, 5, 15) else 5
    try:
        es_chart = build_chart_data("ES", days=days, multiplier=multiplier)
        spx_chart = build_chart_data("SPX", days=days, multiplier=multiplier)
        spx_flow = quantdata_flow_snapshot("SPX")
        spx_gamma = {
            "stock_price": spx_flow.get("stock_price"),
            "call_wall": spx_flow.get("call_wall"),
            "put_wall": spx_flow.get("put_wall"),
            "zero_gamma": spx_flow.get("zero_gamma"),
            "active_gamma_flip": spx_flow.get("active_gamma_flip"),
            "raw_zero_gamma": spx_flow.get("raw_zero_gamma"),
            "zero_gamma_method": spx_flow.get("zero_gamma_method"),
            "zero_gamma_confidence": spx_flow.get("zero_gamma_confidence"),
            "gex_score": spx_flow.get("gex_score"),
            "gex_status": spx_flow.get("gex_status"),
            "quality_flags": spx_flow.get("quality_flags", []),
            "diagnostics": spx_flow.get("gamma_diagnostics"),
        }
        if build_market_state_v6 is not None:
            state = build_market_state_v6(
                es_chart=es_chart,
                spx_chart=spx_chart,
                spx_gamma=spx_gamma,
                spx_flow=spx_flow,
                session=session_status(),
            )
        else:
            state = {
                "version": VERSION,
                "session": session_status(),
                "instruments": {"ES": es_chart, "SPX": spx_chart},
                "gamma": spx_gamma,
                "flow": spx_flow,
                "diagnostics": {"error": "APEX 6.0.1 data bus unavailable"},
            }
        return jsonify({"ok": True, "market_state": state})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/diagnostics/gamma")
def api_gamma_diagnostics():
    """Developer diagnostics for SPX gamma scaling and wall selection."""
    ticker = request.args.get("ticker", "SPX").strip().upper()
    try:
        snap = quantdata_flow_snapshot("SPX" if ticker in {"ES", "ES1!", "/ES", "$SPX", "I:SPX"} else ticker)
        return jsonify({
            "ok": True,
            "ticker": ticker,
            "gamma": {
                "stock_price": snap.get("stock_price"),
                "raw_stock_price": snap.get("raw_stock_price"),
                "call_wall": snap.get("call_wall"),
                "put_wall": snap.get("put_wall"),
                "zero_gamma": snap.get("zero_gamma"),
                "active_gamma_flip": snap.get("active_gamma_flip"),
                "raw_zero_gamma": snap.get("raw_zero_gamma"),
                "zero_gamma_method": snap.get("zero_gamma_method"),
                "zero_gamma_confidence": snap.get("zero_gamma_confidence"),
                "gex_score": snap.get("gex_score"),
                "gex_status": snap.get("gex_status"),
                "quality_flags": snap.get("quality_flags", []),
            },
            "diagnostics": snap.get("gamma_diagnostics"),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "ticker": ticker}), 500



@app.route("/api/diagnostics/es_ticker")
def api_es_ticker_diagnostics():
    """
    Probe ES ticker sources and report which return data.
    GET /api/diagnostics/es_ticker?tf=5&days=1

    Tests the Polygon Futures API (/futures/v1/aggs/) — the correct endpoint
    for Futures Basic plan holders — as well as the SPX cash fallback.
    """
    multiplier = int(request.args.get("tf", "5"))
    multiplier = multiplier if multiplier in (1, 5, 15) else 5
    days = max(1, min(int(request.args.get("days", "1")), 2))

    front_month = _resolve_polygon_futures_ticker("ES")
    mes_front   = "MES" + front_month[2:]

    candidates = [
        ("ES futures API (front-month)", front_month, True,  "futures_api"),
        ("MES futures API (micro)",      mes_front,   True,  "futures_api"),
        ("SPX cash index (I:SPX)",       "I:SPX",     False, "stocks_api"),
    ]

    results = []
    winning_ticker = None
    for label, ticker, is_fut, api_type in candidates:
        try:
            if api_type == "futures_api":
                bars = _futures_fetch_bars(ticker, days=days, multiplier=multiplier)
            else:
                bars = _chart_fetch_bars(ticker, days=days, multiplier=multiplier)
            bar_count = len(bars)
            has_data  = bar_count > 0
            last_close = bars[-1].get("c") if bars else None
            if has_data and winning_ticker is None:
                winning_ticker = ticker
        except Exception:
            bar_count  = 0
            has_data   = False
            last_close = None
        results.append({
            "label":      label,
            "ticker":     ticker,
            "api":        f"GET /futures/v1/aggs/{ticker}" if api_type == "futures_api" else f"GET /v2/aggs/ticker/{ticker}",
            "is_futures": is_fut,
            "bars":       bar_count,
            "has_data":   has_data,
            "last_close": last_close,
        })

    any_futures = any(r["has_data"] and r["is_futures"] for r in results)

    # Build a raw probe for direct inspection — shows exactly what Polygon returned
    raw_probe: Dict[str, Any] = {}
    try:
        today = now_et().date()
        start_iso = f"{today - dt.timedelta(days=5)}T00:00:00Z"
        end_iso   = f"{today + dt.timedelta(days=1)}T00:00:00Z"
        probe_params_base = {
            "resolution": "5",
            "window_start.gte": start_iso,
            "window_start.lte": end_iso,
            "limit": 5,
            "sort": "window_start.asc",
            "apiKey": POLYGON_API_KEY,
        }

        probe_attempts = []
        for base_url in [
            f"https://api.polygon.io/futures/v1/aggs/{front_month}",
            f"https://futures.polygon.io/v1/aggs/{front_month}",
        ]:
            try:
                import requests as _req
                _r = _req.get(base_url, params=probe_params_base, timeout=10)
                attempt = {
                    "url":        base_url.replace(POLYGON_API_KEY, "***") if POLYGON_API_KEY in base_url else base_url,
                    "http_status": _r.status_code,
                    "body_preview": _r.text[:300],
                }
                try:
                    j = _r.json()
                    attempt["keys"]        = list(j.keys())
                    attempt["status"]      = j.get("status")
                    attempt["error"]       = j.get("error") or j.get("message")
                    attempt["results_len"] = len(j.get("results") or j.get("data") or [])
                    attempt["first_result"]= (j.get("results") or j.get("data") or [None])[0]
                except Exception:
                    pass
                probe_attempts.append(attempt)
            except Exception as _e:
                probe_attempts.append({"url": base_url, "error": str(_e)})

        raw_probe = {"attempts": probe_attempts}
    except Exception as _pe:
        raw_probe = {"error": str(_pe)}

    return jsonify({
        "ok":                   True,
        "resolved_front_month": front_month,
        "winning_ticker":       winning_ticker,
        "futures_available":    any_futures,
        "diagnosis": (
            f"Futures data AVAILABLE via /futures/v1/aggs/ endpoint. Using {winning_ticker}."
            if any_futures else
            "Futures API returned no data for ES or MES. "
            "ES panel will use SPX Cash (I:SPX) as fallback. "
            "Futures Basic plan is active — data may be end-of-day only outside market hours."
        ),
        "api_note": (
            "Polygon futures bars use GET /futures/v1/aggs/{ticker}?resolution=5 "
            "NOT /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}. "
            "Response fields: open/high/low/close/volume/window_start(nanoseconds)."
        ),
        "raw_probe":    raw_probe,
        "candidates":   results,
        "updated_at":   now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
    })

def _chart_payload_for_lightweight(symbol: str, days: int, multiplier: int) -> Dict[str, Any]:
    """Convert existing APEX chart data into Lightweight Charts payload."""
    data = build_chart_data(symbol, days=days, multiplier=multiplier)
    if data.get("error"):
        return {
            "symbol": data.get("symbol", symbol),
            "rawSymbol": symbol,
            "polygonTicker": data.get("polygonTicker"),
            "isFutures": False,
            "dataAvailable": False,
            "currentClose": None,
            "candles": [],
            "levels": {},
            "message": data.get("error"),
        }
    candles = []
    for row in data.get("chart", []):
        ts = safe_float(row.get("ts"), 0.0)
        if ts <= 0:
            continue
        candles.append({
            "time": int(ts / 1000),
            "ts": int(ts),
            "open": safe_float(row.get("open")),
            "high": safe_float(row.get("high")),
            "low": safe_float(row.get("low")),
            "close": safe_float(row.get("close")),
            "volume": safe_float(row.get("volume"), 0.0),
            "ema8": row.get("ema8"),
            "ema21": row.get("ema21"),
            "vwap": row.get("vwap"),
        })
    return {
        "symbol": data.get("symbol", symbol),
        "rawSymbol": data.get("rawSymbol", symbol),
        "polygonTicker": data.get("polygonTicker"),
        "isFutures": bool(data.get("isFutures")),
        "dataAvailable": bool(candles) and not data.get("error"),
        "currentClose": data.get("currentClose"),
        "recentHigh": data.get("recentHigh"),
        "recentLow": data.get("recentLow"),
        "barInterval": data.get("barInterval"),
        "candles": candles,
        "levels": {
            "vwap": candles[-1].get("vwap") if candles else None,
            "hvbo_low": data.get("hvboLow"),
            "hvbo_high": data.get("hvboHigh"),
            "resistance": data.get("resistance"),
            "support": data.get("majorSupport"),
        },
        "message": None,
    }


def _bars_from_lightweight_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return bars in the generic shape expected by the volume profile engine."""
    out: List[Dict[str, Any]] = []
    for b in (payload or {}).get("candles", []) or []:
        out.append({
            "open": b.get("open"),
            "high": b.get("high"),
            "low": b.get("low"),
            "close": b.get("close"),
            "volume": b.get("volume", 0.0),
            "ts": b.get("ts") or (safe_float(b.get("time"), 0.0) * 1000),
        })
    return out


def _scaled_proxy_bars(proxy_payload: Dict[str, Any], anchor_payload: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[float]]:
    """Scale SPY/SPX proxy bars into the anchor price scale when the anchor lacks volume.

    SPX index candles often have volume=0. For a tradable SPX 0DTE workflow, a
    SPY volume proxy is more informative than pretending zero-volume SPX bars
    have true profile data. This returns SPY OHLC scaled by current SPX/SPY ratio
    while preserving SPY volume, and the caller clearly flags it as a proxy.
    """
    proxy_close = safe_float(proxy_payload.get("currentClose"), 0.0)
    anchor_close = safe_float(anchor_payload.get("currentClose"), 0.0)
    if proxy_close <= 0 or anchor_close <= 0:
        return [], None
    ratio = anchor_close / proxy_close
    bars = []
    for b in _bars_from_lightweight_payload(proxy_payload):
        bars.append({
            "open": safe_float(b.get("open"), 0.0) * ratio,
            "high": safe_float(b.get("high"), 0.0) * ratio,
            "low": safe_float(b.get("low"), 0.0) * ratio,
            "close": safe_float(b.get("close"), 0.0) * ratio,
            "volume": b.get("volume", 0.0),
            "ts": b.get("ts"),
        })
    return bars, ratio


def _volume_profile_bundle(ticker: str = "SPX", days: int = 1, multiplier: int = 5) -> Dict[str, Any]:
    """Build the APEX 6.3 market auction profile bundle.

    For SPX, prefer SPX price scale. If SPX has no real volume, use SPY volume
    scaled into SPX price coordinates and label it honestly.

    Early-session fallback: if fewer than MIN_PROFILE_BARS intraday bars exist
    (market just opened), extend the window to include prior-day bars so the
    auction intelligence has reference levels to work with.
    """
    MIN_PROFILE_BARS = 12   # require at least 12 bars (~1 hour at 5m) for a useful profile
    symbol = (ticker or "SPX").upper()
    anchor_symbol = "SPX" if symbol in {"SPX", "SPXW", "I:SPX", "$SPX"} else symbol
    anchor_payload = _chart_payload_for_lightweight(anchor_symbol, days, multiplier)
    anchor_bars = _bars_from_lightweight_payload(anchor_payload)
    anchor_volume = sum(safe_float(b.get("volume"), 0.0) for b in anchor_bars)
    source = anchor_symbol
    source_note = "anchor_bars"
    proxy_ratio = None
    profile_bars = anchor_bars
    quality_flags: List[str] = []

    # Early-session: not enough intraday bars yet — fetch prior day too
    if len(anchor_bars) < MIN_PROFILE_BARS and days == 1:
        extended_payload = _chart_payload_for_lightweight(anchor_symbol, 2, multiplier)
        extended_bars    = _bars_from_lightweight_payload(extended_payload)
        if len(extended_bars) > len(anchor_bars):
            anchor_bars   = extended_bars
            anchor_volume = sum(safe_float(b.get("volume"), 0.0) for b in anchor_bars)
            profile_bars  = anchor_bars
            quality_flags.append("EXTENDED_TO_PRIOR_DAY_EARLY_SESSION")

    if anchor_symbol == "SPX" and anchor_volume <= 0:
        spy_payload = _chart_payload_for_lightweight("SPY", days, multiplier)
        scaled, ratio = _scaled_proxy_bars(spy_payload, anchor_payload)
        spy_vol = sum(safe_float(b.get("volume"), 0.0) for b in scaled)
        if scaled and spy_vol > 0:
            profile_bars = scaled
            source = "SPY_VOLUME_PROXY_SCALED_TO_SPX"
            source_note = "SPX index volume unavailable; SPY volume scaled to SPX price coordinates."
            proxy_ratio = ratio
            quality_flags.append("SPY_VOLUME_PROXY_SCALED_TO_SPX")
        else:
            quality_flags.append("NO_REAL_VOLUME_USING_ACTIVITY_PROFILE")
            source_note = "SPX index volume unavailable; using activity profile fallback."

    current_profile = build_volume_profile(profile_bars, ticker=anchor_symbol, profile_range="session") if build_volume_profile else {}
    if quality_flags:
        current_profile["quality_flags"] = list(dict.fromkeys((current_profile.get("quality_flags") or []) + quality_flags))
    current_profile["source"] = source
    current_profile["source_note"] = source_note
    current_profile["proxy_ratio"] = round(proxy_ratio, 6) if proxy_ratio else None

    # Prior segment profile for POC migration: compare the latest half of bars to the first half.
    mid = max(1, len(profile_bars) // 2)
    prior_profile = build_volume_profile(profile_bars[:mid], ticker=anchor_symbol, profile_range="prior_segment") if build_volume_profile and len(profile_bars) >= 6 else {}
    latest_profile = build_volume_profile(profile_bars[mid:], ticker=anchor_symbol, profile_range="latest_segment") if build_volume_profile and len(profile_bars[mid:]) >= 3 else current_profile

    current_price = anchor_payload.get("currentClose")
    auction = build_auction_state(
        current_price=current_price,
        current_profile=latest_profile or current_profile,
        prior_profile=prior_profile,
        previous_day_profile=None,
    ) if build_auction_state else {}

    return {
        "ok": True,
        "version": VERSION,
        "ticker": anchor_symbol,
        "requested_ticker": ticker,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "updated_at_et": now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
        "session": session_status(),
        "profile": current_profile,
        "latest_profile": latest_profile,
        "prior_profile": prior_profile,
        "auction": auction,
    }


@app.route("/api/volume_profile")
def api_volume_profile():
    """APEX 6.3 Volume Profile + Auction endpoint.

    GET /api/volume_profile?ticker=SPX&range=session&tf=5&days=1
    Returns POC, VAH, VAL, HVN/LVN and auction/POC migration context.
    """
    ticker = request.args.get("ticker", "SPX").strip().upper()
    days = max(1, min(int(request.args.get("days", "1")), 5))
    multiplier = int(request.args.get("tf", "5"))
    multiplier = multiplier if multiplier in (1, 5, 15) else 5
    try:
        return jsonify(_volume_profile_bundle(ticker=ticker, days=days, multiplier=multiplier))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "version": VERSION, "ticker": ticker}), 500


@app.route("/api/auction_state")
def api_auction_state():
    """Compact auction-state endpoint for Ribbon/Story/Trade Coach integration."""
    ticker = request.args.get("ticker", "SPX").strip().upper()
    days = max(1, min(int(request.args.get("days", "1")), 5))
    multiplier = int(request.args.get("tf", "5"))
    multiplier = multiplier if multiplier in (1, 5, 15) else 5
    try:
        bundle = _volume_profile_bundle(ticker=ticker, days=days, multiplier=multiplier)
        return jsonify({
            "ok": True,
            "version": VERSION,
            "ticker": bundle.get("ticker"),
            "updated_at": bundle.get("updated_at"),
            "updated_at_et": bundle.get("updated_at_et"),
            "profile_levels": (bundle.get("profile") or {}).get("levels", {}),
            "auction": bundle.get("auction"),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "version": VERSION, "ticker": ticker}), 500


@app.route("/api/charts/state")
def api_charts_state():
    """APEX 6.0.2 chart-state endpoint for the Lightweight Charts frontend."""
    days = max(1, min(int(request.args.get("days", "2")), 5))  # default 2 — shows prior RTH + overnight
    multiplier = int(request.args.get("tf", "5"))
    multiplier = multiplier if multiplier in (1, 5, 15) else 5
    dev_mode = request.args.get("dev", "0") in {"1", "true", "yes", "on"}
    try:
        es_payload = _chart_payload_for_lightweight("ES", days, multiplier)
        spx_payload = _chart_payload_for_lightweight("SPX", days, multiplier)
        spx_flow = quantdata_flow_snapshot("SPX")
        spx_gamma = {
            "stock_price": spx_flow.get("stock_price"),
            "call_wall": spx_flow.get("call_wall"),
            "put_wall": spx_flow.get("put_wall"),
            "zero_gamma": spx_flow.get("zero_gamma"),
            "active_gamma_flip": spx_flow.get("active_gamma_flip"),
            "raw_zero_gamma": spx_flow.get("raw_zero_gamma"),
            "zero_gamma_method": spx_flow.get("zero_gamma_method"),
            "zero_gamma_confidence": spx_flow.get("zero_gamma_confidence"),
            "gex_score": spx_flow.get("gex_score"),
            "gex_status": spx_flow.get("gex_status"),
            "quality_flags": spx_flow.get("quality_flags", []),
            "diagnostics": spx_flow.get("gamma_diagnostics"),
        }
        if build_market_state_v6 is not None:
            market_state = build_market_state_v6(
                es_chart={**es_payload, "currentClose": es_payload.get("currentClose")},
                spx_chart={**spx_payload, "currentClose": spx_payload.get("currentClose")},
                spx_gamma=spx_gamma,
                spx_flow=spx_flow,
                session=session_status(),
            )
        else:
            market_state = {"version": VERSION, "session": session_status(), "gamma": spx_gamma, "flow": spx_flow}

        gamma_levels = {
            "call_wall": spx_gamma.get("call_wall"),
            "put_wall": spx_gamma.get("put_wall"),
            "active_gamma_flip": spx_gamma.get("active_gamma_flip") or spx_gamma.get("zero_gamma"),
        }
        if dev_mode:
            gamma_levels["raw_zero_gamma"] = spx_gamma.get("raw_zero_gamma")

        volume_bundle = _volume_profile_bundle(ticker="SPX", days=days, multiplier=multiplier)
        profile_levels = ((volume_bundle.get("profile") or {}).get("levels") or {})
        auction_state = volume_bundle.get("auction") or {}
        vp_levels = {
            "poc": profile_levels.get("poc"),
            "vah": profile_levels.get("vah"),
            "val": profile_levels.get("val"),
        }

        spx_payload["levels"] = {**spx_payload.get("levels", {}), **gamma_levels, **vp_levels}
        spx_payload["volumeProfile"] = volume_bundle.get("profile")
        spx_payload["auction"] = auction_state

        # ES levels: apply basis offset to all SPX-derived levels so they
        # align correctly on the ES price scale (~+40 to +55 pts above SPX).
        es_close  = safe_float(es_payload.get("currentClose") or 0, 0.0)
        spx_close = safe_float(spx_payload.get("currentClose") or 0, 0.0)
        basis_pts = round(es_close - spx_close, 2) if es_close > 0 and spx_close > 0 else 0.0

        def _shift(v):
            """Add basis to a numeric level value; pass through None."""
            try:
                f = float(v)
                return round(f + basis_pts, 2)
            except (TypeError, ValueError):
                return v

        es_gamma_levels = {k: _shift(v) for k, v in gamma_levels.items()}
        es_vp_levels    = {k: _shift(v) for k, v in vp_levels.items()}
        es_payload["levels"]  = {**es_payload.get("levels", {}), **es_gamma_levels, **es_vp_levels}
        es_payload["basis"]   = basis_pts
        es_payload["volumeProfile"] = volume_bundle.get("profile")
        es_payload["auction"] = auction_state
        es_payload["includeRawZeroGamma"] = False
        spx_payload["includeRawZeroGamma"] = dev_mode
        market_state["volume_profile"] = volume_bundle.get("profile")
        market_state["auction"] = auction_state

        return jsonify({
            "ok": True,
            "version": VERSION,
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "updated_at_et": now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
            "market_state": market_state,
            "volume_profile": volume_bundle.get("profile"),
            "auction": auction_state,
            "charts": {"ES": es_payload, "SPX": spx_payload},
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "version": VERSION}), 500



@app.route("/api/confidence_timeline")
def api_confidence_timeline():
    ticker = request.args.get("ticker", ASSISTANT_TICKER).upper()
    return jsonify(_confidence_timeline_payload(ticker))


@app.route("/api/confidence_timeline/reset", methods=["POST"])
def api_confidence_timeline_reset():
    ticker = request.args.get("ticker", ASSISTANT_TICKER).upper()
    with CONFIDENCE_TIMELINE_LOCK:
        CONFIDENCE_TIMELINE[ticker] = []
    return jsonify({
        "ok": True,
        "version": VERSION,
        "ticker": ticker,
        "message": "Confidence timeline reset",
        "updated_at_et": now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
    })


@app.route("/api/market_health")
def api_market_health():
    """Readiness report for live/pre-market/closed-session diagnostics."""
    try:
        session_ctx = market_session_context()
        charts = api_charts_state().get_json(silent=True) if hasattr(api_charts_state(), "__call__") else None
    except Exception:
        charts = None
        session_ctx = market_session_context()

    try:
        flow = quantdata_flow_snapshot("SPX")
    except Exception as e:
        flow = {"error": str(e)}

    gamma_ok = bool(flow.get("call_wall") and flow.get("put_wall") and flow.get("zero_gamma"))
    flow_ok = flow.get("flow_score") is not None and flow.get("order_flow_score") is not None
    chart_payload = charts or {}
    chart_spx = ((chart_payload.get("charts") or {}).get("SPX") or {}) if isinstance(chart_payload, dict) else {}
    chart_es = ((chart_payload.get("charts") or {}).get("ES") or {}) if isinstance(chart_payload, dict) else {}
    spx_candles = len(chart_spx.get("candles") or [])
    es_available = bool(chart_es.get("isFutures") and chart_es.get("dataAvailable"))
    spx_chart_ok = spx_candles > 0

    market_open = bool(session_ctx.get("is_tradeable_session"))
    trend_status = "OK" if market_open and spx_chart_ok else "WAITING_FOR_SESSION" if not market_open else "DATA_MISSING"
    structure_status = "OK" if market_open and spx_chart_ok else "WAITING_FOR_SESSION" if not market_open else "DATA_MISSING"
    execution_status = "WAITING_FOR_PINE" if market_open else "MARKET_CLOSED"
    risk_status = "OK" if safe_float(flow.get("stock_price"), 0) > 0 else "PRICE_MISSING"

    checks = {
        "session": session_ctx.get("session"),
        "gamma": "OK" if gamma_ok else "DATA_MISSING",
        "flow": "OK" if flow_ok else "DATA_MISSING",
        "charts_spx": "OK" if spx_chart_ok else "DATA_MISSING",
        "es_feed": "OK" if es_available else "ES_UNAVAILABLE",
        "risk": risk_status,
        "trend": trend_status,
        "structure": structure_status,
        "execution": execution_status,
    }
    blocking = [k for k, v in checks.items() if v in {"DATA_MISSING", "PRICE_MISSING"}]
    overall = "READY_FOR_OPEN" if not market_open and gamma_ok and flow_ok and spx_chart_ok else "READY" if market_open and not blocking else "CHECK_WARNINGS"
    return jsonify({
        "ok": True,
        "version": VERSION,
        "overall": overall,
        "checks": checks,
        "session_context": session_ctx,
        "notes": [
            "Closed-market nulls are expected for opening range, session POC, fresh Pine execution, and live session structure.",
            "ES_UNAVAILABLE means Polygon futures data is unavailable and the ES panel may use SPX fallback.",
        ],
        "data": {
            "spx_price": flow.get("stock_price") or chart_spx.get("currentClose"),
            "call_wall": flow.get("call_wall"),
            "put_wall": flow.get("put_wall"),
            "zero_gamma": flow.get("zero_gamma"),
            "spx_candles": spx_candles,
            "es_symbol": chart_es.get("symbol"),
        },
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "updated_at_et": now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
    })


# CHART_HTML replaced by templates/chart.html

# =============================================================================
# APEX 6.3.2 — INSTITUTIONAL FLOW TAPE
# =============================================================================

FLOW_TAPE_DEFAULT_TICKERS = ["SPY", "QQQ", "SPX", "NVDA", "TSLA"]
FLOW_TAPE_DEFAULT_MIN_PREMIUM = 250_000


def _fetch_flow_tape_rows(tickers: List[str], size_per_ticker: int = 50) -> List[dict]:
    """Fetch raw QuantData consolidated order-flow rows for a list of tickers."""
    if not QUANTDATA_API_KEY or not ORDER_FLOW_ENABLED:
        return []
    headers = {"Authorization": f"Bearer {QUANTDATA_API_KEY}", "Content-Type": "application/json"}
    all_rows: List[dict] = []
    for ticker in tickers:
        if BREAKER.is_open("quantdata_order_flow"):
            break
        qd_ticker = "SPX" if ticker.upper() in {"SPXW", "$SPX", "I:SPX"} else ticker.upper()
        payload = {
            "filter": {"ticker": qd_ticker},
            "size": size_per_ticker,
            "sort": {"field": "tradeTime", "direction": "DESCENDING"},
        }
        data = safe_post_json(
            f"{QUANTDATA_BASE_URL}/options/tool/order-flow/consolidated",
            payload, headers=headers, timeout=20,
        )
        BREAKER.record_failure("quantdata_order_flow") if data is None else BREAKER.record_success("quantdata_order_flow")
        rows = rows_from_tool_response(data)
        for r in rows:
            if isinstance(r, dict):
                if not r.get("ticker"):
                    r["ticker"] = qd_ticker
                all_rows.append(r)
    return all_rows


def _compute_engine_health(last: dict) -> tuple:
    """Shared engine health computation (APEX 8.0).

    Returns (health_rows, counts) where counts = {green, yellow, red, total}.
    Used by /api/engine_health and /api/mission_control.
    """
    engines_checked = [
        ("gamma",                   "gamma_regime"),
        ("auction_intelligence",    "auction_intelligence"),
        ("dealer_positioning",      "dealer_positioning"),
        ("flow_intelligence_2",     "flow_intelligence_2"),
        ("options_chain",           "options_chain"),
        ("volatility",              "volatility"),
        ("rotation",                "rotation"),
        ("market_drivers",          "market_drivers"),
        ("strike_magnets",          "strike_magnets"),
        ("institutional_intelligence", "institutional_intelligence"),
        ("execution_intelligence",  "execution_intelligence"),
        ("story",                   "story"),
        ("trade_coach",             "trade_coach"),
        ("playbook",                "playbook"),
    ]

    health_rows = []
    available_count = 0
    for label, key in engines_checked:
        obj = last.get(key)
        if isinstance(obj, dict) and obj.get("available"):
            status   = "GREEN"
            qflags   = obj.get("quality_flags") or []
            status   = "YELLOW" if qflags else "GREEN"
            exec_ms  = obj.get("execution_ms") or 0
            err      = obj.get("error")
            available_count += 1
        elif isinstance(obj, dict):
            status   = "YELLOW"
            qflags   = obj.get("quality_flags") or ["AVAILABLE_KEY_MISSING"]
            exec_ms  = 0
            err      = obj.get("error")
        elif obj is None:
            status   = "RED"
            qflags   = ["NOT_IN_LAST_RESULT"]
            exec_ms  = 0
            err      = "Engine output missing from last scan"
        else:
            status   = "YELLOW"
            qflags   = ["UNEXPECTED_TYPE"]
            exec_ms  = 0
            err      = None

        health_rows.append({
            "engine":   label,
            "status":   status,
            "error":    err,
            "flags":    qflags[:3],
            "exec_ms":  exec_ms,
        })

    timed_out = last.get("timed_out_components") or []
    for row in health_rows:
        if row["engine"] in timed_out:
            row["status"] = "YELLOW"
            row["flags"].append("TIMED_OUT_LAST_RUN")

    counts = {
        "green":  sum(1 for r in health_rows if r["status"] == "GREEN"),
        "yellow": sum(1 for r in health_rows if r["status"] == "YELLOW"),
        "red":    sum(1 for r in health_rows if r["status"] == "RED"),
        "total":  len(health_rows),
        "available": available_count,
    }
    return health_rows, counts


@app.route("/api/engine_health")
def api_engine_health():
    """GET /api/engine_health — per-engine health dashboard (APEX 8.0).

    Returns Green/Yellow/Red status for every engine based on last run.
    Reads from STATE["last_result"] populated by /api/institutional_os.
    """
    with STATE_LOCK:
        last = STATE.get("last_result") or {}

    health_rows, counts = _compute_engine_health(last)
    timed_out = last.get("timed_out_components") or []

    return jsonify({
        "ok":               True,
        "version":          VERSION,
        "engines_total":    counts["total"],
        "engines_available": counts["available"],
        "engines_red":      counts["red"],
        "engines_yellow":   counts["yellow"],
        "timed_out_last":   timed_out,
        "last_response_ms": last.get("response_ms"),
        "last_partial":     last.get("partial", False),
        "engines":          health_rows,
    })


@app.route("/api/execution_intelligence")
def api_execution_intelligence():
    """GET /api/execution_intelligence?ticker=SPX — is NOW the moment to enter?"""
    ticker = normalize_signal_ticker(request.args.get("ticker", ASSISTANT_TICKER))
    with STATE_LOCK:
        cached = STATE.get("last_result") or {}
    eie = cached.get("execution_intelligence")
    if eie and isinstance(eie, dict):
        return jsonify({"ok": True, "ticker": ticker, **eie})
    return jsonify({
        "ok": False, "available": False,
        "reason": "Execution intelligence not yet computed. Run a scan first.",
        "quality_flags": ["NOT_YET_COMPUTED"],
    })


@app.route("/api/market_drivers")
def api_market_drivers():
    """GET /api/market_drivers?ticker=SPX — which stocks are moving the index."""
    ticker = normalize_signal_ticker(request.args.get("ticker", ASSISTANT_TICKER))
    with STATE_LOCK:
        cached = STATE.get("last_result") or {}
    md = cached.get("market_drivers")
    if md and isinstance(md, dict):
        return jsonify({"ok": True, "ticker": ticker, **md})
    return jsonify({"ok": False, "available": False,
                    "reason": "Market drivers not yet computed. Run a scan first.",
                    "quality_flags": ["NOT_YET_COMPUTED"]})


@app.route("/api/strike_magnets")
def api_strike_magnets():
    """GET /api/strike_magnets?ticker=SPX — price magnet map."""
    ticker = normalize_signal_ticker(request.args.get("ticker", ASSISTANT_TICKER))
    with STATE_LOCK:
        cached = STATE.get("last_result") or {}
    sm = cached.get("strike_magnets")
    if sm and isinstance(sm, dict):
        return jsonify({"ok": True, "ticker": ticker, **sm})
    # Try live build if gamma data available
    gamma = cached.get("gamma_regime") or {}
    ms    = cached.get("market_state") or {}
    if gamma and STRIKE_MAGNET_AVAILABLE and build_strike_magnets is not None:
        try:
            sm = build_strike_magnets(gamma_regime=gamma, market_state=ms, dte=0.0)
            return jsonify({"ok": True, "ticker": ticker, **sm})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})
    return jsonify({"ok": False, "available": False,
                    "reason": "Strike magnets require a completed scan cycle.",
                    "quality_flags": ["NOT_YET_COMPUTED"]})


@app.route("/api/dealer_positioning")
def api_dealer_positioning():
    """GET /api/dealer_positioning?ticker=SPX — full dealer positioning object."""
    ticker = normalize_signal_ticker(request.args.get("ticker", ASSISTANT_TICKER))
    with STATE_LOCK:
        cached = STATE.get("last_result") or {}
    dp = cached.get("dealer_positioning")
    if dp and isinstance(dp, dict):
        return jsonify({"ok": True, "ticker": ticker, **dp})
    return jsonify({"ok": False, "available": False,
                    "reason": "Dealer positioning not yet computed.",
                    "quality_flags": ["NOT_YET_COMPUTED"]})


@app.route("/api/options_chain_intelligence")
def api_options_chain_intelligence():
    """GET /api/options_chain_intelligence?ticker=SPX — options chain intel."""
    ticker = normalize_signal_ticker(request.args.get("ticker", ASSISTANT_TICKER))
    with STATE_LOCK:
        cached = STATE.get("last_result") or {}
    oc = cached.get("options_chain")
    if oc and isinstance(oc, dict):
        return jsonify({"ok": True, "ticker": ticker, **oc})
    return jsonify({"ok": False, "available": False,
                    "reason": "Options chain intelligence not yet computed.",
                    "quality_flags": ["NOT_YET_COMPUTED"]})


@app.route("/api/institutional_intelligence")
def api_institutional_intelligence():
    """GET /api/institutional_intelligence?ticker=SPX — canonical intelligence object."""
    ticker = normalize_signal_ticker(request.args.get("ticker", ASSISTANT_TICKER))
    with STATE_LOCK:
        cached = STATE.get("last_result") or {}
    ii = cached.get("institutional_intelligence")
    if ii and isinstance(ii, dict):
        return jsonify({"ok": True, "ticker": ticker, **ii})
    return jsonify({"ok": False, "available": False,
                    "reason": "Institutional intelligence not yet computed. Run a scan first.",
                    "quality_flags": ["NOT_YET_COMPUTED"]})


# =============================================================================
# APEX 8.0 — MISSION CONTROL (composite decision endpoint)
# =============================================================================

def _build_expected_path(last: dict) -> dict:
    """Compose the Expected Path block from already-computed engine outputs.

    Zero new math — pure composition of strike magnets, dealer walls,
    volume profile levels, and the II highest-probability scenario.
    """
    ms  = last.get("market_state") or {}
    sm  = last.get("strike_magnets") or {}
    ii  = last.get("institutional_intelligence") or {}
    dp  = last.get("dealer_positioning") or {}

    def _f(v, d=0.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return d

    price = _f(ms.get("price")) or _f(sm.get("price"))
    if not price:
        return {"available": False, "reason": "No price in last scan."}

    levels = []
    seen = set()

    def _add(strike, label, kind, note=""):
        s = _f(strike)
        if s <= 0:
            return
        key = round(s, 1)
        # Dedupe levels within 2 pts, keep first (higher-priority) label
        for k in seen:
            if abs(k - key) < 2:
                return
        seen.add(key)
        levels.append({
            "level":    round(s, 2),
            "label":    label,
            "kind":     kind,
            "note":     note,
            "distance": round(s - price, 2),
            "side":     "ABOVE" if s > price else "BELOW",
        })

    # Magnets first (already ranked by score in the engine)
    for m in (sm.get("magnets") or []):
        if isinstance(m, dict):
            _add(m.get("strike"), (m.get("type") or "MAGNET").replace("_", " ").title(),
                 "MAGNET", m.get("role") or "")

    # Dealer walls (may duplicate magnets — dedupe handles it)
    d_gamma = dp.get("gamma") or {}
    _add(d_gamma.get("call_wall"),  "Call Wall",  "DEALER", "Dealer resistance")
    _add(d_gamma.get("put_wall"),   "Put Wall",   "DEALER", "Dealer support")
    _add(d_gamma.get("zero_gamma"), "Zero Gamma", "DEALER", "Regime flip level")

    # Value area
    _add(ms.get("vah"), "VAH", "VALUE", "Value area high")
    _add(ms.get("poc"), "POC", "VALUE", "Point of control")
    _add(ms.get("val"), "VAL", "VALUE", "Value area low")

    above = sorted([l for l in levels if l["side"] == "ABOVE"], key=lambda l: l["level"])[:5]
    below = sorted([l for l in levels if l["side"] == "BELOW"], key=lambda l: -l["level"])[:5]

    pin_prob = _f(ii.get("pin_probability"))
    return {
        "available":      True,
        "current_price":  round(price, 2),
        "scenario":       ii.get("highest_probability_scenario") or "",
        "institutional_bias": ii.get("institutional_bias") or "NEUTRAL",
        "pin": {
            "level":       sm.get("nearest_magnet"),
            "type":        sm.get("nearest_type"),
            "probability": round(pin_prob, 1),
            "risk":        sm.get("pin_risk") or "LOW",
            "watch":       sm.get("watch") or "",
        },
        "levels_above":   above,
        "levels_below":   below,
    }


@app.route("/api/mission_control")
def api_mission_control():
    """GET /api/mission_control?ticker=SPX — APEX 8.0 composite decision payload.

    One lightweight call answering: What are institutions doing? Should I trade?
    Is now the moment? What is the expected path?

    Pure composition from STATE["last_result"] — never triggers a scan, never
    calls external APIs. Stable contract for the Mission Control workspace,
    Telegram, and future clients.
    """
    ticker = normalize_signal_ticker(request.args.get("ticker", ASSISTANT_TICKER))

    with STATE_LOCK:
        last = STATE.get("last_result") or {}
        exec_hist = list(SCANNER_STATE.get("exec_score_history", []))

    if not last:
        return jsonify({
            "ok": False, "available": False, "version": VERSION,
            "reason": "No scan completed yet. Mission Control populates after the first /api/institutional_os cycle.",
            "quality_flags": ["NOT_YET_COMPUTED"],
        })

    ii   = last.get("institutional_intelligence") or {}
    eie  = last.get("execution_intelligence") or {}
    cons = last.get("consensus") or {}
    ici  = last.get("ici") or {}
    risk = last.get("risk") or {}
    ms   = last.get("market_state") or {}
    fi2  = last.get("flow_intelligence_2") or {}
    ai   = last.get("auction_intelligence") or {}
    dp   = last.get("dealer_positioning") or {}
    coach = last.get("trade_coach") or {}

    health_rows, health_counts = _compute_engine_health(last)

    # Freshness
    updated_at = last.get("updated_at_et") or last.get("updated_at") or ""
    session_state = str(ii.get("session_state") or last.get("session_state") or session_status())

    # Decision block
    exec_prob   = eie.get("exec_probability")
    stage       = eie.get("stage") or "WATCH"
    n_bull      = int(cons.get("n_bullish") or 0)
    n_bear      = int(cons.get("n_bearish") or 0)
    n_engines   = int(cons.get("n_engines") or 0)
    aligned     = max(n_bull, n_bear)

    decision = {
        "institutional_bias":       ii.get("institutional_bias") or "NEUTRAL",
        "overall_score":            ii.get("overall_score"),
        "execution_score":          exec_prob,
        "stage":                    stage,
        "stage_color":              eie.get("stage_color"),
        "stage_description":        eie.get("stage_description"),
        "trigger_active":           bool(eie.get("trigger_active")),
        "timing":                   eie.get("timing"),
        "timing_note":              eie.get("timing_note"),
        "institutional_confidence": ici.get("ici"),
        "confidence_label":         ici.get("ici_label"),
        "confidence_color":         ici.get("ici_color"),
        "engine_agreement": {
            "aligned":  aligned,
            "total":    n_engines,
            "bullish":  n_bull,
            "bearish":  n_bear,
            "neutral":  int(cons.get("n_neutral") or 0),
            "label":    cons.get("consensus_label") or "",
        },
        "decision_state":           ii.get("decision_state") or last.get("decision_state") or "NO_TRADE",
        "recommendation":           cons.get("recommendation") or last.get("recommendation") or "",
        "action":                   cons.get("action") or "",
        "narrative":                ii.get("executive_summary") or last.get("executive_summary") or "",
        "pine_confirmed":           bool(eie.get("pine_confirmed") or ii.get("pine_confirmed")),
    }

    # Trade card — active when exec stage is ARMED/EXECUTE or trigger fired
    card_active = bool(eie.get("trigger_active")) or stage in ("ARMED", "EXECUTE")
    approved    = risk.get("approved_side") or ""
    trade_card = {
        "active":        card_active and bool(risk.get("entry_zone")),
        "direction":     approved,
        "probability":   exec_prob,
        "entry_zone":    risk.get("entry_zone"),
        "stop":          risk.get("stop"),
        "target1":       risk.get("target1"),
        "target2":       risk.get("target2"),
        "rr_to_t1":      risk.get("rr_to_t1"),
        "rr_to_t2":      risk.get("rr_to_t2"),
        "contract_hint": risk.get("contract_hint"),
        "invalidation":  eie.get("invalidation") or "",
        "coach_state":   coach.get("state") or "",
    }

    payload = {
        "ok":              True,
        "available":       True,
        "version":         VERSION,
        "ticker":          ticker,
        "updated_at_et":   updated_at,
        "session_state":   session_state,
        "stale":           bool(last.get("stale")),
        "partial":         bool(last.get("partial")),
        "engine_health":   health_counts,
        "engine_health_rows": [
            {"engine": r["engine"], "status": r["status"]} for r in health_rows
        ],
        "decision":        decision,
        "trade_card":      trade_card,
        "expected_path":   _build_expected_path(last),
        "consensus":       [
            {"engine": v.get("engine"), "vote": v.get("vote"),
             "strength": v.get("strength"), "skipped": v.get("skipped", False)}
            for v in (cons.get("vote_table") or []) if isinstance(v, dict)
        ],
        "why_bullets":     eie.get("why_bullets") or [],
        "primary_risk":    ii.get("primary_risk") or "",
        "exec_score_history": exec_hist,
        "flow": {
            "bias":       ii.get("flow_bias") or ms.get("flow_bias") or "MIXED",
            "conviction": ii.get("flow_conviction"),
            "urgency":    ii.get("flow_urgency") or fi2.get("urgency") or "LOW",
            "contradictions": ii.get("flow_contradictions") or [],
        },
        "dealer": {
            "gamma_regime": ii.get("gamma_regime") or "NEUTRAL_GAMMA",
            "bias":         ii.get("dealer_bias") or "NEUTRAL",
            "pin_probability": ii.get("pin_probability"),
        },
        "auction": {
            "state":      ii.get("auction_state") or "UNKNOWN",
            "acceptance": ii.get("acceptance") or "",
        },
        "price": ms.get("price"),
    }
    return jsonify(payload)


@app.route("/api/flow_tape")
def api_flow_tape():
    """APEX 6.3.2 Institutional Flow Tape endpoint.

    GET /api/flow_tape?tickers=SPY,QQQ,SPX,NVDA,TSLA&min_premium=250000&size=50

    Returns normalized, classified, importance-scored tape rows plus a summary.
    """
    raw_tickers = request.args.get("tickers", ",".join(FLOW_TAPE_DEFAULT_TICKERS))
    tickers = [t.strip().upper() for t in raw_tickers.split(",") if t.strip()]
    if not tickers:
        tickers = list(FLOW_TAPE_DEFAULT_TICKERS)
    min_premium = float(request.args.get("min_premium", str(FLOW_TAPE_DEFAULT_MIN_PREMIUM)))
    size = int(request.args.get("size", "50"))
    size = max(10, min(size, 200))

    if not FLOW_TAPE_AVAILABLE or build_flow_tape is None:
        return jsonify({
            "ok": False,
            "error": "Flow tape engine not available",
            "version": VERSION,
            "tickers": tickers,
            "rows": [],
        }), 503

    if not QUANTDATA_API_KEY or not ORDER_FLOW_ENABLED:
        return jsonify({
            "ok": True,
            "status": "NOT_CONFIGURED",
            "version": VERSION,
            "tickers": tickers,
            "rows": [],
            "summary": {
                "buy_premium": 0, "sell_premium": 0, "net_premium": 0,
                "sweep_count": 0, "block_count": 0, "row_count": 0,
                "tape_bias": "MIXED",
            },
            "message": "Set QUANTDATA_API_KEY and ORDER_FLOW_ENABLED=true to enable the flow tape.",
            "updated_at_et": now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
        })

    try:
        raw_rows = _fetch_flow_tape_rows(tickers, size_per_ticker=size)
        tape = build_flow_tape(raw_rows, tickers, min_premium=min_premium)
        tape["version"] = VERSION
        tape["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        tape["updated_at_et"] = now_et().strftime("%Y-%m-%d %H:%M:%S ET")
        return jsonify(tape)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "version": VERSION, "tickers": tickers}), 500


# =============================================================================
# APEX 6.4.0 — REPLAY & POST-TRADE ANALYTICS
# =============================================================================

REVIEW_DB_PATH = os.getenv("REVIEW_DB_PATH", DB_PATH)
REPLAY_STORE_LOCK = threading.RLock()

# In-memory replay store indexed by session date string (YYYY-MM-DD)
# Structure: { "2026-06-28": [frame_dict, ...] }
REPLAY_STORE: Dict[str, List[Dict[str, Any]]] = {}
REPLAY_MAX_FRAMES_PER_SESSION = int(os.getenv("REPLAY_MAX_FRAMES", "480"))


def _init_review_db() -> None:
    """Create post-trade review tables if they don't exist."""
    try:
        db_dir = os.path.dirname(REVIEW_DB_PATH)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        conn = sqlite3.connect(REVIEW_DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trade_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    side TEXT,
                    entry_time TEXT,
                    exit_time TEXT,
                    entry_price REAL,
                    exit_price REAL,
                    contract TEXT,
                    pnl REAL,
                    reason_entered TEXT,
                    reason_exited TEXT,
                    followed_plan INTEGER DEFAULT 1,
                    mistakes TEXT,
                    lesson TEXT,
                    screenshot_url TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS replay_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_date TEXT NOT NULL,
                    frame_time TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_replay_session ON replay_snapshots (session_date, ticker, frame_time)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_review_ticker ON trade_reviews (ticker, entry_time)")
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"APEX 6.4.0 review DB init failed (non-fatal): {e}", flush=True)


def _store_replay_frame(session_date: str, frame_time: str, ticker: str, snapshot: Dict[str, Any]) -> None:
    """Persist a replay frame to SQLite (best-effort; never raises)."""
    try:
        import json
        conn = sqlite3.connect(REVIEW_DB_PATH, timeout=5)
        try:
            conn.execute(
                "INSERT INTO replay_snapshots (session_date, frame_time, ticker, snapshot_json) VALUES (?,?,?,?)",
                (session_date, frame_time, ticker, json.dumps(snapshot, default=str))
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def _record_replay_frame(ticker: str, snapshot: Dict[str, Any]) -> None:
    """Called by the background scanner on each cycle to build the intraday replay store."""
    import json
    session_key = now_et().strftime("%Y-%m-%d")
    frame_time = now_et().strftime("%H:%M:%S")
    frame = {
        "session_date": session_key,
        "frame_time": frame_time,
        "ticker": ticker,
        "snapshot": snapshot,
    }
    with REPLAY_STORE_LOCK:
        session_frames = REPLAY_STORE.setdefault(session_key, [])
        # Evict oldest frames beyond the cap
        if len(session_frames) >= REPLAY_MAX_FRAMES_PER_SESSION:
            del session_frames[0]
        session_frames.append(frame)
    # Best-effort persist to DB
    _store_replay_frame(session_key, frame_time, ticker, snapshot)


@app.route("/api/replay/session")
def api_replay_session():
    """APEX 6.4.0 — Replay session index.

    GET /api/replay/session?ticker=SPX&date=YYYY-MM-DD

    Returns summary of available replay frames for the requested session date.
    Pulls from in-memory store (today) or SQLite (historical).
    """
    import json
    ticker = request.args.get("ticker", "SPX").upper()
    date_str = request.args.get("date", now_et().strftime("%Y-%m-%d"))
    try:
        # Try in-memory first (today's session)
        with REPLAY_STORE_LOCK:
            frames = [f for f in REPLAY_STORE.get(date_str, [])
                      if f.get("ticker", "").upper() == ticker]
        if not frames:
            # Fallback: query SQLite for historical
            try:
                conn = sqlite3.connect(REVIEW_DB_PATH, timeout=5)
                conn.row_factory = sqlite3.Row
                try:
                    rows = conn.execute(
                        "SELECT frame_time, snapshot_json FROM replay_snapshots "
                        "WHERE session_date=? AND ticker=? ORDER BY frame_time ASC LIMIT 480",
                        (date_str, ticker)
                    ).fetchall()
                    frames = [
                        {"session_date": date_str, "frame_time": r["frame_time"],
                         "ticker": ticker,
                         "snapshot": json.loads(r["snapshot_json"]) if r["snapshot_json"] else {}}
                        for r in rows
                    ]
                finally:
                    conn.close()
            except Exception:
                frames = []

        return jsonify({
            "ok": True,
            "version": VERSION,
            "ticker": ticker,
            "session_date": date_str,
            "frame_count": len(frames),
            "frames": [
                {
                    "frame_index": i,
                    "frame_time": f.get("frame_time", ""),
                    "decision_state": (f.get("snapshot") or {}).get("decision_state", ""),
                    "ici": (f.get("snapshot") or {}).get("confidence", None),
                    "price": (f.get("snapshot") or {}).get("stock_price", None),
                }
                for i, f in enumerate(frames)
            ],
            "updated_at_et": now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "version": VERSION}), 500


@app.route("/api/replay/frame")
def api_replay_frame():
    """APEX 6.4.0 — Single replay frame.

    GET /api/replay/frame?ticker=SPX&date=YYYY-MM-DD&time=HH:MM

    Returns the full APEX snapshot for the nearest frame matching the requested time.
    """
    import json
    ticker = request.args.get("ticker", "SPX").upper()
    date_str = request.args.get("date", now_et().strftime("%Y-%m-%d"))
    time_str = request.args.get("time", "")

    try:
        # In-memory first
        with REPLAY_STORE_LOCK:
            day_frames = [f for f in REPLAY_STORE.get(date_str, [])
                          if f.get("ticker", "").upper() == ticker]

        if not day_frames:
            conn = sqlite3.connect(REVIEW_DB_PATH, timeout=5)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    "SELECT frame_time, snapshot_json FROM replay_snapshots "
                    "WHERE session_date=? AND ticker=? ORDER BY frame_time ASC LIMIT 480",
                    (date_str, ticker)
                ).fetchall()
                day_frames = [
                    {"frame_time": r["frame_time"],
                     "snapshot": json.loads(r["snapshot_json"]) if r["snapshot_json"] else {}}
                    for r in rows
                ]
            finally:
                conn.close()

        if not day_frames:
            return jsonify({
                "ok": True,
                "status": "NO_FRAMES",
                "ticker": ticker,
                "session_date": date_str,
                "frame": None,
                "message": f"No replay data available for {ticker} on {date_str}.",
            })

        # Find nearest frame by time
        if time_str:
            target = time_str[:5]  # HH:MM
            best = min(day_frames, key=lambda f: abs(
                _time_to_minutes(f.get("frame_time", "00:00")) - _time_to_minutes(target)
            ))
        else:
            best = day_frames[-1]

        return jsonify({
            "ok": True,
            "version": VERSION,
            "ticker": ticker,
            "session_date": date_str,
            "frame_time": best.get("frame_time"),
            "frame": best.get("snapshot") or {},
            "total_frames": len(day_frames),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "version": VERSION}), 500


def _time_to_minutes(t: str) -> int:
    """Convert HH:MM or HH:MM:SS to total minutes since midnight."""
    parts = (t or "00:00").replace(":", "").ljust(6, "0")
    try:
        return int(parts[:2]) * 60 + int(parts[2:4])
    except Exception:
        return 0


@app.route("/api/review/trade", methods=["POST"])
def api_review_trade_post():
    """APEX 6.4.0 — Log a trade review.

    POST /api/review/trade
    Body (JSON):
    {
      "ticker": "SPX",
      "side": "CALL",
      "entry_time": "09:47",
      "exit_time": "10:12",
      "entry_price": 7352.0,
      "exit_price": 7365.0,
      "contract": "SPX 7350C 0DTE",
      "pnl": 420.0,
      "reason_entered": "Pine ENTER_CALL, POC support, bullish tape sweeps",
      "reason_exited": "Hit T1 target",
      "followed_plan": true,
      "mistakes": "",
      "lesson": "Entry near VWAP/POC confluence was ideal.",
      "screenshot_url": ""
    }
    """
    try:
        body = request.get_json(force=True, silent=True) or {}
        ticker = str(body.get("ticker", "SPX")).upper()
        side = str(body.get("side", "")).upper()
        entry_time = str(body.get("entry_time", ""))
        exit_time = str(body.get("exit_time", ""))
        entry_price = body.get("entry_price")
        exit_price = body.get("exit_price")
        contract = str(body.get("contract", ""))
        pnl = body.get("pnl")
        reason_entered = str(body.get("reason_entered", ""))
        reason_exited = str(body.get("reason_exited", ""))
        followed_plan = int(bool(body.get("followed_plan", True)))
        mistakes = str(body.get("mistakes", ""))
        lesson = str(body.get("lesson", ""))
        screenshot_url = str(body.get("screenshot_url", ""))

        conn = sqlite3.connect(REVIEW_DB_PATH, timeout=10)
        try:
            cursor = conn.execute(
                """INSERT INTO trade_reviews
                   (ticker,side,entry_time,exit_time,entry_price,exit_price,
                    contract,pnl,reason_entered,reason_exited,followed_plan,
                    mistakes,lesson,screenshot_url)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ticker, side, entry_time, exit_time, entry_price, exit_price,
                 contract, pnl, reason_entered, reason_exited, followed_plan,
                 mistakes, lesson, screenshot_url)
            )
            conn.commit()
            new_id = cursor.lastrowid
        finally:
            conn.close()

        return jsonify({
            "ok": True,
            "version": VERSION,
            "id": new_id,
            "message": f"Trade review #{new_id} saved.",
            "updated_at_et": now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "version": VERSION}), 500


@app.route("/api/review/trades")
def api_review_trades():
    """APEX 6.4.0 — List trade reviews.

    GET /api/review/trades?ticker=SPX&limit=50
    """
    try:
        ticker = request.args.get("ticker", "").upper()
        limit = max(1, min(int(request.args.get("limit", "100")), 500))
        conn = sqlite3.connect(REVIEW_DB_PATH, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            if ticker:
                rows = conn.execute(
                    "SELECT * FROM trade_reviews WHERE ticker=? ORDER BY id DESC LIMIT ?",
                    (ticker, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM trade_reviews ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        finally:
            conn.close()
        trades = [dict(r) for r in rows]
        return jsonify({
            "ok": True,
            "version": VERSION,
            "ticker": ticker or "ALL",
            "count": len(trades),
            "trades": trades,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "version": VERSION}), 500


@app.route("/api/review/summary")
def api_review_summary():
    """APEX 6.4.0 — Post-trade review analytics summary.

    GET /api/review/summary?ticker=SPX
    """
    try:
        ticker = request.args.get("ticker", "").upper()
        conn = sqlite3.connect(REVIEW_DB_PATH, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            if ticker:
                rows = conn.execute(
                    "SELECT * FROM trade_reviews WHERE ticker=? ORDER BY id ASC", (ticker,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM trade_reviews ORDER BY id ASC"
                ).fetchall()
        finally:
            conn.close()

        trades = [dict(r) for r in rows]
        if not trades:
            return jsonify({
                "ok": True,
                "version": VERSION,
                "ticker": ticker or "ALL",
                "trade_count": 0,
                "summary": {"message": "No trade reviews logged yet."},
            })

        total = len(trades)
        with_pnl = [t for t in trades if t.get("pnl") is not None]
        winners = [t for t in with_pnl if (t.get("pnl") or 0) > 0]
        losers  = [t for t in with_pnl if (t.get("pnl") or 0) <= 0]
        win_rate = round(len(winners) / max(len(with_pnl), 1) * 100, 1)
        avg_pnl  = round(sum(t["pnl"] for t in with_pnl) / max(len(with_pnl), 1), 2) if with_pnl else None
        avg_win  = round(sum(t["pnl"] for t in winners) / max(len(winners), 1), 2) if winners else None
        avg_loss = round(sum(t["pnl"] for t in losers) / max(len(losers), 1), 2) if losers else None
        followed = sum(1 for t in trades if t.get("followed_plan"))
        plan_rate = round(followed / total * 100, 1)

        # Common mistakes
        mistake_counts: Dict[str, int] = {}
        for t in trades:
            for m in (t.get("mistakes") or "").split(";"):
                m = m.strip()
                if m:
                    mistake_counts[m] = mistake_counts.get(m, 0) + 1
        top_mistakes = sorted(mistake_counts.items(), key=lambda x: -x[1])[:5]

        # Lessons
        lessons = [t.get("lesson", "").strip() for t in trades if (t.get("lesson") or "").strip()]

        # Average R (if available: avg_win / abs(avg_loss))
        avg_r = None
        if avg_win and avg_loss and avg_loss < 0:
            avg_r = round(avg_win / abs(avg_loss), 2)

        return jsonify({
            "ok": True,
            "version": VERSION,
            "ticker": ticker or "ALL",
            "trade_count": total,
            "summary": {
                "win_rate_pct":     win_rate,
                "winner_count":     len(winners),
                "loser_count":      len(losers),
                "avg_pnl":          avg_pnl,
                "avg_win":          avg_win,
                "avg_loss":         avg_loss,
                "avg_r":            avg_r,
                "followed_plan_pct": plan_rate,
                "top_mistakes":     [{"mistake": m, "count": c} for m, c in top_mistakes],
                "recent_lessons":   lessons[-5:],
            },
            "updated_at_et": now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "version": VERSION}), 500


@app.route("/chart")
def chart_dashboard():
    """Market Intelligence Terminal — ES and SPX side by side."""
    return render_template("chart.html", version=VERSION, asset_version=STATIC_ASSET_VERSION)


# Existing Render/Gunicorn service should keep RUN_SCANNER_ON_IMPORT=true.
# Placed after all route registrations so direct `python app.py` and Gunicorn
# expose the same endpoints.
try:
    init_tracking_db()
except Exception as e:
    print(f"Unexpected error during tracking init (app continues, tracking disabled): {e}", flush=True)
try:
    _init_review_db()
except Exception as e:
    print(f"APEX 6.4.0 review DB init error (non-fatal): {e}", flush=True)
try:
    init_signal_spine()
except Exception as e:
    print(f"APEX signal spine init error (non-fatal): {e}", flush=True)
try:
    # Trade Command Center + E*TRADE sandbox adapter (isolated module).
    # Non-fatal: if anything here fails to import or register, the rest of APEX
    # is completely unaffected — the trade routes simply won't be available.
    from engine.execution.trade_routes import register_trade_routes

    def _spx_spot_provider():
        try:
            with STATE_LOCK:
                lr = STATE.get("last_result") or {}
            return (lr.get("market_state") or {}).get("price")
        except Exception:
            return None

    def _spx_expected_path_provider():
        try:
            with STATE_LOCK:
                lr = STATE.get("last_result") or {}
            r = lr.get("risk") or {}
            return r.get("target1") or r.get("target2")
        except Exception:
            return None

    def _spx_candles_provider(days, tf):
        # Reuse APEX's existing SPX cash fetch (I:SPX) — real index bars.
        return _chart_fetch_bars("I:SPX", days=days, multiplier=tf)

    # Real SPX option chain + expirations from Polygon (feeds the OptionsDataBus,
    # ahead of the E*TRADE sandbox fallback).
    from engine.options import polygon_chain as _polygon_chain
    _POLY_UNDERLYING = os.getenv("POLYGON_OPTIONS_UNDERLYING", "I:SPX").strip() or "I:SPX"
    try:
        _POLY_STRIKE_WINDOW = float(os.getenv("POLYGON_STRIKE_WINDOW_PCT", "0.05"))
    except Exception:
        _POLY_STRIKE_WINDOW = 0.05

    def _poly_chain_fetcher(symbol, expiration, side):
        if not POLYGON_API_KEY:
            return None
        try:
            spot = _spx_spot_provider()
        except Exception:
            spot = None
        return _polygon_chain.fetch_chain(
            safe_get_json, expiration, side,
            underlying=_POLY_UNDERLYING, next_page=_polygon_next_page,
            spot=spot, window_pct=_POLY_STRIKE_WINDOW)

    def _poly_expirations_provider():
        if not POLYGON_API_KEY:
            return None
        return _polygon_chain.fetch_expirations(
            safe_get_json, underlying=_POLY_UNDERLYING, next_page=_polygon_next_page)

    register_trade_routes(
        app,
        spot_provider=_spx_spot_provider,
        expected_path_provider=_spx_expected_path_provider,
        spx_candles_provider=_spx_candles_provider,
        polygon_chain_fetcher=_poly_chain_fetcher,
        polygon_expirations_provider=_poly_expirations_provider,
    )
    print("APEX Trade Command Center routes registered (sandbox).", flush=True)
except Exception as e:
    print(f"Trade Command Center unavailable (non-fatal): {e}", flush=True)

# APEX 8.0 — Active Trade Director routes (isolated, non-fatal).
# Registered independently of the Trade Command Center so a failure in either
# leaves the other unaffected. All inputs are injected from existing globals —
# the Director never fetches data itself and never bypasses execution controls.
try:
    if ACTIVE_TRADE_DIRECTOR_AVAILABLE and register_director_routes is not None:

        def _atd_last_result():
            try:
                with STATE_LOCK:
                    return dict(STATE.get("last_result") or {})
            except Exception:
                return {}

        def _atd_flow_snapshot(ticker):
            try:
                return quantdata_flow_snapshot(ticker)
            except Exception:
                return {}

        def _atd_session():
            try:
                return market_session_context()
            except Exception:
                return {}

        def _atd_signal():
            try:
                with TRADE_ASSISTANT_LOCK:
                    dec = TRADE_ASSISTANT_STATE.get("last_decision") or {}
                    sig = TRADE_ASSISTANT_STATE.get("last_signal") or {}
                return {"fresh_signal": bool(dec.get("fresh_signal")), **({} if not isinstance(sig, dict) else sig)}
            except Exception:
                return {}

        def _atd_open_brackets():
            try:
                from engine.execution.bracket_manager import get_bracket_manager
                return [b.to_dict() for b in get_bracket_manager().open_brackets()]
            except Exception:
                return []

        def _atd_broker_positions():
            try:
                from engine.brokers.etrade_adapter import ETradeAdapter
                adapter = ETradeAdapter()
                if not getattr(adapter, "configured", False):
                    return []
                r = adapter.get_positions(adapter.account_id_key)
                return (r.data or {}).get("positions", []) if getattr(r, "ok", False) else []
            except Exception:
                return []

        def _atd_manual_position():
            try:
                with ACTIVE_POSITION_LOCK:
                    return dict(ACTIVE_POSITION)
            except Exception:
                return {}

        register_director_routes(
            app,
            last_result_provider=_atd_last_result,
            flow_snapshot_provider=_atd_flow_snapshot,
            session_provider=_atd_session,
            signal_provider=_atd_signal,
            broker_positions_provider=_atd_broker_positions,
            open_brackets_provider=_atd_open_brackets,
            manual_position_provider=_atd_manual_position,
            default_ticker=ASSISTANT_TICKER,
        )
        print(f"APEX Active Trade Director routes registered ({DIRECTOR_VERSION}).", flush=True)
except Exception as e:
    print(f"Active Trade Director unavailable (non-fatal): {e}", flush=True)
if RUN_SCANNER_ON_IMPORT:
    start_background_scanner()

if __name__ == "__main__":
    print(f"Starting APEX {VERSION}", flush=True)
    if os.getenv("RUN_SCANNER_ON_IMPORT", "false").lower() != "true":
        print("Background scanner disabled for direct app.py execution. Set RUN_SCANNER_ON_IMPORT=true to enable it.", flush=True)
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
