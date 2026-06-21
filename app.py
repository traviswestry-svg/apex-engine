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

VERSION = "3.4.2_DASHBOARD_JS_FIX"
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
    "last_scan_status": "Starting APEX 3.4.2 scanner...",
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
<body>
<div class="wrap">
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
