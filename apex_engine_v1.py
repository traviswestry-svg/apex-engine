#!/usr/bin/env python3
"""
APEX ENGINE v1.5 - Polygon-Only Trading Decision Engine

Features:
- Multi-stock swing scanner
- SPY/QQQ 0DTE sniper mode
- LEAP candidate mode
- Re-entry engine
- Telegram A+ alerts only
- Duplicate alert protection by ticker/strategy/day
- Dashboard JSON output for Netlify/static hosting
- SPX included but safely skipped unless your Polygon account has indices entitlement

Environment variables required:
- POLYGON_API_KEY
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
Optional:
- MAX_RISK_PER_TRADE=750
- ACCOUNT_SIZE=60000
- MIN_GRADE=A+
- SEND_TELEGRAM=true
- OUTPUT_DIR=.

Render Cron command:
python apex_engine_v1.py
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

# =============================
# CONFIG
# =============================

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

MAX_RISK_PER_TRADE = float(os.getenv("MAX_RISK_PER_TRADE", "750"))
ACCOUNT_SIZE = float(os.getenv("ACCOUNT_SIZE", "60000"))
SEND_TELEGRAM = os.getenv("SEND_TELEGRAM", "true").lower() in {"1", "true", "yes", "y"}
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "."))

# Keep SPX in list, but skip safely until Indices entitlement is added.
TICKERS = [
    "SPX", "SPY", "QQQ", "NVDA", "TSLA", "META", "MSFT", "AAPL", "AMZN",
    "COIN", "AMD", "NFLX", "PLTR", "SMH", "QCOM", "NBIS"
]

ZERO_DTE_TICKERS = {"SPY", "QQQ"}  # Add SPX after Polygon Indices entitlement is active.
LEAP_TICKERS = {"NVDA", "MSFT", "AAPL", "AMZN", "META", "AMD", "PLTR", "SMH", "QCOM"}

# Market hours in ET converted approximate UTC for cron guidance. Engine itself can run anytime.
REQUEST_TIMEOUT = 12
POLYGON_BASE = "https://api.polygon.io"

ALERT_STATE_FILE = OUTPUT_DIR / "apex_alert_state.json"
DASHBOARD_FILE = OUTPUT_DIR / "apex_dashboard.json"
SCAN_LOG_FILE = OUTPUT_DIR / "apex_last_scan.json"

# =============================
# DATA MODELS
# =============================

@dataclass
class MarketMetrics:
    ticker: str
    price: float
    prev_close: float
    day_open: float
    day_high: float
    day_low: float
    volume: float
    avg_volume_20: float
    rel_volume: float
    ema8: float
    ema21: float
    ema50: float
    ema200: float
    rsi14: float
    atr14: float
    vwap: Optional[float]
    change_pct: float

@dataclass
class OptionPick:
    ticker: str
    option_ticker: str
    option_type: str
    strike: float
    expiration: str
    dte: int
    bid: Optional[float]
    ask: Optional[float]
    mid: Optional[float]
    delta: Optional[float]
    gamma: Optional[float]
    iv: Optional[float]
    open_interest: Optional[float]
    volume: Optional[float]
    stop_pct: float
    target1_pct: float
    target2_pct: float
    max_contracts: int
    estimated_risk_per_contract: Optional[float]

@dataclass
class TradeIdea:
    ticker: str
    strategy: str  # SWING / 0DTE / LEAP / RE-ENTRY
    direction: str  # CALL / PUT
    grade: str
    score: int
    status: str  # READY / WAIT / RE-ENTRY READY
    setup: str
    entry_zone: str
    stop: str
    target1: str
    target2: str
    risk_note: str
    timestamp_utc: str
    metrics: Dict[str, Any]
    option: Optional[Dict[str, Any]]
    alert_reason: str

# =============================
# UTILS
# =============================

def log(msg: str) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{now}] {msg}", flush=True)


def safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def round_price(x: Optional[float], ndigits: int = 2) -> Optional[float]:
    if x is None or not math.isfinite(x):
        return None
    return round(float(x), ndigits)


def load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

# =============================
# INDICATORS
# =============================

def ema(values: List[float], period: int) -> float:
    if not values:
        return 0.0
    if len(values) < period:
        return sum(values) / len(values)
    k = 2 / (period + 1)
    e = sum(values[:period]) / period
    for price in values[period:]:
        e = price * k + e * (1 - k)
    return e


def rsi(values: List[float], period: int = 14) -> float:
    if len(values) <= period:
        return 50.0
    gains = []
    losses = []
    for i in range(1, len(values)):
        delta = values[i] - values[i - 1]
        gains.append(max(delta, 0))
        losses.append(abs(min(delta, 0)))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    if len(closes) < 2:
        return 0.0
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    if not trs:
        return 0.0
    recent = trs[-period:]
    return sum(recent) / len(recent)

# =============================
# POLYGON CLIENT
# =============================

class PolygonClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()

    def get(self, path: str, params: Optional[Dict[str, Any]] = None, timeout: int = REQUEST_TIMEOUT) -> Optional[Dict[str, Any]]:
        if not self.api_key:
            raise RuntimeError("Missing POLYGON_API_KEY")
        url = f"{POLYGON_BASE}{path}"
        params = dict(params or {})
        params["apiKey"] = self.api_key
        try:
            r = self.session.get(url, params=params, timeout=timeout)
            if r.status_code == 403:
                log(f"Polygon not authorized for endpoint: {path}")
                return None
            if r.status_code >= 400:
                log(f"Polygon HTTP {r.status_code} for {path}: {r.text[:200]}")
                return None
            return r.json()
        except requests.Timeout:
            log(f"Polygon timeout for {path}")
            return None
        except Exception as e:
            log(f"Polygon error for {path}: {e}")
            return None

    def daily_aggs(self, ticker: str, days: int = 260) -> Optional[List[Dict[str, Any]]]:
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=days * 2)
        path = f"/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}"
        data = self.get(path, {"adjusted": "true", "sort": "asc", "limit": 5000})
        if not data or data.get("status") in {"NOT_AUTHORIZED", "ERROR"}:
            return None
        return data.get("results") or []

    def intraday_aggs(self, ticker: str, multiplier: int = 5, timespan: str = "minute", days: int = 2) -> List[Dict[str, Any]]:
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=days)
        path = f"/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{start}/{end}"
        data = self.get(path, {"adjusted": "true", "sort": "asc", "limit": 5000}, timeout=10)
        if not data:
            return []
        return data.get("results") or []

    def option_chain_snapshot(
        self,
        ticker: str,
        direction: str,
        min_dte: int,
        max_dte: int,
        target_delta_low: float,
        target_delta_high: float,
        price: float,
        limit: int = 250,
    ) -> List[Dict[str, Any]]:
        """Fetch limited option snapshot pages to avoid long Render hangs."""
        today = datetime.now(timezone.utc).date()
        exp_gte = today + timedelta(days=min_dte)
        exp_lte = today + timedelta(days=max_dte)
        contract_type = "call" if direction.upper() == "CALL" else "put"

        # Limit strike window around price to reduce data load.
        if direction.upper() == "CALL":
            strike_gte = max(1, price * 0.85)
            strike_lte = price * 1.20
        else:
            strike_gte = max(1, price * 0.80)
            strike_lte = price * 1.15

        path = f"/v3/snapshot/options/{ticker}"
        params = {
            "contract_type": contract_type,
            "expiration_date.gte": str(exp_gte),
            "expiration_date.lte": str(exp_lte),
            "strike_price.gte": round(strike_gte, 2),
            "strike_price.lte": round(strike_lte, 2),
            "limit": limit,
            "order": "asc",
            "sort": "expiration_date",
        }
        data = self.get(path, params, timeout=15)
        if not data:
            return []
        results = data.get("results") or []
        # Filter by delta if available; keep if Greeks missing so system still works.
        filtered = []
        for c in results:
            greeks = c.get("greeks") or {}
            delta = greeks.get("delta")
            if delta is None:
                filtered.append(c)
                continue
            abs_delta = abs(safe_float(delta))
            if target_delta_low <= abs_delta <= target_delta_high:
                filtered.append(c)
        return filtered[:limit]

# =============================
# MARKET METRICS
# =============================

def build_metrics(client: PolygonClient, ticker: str) -> Optional[MarketMetrics]:
    aggs = client.daily_aggs(ticker)
    if not aggs or len(aggs) < 50:
        return None

    closes = [safe_float(a.get("c")) for a in aggs]
    highs = [safe_float(a.get("h")) for a in aggs]
    lows = [safe_float(a.get("l")) for a in aggs]
    volumes = [safe_float(a.get("v")) for a in aggs]
    opens = [safe_float(a.get("o")) for a in aggs]

    price = closes[-1]
    prev_close = closes[-2] if len(closes) >= 2 else price
    day_open = opens[-1]
    day_high = highs[-1]
    day_low = lows[-1]
    volume = volumes[-1]
    avg_volume_20 = sum(volumes[-21:-1]) / min(20, len(volumes[-21:-1])) if len(volumes) > 21 else max(volume, 1)
    rel_volume = volume / avg_volume_20 if avg_volume_20 else 1.0
    change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0.0

    # Intraday VWAP approximation from 5-min bars.
    vwap = None
    intraday = client.intraday_aggs(ticker, days=2)
    if intraday:
        today_utc = datetime.now(timezone.utc).date()
        # use all recent bars from latest day present
        latest_day_ms = intraday[-1].get("t")
        if latest_day_ms:
            latest_day = datetime.fromtimestamp(latest_day_ms / 1000, timezone.utc).date()
            day_bars = [b for b in intraday if datetime.fromtimestamp(b.get("t", 0) / 1000, timezone.utc).date() == latest_day]
            pv_sum = sum(((safe_float(b.get("h")) + safe_float(b.get("l")) + safe_float(b.get("c"))) / 3) * safe_float(b.get("v")) for b in day_bars)
            vol_sum = sum(safe_float(b.get("v")) for b in day_bars)
            if vol_sum:
                vwap = pv_sum / vol_sum

    return MarketMetrics(
        ticker=ticker,
        price=price,
        prev_close=prev_close,
        day_open=day_open,
        day_high=day_high,
        day_low=day_low,
        volume=volume,
        avg_volume_20=avg_volume_20,
        rel_volume=rel_volume,
        ema8=ema(closes, 8),
        ema21=ema(closes, 21),
        ema50=ema(closes, 50),
        ema200=ema(closes, 200),
        rsi14=rsi(closes, 14),
        atr14=atr(highs, lows, closes, 14),
        vwap=vwap,
        change_pct=change_pct,
    )

# =============================
# STRATEGY SCORING
# =============================

def grade_from_score(score: int) -> str:
    if score >= 7:
        return "A+"
    if score >= 6:
        return "A"
    if score >= 5:
        return "B+"
    return "B"


def is_uptrend(m: MarketMetrics) -> bool:
    return m.price > m.ema50 > m.ema200


def is_downtrend(m: MarketMetrics) -> bool:
    return m.price < m.ema50 < m.ema200


def near(value: float, target: float, pct: float) -> bool:
    if target == 0:
        return False
    return abs(value - target) / target <= pct


def swing_score(m: MarketMetrics) -> Tuple[int, str, str]:
    score = 0
    reasons = []
    direction = "CALL"

    if is_uptrend(m):
        score += 2
        reasons.append("bull trend above EMA50/200")
        direction = "CALL"
    elif is_downtrend(m):
        score += 2
        reasons.append("bear trend below EMA50/200")
        direction = "PUT"
    else:
        return 0, direction, "trend not clean"

    if direction == "CALL":
        if m.ema21 * 0.985 <= m.price <= m.ema21 * 1.035:
            score += 2
            reasons.append("near EMA21 pullback zone")
        elif m.price <= m.ema50 * 1.02:
            score += 1
            reasons.append("near EMA50 deeper pullback")
        if 45 <= m.rsi14 <= 65:
            score += 1
            reasons.append("RSI reset bullish")
        if m.price > m.ema8:
            score += 1
            reasons.append("reclaiming EMA8")
    else:
        if m.ema21 * 0.965 <= m.price <= m.ema21 * 1.015:
            score += 2
            reasons.append("near EMA21 bearish retest")
        if 35 <= m.rsi14 <= 55:
            score += 1
            reasons.append("RSI bearish reset")
        if m.price < m.ema8:
            score += 1
            reasons.append("below EMA8")

    if m.rel_volume >= 1.2:
        score += 1
        reasons.append("relative volume expansion")
    if abs(m.change_pct) >= 0.7:
        score += 1
        reasons.append("meaningful daily move")

    return score, direction, "; ".join(reasons)


def swing_status(m: MarketMetrics, direction: str) -> Tuple[str, str]:
    if direction == "CALL":
        if m.price <= m.ema21 * 1.01 and m.price >= m.ema21 * 0.985:
            return "READY", f"{round_price(m.ema21*0.985)} - {round_price(m.ema21*1.01)}"
        if m.price <= m.ema21 * 1.035:
            return "WAIT", f"wait for {round_price(m.ema21)} area"
        return "WAIT", "extended - wait for pullback"
    else:
        if m.price >= m.ema21 * 0.99 and m.price <= m.ema21 * 1.015:
            return "READY", f"{round_price(m.ema21*0.99)} - {round_price(m.ema21*1.015)}"
        return "WAIT", f"wait for retest near {round_price(m.ema21)}"


def zero_dte_score(m: MarketMetrics) -> Tuple[int, str, str, str]:
    score = 0
    reasons = []
    direction = "CALL"
    setup = "0DTE SNIPER"

    # Intraday proxy using daily + VWAP because this runs as cron and may not always have perfect intraday state.
    if m.vwap:
        if m.price > m.vwap and m.ema8 > m.ema21:
            score += 2
            direction = "CALL"
            reasons.append("price above VWAP and EMA8>EMA21")
        elif m.price < m.vwap and m.ema8 < m.ema21:
            score += 2
            direction = "PUT"
            reasons.append("price below VWAP and EMA8<EMA21")
    else:
        if m.price > m.day_open and m.ema8 > m.ema21:
            score += 1
            direction = "CALL"
            reasons.append("above day open with EMA8>EMA21")
        elif m.price < m.day_open and m.ema8 < m.ema21:
            score += 1
            direction = "PUT"
            reasons.append("below day open with EMA8<EMA21")

    # Opening range / day range proxy.
    day_range = max(m.day_high - m.day_low, 0.01)
    pos_in_range = (m.price - m.day_low) / day_range
    if direction == "CALL" and pos_in_range >= 0.70:
        score += 2
        reasons.append("near high-of-day breakout zone")
    elif direction == "PUT" and pos_in_range <= 0.30:
        score += 2
        reasons.append("near low-of-day breakdown zone")

    # Avoid chop.
    if not (45 <= m.rsi14 <= 55):
        score += 1
        reasons.append("RSI outside chop zone")
    if m.rel_volume >= 1.3:
        score += 1
        reasons.append("volume expansion")
    if abs(m.change_pct) >= 0.4:
        score += 1
        reasons.append("directional movement")

    # Anti-chase: too far from VWAP or EMA21 gets downgraded.
    chase = False
    reference = m.vwap or m.ema21
    if reference and abs(m.price - reference) / reference > 0.018:
        chase = True
        score -= 1
        reasons.append("anti-chase penalty")

    status = "READY" if score >= 6 and not chase else "WAIT"
    return score, direction, setup, "; ".join(reasons) + f"; status={status}"


def zero_dte_status(m: MarketMetrics, direction: str) -> Tuple[str, str]:
    reference = m.vwap or m.ema21
    if not reference:
        return "WAIT", "wait for VWAP/EMA confirmation"
    dist = abs(m.price - reference) / reference
    if dist <= 0.012 and m.rel_volume >= 1.2:
        return "READY", f"near VWAP/EMA trigger {round_price(reference)}"
    if dist <= 0.02:
        return "WAIT", f"wait for cleaner touch near {round_price(reference)}"
    return "WAIT", "extended - do not chase"


def reentry_score(m: MarketMetrics) -> Tuple[int, str, str]:
    score = 0
    direction = "CALL"
    reasons = []

    if is_uptrend(m):
        direction = "CALL"
        score += 2
        reasons.append("trend still bullish")
        if m.price >= m.ema21 * 0.99 and m.price <= m.ema21 * 1.02:
            score += 3
            reasons.append("pullback into EMA21 re-entry zone")
        if 48 <= m.rsi14 <= 62:
            score += 1
            reasons.append("RSI reset for re-entry")
        if m.price > m.ema50:
            score += 1
            reasons.append("holds EMA50 support")
    elif is_downtrend(m):
        direction = "PUT"
        score += 2
        reasons.append("trend still bearish")
        if m.price <= m.ema21 * 1.01 and m.price >= m.ema21 * 0.98:
            score += 3
            reasons.append("retest into EMA21 short zone")
        if 38 <= m.rsi14 <= 52:
            score += 1
            reasons.append("RSI reset bearish")
        if m.price < m.ema50:
            score += 1
            reasons.append("below EMA50 resistance")
    return score, direction, "; ".join(reasons)


def leap_score(m: MarketMetrics) -> Tuple[int, str, str]:
    score = 0
    direction = "CALL"
    reasons = []
    if is_uptrend(m):
        score += 3
        reasons.append("long-term uptrend")
    else:
        return 0, direction, "not a long-term uptrend"
    # LEAP ideal: not overextended, RSI not too hot.
    if m.price <= m.ema50 * 1.10:
        score += 2
        reasons.append("not excessively extended from EMA50")
    if 45 <= m.rsi14 <= 68:
        score += 1
        reasons.append("RSI acceptable for LEAP entry")
    if m.rel_volume >= 1.0:
        score += 1
        reasons.append("normal or stronger participation")
    return score, direction, "; ".join(reasons)

# =============================
# OPTION SELECTION
# =============================

def get_mid(contract: Dict[str, Any]) -> Optional[float]:
    quote = contract.get("last_quote") or {}
    bid = quote.get("bid")
    ask = quote.get("ask")
    if bid is not None and ask is not None and safe_float(ask) > 0:
        return (safe_float(bid) + safe_float(ask)) / 2
    trade = contract.get("last_trade") or {}
    price = trade.get("price")
    if price is not None:
        return safe_float(price)
    details = contract.get("details") or {}
    return None


def build_option_pick(
    client: PolygonClient,
    ticker: str,
    direction: str,
    strategy: str,
    price: float,
) -> Optional[OptionPick]:
    if ticker == "SPX":
        return None

    if strategy == "0DTE":
        min_dte, max_dte = 0, 1
        delta_low, delta_high = 0.45, 0.65
        stop_pct, target1_pct, target2_pct = 0.45, 0.30, 0.60
    elif strategy == "LEAP":
        min_dte, max_dte = 90, 365
        delta_low, delta_high = 0.65, 0.85
        stop_pct, target1_pct, target2_pct = 0.30, 0.40, 0.100
    else:  # SWING / RE-ENTRY
        min_dte, max_dte = 7, 30
        delta_low, delta_high = 0.55, 0.75
        stop_pct, target1_pct, target2_pct = 0.35, 0.40, 0.80

    log(f"Fetching options for {ticker} {direction} {strategy} DTE {min_dte}-{max_dte}")
    contracts = client.option_chain_snapshot(ticker, direction, min_dte, max_dte, delta_low, delta_high, price)
    if not contracts:
        return None

    def contract_rank(c: Dict[str, Any]) -> Tuple[float, float, float]:
        details = c.get("details") or {}
        greeks = c.get("greeks") or {}
        mid = get_mid(c) or 9999
        delta = abs(safe_float(greeks.get("delta"), 0.60))
        target_delta = 0.55 if strategy == "0DTE" else (0.72 if strategy == "LEAP" else 0.65)
        exp = details.get("expiration_date") or "9999-12-31"
        try:
            dte = (datetime.strptime(exp, "%Y-%m-%d").date() - datetime.now(timezone.utc).date()).days
        except Exception:
            dte = 999
        return (abs(delta - target_delta), dte, mid)

    best = sorted(contracts, key=contract_rank)[0]
    details = best.get("details") or {}
    greeks = best.get("greeks") or {}
    quote = best.get("last_quote") or {}
    day = best.get("day") or {}
    oi = best.get("open_interest")
    mid = get_mid(best)
    estimated_risk = mid * 100 * stop_pct if mid else None
    max_contracts = max(1, int(MAX_RISK_PER_TRADE // estimated_risk)) if estimated_risk and estimated_risk > 0 else 1
    max_contracts = min(max_contracts, 10)  # safety cap
    exp = details.get("expiration_date") or ""
    try:
        dte = (datetime.strptime(exp, "%Y-%m-%d").date() - datetime.now(timezone.utc).date()).days
    except Exception:
        dte = -1

    return OptionPick(
        ticker=ticker,
        option_ticker=details.get("ticker", ""),
        option_type=direction,
        strike=safe_float(details.get("strike_price")),
        expiration=exp,
        dte=dte,
        bid=round_price(safe_float(quote.get("bid")) if quote.get("bid") is not None else None),
        ask=round_price(safe_float(quote.get("ask")) if quote.get("ask") is not None else None),
        mid=round_price(mid),
        delta=round_price(safe_float(greeks.get("delta")) if greeks.get("delta") is not None else None, 3),
        gamma=round_price(safe_float(greeks.get("gamma")) if greeks.get("gamma") is not None else None, 4),
        iv=round_price(safe_float(best.get("implied_volatility")) if best.get("implied_volatility") is not None else None, 3),
        open_interest=safe_float(oi) if oi is not None else None,
        volume=safe_float(day.get("volume")) if day.get("volume") is not None else None,
        stop_pct=stop_pct,
        target1_pct=target1_pct,
        target2_pct=target2_pct,
        max_contracts=max_contracts,
        estimated_risk_per_contract=round_price(estimated_risk),
    )

# =============================
# IDEA BUILDERS
# =============================

def metrics_public(m: MarketMetrics) -> Dict[str, Any]:
    return {
        "price": round_price(m.price),
        "change_pct": round_price(m.change_pct),
        "rel_volume": round_price(m.rel_volume),
        "rsi14": round_price(m.rsi14),
        "ema8": round_price(m.ema8),
        "ema21": round_price(m.ema21),
        "ema50": round_price(m.ema50),
        "ema200": round_price(m.ema200),
        "vwap": round_price(m.vwap),
        "atr14": round_price(m.atr14),
    }


def format_stop_target(option: Optional[OptionPick]) -> Tuple[str, str, str]:
    if not option or not option.mid:
        return ("Use chart invalidation / $750 max risk", "+40% option or structure target", "+80% option or runner")
    stop_price = option.mid * (1 - option.stop_pct)
    t1 = option.mid * (1 + option.target1_pct)
    t2 = option.mid * (1 + option.target2_pct)
    return (
        f"Option stop near {round_price(stop_price)} (-{int(option.stop_pct*100)}%)",
        f"Target 1 near {round_price(t1)} (+{int(option.target1_pct*100)}%)",
        f"Target 2 near {round_price(t2)} (+{int(option.target2_pct*100)}%)",
    )


def make_idea(
    client: PolygonClient,
    m: MarketMetrics,
    strategy: str,
    direction: str,
    score: int,
    status: str,
    setup: str,
    entry_zone: str,
    reason: str,
) -> Optional[TradeIdea]:
    grade = grade_from_score(score)
    # High impact upgrade: only output A+ ideas.
    if grade != "A+":
        return None
    # Alerts only for actionable states.
    if status not in {"READY", "RE-ENTRY READY"}:
        # Still output on dashboard? User wanted high-impact A+ only; keep WAIT off to reduce clutter.
        return None

    option = build_option_pick(client, m.ticker, direction, strategy, m.price)
    stop, target1, target2 = format_stop_target(option)
    risk_note = f"Max planned risk ${MAX_RISK_PER_TRADE:.0f}; contracts based on option stop."
    if option and option.estimated_risk_per_contract:
        risk_note = (
            f"Max risk ${MAX_RISK_PER_TRADE:.0f}; estimated risk/contract ${option.estimated_risk_per_contract}; "
            f"max contracts {option.max_contracts}."
        )

    return TradeIdea(
        ticker=m.ticker,
        strategy=strategy,
        direction=direction,
        grade=grade,
        score=score,
        status=status,
        setup=setup,
        entry_zone=entry_zone,
        stop=stop,
        target1=target1,
        target2=target2,
        risk_note=risk_note,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        metrics=metrics_public(m),
        option=asdict(option) if option else None,
        alert_reason=reason,
    )

# =============================
# TELEGRAM + DUPLICATES
# =============================

def alert_key(idea: TradeIdea) -> str:
    return f"{today_key()}::{idea.ticker}::{idea.strategy}::{idea.direction}::{idea.status}"


def should_alert(idea: TradeIdea) -> bool:
    state = load_json(ALERT_STATE_FILE, {})
    key = alert_key(idea)
    if state.get(key):
        return False
    state[key] = datetime.now(timezone.utc).isoformat()
    # Keep only recent/current day keys to prevent file growing forever.
    current = today_key()
    state = {k: v for k, v in state.items() if k.startswith(current)}
    save_json(ALERT_STATE_FILE, state)
    return True


def telegram_message(idea: TradeIdea) -> str:
    opt = idea.option or {}
    option_line = "Option: No contract selected"
    if opt:
        option_line = (
            f"Option: {opt.get('option_ticker') or idea.ticker} | {opt.get('option_type')} "
            f"{opt.get('strike')} exp {opt.get('expiration')} ({opt.get('dte')} DTE) | "
            f"mid {opt.get('mid')} | delta {opt.get('delta')} | contracts {opt.get('max_contracts')}"
        )
    m = idea.metrics
    return (
        f"🔥 APEX A+ ALERT\n"
        f"Ticker: {idea.ticker}\n"
        f"Strategy: {idea.strategy}\n"
        f"Direction: {idea.direction}\n"
        f"Status: {idea.status}\n"
        f"Score: {idea.score}/8\n"
        f"Setup: {idea.setup}\n"
        f"Entry: {idea.entry_zone}\n"
        f"{option_line}\n"
        f"Stop: {idea.stop}\n"
        f"Target 1: {idea.target1}\n"
        f"Target 2: {idea.target2}\n"
        f"Risk: {idea.risk_note}\n"
        f"Price: {m.get('price')} | RSI: {m.get('rsi14')} | RelVol: {m.get('rel_volume')}x\n"
        f"Reason: {idea.alert_reason}"
    )


def send_telegram(text: str) -> bool:
    if not SEND_TELEGRAM:
        log("Telegram disabled by SEND_TELEGRAM=false")
        return False
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram token/chat id missing; skipping alert")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code >= 400:
            log(f"Telegram failed HTTP {r.status_code}: {r.text[:200]}")
            return False
        return True
    except Exception as e:
        log(f"Telegram error: {e}")
        return False

# =============================
# MAIN SCAN
# =============================

def scan_ticker(client: PolygonClient, ticker: str) -> List[TradeIdea]:
    ideas: List[TradeIdea] = []
    log(f"Scanning {ticker}...")
    m = build_metrics(client, ticker)
    if not m:
        log(f"Skipping {ticker}: no metrics or not authorized")
        return ideas

    # 0DTE sniper first for SPY/QQQ.
    if ticker in ZERO_DTE_TICKERS:
        score, direction, setup, reason = zero_dte_score(m)
        status, entry = zero_dte_status(m, direction)
        idea = make_idea(client, m, "0DTE", direction, score, status, setup, entry, reason)
        if idea:
            ideas.append(idea)

    # Re-entry engine before base swing to catch actionable pullbacks.
    re_score, re_direction, re_reason = reentry_score(m)
    re_status = "RE-ENTRY READY" if re_score >= 7 else "WAIT"
    re_entry = f"EMA21/VWAP pullback zone near {round_price(m.ema21)}"
    re_idea = make_idea(client, m, "RE-ENTRY", re_direction, re_score, re_status, "A+ RE-ENTRY", re_entry, re_reason)
    if re_idea:
        ideas.append(re_idea)

    # Swing engine.
    sw_score, sw_direction, sw_reason = swing_score(m)
    sw_status, sw_entry = swing_status(m, sw_direction)
    sw_idea = make_idea(client, m, "SWING", sw_direction, sw_score, sw_status, "Pullback continuation", sw_entry, sw_reason)
    if sw_idea:
        ideas.append(sw_idea)

    # LEAP engine only for selected long-term names; lower frequency but still A+ only.
    if ticker in LEAP_TICKERS:
        lp_score, lp_direction, lp_reason = leap_score(m)
        lp_status = "READY" if lp_score >= 7 and m.price <= m.ema50 * 1.08 else "WAIT"
        lp_entry = f"Long-term entry zone: near EMA50 {round_price(m.ema50)} to current {round_price(m.price)}"
        lp_idea = make_idea(client, m, "LEAP", lp_direction, lp_score, lp_status, "Long-term accumulation", lp_entry, lp_reason)
        if lp_idea:
            ideas.append(lp_idea)

    return ideas


def rank_ideas(ideas: List[TradeIdea]) -> List[TradeIdea]:
    strategy_priority = {"SWING": 0, "RE-ENTRY": 1, "0DTE": 2, "LEAP": 3}
    return sorted(
        ideas,
        key=lambda x: (
            -x.score,
            strategy_priority.get(x.strategy, 9),
            x.ticker,
        ),
    )


def main() -> int:
    log("Apex Engine v1.5 starting — Polygon-only mode. Benzinga disabled.")
    log("High-impact upgrades active: A+ only, 0DTE SPY/QQQ sniper, re-entry engine, Telegram A+ alerts only, dashboard JSON.")

    if not POLYGON_API_KEY:
        log("ERROR: Missing POLYGON_API_KEY environment variable")
        return 1

    client = PolygonClient(POLYGON_API_KEY)
    all_ideas: List[TradeIdea] = []

    for ticker in TICKERS:
        try:
            ideas = scan_ticker(client, ticker)
            all_ideas.extend(ideas)
        except Exception as e:
            log(f"Error scanning {ticker}: {e}")
        time.sleep(0.25)  # gentle API pacing

    ranked = rank_ideas(all_ideas)

    # Save dashboard artifacts.
    dashboard = {
        "engine": "Apex Engine v1.5",
        "mode": "Polygon-only; Benzinga disabled",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "account_size": ACCOUNT_SIZE,
        "max_risk_per_trade": MAX_RISK_PER_TRADE,
        "qualified_count": len(ranked),
        "best_setup": asdict(ranked[0]) if ranked else None,
        "ideas": [asdict(i) for i in ranked],
        "notes": [
            "Only A+ actionable ideas are shown.",
            "Tickers not displayed should be treated as no trade.",
            "SPX is safely skipped until Polygon Indices entitlement is enabled.",
            "Execution is manual in Power E*TRADE; alerts are not trade instructions.",
        ],
    }
    save_json(DASHBOARD_FILE, dashboard)
    save_json(SCAN_LOG_FILE, dashboard)

    log(f"Scan complete. Qualified ideas: {len(ranked)}")
    if ranked:
        for idea in ranked[:10]:
            opt = idea.option or {}
            log(
                f"A+ {idea.strategy} {idea.ticker} {idea.direction} {idea.status} | "
                f"score {idea.score} | option {opt.get('option_ticker', 'N/A')} mid {opt.get('mid', 'N/A')}"
            )

    # Telegram A+ only + duplicate protection.
    alerts_sent = 0
    for idea in ranked:
        if should_alert(idea):
            if send_telegram(telegram_message(idea)):
                alerts_sent += 1
                log(f"Telegram alert sent: {idea.ticker} {idea.strategy}")
            else:
                log(f"Telegram alert skipped/failed: {idea.ticker} {idea.strategy}")
        else:
            log(f"Duplicate alert suppressed: {idea.ticker} {idea.strategy}")

    log(f"Alerts sent: {alerts_sent}")
    log(f"Dashboard saved to {DASHBOARD_FILE.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
