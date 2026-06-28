from __future__ import annotations

import datetime as dt
import os
import time
import threading
import sqlite3
import statistics
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, jsonify, render_template_string, request

# APEX 4.5 nine-engine decision support system
try:
    from apex_engines import build_institutional_decision as _build_institutional_decision
    APEX_ENGINES_AVAILABLE = True
except ImportError:
    _build_institutional_decision = None
    APEX_ENGINES_AVAILABLE = False
    print("apex_engines.py not found — nine-engine pipeline disabled. Deploy apex_engines.py alongside app.py.", flush=True)

VERSION = "3.5.1_SESSION_AWARE_TRADE_ASSISTANT"
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
SENT_ALERTS: set[str] = set()
SENT_ALERTS_LOCK = threading.Lock()
STATE_LOCK = threading.RLock()
SCAN_LOCK = threading.Lock()
SCANNER_START_LOCK = threading.Lock()
SCANNER_STARTED = False
TRADE_ASSISTANT_LOCK = threading.RLock()
TRADE_ASSISTANT_STATE: Dict[str, Any] = {
    "state": "WAITING",
    "message": "Waiting for Flow/GEX snapshot and Pine trigger",
    "last_signal": None,
    "last_decision": None,
    "updated_at": None,
    "updated_at_et": None,
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
    "last_scan_status": "Starting APEX 3.5.1 scanner...",
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


def session_status() -> str:
    n = now_et()
    if n.weekday() >= 5:
        return "CLOSED"
    minutes = n.hour * 60 + n.minute
    if 9 * 60 + 30 <= minutes <= 16 * 60:
        return "MARKET_OPEN"
    if 4 * 60 <= minutes < 9 * 60 + 30:
        return "PREMARKET"
    return "AFTER_HOURS"


def market_session_context() -> Dict[str, Any]:
    """Session-aware guidance for the Trade Assistant.

    The assistant should not imply an executable entry when the market is
    closed, premarket, or after-hours. Flow/GEX can define the game plan, but
    only a fresh Pine trigger during MARKET_OPEN can produce ENTER_NOW.
    """
    status = session_status()
    n = now_et()
    minutes = n.hour * 60 + n.minute
    open_minutes = 9 * 60 + 30
    close_minutes = 16 * 60
    if status == "MARKET_OPEN":
        return {
            "session": status,
            "is_tradeable_session": True,
            "banner_level": "GREEN",
            "banner_title": "MARKET OPEN",
            "banner_message": "Live mode: entries require Flow/GEX approval plus a fresh Pine trigger.",
            "assistant_mode": "LIVE_TRADE_ASSISTANT",
        }
    if status == "PREMARKET":
        mins_to_open = max(0, open_minutes - minutes)
        return {
            "session": status,
            "is_tradeable_session": False,
            "minutes_to_open": mins_to_open,
            "banner_level": "YELLOW",
            "banner_title": "PREMARKET GAME PLAN",
            "banner_message": f"No entries yet. Use the bias as the opening plan; wait for market open and a fresh Pine trigger. Open in ~{mins_to_open} min.",
            "assistant_mode": "GAME_PLAN",
        }
    if status == "AFTER_HOURS":
        return {
            "session": status,
            "is_tradeable_session": False,
            "banner_level": "YELLOW",
            "banner_title": "AFTER HOURS",
            "banner_message": "Execution disabled. Use current Flow/GEX as review and preparation only; it will be refreshed next session.",
            "assistant_mode": "REVIEW_PREP",
        }
    return {
        "session": status,
        "is_tradeable_session": False,
        "banner_level": "RED",
        "banner_title": "MARKET CLOSED",
        "banner_message": "No new entries while the market is closed. Bias is informational only; wait for the next open and a fresh Pine trigger.",
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


def get_daily_bars(ticker: str, days: int = 320) -> List[dict]:
    end = now_et().date()
    start = end - dt.timedelta(days=days * 2)
    url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}"
    data = safe_get_json(url, params={"adjusted": "true", "sort": "asc", "limit": 5000}, timeout=20)
    return data.get("results", []) if data else []


def get_intraday_bars(ticker: str, multiplier: int = 5, limit_days: int = 3) -> List[dict]:
    end = now_et().date()
    start = end - dt.timedelta(days=limit_days)
    url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/{multiplier}/minute/{start}/{end}"
    data = safe_get_json(url, params={"adjusted": "true", "sort": "asc", "limit": 5000}, timeout=15)
    return data.get("results", []) if data else []


def get_vix_price() -> Optional[float]:
    """Fetch the current VIX spot price from Polygon."""
    data = safe_get_json("https://api.polygon.io/v2/last/trade/VXX", timeout=10)
    if data and "results" in data:
        return safe_float(data["results"].get("p") or data["results"].get("price"), 0.0) or None
    # Fallback: daily snapshot for VIX
    data = safe_get_json("https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/VIXY", timeout=10)
    if data and "ticker" in data:
        day = (data["ticker"].get("day") or {})
        return safe_float(day.get("c") or day.get("vw"), 0.0) or None
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
    """QuantData gamma exposure-by-strike layer.

    Uses QuantData's /options/tool/exposure-by-strike endpoint with greekMode=GAMMA
    and representationMode=RAW.

    v3.4.5 fix:
    - Filters strike selection around current spot before choosing walls.
    - Chooses call wall from strikes at/above spot and put wall from strikes at/below spot.
    - Uses absolute exposure magnitude so negative put exposure is handled correctly.
    - Calculates zero-gamma from cumulative filtered net exposure instead of grabbing an
      extreme far-away strike with the smallest single-row net value.
    """
    empty = {"gex_score": 50.0, "gex_status": "NEUTRAL - GEX NOT CONFIGURED", "call_wall": None, "put_wall": None, "zero_gamma": None, "stock_price": None, "gex_notes": ["Set QUANTDATA_API_KEY and GEX_ENABLED=true to enable gamma exposure."]}
    if not QUANTDATA_API_KEY or not GEX_ENABLED:
        return empty
    if BREAKER.is_open("quantdata_gex"):
        BREAKER.record_skip("quantdata_gex")
        return {"gex_score": 50.0, "gex_status": "NEUTRAL - CIRCUIT OPEN", "call_wall": None, "put_wall": None, "zero_gamma": None, "stock_price": None, "gex_notes": ["quantdata_gex skipped after repeated failures this scan cycle."]}

    headers = {"Authorization": f"Bearer {QUANTDATA_API_KEY}", "Content-Type": "application/json"}
    payload = {"greekMode": "GAMMA", "representationMode": "RAW", "filter": {"ticker": ticker}}
    data = safe_post_json(f"{QUANTDATA_BASE_URL}/options/tool/exposure-by-strike", payload, headers=headers, timeout=20)
    BREAKER.record_failure("quantdata_gex") if data is None else BREAKER.record_success("quantdata_gex")
    if not isinstance(data, dict):
        return {"gex_score": 50.0, "gex_status": "NEUTRAL - NO GEX RETURNED", "call_wall": None, "put_wall": None, "zero_gamma": None, "stock_price": None, "gex_notes": ["QuantData exposure-by-strike returned no usable response."]}

    ticker_data = (data.get("data") or {}).get(ticker) if isinstance(data.get("data"), dict) else None
    if not isinstance(ticker_data, dict):
        for k, v in (data.get("data") or {}).items() if isinstance(data.get("data"), dict) else []:
            if str(k).upper() == ticker.upper() and isinstance(v, dict):
                ticker_data = v
                break
    if not isinstance(ticker_data, dict):
        return {"gex_score": 50.0, "gex_status": "NEUTRAL - NO GEX MAP", "call_wall": None, "put_wall": None, "zero_gamma": None, "stock_price": None, "gex_notes": ["No exposureMap found for ticker."]}

    exposure_map = ticker_data.get("exposureMap") or {}
    stock_price = safe_float(ticker_data.get("stockPrice"), None)
    by_strike: Dict[float, Dict[str, float]] = {}

    if isinstance(exposure_map, dict):
        for _exp, strikes in exposure_map.items():
            if not isinstance(strikes, dict):
                continue
            for strike_raw, cell in strikes.items():
                if not isinstance(cell, dict):
                    continue
                strike = safe_float(strike_raw, None)
                if strike is None:
                    continue
                bucket = by_strike.setdefault(strike, {"call": 0.0, "put": 0.0, "net": 0.0})
                call_exp = safe_float(cell.get("callExposure"), 0.0)
                put_exp = safe_float(cell.get("putExposure"), 0.0)
                bucket["call"] += call_exp
                bucket["put"] += put_exp
                bucket["net"] += call_exp + put_exp

    if not by_strike:
        return {"gex_score": 50.0, "gex_status": "NEUTRAL - EMPTY GEX MAP", "call_wall": None, "put_wall": None, "zero_gamma": None, "stock_price": stock_price, "gex_notes": ["Exposure map contained no strike rows."]}

    # If QuantData does not provide a spot price, use the median strike as a defensive fallback.
    if not stock_price or stock_price <= 0:
        sorted_all = sorted(by_strike.keys())
        stock_price = sorted_all[len(sorted_all) // 2]

    # Wall levels should be relevant to the current trading area, not far OTM/LEAPS strikes.
    # SPX can have wider strike maps, so keep a 10% band around spot by default.
    band_pct = 0.10 if ticker.upper() in ("SPX", "SPXW") else 0.12
    low_bound = stock_price * (1 - band_pct)
    high_bound = stock_price * (1 + band_pct)
    filtered = {k: v for k, v in by_strike.items() if low_bound <= k <= high_bound}

    # If the band is too sparse, widen once before falling back to all strikes.
    if len(filtered) < 10:
        wide_low = stock_price * 0.80
        wide_high = stock_price * 1.20
        filtered = {k: v for k, v in by_strike.items() if wide_low <= k <= wide_high}
        low_bound, high_bound = wide_low, wide_high
    if not filtered:
        filtered = by_strike
        low_bound, high_bound = min(by_strike.keys()), max(by_strike.keys())

    calls_above = {k: v for k, v in filtered.items() if k >= stock_price}
    puts_below = {k: v for k, v in filtered.items() if k <= stock_price}

    # Use absolute exposure magnitude. Put exposure is commonly negative, so min() alone can be misleading.
    call_pool = calls_above or filtered
    put_pool = puts_below or filtered
    call_wall = max(call_pool.items(), key=lambda kv: abs(kv[1]["call"]))[0]
    put_wall = max(put_pool.items(), key=lambda kv: abs(kv[1]["put"]))[0]

    # Approximate zero-gamma from cumulative net exposure across the filtered strike curve.
    # Prefer the cumulative zero crossing closest to spot; fallback to closest cumulative value.
    sorted_rows = sorted(filtered.items(), key=lambda kv: kv[0])
    cumulative = 0.0
    prev_strike = None
    prev_cum = None
    crossing_candidates: List[float] = []
    best_abs = None
    best_zero = sorted_rows[0][0]
    for strike, vals in sorted_rows:
        cumulative += vals["net"]
        if prev_cum is not None and ((prev_cum <= 0 <= cumulative) or (prev_cum >= 0 >= cumulative)):
            crossing_candidates.append((prev_strike + strike) / 2 if prev_strike is not None else strike)
        abs_cum = abs(cumulative)
        if best_abs is None or abs_cum < best_abs:
            best_abs = abs_cum
            best_zero = strike
        prev_strike = strike
        prev_cum = cumulative
    zero_gamma = min(crossing_candidates, key=lambda x: abs(x - stock_price)) if crossing_candidates else best_zero

    total_net = sum(v["net"] for v in filtered.values())
    total_abs = sum(abs(v["call"]) + abs(v["put"]) for v in filtered.values()) or 1.0
    net_ratio = total_net / total_abs
    score = max(0, min(100, 50 + net_ratio * 50))
    status = "POSITIVE GAMMA / PIN RISK" if score >= 60 else "NEGATIVE GAMMA / TREND RISK" if score <= 40 else "MIXED GAMMA"

    return {
        "gex_score": round(score, 1),
        "gex_status": status,
        "call_wall": round(call_wall, 2),
        "put_wall": round(put_wall, 2),
        "zero_gamma": round(zero_gamma, 2),
        "stock_price": round(stock_price, 2) if stock_price else None,
        "net_gamma_ratio": round(net_ratio, 4),
        "strike_count": len(filtered),
        "raw_strike_count": len(by_strike),
        "gex_notes": [
            f"Call wall {call_wall:.2f}",
            f"Put wall {put_wall:.2f}",
            f"Approx zero-gamma {zero_gamma:.2f}",
            f"Spot {stock_price:.2f}",
            f"Filtered strikes {len(filtered)}/{len(by_strike)} within {low_bound:.2f}-{high_bound:.2f}",
        ],
    }


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
        "stock_price": gex.get("stock_price"),
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

VERSION_45 = "4.5.0_INSTITUTIONAL_OS"

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

APEX_OS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>APEX Institutional OS</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700;800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#05080f;--surf:#0d141f;--surf2:#121c2b;--bdr:#1c2940;
  --text:#e8f1fc;--muted:#8295b3;--faint:#5a6b87;
  --blue:#38bdf8;--green:#22c55e;--amber:#f59e0b;--red:#ef4444;--purple:#a78bfa;
  --mono:'JetBrains Mono',ui-monospace,monospace;--sans:'Inter',system-ui,sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:var(--sans);background:var(--bg);color:var(--text);-webkit-font-smoothing:antialiased}
.wrap{max-width:1400px;margin:0 auto;padding:16px 16px 60px}
.topbar{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:14px;padding:12px 16px;background:var(--surf);border:1px solid var(--bdr);border-radius:12px}
.logo{font-family:var(--mono);font-size:18px;font-weight:800;color:var(--blue)}
.logo span{font-size:12px;font-weight:400;color:var(--faint);margin-left:8px}
.top-meta{display:flex;align-items:center;gap:16px;font-family:var(--mono);font-size:12px;color:var(--muted)}
.spx-price{color:var(--text);font-weight:700;font-size:14px}
.session-pill{padding:3px 10px;border-radius:999px;font-size:11px;font-weight:700;border:1px solid var(--bdr)}
.sess-open{color:var(--green);border-color:rgba(34,197,94,.4);background:rgba(34,197,94,.08)}
.sess-closed{color:var(--amber);border-color:rgba(245,158,11,.4);background:rgba(245,158,11,.08)}
.dot-live{width:7px;height:7px;border-radius:50%;background:var(--blue);animation:pulse 1.4s ease-in-out infinite;display:inline-block;margin-right:5px}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(56,189,248,.6)}50%{box-shadow:0 0 0 6px rgba(56,189,248,0)}}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:10px}
.card{background:var(--surf);border:1px solid var(--bdr);border-radius:12px;padding:14px 16px}
.card-label{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.9px;color:var(--faint);margin-bottom:10px}
.decision-badge{display:inline-flex;align-items:center;gap:8px;padding:7px 14px;border-radius:8px;font-weight:700;font-size:14px;margin-bottom:12px;font-family:var(--mono)}
.badge-call{background:rgba(34,197,94,.1);color:var(--green);border:1px solid rgba(34,197,94,.3)}
.badge-put{background:rgba(239,68,68,.1);color:var(--red);border:1px solid rgba(239,68,68,.3)}
.badge-caution{background:rgba(245,158,11,.1);color:var(--amber);border:1px solid rgba(245,158,11,.3)}
.badge-neutral{background:rgba(130,149,179,.1);color:var(--muted);border:1px solid var(--bdr)}
.readiness-num{font-size:54px;font-weight:800;line-height:1;font-family:var(--mono)}
.num-green{color:var(--green)}
.num-amber{color:var(--amber)}
.num-red{color:var(--red)}
.gate-row{display:flex;align-items:center;gap:7px;font-size:12px;color:var(--muted);margin:3px 0}
.gate-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.gd-on{background:var(--green)}
.gd-warn{background:var(--amber)}
.gd-off{background:var(--red)}
.decay-bar{height:4px;border-radius:2px;background:var(--surf2);overflow:hidden;margin:6px 0 2px}
.decay-fill{height:100%;border-radius:2px;transition:width .5s;background:var(--blue)}
.decay-meta{display:flex;justify-content:space-between;font-size:10px;color:var(--faint)}
.story-entry{display:flex;gap:10px;align-items:flex-start;margin-bottom:8px}
.story-time{font-family:var(--mono);font-size:10px;color:var(--faint);flex-shrink:0;width:36px;padding-top:2px}
.story-connector{display:flex;flex-direction:column;align-items:center;flex-shrink:0}
.s-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;margin-top:2px}
.s-line{width:1px;flex:1;min-height:14px;background:var(--bdr);margin:3px 0}
.story-text{font-size:12px;color:var(--muted);line-height:1.6;padding-bottom:4px}
.coach-block{font-size:13px;color:var(--muted);line-height:1.75;padding:11px 13px;background:var(--surf2);border-radius:8px;border-left:3px solid var(--blue)}
.level-row{display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid var(--bdr);font-size:12px}
.level-label{color:var(--faint)}
.level-val{font-family:var(--mono);font-weight:500}
.badge-small{font-size:10px;padding:2px 7px;border-radius:4px;font-weight:700}
.bs-bull{background:rgba(34,197,94,.12);color:var(--green)}
.bs-bear{background:rgba(239,68,68,.12);color:var(--red)}
.bs-neut{background:rgba(130,149,179,.1);color:var(--muted)}
.heat-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}
.heat-item{padding:10px;border-radius:8px;text-align:center;border:1px solid var(--bdr)}
.heat-ticker{font-family:var(--mono);font-size:12px;font-weight:700}
.heat-score{font-size:20px;font-weight:800;font-family:var(--mono)}
.heat-action{font-size:10px;font-weight:700;margin-top:2px;text-transform:uppercase}
.h-enter{background:rgba(34,197,94,.08);border-color:rgba(34,197,94,.25)}
.h-enter .heat-ticker,.h-enter .heat-score,.h-enter .heat-action{color:var(--green)}
.h-watch{background:rgba(56,189,248,.06);border-color:rgba(56,189,248,.2)}
.h-watch .heat-ticker,.h-watch .heat-score,.h-watch .heat-action{color:var(--blue)}
.h-wait{background:rgba(245,158,11,.06);border-color:rgba(245,158,11,.2)}
.h-wait .heat-ticker,.h-wait .heat-score,.h-wait .heat-action{color:var(--amber)}
.h-no{background:rgba(239,68,68,.06);border-color:rgba(239,68,68,.2)}
.h-no .heat-ticker,.h-no .heat-score,.h-no .heat-action{color:var(--red)}
.planner-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.pl-item{display:flex;justify-content:space-between;align-items:center;font-size:12px;padding:5px 0;border-bottom:1px solid var(--bdr)}
.pl-key{color:var(--faint)}
.pl-val{font-family:var(--mono);font-weight:500}
.flow-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:10px}
.flow-card{background:var(--surf2);border:1px solid var(--bdr);border-radius:8px;padding:10px 12px}
.flow-name{font-size:10px;text-transform:uppercase;letter-spacing:.8px;color:var(--faint);margin-bottom:4px}
.flow-val{font-size:17px;font-weight:700;font-family:var(--mono)}
.flow-sub{font-size:10px;color:var(--muted);margin-top:2px}
.action-bar{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.btn{font-size:11px;padding:5px 11px;border-radius:7px;border:1px solid var(--bdr);background:transparent;color:var(--muted);cursor:pointer;font-family:var(--sans);transition:all .15s}
.btn:hover{background:var(--surf2);color:var(--text)}
.btn-primary{border-color:rgba(56,189,248,.5);color:var(--blue);background:rgba(56,189,248,.06)}
.btn-primary:hover{background:rgba(56,189,248,.12)}
.conf-num{font-size:28px;font-weight:800;font-family:var(--mono)}
.section-full{margin-bottom:10px}
.last-updated{font-size:10px;color:var(--faint);text-align:right;margin-top:8px}
.checklist{display:flex;flex-direction:column;gap:5px;margin-top:8px}
.err-box{background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.25);border-radius:8px;padding:10px 14px;color:var(--red);font-size:12px;margin-bottom:10px}
.apex-nav{display:flex;align-items:center;gap:6px;padding:8px 14px;background:var(--surf);border:1px solid var(--bdr);border-radius:12px;margin-bottom:12px;flex-wrap:wrap}
.apex-nav .nav-logo{font-family:var(--mono);font-size:13px;font-weight:800;color:var(--blue);margin-right:10px;text-decoration:none}
.apex-nav a{font-size:12px;font-weight:600;padding:5px 12px;border-radius:7px;border:1px solid transparent;color:var(--muted);text-decoration:none;transition:all .15s}
.apex-nav a:hover{background:var(--surf2);color:var(--text);border-color:var(--bdr)}
.apex-nav a.active{background:rgba(56,189,248,.1);color:var(--blue);border-color:rgba(56,189,248,.35)}
.apex-nav .nav-sep{width:1px;height:18px;background:var(--bdr);margin:0 4px}
</style>
</head>
<body>
<div class="wrap" id="root">

<nav class="apex-nav">
  <a href="/" class="nav-logo">APEX</a>
  <a href="/">Scanner</a>
  <a href="/apex_os" class="active">Institutional OS</a>
  <a href="/assistant">Trade Assistant</a>
  <a href="/flow">Flow / GEX</a>
  <a href="/chart">Charts</a>
  <div class="nav-sep"></div>
  <a href="/api/v45/status" target="_blank">Status</a>
  <a href="/health" target="_blank">Health</a>
</nav>

<div class="topbar">
  <div>
    <div class="logo">APEX <span>Institutional OS v4.5</span></div>
  </div>
  <div class="top-meta">
    <span><span class="dot-live"></span><span id="clockEl">--:--:-- ET</span></span>
    <span id="sessionPill" class="session-pill sess-closed">LOADING</span>
    <span>SPX <span class="spx-price" id="spxEl">--</span></span>
    <button class="btn btn-primary" onclick="loadOS()">↻ Refresh</button>
  </div>
</div>

<div id="errBox" class="err-box" style="display:none">Error loading APEX data.</div>

<div class="grid2">
  <div class="card">
    <div class="card-label">Decision engine</div>
    <div id="decisionBadge" class="decision-badge badge-neutral">— Loading</div>
    <div style="display:flex;gap:16px;align-items:flex-end">
      <div>
        <div id="confNum" class="conf-num" style="color:var(--blue)">--</div>
        <div style="font-size:11px;color:var(--faint);margin-top:3px">Confidence</div>
      </div>
      <div style="flex:1">
        <div style="font-size:10px;color:var(--faint);margin-bottom:2px">Signal decay</div>
        <div id="decayFill" class="decay-bar"><div class="decay-fill" id="decayBar" style="width:0%"></div></div>
        <div class="decay-meta"><span id="decayAge">--</span><span id="decayExp">--</span></div>
      </div>
    </div>
    <div style="font-size:12px;color:var(--muted);margin-top:10px;line-height:1.6" id="decisionMsg">--</div>
    <div style="font-size:11px;color:var(--faint);margin-top:6px;font-style:italic" id="decisionAction">--</div>
  </div>

  <div class="card">
    <div class="card-label">Trade readiness</div>
    <div style="display:flex;gap:14px;align-items:flex-start">
      <div>
        <div class="readiness-num num-green" id="readinessNum">--</div>
        <div style="font-size:11px;color:var(--faint)">/ 100</div>
      </div>
      <div class="checklist" id="gateChecks"></div>
    </div>
  </div>
</div>

<div class="grid2">
  <div class="card">
    <div class="card-label">Institutional story</div>
    <div id="storyWrap"></div>
  </div>
  <div class="card">
    <div class="card-label">AI trade coach</div>
    <div id="coachText" class="coach-block">Loading institutional narrative...</div>
    <div class="action-bar">
      <button class="btn btn-primary" onclick="window.location.href='/api/institutional_os'">Full JSON ↗</button>
      <button class="btn" onclick="window.location.href='/assistant'">Assistant ↗</button>
      <button class="btn" onclick="window.location.href='/flow'">Flow dashboard ↗</button>
    </div>
  </div>
</div>

<div class="grid3">
  <div class="card">
    <div class="card-label">GEX levels</div>
    <div id="gexRows"></div>
  </div>
  <div class="card">
    <div class="card-label">Flow inputs</div>
    <div class="flow-grid" id="flowGrid"></div>
  </div>
  <div class="card">
    <div class="card-label">Trade planner</div>
    <div id="plannerWrap"></div>
  </div>
</div>

<div class="section-full card">
  <div class="card-label">Institutional heat map</div>
  <div class="heat-grid" id="heatGrid"></div>
</div>

<div class="last-updated" id="lastUpdated">--</div>

</div>

<script>
let osData = null;

function clock(){
  const now = new Date();
  const et = new Intl.DateTimeFormat('en-US',{hour:'numeric',minute:'2-digit',second:'2-digit',hour12:true,timeZone:'America/New_York'}).format(now);
  document.getElementById('clockEl').textContent = et + ' ET';
}
setInterval(clock, 1000); clock();

function badgeClass(state){
  if(!state) return 'badge-neutral';
  if(state.includes('CALL')) return 'badge-call';
  if(state.includes('PUT')) return 'badge-put';
  if(state.includes('CAUTION') || state.includes('WAITING')) return 'badge-caution';
  return 'badge-neutral';
}

function renderDecision(d){
  if(!d) return;
  const badge = document.getElementById('decisionBadge');
  const state = d.state || 'WAITING';
  badge.className = 'decision-badge ' + badgeClass(state);
  badge.textContent = (state.includes('CALL') ? '▲ ' : state.includes('PUT') ? '▼ ' : '— ') + state.replace(/_/g,' ');
  document.getElementById('decisionMsg').textContent = d.message || '--';
  document.getElementById('decisionAction').textContent = d.action || '';

  // Alignment / confidence
  const align = d.institutional_alignment || 0;
  const num = document.getElementById('confNum');
  num.textContent = Math.round(align) + '%';
  num.style.color = align >= 70 ? 'var(--green)' : align >= 50 ? 'var(--amber)' : 'var(--red)';
  const rNum = document.getElementById('readinessNum');
  const gates = d.checklist || [];
  const passCount = gates.filter(g => g.ok).length;
  const pct = gates.length ? Math.round(passCount / gates.length * 100) : 0;
  rNum.textContent = pct;
  rNum.className = 'readiness-num ' + (pct >= 75 ? 'num-green' : pct >= 50 ? 'num-amber' : 'num-red');
  // Gates
  const gc = document.getElementById('gateChecks');
  gc.innerHTML = (d.checklist || []).map(g => `<div class="gate-row"><span class="gate-dot ${g.ok ? 'gd-on' : 'gd-warn'}"></span>${g.label}</div>`).join('');

  // Decay
  const secs = d.signal_seconds_remaining || 0;
  const ttl = d.signal_ttl_seconds || 360;
  const decPct = Math.round(secs / ttl * 100);
  document.getElementById('decayBar').style.width = decPct + '%';
  document.getElementById('decayAge').textContent = secs > 0 ? secs + 's left' : 'Expired';
  document.getElementById('decayExp').textContent = secs > 0 ? 'Live' : 'No signal';
}

function renderStory(story){
  const el = document.getElementById('storyWrap');
  if(!story || !story.chapters || !story.chapters.length){
    el.innerHTML = '<div style="color:var(--faint);font-size:12px">No story data yet.</div>';
    return;
  }
  el.innerHTML = story.chapters.map((c, i) => `
    <div class="story-entry">
      <span class="story-time">${c.time || '--'}</span>
      <div class="story-connector">
        <span class="s-dot" style="background:${c.color || '#5a6b87'}"></span>
        ${i < story.chapters.length - 1 ? '<span class="s-line"></span>' : ''}
      </div>
      <div class="story-text"><strong style="color:${c.color || 'var(--muted)'}; font-size:10px; text-transform:uppercase; letter-spacing:.6px">${c.chapter}</strong><br>${c.text}</div>
    </div>`).join('');
}

function renderCoach(story, decision){
  const el = document.getElementById('coachText');
  if(story && story.full_narrative){
    el.textContent = story.full_narrative;
  } else if(decision){
    el.textContent = decision.action || 'Waiting for institutional data...';
  }
}

function renderGex(flow){
  const el = document.getElementById('gexRows');
  if(!flow){ el.innerHTML = ''; return; }
  const rows = [
    {label:'Call wall', val: flow.call_wall ? flow.call_wall.toLocaleString() : '--', cls:'bs-bull'},
    {label:'Put wall', val: flow.put_wall ? flow.put_wall.toLocaleString() : '--', cls:'bs-bear'},
    {label:'Zero gamma', val: flow.zero_gamma ? flow.zero_gamma.toLocaleString() : '--', cls:'bs-neut'},
    {label:'GEX score', val: flow.gex_score != null ? flow.gex_score : '--', cls: flow.gex_score >= 60 ? 'bs-bull' : flow.gex_score <= 40 ? 'bs-bear' : 'bs-neut'},
    {label:'Spot price', val: flow.stock_price ? flow.stock_price.toLocaleString() : '--', cls:'bs-neut'},
  ];
  el.innerHTML = rows.map(r => `<div class="level-row"><span class="level-label">${r.label}</span><div style="display:flex;align-items:center;gap:6px"><span class="level-val">${r.val}</span><span class="badge-small ${r.cls}">${r.val !== '--' ? '✓' : '?'}</span></div></div>`).join('');
}

function renderFlow(flow){
  const el = document.getElementById('flowGrid');
  if(!flow){ el.innerHTML = ''; return; }
  const items = [
    {name:'Net flow', val: flow.net_premium != null ? '$' + (flow.net_premium/1e6).toFixed(1)+'M' : '--', sub: flow.bias || '--'},
    {name:'Flow score', val: flow.flow_score != null ? flow.flow_score : '--', sub: 'Inst. options'},
    {name:'Order flow', val: flow.order_flow_score != null ? flow.order_flow_score : '--', sub: 'Sweeps: ' + (flow.sweep_count || 0)},
    {name:'GEX score', val: flow.gex_score != null ? flow.gex_score : '--', sub: 'Gamma exposure'},
    {name:'Alignment', val: flow.institutional_alignment != null ? Math.round(flow.institutional_alignment) + '%' : '--', sub: flow.decision_color || '--'},
    {name:'Approved', val: flow.approved_side || '--', sub: flow.decision || ''},
  ];
  el.innerHTML = items.map(i => `<div class="flow-card"><div class="flow-name">${i.name}</div><div class="flow-val">${i.val}</div><div class="flow-sub">${i.sub}</div></div>`).join('');
}

function renderPlanner(plan){
  const el = document.getElementById('plannerWrap');
  if(!plan){ el.innerHTML = '<div style="color:var(--faint);font-size:12px">Waiting for signal...</div>'; return; }
  const contract = plan.recommended_contract || '--';
  const rows = [
    {key:'Contract', val: contract},
    {key:'Entry zone', val: plan.entry_zone || '--'},
    {key:'Stop', val: plan.stop_price || '--'},
    {key:'Target 1', val: plan.target_1 || '--'},
    {key:'Target 2', val: plan.target_2 || '--'},
    {key:'R:R', val: plan.rr_to_t1 ? plan.rr_to_t1 + ':1' : '--'},
  ];
  el.innerHTML = `<div style="font-size:13px;font-family:var(--mono);font-weight:700;color:var(--blue);margin-bottom:8px">${contract}</div>
    <div class="planner-grid">${rows.map(r => `<div class="pl-item"><span class="pl-key">${r.key}</span><span class="pl-val">${r.val}</span></div>`).join('')}</div>`;
}

function renderHeatmap(heatmap){
  const el = document.getElementById('heatGrid');
  if(!heatmap || !heatmap.tickers){ el.innerHTML = ''; return; }
  el.innerHTML = heatmap.tickers.map(t => {
    const cls = t.action_class === 'enter' ? 'h-enter' : t.action_class === 'watch' ? 'h-watch' : t.action_class === 'wait' ? 'h-wait' : 'h-no';
    return `<div class="heat-item ${cls}">
      <div class="heat-ticker">${t.ticker}</div>
      <div class="heat-score">${Math.round(t.score || 0)}</div>
      <div class="heat-action">${t.action}</div>
    </div>`;
  }).join('');
}

function renderSPX(flow){
  if(flow && flow.stock_price){
    document.getElementById('spxEl').textContent = parseFloat(flow.stock_price).toLocaleString();
  }
}

function renderSession(session){
  const pill = document.getElementById('sessionPill');
  if(!session){ return; }
  const s = session.session || '';
  pill.textContent = s.replace('_', ' ');
  pill.className = 'session-pill ' + (s === 'MARKET_OPEN' ? 'sess-open' : 'sess-closed');
}

async function loadOS(){
  try{
    const ticker = new URLSearchParams(window.location.search).get('ticker') || 'SPX';
    const r = await fetch('/api/institutional_os?ticker=' + ticker + '&heatmap=1');
    if(!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    osData = data;
    document.getElementById('errBox').style.display = 'none';

    renderSession(data.session);
    renderDecision(data.decision);
    renderStory(data.story);
    renderCoach(data.story, data.decision);
    renderGex(data.flow);
    renderFlow({...data.flow, institutional_alignment: data.decision?.institutional_alignment, approved_side: data.decision?.approved_side, decision_color: data.flow?.decision_color, decision: data.flow?.decision_color});
    renderPlanner(data.decision?.trade_plan);
    renderHeatmap(data.heatmap);
    renderSPX(data.flow);
    document.getElementById('lastUpdated').textContent = 'Updated: ' + (data.updated_at || '--');
  }catch(e){
    document.getElementById('errBox').style.display = '';
    document.getElementById('errBox').textContent = 'Error loading APEX OS: ' + e.message;
  }
}

loadOS();
setInterval(loadOS, 10000);
</script>
</body>
</html>"""

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>APEX 3.3 Dashboard</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700;800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#05080f; --surface:#0d141f; --surface-alt:#121c2b; --border:#1c2940;
  --text:#e8f1fc; --muted:#8295b3; --faint:#5a6b87;
  --accent:#38bdf8; --green:#22c55e; --amber:#f59e0b; --red:#ef4444; --purple:#a78bfa;
  --mono:'JetBrains Mono',ui-monospace,monospace; --sans:'Inter',system-ui,-apple-system,sans-serif;
}
*{box-sizing:border-box}
body{margin:0;font-family:var(--sans);background:var(--bg);color:var(--text);-webkit-font-smoothing:antialiased}
.wrap{max-width:1320px;margin:0 auto;padding:20px 18px 60px}
a{color:inherit}

/* header */
.topbar{display:flex;align-items:baseline;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:14px}
.brand{display:flex;align-items:baseline;gap:10px}
.brand h1{font-family:var(--mono);font-size:21px;font-weight:800;color:var(--accent);margin:0;letter-spacing:-.01em}
.brand .ver{font-family:var(--mono);font-size:11px;color:var(--faint)}
.session-pill{font-family:var(--mono);font-size:11px;font-weight:700;padding:4px 10px;border-radius:999px;border:1px solid var(--border);color:var(--muted)}
.session-pill.open{color:var(--green);border-color:rgba(34,197,94,.35);background:rgba(34,197,94,.08)}

/* status strip: the signature element -- always-visible scan/system health */
.statusbar{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:12px 16px;display:flex;flex-wrap:wrap;align-items:center;gap:18px;margin-bottom:16px}
.scan-indicator{display:flex;align-items:center;gap:9px;font-family:var(--mono);font-size:12.5px}
.dot{width:9px;height:9px;border-radius:50%;background:var(--faint);flex-shrink:0}
.dot.live{background:var(--accent);animation:pulse 1.4s ease-in-out infinite}
.dot.ok{background:var(--green)}
.dot.err{background:var(--red)}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(56,189,248,.55)}50%{box-shadow:0 0 0 6px rgba(56,189,248,0)}}
@media (prefers-reduced-motion:reduce){.dot.live{animation:none}}
.statusbar .sep{width:1px;height:18px;background:var(--border)}
.scan-now-btn{font-family:var(--sans);font-size:12px;font-weight:600;padding:5px 11px;border-radius:8px;border:1px solid var(--accent);background:transparent;color:var(--accent);cursor:pointer}
.scan-now-btn:hover{background:rgba(56,189,248,.1)}
.scan-now-btn:disabled{opacity:.5;cursor:default}
.scan-now-btn:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.source-chips{display:flex;gap:6px;flex-wrap:wrap}
.chip{font-family:var(--mono);font-size:10.5px;padding:3px 8px;border-radius:6px;border:1px solid var(--border);color:var(--muted);display:flex;align-items:center;gap:5px}
.chip .dot{width:6px;height:6px}
.chip.breaker-open{color:var(--red);border-color:rgba(239,68,68,.4);background:rgba(239,68,68,.08)}
.regime-badge{margin-left:auto;font-family:var(--mono);font-size:12px;font-weight:700;padding:4px 10px;border-radius:8px}
.regime-RISKON,.regime-RISK_ON{color:var(--green);background:rgba(34,197,94,.1)}
.regime-DEFENSIVE{color:var(--red);background:rgba(239,68,68,.1)}
.regime-NEUTRAL{color:var(--amber);background:rgba(245,158,11,.1)}

/* toolbar */
.toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:16px}
.search{flex:1;min-width:160px;background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:9px 12px;color:var(--text);font-family:var(--mono);font-size:13px}
.search::placeholder{color:var(--faint)}
.search:focus{outline:2px solid var(--accent);outline-offset:1px}
.filters{display:flex;gap:6px;flex-wrap:wrap}
.fbtn{font-family:var(--sans);font-size:12.5px;font-weight:600;padding:7px 12px;border-radius:999px;border:1px solid var(--border);background:var(--surface);color:var(--muted);cursor:pointer}
.fbtn:hover{color:var(--text)}
.fbtn.active{background:var(--accent);border-color:var(--accent);color:#04131f}
.fbtn:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
select{font-family:var(--sans);font-size:12.5px;background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:10px;padding:8px 10px}

/* empty state */
.empty{background:var(--surface);border:1px dashed var(--border);border-radius:14px;padding:28px 22px;color:var(--muted);text-align:center}
.empty b{color:var(--text)}

/* grid + cards */
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:14px}
.card{background:var(--surface);border:1px solid var(--border);border-left:4px solid var(--accent);border-radius:14px;padding:16px;opacity:0;animation:rise .35s ease forwards}
@keyframes rise{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){.card{animation:none;opacity:1}}
.card.ready{border-left-color:var(--green)}
.card.pre{border-left-color:var(--amber)}
.card.accum{border-left-color:var(--purple)}
.card-head{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}
.ticker{font-family:var(--mono);font-size:24px;font-weight:800}
.grade{color:var(--green);margin-left:4px}
.price{color:var(--muted);font-family:var(--mono);font-size:14px;font-weight:500;margin-left:8px}
.badges{margin-top:4px;display:flex;gap:5px;flex-wrap:wrap}
.badge{display:inline-block;padding:3px 8px;border-radius:999px;background:var(--surface-alt);color:var(--muted);font-size:10.5px;font-family:var(--mono)}
.badge.dir-CALL{color:var(--green)}
.badge.zone-badge{color:#04131f;background:var(--accent);font-weight:700}
.badge.src-live{color:var(--green);border:1px solid rgba(34,197,94,.35);background:rgba(34,197,94,.08);font-weight:700}
.badge.src-est{color:var(--amber);border:1px solid rgba(245,158,11,.4);background:rgba(245,158,11,.1);font-weight:700}
.badge.src-stale{color:var(--red);border:1px solid rgba(239,68,68,.4);background:rgba(239,68,68,.1);font-weight:700}
.badge.dir-PUT{color:var(--red)}
.score{font-family:var(--mono);font-size:24px;font-weight:800;color:var(--accent)}
.scores{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:12px}
.scorebox{background:var(--surface-alt);border-radius:9px;padding:7px;text-align:center}
.scorebox .l{font-size:9.5px;color:var(--faint);text-transform:uppercase;letter-spacing:.05em}
.scorebox .v{font-family:var(--mono);font-size:14px;font-weight:700;margin-top:1px}
.section{margin-top:12px}
.label{color:var(--faint);font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;font-weight:700;margin-bottom:3px}
.value{font-size:13px;line-height:1.45;color:var(--text)}
.value.mono{font-family:var(--mono);font-size:12.5px}
.atr-note{margin-top:6px;font-family:var(--mono);font-size:11.5px;color:var(--muted)}
.ballpark-tag{display:inline-block;margin-left:6px;padding:1px 6px;border-radius:5px;background:var(--surface-alt);color:var(--faint);font-size:9.5px;font-weight:700;letter-spacing:.03em;text-transform:uppercase;vertical-align:middle}
.exec-grid{margin-top:4px;background:var(--surface-alt);border-radius:9px;padding:8px 10px}
.exec-row{display:flex;justify-content:space-between;gap:10px;padding:3px 0;font-family:var(--mono);font-size:12px}
.exec-row .exec-l{color:var(--faint)}
.exec-row .exec-v{color:var(--text);font-weight:600}
details{margin-top:12px}
summary{cursor:pointer;color:var(--accent);font-size:12px;font-weight:600;list-style:none}
summary::-webkit-details-marker{display:none}
summary:before{content:'▸ ';font-size:10px}
details[open] summary:before{content:'▾ '}
details:focus-within summary{outline:2px solid var(--accent);outline-offset:2px}
.why-list{margin-top:8px;color:var(--muted);font-size:12.5px;line-height:1.6}

footer{margin-top:28px;color:var(--faint);font-size:11px;font-family:var(--mono);text-align:center}
</style>
</head>
<style>
.apex-nav{display:flex;align-items:center;gap:6px;padding:8px 14px;background:#0d141f;border:1px solid #1c2940;border-radius:12px;margin-bottom:12px;flex-wrap:wrap}
.apex-nav .nav-logo{font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:800;color:#38bdf8;margin-right:10px;text-decoration:none}
.apex-nav a{font-size:12px;font-weight:600;padding:5px 12px;border-radius:7px;border:1px solid transparent;color:#8295b3;text-decoration:none;transition:all .15s;font-family:'Inter',sans-serif}
.apex-nav a:hover{background:#121c2b;color:#e8f1fc;border-color:#1c2940}
.apex-nav a.active{background:rgba(56,189,248,.1);color:#38bdf8;border-color:rgba(56,189,248,.35)}
.apex-nav .nav-sep{width:1px;height:18px;background:#1c2940;margin:0 4px}
</style>
<body>
<div class="wrap">
  <nav class="apex-nav">
    <a href="/" class="nav-logo">APEX</a>
    <a href="/" class="active">Scanner</a>
    <a href="/apex_os">Institutional OS</a>
    <a href="/assistant">Trade Assistant</a>
    <a href="/flow">Flow / GEX</a>
    <a href="/chart">Charts</a>
    <div class="nav-sep"></div>
    <a href="/api/v45/status" target="_blank">Status</a>
    <a href="/health" target="_blank">Health</a>
  </nav>
  <div class="topbar">
    <div class="brand"><h1>APEX Institutional Forecast Engine</h1><span class="ver" id="ver"></span></div>
    <span class="session-pill" id="sessionPill">--</span>
  </div>

  <div class="statusbar" id="statusbar">
    <div class="scan-indicator"><span class="dot" id="scanDot"></span><span id="scanText">Connecting...</span></div>
    <button class="scan-now-btn" id="scanNowBtn" type="button">Scan Now</button>
    <div class="sep"></div>
    <div class="source-chips" id="sourceChips"></div>
    <div class="regime-badge" id="regimeBadge"></div>
  </div>

  <div class="toolbar">
    <input class="search" id="search" type="text" placeholder="Filter by ticker...">
    <div class="filters" id="statusFilters"></div>
    <button class="fbtn" id="zoneToggle" type="button" aria-pressed="false">In Zone Only</button>
    <select id="sortSel">
      <option value="rank">Sort: Default rank</option>
      <option value="final_score">Sort: Final score</option>
      <option value="breakout_probability">Sort: Breakout probability</option>
      <option value="accumulation_score">Sort: Accumulation score</option>
      <option value="ticker">Sort: Ticker A-Z</option>
    </select>
  </div>

  <div id="content"></div>
  <footer id="footerNote"></footer>
</div>

<script id="initial-data" type="application/json">{{ data | tojson }}</script>
<script>
let state = JSON.parse(document.getElementById('initial-data').textContent || '{}');
let activeFilter = 'ALL';
let zoneOnly = false;
let lastFetchOk = true;
let lastRenderSignature = null;

const STATUS_META = {
  'READY - IN BUY ZONE': {cls:'ready', label:'Ready'},
  'PRE-BREAKOUT WATCHLIST': {cls:'pre', label:'Pre-Breakout'},
  'ACCUMULATION WATCHLIST': {cls:'accum', label:'Accumulating'},
  'WATCHLIST - WAIT FOR ZONE': {cls:'', label:'Watching'},
};

function fmtAgo(iso){
  if(!iso) return 'never';
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime())/1000));
  if(s < 60) return s + 's ago';
  if(s < 3600) return Math.floor(s/60) + 'm ago';
  if(s < 86400) return Math.floor(s/3600) + 'h ago';
  const days = Math.floor(s/86400);
  return days + 'd ' + Math.floor((s%86400)/3600) + 'h ago';
}

function quoteAgeBadge(iso, timeframe){
  if(!iso){
    return '<span class="badge src-est" title="No quote timestamp returned -- freshness unknown.">Quote age: unknown</span>';
  }
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime())/1000));
  let cls = 'src-live', label = fmtAgo(iso);
  if(s >= 3600) cls = 'src-stale';       // 1hr+ -- treat as stale regardless of session
  else if(s >= 60) cls = 'src-est';      // 1-60min -- caution
  const tf = timeframe ? ' (' + timeframe + ')' : '';
  return '<span class="badge ' + cls + '" title="Quote last updated ' + label + tf + '. Polygon plan tiers below Options Advanced are 15-minute delayed even when live.">Quote age: ' + label + '</span>';
}

function renderStatusbar(){
  const dot = document.getElementById('scanDot');
  const text = document.getElementById('scanText');
  document.getElementById('ver').textContent = state.mode || '';
  const pill = document.getElementById('sessionPill');
  pill.textContent = state.session || 'UNKNOWN';
  pill.className = 'session-pill' + (state.session === 'MARKET_OPEN' ? ' open' : '');

  if(!lastFetchOk){
    dot.className = 'dot err'; text.textContent = 'Connection lost -- retrying...';
  } else if(state.scan_in_progress){
    dot.className = 'dot live';
    text.textContent = (state.last_scan_status || 'Scan running...') ;
  } else if(state.last_error){
    dot.className = 'dot err'; text.textContent = 'Last scan failed: ' + state.last_error;
  } else {
    dot.className = 'dot ok';
    const dur = state.last_scan_duration_seconds;
    text.textContent = 'Idle -- last scan ' + fmtAgo(state.updated_at) + (dur ? ' (' + dur + 's)' : '');
  }

  const sources = state.data_sources || {};
  const breaker = state.circuit_breaker || {open_circuits:[], skipped_calls:{}};
  const chips = [];
  for(const [name, ok] of Object.entries(sources)){
    chips.push('<span class="chip"><span class="dot ' + (ok?'ok':'') + '"></span>' + name + '</span>');
  }
  (breaker.open_circuits || []).forEach(name => {
    const skipped = (breaker.skipped_calls || {})[name] || 0;
    chips.push('<span class="chip breaker-open" title="Repeated failures this scan -- skipped automatically">' + name.replace(/_/g,' ') + ' down (' + skipped + ' skipped)</span>');
  });
  document.getElementById('sourceChips').innerHTML = chips.join('');

  const regime = state.market_regime || {};
  const rb = document.getElementById('regimeBadge');
  if(regime.market_regime){
    rb.textContent = 'Regime: ' + regime.market_regime + ' (' + regime.market_regime_score + ')';
    rb.className = 'regime-badge regime-' + regime.market_regime.replace(/\\s+/g,'');
  } else { rb.textContent = ''; }

  document.getElementById('footerNote').textContent =
    (state.ticker_count || 0) + ' tickers scanned | updated ' + fmtAgo(state.updated_at) + ' | checking for updates every 30s (only redraws when something changes)';
}

function renderFilters(ideas){
  const counts = {ALL: ideas.length};
  ideas.forEach(i => { counts[i.status] = (counts[i.status]||0) + 1; });
  const order = ['ALL', 'READY - IN BUY ZONE', 'PRE-BREAKOUT WATCHLIST', 'ACCUMULATION WATCHLIST', 'WATCHLIST - WAIT FOR ZONE'];
  const box = document.getElementById('statusFilters');
  box.innerHTML = order.filter(k => k === 'ALL' || counts[k]).map(k => {
    const label = k === 'ALL' ? 'All' : (STATUS_META[k] ? STATUS_META[k].label : k);
    return '<button class="fbtn' + (activeFilter===k?' active':'') + '" data-f="' + k + '">' + label + ' (' + (counts[k]||0) + ')</button>';
  }).join('');
  box.querySelectorAll('.fbtn').forEach(b => b.onclick = () => { activeFilter = b.dataset.f; renderCards(); });
}

function cardHtml(idea){
  const meta = STATUS_META[idea.status] || {cls:'', label: idea.status || ''};
  const notes = (idea.notes || []).slice(0, 8).map(n => '<div>&bull; ' + n + '</div>').join('');
  const inZone = (idea.buy_zone_status||'').includes('INSIDE');
  return '<div class="card ' + meta.cls + '" data-ticker="' + idea.ticker + '">' +
    '<div class="card-head"><div><div class="ticker">' + idea.ticker + '<span class="grade">' + (idea.grade||'') + '</span>' +
    '<span class="price">$' + (idea.price!=null ? idea.price : '--') + '</span></div>' +
    '<div class="badges"><span class="badge dir-' + idea.direction + '">' + idea.direction + '</span>' +
    '<span class="badge">' + idea.trader_type + '</span><span class="badge">' + meta.label + '</span>' +
    (inZone ? '<span class="badge zone-badge">IN ZONE</span>' : '') + '</div></div>' +
    '<div class="score">' + (idea.final_score!=null ? idea.final_score : '--') + '</div></div>' +
    '<div class="scores">' +
      scorebox('Tech', idea.technical_score) + scorebox('Flow', idea.flow_score_directional) +
      scorebox('Order', idea.order_flow_score_directional) + scorebox('Dark', idea.dark_pool_score) +
      scorebox('Accum', idea.accumulation_score) + scorebox('Breakout', idea.breakout_probability, '%') +
      scorebox('Catalyst', idea.catalyst_score) + scorebox('RVOL', idea.rel_volume) +
    '</div>' +
    '<div class="section"><div class="label">Institutional Forecast</div><div class="value">' + (idea.accumulation_status||'') +
      '<br>' + (idea.buy_zone_status||'') + ' &middot; Zone ' + (idea.entry_range||'') + ' &middot; Distance ' + idea.distance_to_buy_zone_pct + '%</div></div>' +
    '<div class="section"><div class="label">Trigger</div><div class="value">' + (idea.confirmation_trigger||'') + '</div></div>' +
    '<div class="section"><div class="label">Option</div><div class="value mono">' + (idea.option_contract||'') + '<br>' + (idea.option_liquidity||'') + ' &middot; Contracts: ' + idea.recommended_contracts + '</div></div>' +
    execSection(idea) +
    '<div class="section"><div class="label">Stock Targets / Stop</div><div class="value mono">T1 ' + idea.target_1_price + ' &middot; T2 ' + idea.target_2_price + ' &middot; Stop ' + idea.stock_stop + '</div>' + atrTimingNote(idea) + historicalTimingNote(idea) + '</div>' +
    '<details><summary>Why this setup (' + (idea.notes||[]).length + ' signals)</summary><div class="why-list">' + notes + '</div></details>' +
  '</div>';
}
let backtestStats = {enabled: false, buckets: []};

function scoreBucketJs(score){
  if(score >= 90) return '90-100';
  if(score >= 85) return '85-89';
  if(score >= 78) return '78-84';
  return '<78';
}

async function loadBacktestStats(){
  try{
    const res = await fetch('/api/backtest_stats', {cache:'no-store'});
    if(res.ok) backtestStats = await res.json();
  } catch(e){ /* leave previous value in place */ }
}

function historicalTimingNote(idea){
  if(!backtestStats.enabled || idea.final_score == null) return '';
  const bucket = scoreBucketJs(idea.final_score);
  const match = (backtestStats.buckets || []).find(b => b.score_bucket === bucket && b.direction === idea.direction);
  if(!match || !match.sufficient_sample){
    const n = match ? match.n : 0;
    return '<div class="atr-note">Historical timing: not enough resolved trades yet for ' + bucket + ' ' + idea.direction + 's (n=' + n + ', need ' + (backtestStats.min_sample_for_display||10) + ') <span class="ballpark-tag">forward-tracked, building sample</span></div>';
  }
  return '<div class="atr-note">Historical: ' + bucket + ' ' + idea.direction + 's hit a target ' + match.win_rate_pct + '% of the time' +
    (match.median_days_to_win!=null ? ', median ' + match.median_days_to_win + 'd to target' : '') +
    (match.median_days_to_stop!=null ? ' (median ' + match.median_days_to_stop + 'd to stop when it failed)' : '') +
    ' <span class="ballpark-tag">n=' + match.n + ', real outcomes from this engine</span></div>';
}

function atrTimingNote(idea){
  if(idea.atr_days_to_t1 == null){ return ''; }
  return '<div class="atr-note" title="Distance to target divided by the average daily range (ATR) for this ticker. Assumes a straight-line average-volatility day -- real moves gap, chop, or stall. This is a ballpark scale of patience, not a forecast of when the trigger fires or how long to hold.">' +
    '~' + idea.atr_days_to_t1 + 'd to T1, ~' + idea.atr_days_to_t2 + 'd to T2, ~' + idea.atr_days_to_stop + 'd to stop ' +
    '<span class="ballpark-tag">ATR ballpark, not a forecast</span></div>';
}

function scorebox(label, val, suffix){
  return '<div class="scorebox"><div class="l">' + label + '</div><div class="v">' + (val!=null ? val : '--') + (suffix&&val!=null?suffix:'') + '</div></div>';
}

function execSection(idea){
  if(idea.option_entry_limit == null){
    return '<div class="section"><div class="label">Option Execution</div><div class="value mono">No clean contract found yet -- wait for liquid selection.</div></div>';
  }
  const row = (label, val) => '<div class="exec-row"><span class="exec-l">' + label + '</span><span class="exec-v">' + val + '</span></div>';
  const sourceBadge = (label, source) => {
    const live = source === 'live';
    return '<span class="badge ' + (live ? 'src-live' : 'src-est') + '" title="' +
      (live ? label + ': live NBBO from the snapshot.' : label + ': no live data returned -- this number is estimated, not a real market quote.') +
      '">' + label + ': ' + (live ? 'LIVE' : 'EST') + '</span>';
  };
  return '<div class="section"><div class="label">Option Execution &middot; ' + (idea.trade_side||'') + '&nbsp;&nbsp;' +
    sourceBadge('Quote', idea.quote_source) + sourceBadge('Greeks', idea.greeks_source) + quoteAgeBadge(idea.option_quote_updated_at, idea.option_quote_timeframe) +
    '</div><div class="exec-grid">' +
    row('Entry (limit)', '$' + idea.option_entry_limit) +
    row('Stop', '$' + idea.option_stop_price) +
    row('Exit (fast +20%)', '$' + idea.option_exit_fast) +
    row('Exit (T1)', '$' + idea.option_exit_target_1) +
    row('Exit (T2)', '$' + idea.option_exit_target_2) +
    row('Bid / Ask', '$' + idea.option_bid + ' / $' + idea.option_ask) +
    row('Spread', '$' + idea.option_bid_ask_spread + (idea.option_spread_pct!=null ? ' (' + (idea.option_spread_pct*100).toFixed(1) + '%)' : '')) +
    row('Debit / contract', '$' + idea.per_contract_debit) +
    row('Total debit (' + idea.recommended_contracts + 'x)', '$' + idea.total_debit) +
  '</div></div>';
}

function renderCards(){
  let ideas = (state.ideas || []).slice();
  renderFilters(ideas);
  const q = document.getElementById('search').value.trim().toUpperCase();
  if(activeFilter !== 'ALL') ideas = ideas.filter(i => i.status === activeFilter);
  if(zoneOnly) ideas = ideas.filter(i => (i.buy_zone_status||'').includes('INSIDE'));
  if(q) ideas = ideas.filter(i => (i.ticker||'').toUpperCase().includes(q));
  const sortKey = document.getElementById('sortSel').value;
  if(sortKey !== 'rank'){
    ideas.sort((a,b) => sortKey === 'ticker' ? (a.ticker||'').localeCompare(b.ticker||'') : (b[sortKey]||0) - (a[sortKey]||0));
  }
  const content = document.getElementById('content');

  // Skip the DOM rebuild entirely if the visible set is identical to what's already
  // on screen -- this is what stops a routine poll from yanking you off whatever
  // you're reading. Only ticker/score/status feed the signature since those are the
  // only things that change the rendered output.
  const signature = ideas.length
    ? JSON.stringify(ideas.map(i => [i.ticker, i.final_score, i.status, i.recommended_contracts]))
    : 'EMPTY:' + JSON.stringify((state.scan_debug || []).map(d => [d.ticker, d.final_score]));
  if(signature === lastRenderSignature) return;
  lastRenderSignature = signature;

  if(ideas.length === 0){
    const debug = state.scan_debug || [];
    let extra = '';
    if(debug.length){
      const rows = debug.slice(0,6).map(d =>
        '<div style="display:flex;justify-content:space-between;gap:10px;padding:4px 0;border-top:1px solid var(--border);font-family:var(--mono);font-size:11.5px">' +
        '<span>' + d.ticker + ' <span style="color:var(--faint)">' + (d.direction||'') + '</span></span>' +
        '<span style="color:var(--accent)">' + (d.final_score!=null ? d.final_score : '--') + '</span></div>'
      ).join('');
      extra = '<div style="margin-top:14px;text-align:left"><div class="label">Closest to qualifying this scan</div>' + rows + '</div>';
    }
    content.innerHTML = '<div class="empty"><b>No qualified setups match right now.</b><br>APEX keeps low-quality names hidden until they clear the score threshold -- check back after the next scan, or clear filters above.' + extra + '</div>';
    return;
  }

  // Preserve scroll position and which "Why this setup" panels were expanded,
  // since a routine refresh shouldn't reset either.
  const scrollY = window.scrollY;
  const openTickers = new Set(
    Array.from(content.querySelectorAll('.card')).filter(c => c.querySelector('details[open]')).map(c => c.dataset.ticker)
  );
  content.innerHTML = '<div class="grid">' + ideas.map(cardHtml).join('') + '</div>';
  content.querySelectorAll('.card').forEach(c => {
    if(openTickers.has(c.dataset.ticker)){
      const d = c.querySelector('details');
      if(d) d.open = true;
    }
  });
  window.scrollTo(0, scrollY);
}

async function poll(){
  try{
    const res = await fetch('/dashboard.json', {cache:'no-store'});
    if(!res.ok) throw new Error('HTTP ' + res.status);
    state = await res.json();
    lastFetchOk = true;
  } catch(e){
    lastFetchOk = false;
  }
  renderStatusbar();
  renderCards();
}

document.getElementById('search').addEventListener('input', renderCards);
document.getElementById('sortSel').addEventListener('change', renderCards);
document.getElementById('zoneToggle').addEventListener('click', () => {
  zoneOnly = !zoneOnly;
  const btn = document.getElementById('zoneToggle');
  btn.classList.toggle('active', zoneOnly);
  btn.setAttribute('aria-pressed', String(zoneOnly));
  renderCards();
});
document.getElementById('scanNowBtn').addEventListener('click', async () => {
  const btn = document.getElementById('scanNowBtn');
  btn.disabled = true;
  const originalLabel = btn.textContent;
  btn.textContent = 'Scanning...';
  try{
    await fetch('/api/run', {method:'POST', cache:'no-store'});
  } catch(e){
    // poll() below will surface connection issues via lastFetchOk
  }
  lastRenderSignature = null; // force a redraw even if the result looks unchanged
  await poll();
  btn.disabled = false;
  btn.textContent = originalLabel;
});
renderStatusbar();
renderCards();
loadBacktestStats().then(() => { lastRenderSignature = null; renderCards(); });
setInterval(poll, 30000);
setInterval(renderStatusbar, 1000);
setInterval(() => { loadBacktestStats().then(() => { lastRenderSignature = null; renderCards(); }); }, 300000);
</script>
</body>
</html>
"""




FLOW_HTML = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>APEX Flow / GEX Dashboard</title>
<style>
:root{--bg:#090d14;--panel:#101827;--panel2:#131f32;--text:#eef4ff;--muted:#8fa0b8;--accent:#6ee7f9;--good:#22c55e;--bad:#ef4444;--warn:#f59e0b;--border:#263244}*{box-sizing:border-box}body{margin:0;background:#090d14;font-family:Arial,Helvetica,sans-serif;color:var(--text)}
.apex-nav{display:flex;align-items:center;gap:6px;padding:10px 16px;background:#101827;border-bottom:1px solid #263244;flex-wrap:wrap}
.apex-nav .nav-logo{font-family:monospace;font-size:13px;font-weight:800;color:#6ee7f9;margin-right:10px;text-decoration:none}
.apex-nav a{font-size:12px;font-weight:600;padding:5px 12px;border-radius:7px;border:1px solid transparent;color:#8fa0b8;text-decoration:none;transition:all .15s}
.apex-nav a:hover{background:#131f32;color:#eef4ff;border-color:#263244}
.apex-nav a.active{background:rgba(110,231,249,.08);color:#6ee7f9;border-color:rgba(110,231,249,.3)}
.apex-nav .nav-sep{width:1px;height:18px;background:#263244;margin:0 4px}
.brand{font-size:20px;font-weight:800;padding:14px 18px 0}.sub-title{color:var(--muted);font-size:13px;padding:2px 18px 10px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:14px;padding:18px}.card{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--border);border-radius:16px;padding:16px;box-shadow:0 12px 30px rgba(0,0,0,.28)}.top{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}.ticker{font-size:26px;font-weight:900}.badge{padding:6px 10px;border-radius:999px;font-size:12px;font-weight:800;background:#263244}.BULLISH{color:var(--good)}.BEARISH{color:var(--bad)}.MIXED{color:var(--warn)}.decision{border-radius:14px;padding:14px;margin:10px 0 14px;border:1px solid var(--border);background:#0a111d}.decisionTitle{font-size:24px;font-weight:900;letter-spacing:.2px}.decisionSub{font-size:13px;color:var(--muted);margin-top:4px}.GREENBOX{border-color:rgba(34,197,94,.65);box-shadow:0 0 0 1px rgba(34,197,94,.16) inset}.YELLOWBOX{border-color:rgba(245,158,11,.65);box-shadow:0 0 0 1px rgba(245,158,11,.16) inset}.REDBOX{border-color:rgba(239,68,68,.65);box-shadow:0 0 0 1px rgba(239,68,68,.16) inset}.GREEN{color:var(--good)}.YELLOW{color:var(--warn)}.RED{color:var(--bad)}.metrics{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}.metric{background:#0a111d;border:1px solid #223047;border-radius:12px;padding:10px}.label{font-size:12px;color:var(--muted)}.value{font-size:20px;font-weight:800;margin-top:5px}.wide{grid-column:1/-1}.levels{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:10px}.notes{font-size:12px;color:var(--muted);line-height:1.5;margin-top:12px}.status{padding:0 18px 8px;color:var(--muted);font-size:13px}.btn{background:#10243a;color:var(--text);border:1px solid #31506e;border-radius:10px;padding:9px 12px;cursor:pointer}.btn:hover{border-color:var(--accent)}@media(max-width:600px){.metrics,.levels{grid-column:1fr}}
</style>
</head>
<body>
<nav class="apex-nav">
  <a href="/" class="nav-logo">APEX</a>
  <a href="/">Scanner</a>
  <a href="/apex_os">Institutional OS</a>
  <a href="/assistant">Trade Assistant</a>
  <a href="/flow" class="active">Flow / GEX</a>
  <a href="/chart">Charts</a>
  <div class="nav-sep"></div>
  <a href="/api/v45/status" target="_blank">Status</a>
  <a href="/health" target="_blank">Health</a>
</nav>
<div class="brand">APEX Flow / GEX</div>
<div class="sub-title">Net flow, sweeps, call/put premium and gamma levels from QuantData &nbsp;·&nbsp; <button class="btn" onclick="loadFlow()" style="font-size:12px;padding:4px 10px">Refresh</button></div>
<div class="status" id="status">Loading flow data...</div>
<div class="grid" id="grid"></div>
<script>
function money(v){ if(v===null||v===undefined) return '--'; const n=Number(v); const sign=n<0?'-':''; const a=Math.abs(n); if(a>=1e9) return sign+'$'+(a/1e9).toFixed(2)+'B'; if(a>=1e6) return sign+'$'+(a/1e6).toFixed(2)+'M'; if(a>=1e3) return sign+'$'+(a/1e3).toFixed(1)+'K'; return sign+'$'+a.toFixed(0); }
function val(v){ return (v===null||v===undefined||v==='')?'--':v; }
function card(x){
 const bias=x.bias||'MIXED';
 const cls=bias.replace(/[^A-Z]/g,'');
 const dColor=x.decision_color||'YELLOW';
 const icon=dColor==='GREEN'?'🟢':dColor==='RED'?'🔴':'🟡';
 return `<div class="card">
  <div class="top"><div><div class="ticker">${x.ticker}</div><div class="sub">${val(x.flow_status)}</div></div><div class="badge ${cls}">${bias}</div></div>
  <div class="decision ${dColor}BOX">
    <div class="decisionTitle ${dColor}">${icon} ${val(x.decision)}</div>
    <div class="decisionSub">Institutional Alignment: ${val(x.institutional_alignment)}/100 · Approved side: ${val(x.approved_side)}</div>
  </div>
  <div class="metrics">
    <div class="metric"><div class="label">Call premium</div><div class="value BULLISH">${money(x.call_premium)}</div></div>
    <div class="metric"><div class="label">Put premium</div><div class="value BEARISH">${money(x.put_premium)}</div></div>
    <div class="metric"><div class="label">Net premium</div><div class="value ${x.net_premium>=0?'BULLISH':'BEARISH'}">${money(x.net_premium)}</div></div>
    <div class="metric"><div class="label">Call/put ratio</div><div class="value">${val(x.flow_ratio)}</div></div>
    <div class="metric"><div class="label">Flow score</div><div class="value">${val(x.flow_score)}</div></div>
    <div class="metric"><div class="label">Order score / sweeps</div><div class="value">${val(x.order_flow_score)} / ${val(x.sweep_count)}</div></div>
  </div>
  <div class="levels">
    <div class="metric"><div class="label">Call wall</div><div class="value">${val(x.call_wall)}</div></div>
    <div class="metric"><div class="label">Zero gamma</div><div class="value">${val(x.zero_gamma)}</div></div>
    <div class="metric"><div class="label">Put wall</div><div class="value">${val(x.put_wall)}</div></div>
  </div>
  <div class="notes">${(x.notes||[]).slice(0,6).map(n=>'• '+n).join('<br>')}</div>
 </div>`;
}
async function loadFlow(){
 const status=document.getElementById('status'); const grid=document.getElementById('grid');
 status.textContent='Refreshing QuantData flow...';
 try{
   const r=await fetch('/api/flow',{cache:'no-store'}); const data=await r.json();
   if(!r.ok) throw new Error(data.error||('HTTP '+r.status));
   grid.innerHTML=(data.items||[]).map(card).join('') || '<div class="card">No flow rows returned.</div>';
   status.textContent=`Updated ${data.updated_at_et || data.updated_at || ''} · QuantData ${data.quantdata_configured?'configured':'not configured'}`;
 }catch(e){ status.textContent='Flow dashboard error: '+e.message; }
}
loadFlow(); setInterval(loadFlow, 60000);
</script>
</body>
</html>
"""


ASSISTANT_HTML = """
<!doctype html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>APEX Trade Assistant</title>
<style>
:root{--bg:#070a10;--panel:#101827;--panel2:#131f32;--text:#eef4ff;--muted:#91a4bd;--good:#22c55e;--bad:#ef4444;--warn:#f59e0b;--cyan:#6ee7f9;--border:#263244}*{box-sizing:border-box}body{margin:0;background:#070a10;color:var(--text);font-family:Arial,Helvetica,sans-serif}
.apex-nav{display:flex;align-items:center;gap:6px;padding:10px 16px;background:#101827;border-bottom:1px solid #263244;flex-wrap:wrap}
.apex-nav .nav-logo{font-family:monospace;font-size:13px;font-weight:800;color:#6ee7f9;margin-right:10px;text-decoration:none}
.apex-nav a{font-size:12px;font-weight:600;padding:5px 12px;border-radius:7px;border:1px solid transparent;color:#91a4bd;text-decoration:none;transition:all .15s}
.apex-nav a:hover{background:#131f32;color:#eef4ff;border-color:#263244}
.apex-nav a.active{background:rgba(110,231,249,.08);color:#6ee7f9;border-color:rgba(110,231,249,.3)}
.apex-nav .nav-sep{width:1px;height:18px;background:#263244;margin:0 4px}
.wrap{max-width:1180px;margin:0 auto;padding:18px}.sub-header{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:10px 0 18px}.brand{font-size:22px;font-weight:900}.sub{color:var(--muted);margin-top:5px;font-size:13px}.btn{background:#10243a;color:var(--cyan);border:1px solid #31506e;border-radius:10px;padding:9px 12px;cursor:pointer}.panel{margin-top:4px;background:linear-gradient(180deg,#101827,#131f32);border:1px solid var(--border);border-radius:18px;padding:18px}.banner{border:1px solid var(--border);border-radius:14px;padding:12px 14px;margin-bottom:12px;background:#09111d}.banner.GREEN{border-color:rgba(34,197,94,.5)}.banner.YELLOW{border-color:rgba(245,158,11,.55)}.banner.RED{border-color:rgba(239,68,68,.55)}.banner-title{font-weight:900;font-size:16px}.banner-msg{color:var(--muted);margin-top:4px;font-size:13px}.state{font-size:42px;font-weight:1000;line-height:1.05;margin:10px 0}.good{color:var(--good)}.bad{color:var(--bad)}.warn{color:var(--warn)}.info{color:var(--cyan)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}.box{background:#090f1a;border:1px solid #223047;border-radius:14px;padding:14px}.label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}.val{font-size:22px;font-weight:900;margin-top:6px}.action{font-size:20px;font-weight:900;margin:12px 0 4px}.notes{color:#b7c7dd;line-height:1.55}.flash{animation:pulse 1.2s infinite}.planner{display:grid;grid-template-columns:1.25fr .75fr;gap:14px;margin-top:14px}.bigplan{background:#07111f;border:1px solid #2b405d;border-radius:16px;padding:16px}.summary{font-size:22px;font-weight:900;line-height:1.25}.countdown{font-size:34px;font-weight:1000}.check{display:flex;align-items:center;gap:8px;margin:7px 0;color:#cbd8ea}.ok{color:var(--good)}.no{color:var(--bad)}.rules{margin-top:10px;color:#b7c7dd;line-height:1.5}.stale{border-color:rgba(245,158,11,.7)}@keyframes pulse{0%,100%{box-shadow:0 0 0 rgba(34,197,94,0)}50%{box-shadow:0 0 30px rgba(34,197,94,.45)}}@media(max-width:820px){.planner{grid-template-columns:1fr}.state{font-size:34px}}
</style></head><body>
<nav class="apex-nav">
  <a href="/" class="nav-logo">APEX</a>
  <a href="/">Scanner</a>
  <a href="/apex_os">Institutional OS</a>
  <a href="/assistant" class="active">Trade Assistant</a>
  <a href="/flow">Flow / GEX</a>
  <a href="/chart">Charts</a>
  <div class="nav-sep"></div>
  <a href="/api/v45/status" target="_blank">Status</a>
  <a href="/health" target="_blank">Health</a>
</nav>
<div class="wrap">
<div class="sub-header"><div><div class="brand">APEX Trade Assistant</div><div class="sub">Session-aware Flow/GEX bias + Pine trigger + execution plan</div></div><div><button class="btn" onclick="loadAssistant()">Refresh</button></div></div>
<div id="app" class="panel">Loading...</div></div>
<script>
function cls(p){ if(p==='URGENT') return 'good flash'; if(p==='BLOCKED') return 'bad'; if(p==='WARNING') return 'warn'; if(p==='INFO') return 'info'; return 'warn';}
function money(v){if(v==null)return'--';let n=Number(v),s=n<0?'-':'',a=Math.abs(n);if(a>=1e9)return s+'$'+(a/1e9).toFixed(2)+'B';if(a>=1e6)return s+'$'+(a/1e6).toFixed(2)+'M';return s+'$'+a.toFixed(0)}
function mmss(s){s=Number(s||0);let m=Math.floor(s/60),r=s%60;return String(m).padStart(2,'0')+':'+String(r).padStart(2,'0')}
function yes(v){return v?'✅':'❌'}
async function loadAssistant(){const el=document.getElementById('app');try{const r=await fetch('/api/assistant?ticker=SPX',{cache:'no-store'});const d=await r.json();const f=d.flow||{}, a=d.assistant||{}, p=a.trade_plan||{};const checklist=(a.checklist||[]).map(x=>`<div class="check"><span class="${x.ok?'ok':'no'}">${yes(x.ok)}</span><span>${x.label}</span></div>`).join('');const rules=(p.exit_rules||[]).map(x=>'• '+x).join('<br>');const sc=a.session_context||p.session_context||{};const banner=`<div class="banner ${sc.banner_level||'YELLOW'}"><div class="banner-title">${sc.banner_title||'SESSION STATUS'}</div><div class="banner-msg">${sc.banner_message||''}</div></div>`;el.className='panel '+(p.signal_expired?'stale':'');el.innerHTML=banner+`<div class="label">${a.updated_at_et||''}</div><div class="state ${cls(a.priority)}">${a.state||'WAITING'}</div><div class="sub">${a.message||''}</div><div class="action">${a.action||''}</div><div class="grid"><div class="box"><div class="label">Approved Side</div><div class="val">${a.approved_side||'--'}</div></div><div class="box"><div class="label">Assistant Mode</div><div class="val">${sc.assistant_mode||'--'}</div></div><div class="box"><div class="label">Alignment</div><div class="val">${a.institutional_alignment||'--'}/100</div></div><div class="box"><div class="label">Net Premium</div><div class="val">${money(f.net_premium)}</div></div><div class="box"><div class="label">Flow / Order</div><div class="val">${f.flow_score||'--'} / ${f.order_flow_score||'--'}</div></div><div class="box"><div class="label">Signal Countdown</div><div class="val countdown">${(a.fresh_signal&&sc.is_tradeable_session)?mmss(p.signal_seconds_remaining):'--'}</div></div></div><div class="planner"><div class="bigplan"><div class="label">Execution Plan</div><div class="summary">${p.execution_summary||'Waiting for setup'}</div><div class="grid" style="margin-top:12px"><div class="box"><div class="label">Contract</div><div class="val">${p.recommended_contract||'--'}</div></div><div class="box"><div class="label">Entry Zone</div><div class="val">${p.entry_zone||'--'}</div></div><div class="box"><div class="label">Stop</div><div class="val">${p.stop_price||'--'}</div></div><div class="box"><div class="label">Targets</div><div class="val">${p.target_1||'--'} / ${p.target_2||'--'}</div></div></div><div class="rules">${rules}</div></div><div class="bigplan"><div class="label">Checklist</div>${checklist}<div class="notes" style="margin-top:12px">${(a.reasons||[]).map(x=>'• '+x).join('<br>')}</div></div></div>`}catch(e){el.innerHTML='Error: '+e.message}}
loadAssistant(); setInterval(loadAssistant, 5000);
</script></body></html>
"""

@app.route("/assistant")
def assistant_dashboard():
    return render_template_string(ASSISTANT_HTML)


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
    side = str(payload.get("signal", payload.get("side", "NONE"))).upper()
    signal = {
        "ticker": ticker,
        "signal": side,
        "direction": str(payload.get("direction", "")),
        "score": payload.get("score"),
        "close": payload.get("close"),
        "timeframe": payload.get("timeframe"),
        "system": payload.get("system", "APEX_PRO"),
        "received_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "received_at_et": now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
    }
    flow_item = quantdata_flow_snapshot(ticker)
    assistant = build_trade_assistant_decision(flow_item, signal)
    with TRADE_ASSISTANT_LOCK:
        TRADE_ASSISTANT_STATE.update(assistant)
        TRADE_ASSISTANT_STATE["last_signal"] = signal
        TRADE_ASSISTANT_STATE["last_decision"] = assistant
    if assistant.get("alert"):
        send_telegram(f"🚨 APEX 3.5 ENTER {side} NOW\nTicker: {ticker}\nPine Score: {signal.get('score')}\nInstitutional Alignment: {assistant.get('institutional_alignment')}/100\nPlan: {(assistant.get('trade_plan') or {}).get('execution_summary')}\nCountdown: {(assistant.get('trade_plan') or {}).get('signal_seconds_remaining')}s")
    return jsonify({"ok": True, "version": VERSION, "signal": signal, "flow": flow_item, "assistant": assistant})

@app.route("/flow")
def flow_dashboard():
    return render_template_string(FLOW_HTML)

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

@app.route("/")
def dashboard():
    with STATE_LOCK:
        data = dict(STATE)
    return render_template_string(HTML, data=data)

@app.route("/dashboard.json")
def dashboard_json():
    with STATE_LOCK:
        return jsonify(dict(STATE))

@app.route("/api/status")
def api_status():
    with STATE_LOCK:
        return jsonify(dict(STATE))

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

@app.route("/health")
def health():
    with STATE_LOCK:
        return jsonify({
            "ok": True,
            "mode": VERSION,
            "updated_at": STATE.get("updated_at"),
            "scanner_started": SCANNER_STARTED,
            "scan_in_progress": STATE.get("scan_in_progress"),
            "last_scan_duration_seconds": STATE.get("last_scan_duration_seconds"),
            "sources": STATE.get("data_sources"),
        })

# Existing Render/Gunicorn service should keep RUN_SCANNER_ON_IMPORT=true.
# CLI imports, tests, and library imports stay clean by default and will not start
# a background scanner or send Telegram alerts accidentally.
try:
    init_tracking_db()  # idempotent CREATE TABLE IF NOT EXISTS -- safe to run on every import.
    # Belt-and-suspenders: init_tracking_db() already catches its own exceptions and
    # sets TRACKING_AVAILABLE=False on failure, but this wrapper exists so that even a
    # future bug inside it can never again prevent gunicorn from importing this module.
except Exception as e:
    print(f"Unexpected error during tracking init (app continues, tracking disabled): {e}", flush=True)
if RUN_SCANNER_ON_IMPORT:
    start_background_scanner()

if __name__ == "__main__":
    print(f"Starting APEX {VERSION}", flush=True)
    if os.getenv("RUN_SCANNER_ON_IMPORT", "false").lower() != "true":
        print("Background scanner disabled for direct app.py execution. Set RUN_SCANNER_ON_IMPORT=true to enable it.", flush=True)
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)


# =============================================================================
# APEX 4.5 NEW API ROUTES
# =============================================================================

@app.route("/apex_os")
def apex_os_dashboard():
    """APEX Institutional OS — the full v4.5 dashboard."""
    return render_template_string(APEX_OS_HTML)


@app.route("/api/institutional_os")
def api_institutional_os():
    """
    Master endpoint for the APEX Institutional OS dashboard.
    When apex_engines.py is available, runs the full nine-engine pipeline.
    Falls back to the 4.5 build_institutional_os() if apex_engines not loaded.
    """
    ticker = request.args.get("ticker", ASSISTANT_TICKER).upper()
    include_heatmap = request.args.get("heatmap", "1") == "1"

    if APEX_ENGINES_AVAILABLE and _build_institutional_decision is not None:
        try:
            with TRADE_ASSISTANT_LOCK:
                last_signal = TRADE_ASSISTANT_STATE.get("last_signal")
            session_ctx = market_session_context()

            # Fetch all data inputs in parallel
            with ThreadPoolExecutor(max_workers=6, thread_name_prefix="apex-os-fetch") as pool:
                f_flow    = pool.submit(quantdata_flow_snapshot, ticker)
                f_spy     = pool.submit(get_daily_bars, "SPY", 260)
                f_qqq     = pool.submit(get_daily_bars, "QQQ", 260)
                f_daily   = pool.submit(get_daily_bars, ticker, 260)
                f_intra   = pool.submit(get_intraday_bars, ticker, 5, 3)
                f_vix     = pool.submit(get_vix_price)

            flow_snapshot = f_flow.result()
            spy_bars      = f_spy.result()
            qqq_bars      = f_qqq.result()
            daily_bars    = f_daily.result()
            intraday_bars = f_intra.result()
            vix_price     = f_vix.result()

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
            result["version"] = VERSION_45
            result["engine_mode"] = "NINE_ENGINE_PIPELINE"

            # Update Telegram if there's an ENTER signal
            recommendation = result.get("recommendation", "")
            if "ENTER" in recommendation and "NOW" in recommendation:
                story = result.get("story", {})
                summary = story.get("executive_summary", "")
                consensus_label = result.get("consensus_label", "")
                send_telegram(
                    f"🚨 APEX 4.5 {recommendation}\n"
                    f"Ticker: {ticker}\n"
                    f"Consensus: {consensus_label}\n"
                    f"Summary: {summary}\n"
                    f"Contract: {result.get('risk', {}).get('contract_hint', '--')}\n"
                    f"Entry: {result.get('risk', {}).get('entry_zone', '--')}\n"
                    f"Stop: {result.get('risk', {}).get('stop', '--')}\n"
                    f"Targets: {result.get('risk', {}).get('target1', '--')} / {result.get('risk', {}).get('target2', '--')}"
                )

            return jsonify({"ok": True, **result})

        except Exception as e:
            # Nine-engine pipeline failed — fall back to 4.5 build_institutional_os
            print(f"Nine-engine pipeline error (falling back): {e}", flush=True)
            try:
                data = build_institutional_os(ticker, include_heatmap=include_heatmap)
                data["engine_mode"] = "FALLBACK_45"
                data["pipeline_error"] = str(e)
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

        result = _build_institutional_decision(
            ticker=ticker,
            flow_snapshot=f_flow.result(),
            spy_bars=f_spy.result(),
            qqq_bars=f_qqq.result(),
            daily_bars=f_daily.result(),
            intraday_bars=f_intra.result(),
            signal=last_signal,
            vix_price=f_vix.result(),
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


def _chart_fetch_bars(polygon_ticker: str, days: int = 3, multiplier: int = 15) -> List[dict]:
    """
    Fetch bars for the last N trading days via Polygon.io.
    Supports 1-min, 5-min, and 15-min bars via the multiplier param.
    ES futures use ES1!, SPX uses SPY as proxy.
    """
    end = now_et().date()
    # 1-min bars need a tighter window (Polygon free tier limits history)
    day_buffer = max(days * 4, 14) if multiplier >= 5 else max(days * 2, 5)
    start = end - dt.timedelta(days=day_buffer)
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
    # Ticker routing
    SPX_PROXY = "SPY"
    ES_TICKER = "ES1!"

    # Clamp multiplier to supported values
    multiplier = multiplier if multiplier in (1, 5, 15) else 15

    symbol_upper = symbol.upper().strip()
    if symbol_upper in ("SPX", "SPY", "$SPX"):
        polygon_ticker = SPX_PROXY
        display_name = "SPX  (via SPY)"
        is_futures = False
        spx_proxy = True
    elif symbol_upper in ("ES", "ES1!", "/ES"):
        polygon_ticker = ES_TICKER
        display_name = "ES Futures (ES1!)"
        is_futures = True
        spx_proxy = False
    else:
        polygon_ticker = symbol_upper
        display_name = symbol_upper
        is_futures = False
        spx_proxy = False

    raw_bars = _chart_fetch_bars(polygon_ticker, days=days, multiplier=multiplier)
    if not raw_bars:
        return {"error": f"No data returned for {polygon_ticker}", "symbol": symbol}

    # Group bars by trading day, keep last N days
    from collections import defaultdict
    days_map: dict = defaultdict(list)
    for b in raw_bars:
        ts = safe_float(b.get("t"), 0.0)
        day_key = dt.datetime.utcfromtimestamp(ts / 1000).strftime("%Y-%m-%d") if ts else "unknown"
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
        # ET approximation (UTC-4 EDT, UTC-5 EST) — good enough for bar labels
        et_hour = dt_utc.hour - 4
        try:
            label = dt_utc.replace(hour=max(0, et_hour)).strftime("%-I:%M %p")
        except ValueError:
            label = dt_utc.replace(hour=max(0, et_hour)).strftime("%I:%M %p").lstrip("0")
        day_label = dt_utc.strftime("%b %d")

        chart.append({
            "ts":     int(ts),
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
    try:
        gex_ticker = "SPX" if spx_proxy else "ES"
        flow_snap  = quantdata_flow_snapshot(gex_ticker)
        if flow_snap.get("call_wall"):
            call_wall  = safe_float(flow_snap["call_wall"], call_wall)
        if flow_snap.get("put_wall"):
            put_wall   = safe_float(flow_snap["put_wall"], put_wall)
        if flow_snap.get("zero_gamma"):
            gamma_flip = safe_float(flow_snap["zero_gamma"], gamma_flip)
    except Exception:
        pass

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
        "updatedAt":       now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
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


CHART_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>APEX — Market Intelligence Terminal</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700;800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-chart-financial@0.1.1/dist/chartjs-chart-financial.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/luxon@3.4.4/build/global/luxon.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-luxon@1.3.1/dist/chartjs-adapter-luxon.umd.min.js"></script>
<style>
:root{
  --bg:#05080f;--surf:#0d141f;--surf2:#121c2b;--bdr:#1c2940;
  --text:#e8f1fc;--muted:#8295b3;--faint:#5a6b87;
  --blue:#38bdf8;--green:#22c55e;--amber:#f59e0b;--red:#ef4444;--purple:#a78bfa;
  --bullish:#22c55e;--bearish:#ef4444;--caution:#f59e0b;--neutral:#8295b3;
  --mono:'JetBrains Mono',monospace;--sans:'Inter',system-ui,sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:var(--sans);background:var(--bg);color:var(--text);-webkit-font-smoothing:antialiased}
.apex-nav{display:flex;align-items:center;gap:6px;padding:10px 16px;background:var(--surf);border-bottom:1px solid var(--bdr);flex-wrap:wrap}
.apex-nav .nav-logo{font-family:var(--mono);font-size:13px;font-weight:800;color:var(--blue);margin-right:10px;text-decoration:none}
.apex-nav a{font-size:12px;font-weight:600;padding:5px 12px;border-radius:7px;border:1px solid transparent;color:var(--muted);text-decoration:none;transition:all .15s}
.apex-nav a:hover{background:var(--surf2);color:var(--text);border-color:var(--bdr)}
.apex-nav a.active{background:rgba(56,189,248,.1);color:var(--blue);border-color:rgba(56,189,248,.35)}
.apex-nav .nav-sep{width:1px;height:18px;background:var(--bdr);margin:0 4px}
.wrap{padding:14px 14px 60px}
.page-header{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:14px}
.page-title{font-family:var(--mono);font-size:16px;font-weight:800;color:var(--blue)}
.page-sub{font-size:12px;color:var(--muted);margin-top:2px}
.controls{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.day-btn{font-family:var(--mono);font-size:11px;font-weight:700;padding:5px 12px;border-radius:7px;border:1px solid var(--bdr);background:transparent;color:var(--muted);cursor:pointer;transition:all .15s}
.day-btn:hover{background:var(--surf2);color:var(--text)}
.day-btn.active{background:rgba(56,189,248,.1);color:var(--blue);border-color:rgba(56,189,248,.4)}
.tf-btn{font-family:var(--mono);font-size:11px;font-weight:700;padding:5px 10px;border-radius:7px;border:1px solid var(--bdr);background:transparent;color:var(--muted);cursor:pointer;transition:all .15s}
.tf-btn:hover{background:var(--surf2);color:var(--text)}
.tf-btn.active{background:rgba(167,139,250,.1);color:var(--purple);border-color:rgba(167,139,250,.4)}
.refresh-btn{font-family:var(--sans);font-size:11px;font-weight:600;padding:5px 13px;border-radius:7px;border:1px solid rgba(56,189,248,.4);background:rgba(56,189,248,.06);color:var(--blue);cursor:pointer;transition:all .15s}
.refresh-btn:hover{background:rgba(56,189,248,.12)}
.last-update{font-size:10px;color:var(--faint);font-family:var(--mono)}
.ctrl-label{font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.8px;color:var(--faint);font-family:var(--mono)}
.ctrl-sep{width:1px;height:20px;background:var(--bdr);margin:0 2px}

/* Side-by-side chart panels */
.charts-row{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}
@media(max-width:900px){.charts-row{grid-template-columns:1fr}}
.chart-panel{background:var(--surf);border:1px solid var(--bdr);border-radius:12px;overflow:hidden}
.chart-panel-inner{display:flex;gap:0}
.chart-main{flex:1;min-width:0;padding:12px}
.chart-sidebar{width:148px;flex-shrink:0;border-left:1px solid var(--bdr);padding:10px 8px;display:flex;flex-direction:column;gap:4px;overflow-y:auto;max-height:420px}

/* Regime banner */
.regime-bar{padding:8px 12px;border-bottom:1px solid var(--bdr);display:flex;align-items:center;justify-content:space-between;gap:8px}
.regime-label{font-size:12px;font-weight:700;font-family:var(--mono)}
.regime-bullish{color:var(--bullish)}
.regime-bearish{color:var(--bearish)}
.regime-caution{color:var(--caution)}
.regime-neutral{color:var(--neutral)}
.strength-pill{font-size:10px;font-weight:700;padding:2px 8px;border-radius:999px;background:var(--surf2);color:var(--muted);font-family:var(--mono)}

/* Canvas */
.chart-canvas-wrap{position:relative;height:340px}
canvas{display:block}

/* Legend */
.chart-legend{display:flex;align-items:center;gap:12px;padding:6px 12px 8px;border-top:1px solid var(--bdr);flex-wrap:wrap}
.leg-item{display:flex;align-items:center;gap:5px;font-size:10px;color:var(--muted)}
.leg-dot{width:10px;height:3px;border-radius:2px;flex-shrink:0}

/* Sidebar level cards */
.level-card{padding:5px 6px;border-radius:6px;background:var(--surf2);margin-bottom:2px}
.level-card-label{font-size:9px;text-transform:uppercase;letter-spacing:.7px;color:var(--faint);font-weight:700}
.level-card-val{font-family:var(--mono);font-size:13px;font-weight:800;margin-top:1px}
.lc-resistance{border-left:2px solid var(--red)}
.lc-resistance .level-card-val{color:var(--red)}
.lc-gamma{border-left:2px solid var(--amber)}
.lc-gamma .level-card-val{color:var(--amber)}
.lc-hvbo{border-left:2px solid var(--purple)}
.lc-hvbo .level-card-val{color:var(--purple)}
.lc-call{border-left:2px solid var(--green)}
.lc-call .level-card-val{color:var(--green)}
.lc-price{border-left:2px solid var(--blue)}
.lc-price .level-card-val{color:var(--blue)}
.lc-support{border-left:2px solid rgba(239,68,68,.5)}
.lc-support .level-card-val{color:rgba(239,68,68,.8)}
.lc-put{border-left:2px solid rgba(239,68,68,.7)}
.lc-put .level-card-val{color:var(--red)}
.sidebar-title{font-size:9px;text-transform:uppercase;letter-spacing:.8px;color:var(--faint);font-weight:700;padding:2px 0 4px;border-bottom:1px solid var(--bdr);margin-bottom:4px}

/* Symbol header */
.symbol-head{padding:10px 12px 0;display:flex;align-items:baseline;gap:8px}
.symbol-name{font-family:var(--mono);font-size:14px;font-weight:800;color:var(--text)}
.symbol-price{font-family:var(--mono);font-size:22px;font-weight:800;color:var(--blue)}
.symbol-date{font-size:10px;color:var(--faint);font-family:var(--mono)}

/* Error / loading */
.panel-msg{padding:40px;text-align:center;color:var(--muted);font-size:13px}
.err{color:var(--red)}
</style>
</head>
<body>
<nav class="apex-nav">
  <a href="/" class="nav-logo">APEX</a>
  <a href="/">Scanner</a>
  <a href="/apex_os">Institutional OS</a>
  <a href="/assistant">Trade Assistant</a>
  <a href="/flow">Flow / GEX</a>
  <a href="/chart" class="active">Charts</a>
  <div class="nav-sep"></div>
  <a href="/api/v45/status" target="_blank">Status</a>
  <a href="/health" target="_blank">Health</a>
</nav>

<div class="wrap">
  <div class="page-header">
    <div>
      <div class="page-title">Market Intelligence Terminal</div>
      <div class="page-sub">ES Futures &amp; SPX — EMA 8/21 · VWAP · HVBO · Gamma levels</div>
    </div>
    <div class="controls">
      <span class="ctrl-label">DAYS</span>
      <button class="day-btn" data-d="1">1D</button>
      <button class="day-btn active" data-d="2">2D</button>
      <button class="day-btn" data-d="3">3D</button>
      <button class="day-btn" data-d="5">5D</button>
      <div class="ctrl-sep"></div>
      <span class="ctrl-label">TF</span>
      <button class="tf-btn" data-tf="1">1m</button>
      <button class="tf-btn" data-tf="5">5m</button>
      <button class="tf-btn active" data-tf="15">15m</button>
      <div class="ctrl-sep"></div>
      <button class="refresh-btn" id="refreshBtn">↻ Refresh</button>
      <span class="last-update" id="lastUpdate">--</span>
    </div>
  </div>

  <div class="charts-row" id="chartsRow">
    <div class="chart-panel" id="panelES">
      <div class="panel-msg">Loading ES…</div>
    </div>
    <div class="chart-panel" id="panelSPX">
      <div class="panel-msg">Loading SPX…</div>
    </div>
  </div>
</div>

<script>
// ── State ────────────────────────────────────────────────────────────────────
let activeDays = 2;
let activeTf   = 15;   // timeframe in minutes: 1, 5, or 15
let chartInstances = {};

// ── Utilities ────────────────────────────────────────────────────────────────
function fmt(v){ return v != null ? Number(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}) : '--'; }
function fmtV(v){ if(!v) return '--'; if(v>=1e6) return (v/1e6).toFixed(1)+'M'; if(v>=1e3) return (v/1e3).toFixed(0)+'K'; return v.toFixed(0); }

function regimeClass(color){
  return color === 'bullish' ? 'regime-bullish' :
         color === 'bearish' ? 'regime-bearish' :
         color === 'caution' ? 'regime-caution' : 'regime-neutral';
}

// ── Sidebar levels HTML ───────────────────────────────────────────────────────
function sidebarHTML(d){
  const card = (cls, label, val) =>
    `<div class="level-card ${cls}">
       <div class="level-card-label">${label}</div>
       <div class="level-card-val">$${fmt(val)}</div>
     </div>`;
  return `
    <div class="sidebar-title">Key Levels</div>
    ${card('lc-resistance','Recent High ↑',d.recentHigh)}
    ${card('lc-gamma','Gamma Flip ⚡',d.gammaFlip)}
    ${card('lc-hvbo','HVBO High ▲',d.hvboHigh)}
    ${card('lc-call','Call Wall ☑',d.callWall)}
    ${card('lc-price','Current Close',d.currentClose)}
    ${card('lc-hvbo','HVBO Low ▼',d.hvboLow)}
    ${card('lc-support','Major Support ↓',d.majorSupport)}
    ${card('lc-support','Secondary Sup.',d.secondarySupport)}
    ${card('lc-put','Put Wall ☒',d.putWall)}
  `;
}

// ── Build one chart panel ─────────────────────────────────────────────────────
function buildPanel(panelId, data) {
  const panel = document.getElementById(panelId);
  if (!panel) return;

  // Destroy any existing Chart.js instance
  if (chartInstances[panelId]) {
    chartInstances[panelId].destroy();
    delete chartInstances[panelId];
  }

  const rc = regimeClass(data.regimeColor);
  const dateRange = data.tradingDays && data.tradingDays.length
    ? `${data.tradingDays[0]} – ${data.tradingDays[data.tradingDays.length-1]}`
    : '';

  panel.innerHTML = `
    <div class="regime-bar">
      <div>
        <div style="font-size:9px;text-transform:uppercase;letter-spacing:.8px;color:var(--faint);font-weight:700">MARKET REGIME</div>
        <div class="regime-label ${rc}">${data.regime}</div>
      </div>
      <div class="strength-pill">${data.strengthLabel} · ${data.strength}/5</div>
    </div>
    <div class="symbol-head">
      <div class="symbol-name">${data.symbol}</div>
      <div class="symbol-price">$${fmt(data.currentClose)}</div>
      <div class="symbol-date">${data.barInterval} · ${dateRange}</div>
    </div>
    <div class="chart-panel-inner">
      <div class="chart-main">
        <div class="chart-canvas-wrap">
          <canvas id="canvas_${panelId}"></canvas>
        </div>
        <div class="chart-legend">
          <div class="leg-item"><div class="leg-dot" style="background:#22c55e"></div>Bull candle</div>
          <div class="leg-item"><div class="leg-dot" style="background:#ef4444"></div>Bear candle</div>
          <div class="leg-item"><div class="leg-dot" style="background:#34d399;height:2px"></div>EMA 8</div>
          <div class="leg-item"><div class="leg-dot" style="background:#818cf8;height:2px"></div>EMA 21</div>
          <div class="leg-item"><div class="leg-dot" style="background:#f59e0b;height:2px"></div>VWAP</div>
        </div>
      </div>
      <div class="chart-sidebar">${sidebarHTML(data)}</div>
    </div>
  `;

  const chart = data.chart || [];
  if (!chart.length) return;

  // Build Chart.js dataset
  // candlestick dataset (financial plugin format: {x, o, h, l, c})
  const candleData = chart.map((b, i) => ({
    x: i,
    o: b.open, h: b.high, l: b.low, c: b.close,
  }));

  const ema8Data  = chart.map((b, i) => b.ema8  != null ? {x:i, y:b.ema8}  : null).filter(Boolean);
  const ema21Data = chart.map((b, i) => b.ema21 != null ? {x:i, y:b.ema21} : null).filter(Boolean);
  const vwapData  = chart.map((b, i) => ({x:i, y:b.vwap}));

  // Horizontal level lines
  const n = chart.length;
  const levelLine = (val, color, dash=[]) => ({
    type: 'line',
    data: [{x:0,y:val},{x:n-1,y:val}],
    borderColor: color,
    borderWidth: 1,
    borderDash: dash,
    pointRadius: 0,
    fill: false,
    tension: 0,
    order: 10,
  });

  // HVBO shaded band (via two filled datasets)
  const hvboHigh = data.hvboHigh;
  const hvboLow  = data.hvboLow;

  const xLabels = chart.map((_, i) => i);

  const ctx = document.getElementById('canvas_' + panelId);
  if (!ctx) return;

  const inst = new Chart(ctx, {
    type: 'candlestick',
    data: {
      labels: xLabels,
      datasets: [
        {
          label: 'Price',
          type: 'candlestick',
          data: candleData,
          color: {
            up:   '#22c55e',
            down: '#ef4444',
            unchanged: '#8295b3',
          },
          borderColor: {
            up:   '#22c55e',
            down: '#ef4444',
            unchanged: '#8295b3',
          },
          order: 1,
        },
        // HVBO band (filled between hvboLow and hvboHigh)
        {
          label: 'HVBO Band',
          type: 'line',
          data: chart.map((_,i) => ({x:i, y:hvboHigh})),
          borderColor: 'rgba(167,139,250,0.35)',
          backgroundColor: 'rgba(167,139,250,0.07)',
          borderWidth: 1,
          pointRadius: 0,
          fill: '+1',
          tension: 0,
          order: 9,
        },
        {
          label: 'HVBO Low',
          type: 'line',
          data: chart.map((_,i) => ({x:i, y:hvboLow})),
          borderColor: 'rgba(167,139,250,0.35)',
          backgroundColor: 'rgba(167,139,250,0.07)',
          borderWidth: 1,
          pointRadius: 0,
          fill: false,
          tension: 0,
          order: 9,
        },
        // EMA 8
        {
          label: 'EMA 8',
          type: 'line',
          data: ema8Data,
          borderColor: '#34d399',
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false,
          tension: 0.2,
          order: 2,
        },
        // EMA 21
        {
          label: 'EMA 21',
          type: 'line',
          data: ema21Data,
          borderColor: '#818cf8',
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false,
          tension: 0.2,
          order: 3,
        },
        // VWAP
        {
          label: 'VWAP',
          type: 'line',
          data: vwapData,
          borderColor: '#f59e0b',
          borderWidth: 1.5,
          borderDash: [4, 3],
          pointRadius: 0,
          fill: false,
          tension: 0,
          order: 4,
        },
        // Gamma Flip
        levelLine(data.gammaFlip, 'rgba(245,158,11,0.6)', [6,3]),
        // Call Wall
        levelLine(data.callWall,  'rgba(34,197,94,0.5)',  [4,2]),
        // Put Wall
        levelLine(data.putWall,   'rgba(239,68,68,0.5)',  [4,2]),
        // Resistance
        levelLine(data.resistance,'rgba(239,68,68,0.35)', [2,2]),
        // Major Support
        levelLine(data.majorSupport,'rgba(239,68,68,0.35)',[2,2]),
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#0d141f',
          borderColor: '#1c2940',
          borderWidth: 1,
          titleColor: '#e8f1fc',
          bodyColor: '#8295b3',
          callbacks: {
            label(ctx) {
              const raw = ctx.raw;
              if (raw && raw.o != null) {
                return `O: ${fmt(raw.o)}  H: ${fmt(raw.h)}  L: ${fmt(raw.l)}  C: ${fmt(raw.c)}`;
              }
              return ctx.dataset.label + ': ' + fmt(raw?.y ?? raw);
            },
          },
        },
      },
      scales: {
        x: {
          type: 'linear',
          ticks: {
            maxTicksLimit: 8,
            color: '#5a6b87',
            font: { size: 10, family: "'JetBrains Mono', monospace" },
            callback(val) {
              const b = chart[Math.round(val)];
              return b ? b.time : '';
            },
          },
          grid: { color: 'rgba(28,41,64,0.6)' },
        },
        y: {
          position: 'right',
          ticks: {
            color: '#5a6b87',
            font: { size: 10, family: "'JetBrains Mono', monospace" },
            callback: v => '$' + fmt(v),
          },
          grid: { color: 'rgba(28,41,64,0.6)' },
        },
      },
    },
  });

  chartInstances[panelId] = inst;
}

// ── Fetch + render one panel ──────────────────────────────────────────────────
async function loadPanel(panelId, ticker) {
  const panel = document.getElementById(panelId);
  if (!panel) return;
  panel.innerHTML = `<div class="panel-msg">Loading ${ticker}…</div>`;
  try {
    const r = await fetch('/api/chart_data?ticker=' + ticker + '&days=' + activeDays + '&tf=' + activeTf, {cache:'no-store'});
    const data = await r.json();
    if (!r.ok || data.error) {
      panel.innerHTML = `<div class="panel-msg err">Error loading ${ticker}: ${data.error || 'HTTP '+r.status}</div>`;
      return;
    }
    buildPanel(panelId, data);
  } catch(e) {
    panel.innerHTML = `<div class="panel-msg err">Network error loading ${ticker}: ${e.message}</div>`;
  }
}

// ── Refresh both charts ───────────────────────────────────────────────────────
async function loadAll() {
  document.getElementById('refreshBtn').textContent = '↻ Loading…';
  document.getElementById('lastUpdate').textContent = '';
  await Promise.all([
    loadPanel('panelES',  'ES'),
    loadPanel('panelSPX', 'SPX'),
  ]);
  document.getElementById('refreshBtn').textContent = '↻ Refresh';
  document.getElementById('lastUpdate').textContent =
    'Updated: ' + new Date().toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'}) + ' ET';
}

// ── Day selector buttons ──────────────────────────────────────────────────────
document.querySelectorAll('.day-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.day-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    activeDays = parseInt(btn.dataset.d);
    // Smart default TF: 1D→5m, 2D+→15m (user can still override)
    if (activeDays === 1 && activeTf === 15) {
      setTf(5);
    } else if (activeDays >= 3 && activeTf === 1) {
      setTf(15);
    }
    loadAll();
  });
});

// ── Timeframe selector buttons ────────────────────────────────────────────────
function setTf(tf) {
  activeTf = tf;
  document.querySelectorAll('.tf-btn').forEach(b => {
    b.classList.toggle('active', parseInt(b.dataset.tf) === tf);
  });
}

document.querySelectorAll('.tf-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    setTf(parseInt(btn.dataset.tf));
    loadAll();
  });
});

document.getElementById('refreshBtn').addEventListener('click', loadAll);

// Initial load + auto-refresh every 3 minutes during session hours
loadAll();
setInterval(loadAll, 180000);
</script>
</body>
</html>"""


@app.route("/chart")
def chart_dashboard():
    """Market Intelligence Terminal — ES and SPX side by side."""
    return render_template_string(CHART_HTML)

