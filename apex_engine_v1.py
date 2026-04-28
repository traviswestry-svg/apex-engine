#!/usr/bin/env python3
from __future__ import annotations

print("🔥 APEX ENGINE VERSION 2.3 LIVE - POSITION SIZING + CONFIRMATION TRIGGERS 🔥")

import base64
import json
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone, time
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests


# =========================
# ENVIRONMENT
# =========================

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

ACCOUNT_SIZE = float(os.getenv("ACCOUNT_SIZE", "60000"))
MAX_RISK_PER_TRADE = float(os.getenv("MAX_RISK_PER_TRADE", "750"))

SEND_TELEGRAM = os.getenv("SEND_TELEGRAM", "true").lower() == "true"
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "12"))

DASHBOARD_FILE = os.getenv("DASHBOARD_FILE", "dashboard.json")
ALERT_CACHE_FILE = os.getenv("ALERT_CACHE_FILE", "sent_alerts.json")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.getenv("GITHUB_REPO", "").strip()
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main").strip()
GITHUB_DASHBOARD_PATH = os.getenv("GITHUB_DASHBOARD_PATH", "dashboard.json").strip()

POLYGON_BASE = "https://api.polygon.io"
EASTERN = ZoneInfo("America/New_York")

TICKERS = [
    "SPY", "QQQ", "SPX",
    "NVDA", "TSLA", "META", "MSFT", "AAPL", "AMZN",
    "COIN", "AMD", "NFLX", "PLTR", "SMH", "QCOM", "NBIS"
]

ZERO_DTE_TICKERS = {"SPY", "QQQ"}


# =========================
# DATA MODELS
# =========================

@dataclass
class Metrics:
    ticker: str
    price: float
    prev_close: float
    volume: float
    avg_volume_20: float
    rel_volume: float
    ema8: float
    ema21: float
    ema50: float
    ema200: float
    rsi: float
    atr: float
    vwap: Optional[float]


@dataclass
class OptionPick:
    contract: str
    expiration: str
    strike: float
    option_type: str
    dte: int
    estimated_entry: float
    stop_pct: float
    risk_per_contract: float
    max_contracts: int
    spread_pct: Optional[float]
    volume: Optional[int]
    open_interest: Optional[int]
    liquidity_ok: bool
    liquidity_note: str


@dataclass
class Idea:
    ticker: str
    grade: str
    score: int
    trader_type: str
    strategy: str
    direction: str
    status: str

    trade_permission: str
    confirmation_trigger: str
    no_trade_reason: str
    sniper_trigger: str

    entry_zone: str
    entry_range: str

    option_contract: str
    estimated_option_entry: Optional[float]
    dte: Optional[int]
    max_contracts: int
    recommended_contracts: int
    confidence_size_pct: int
    max_risk: float
    position_plan: str

    exit_plan: str
    stop_loss: str
    targets: List[str]
    target_1: str
    target_2: str
    runner_rule: str
    time_stop: str
    profit_protection: str
    exit_checklist: List[str]

    price: float
    rsi: float
    rel_volume: float
    notes: List[str]


# =========================
# BASIC HELPERS
# =========================

def log(msg: str) -> None:
    print(msg, flush=True)


def now_et() -> datetime:
    return datetime.now(EASTERN)


def today_key() -> str:
    return now_et().date().isoformat()


def session_name() -> str:
    n = now_et().time()
    if time(4, 0) <= n < time(9, 30):
        return "PREMARKET"
    if time(9, 30) <= n <= time(16, 0):
        return "MARKET_OPEN"
    return "AFTER_HOURS"


def is_market_open() -> bool:
    n = now_et().time()
    return time(9, 30) <= n <= time(16, 0)


def execution_window(strategy: str) -> bool:
    n = now_et().time()
    if strategy == "0DTE":
        return is_market_open() and time(9, 45) <= n <= time(15, 30)
    return is_market_open() and time(9, 45) <= n <= time(15, 45)


def f(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def rp(x: Any, digits: int = 2) -> float:
    return round(f(x), digits)


# =========================
# INDICATORS
# =========================

def ema(vals: List[float], period: int) -> float:
    vals = [f(v) for v in vals if v is not None]
    if not vals:
        return 0.0
    if len(vals) < period:
        return vals[-1]
    k = 2 / (period + 1)
    e = sum(vals[:period]) / period
    for p in vals[period:]:
        e = p * k + e * (1 - k)
    return e


def rsi(vals: List[float], period: int = 14) -> float:
    if len(vals) <= period:
        return 50.0
    gains: List[float] = []
    losses: List[float] = []
    for i in range(1, len(vals)):
        diff = vals[i] - vals[i - 1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0:
        return 100.0
    return 100 - (100 / (1 + ag / al))


def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    if len(closes) < 2:
        return 0.0
    trs: List[float] = []
    for i in range(1, len(closes)):
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    if not trs:
        return 0.0
    return sum(trs[-period:]) / min(period, len(trs))


def vwap_from_bars(bars: List[Dict[str, Any]]) -> Optional[float]:
    pv = 0.0
    vol = 0.0
    for b in bars:
        v = f(b.get("v"))
        typical = (f(b.get("h")) + f(b.get("l")) + f(b.get("c"))) / 3
        pv += typical * v
        vol += v
    return pv / vol if vol else None


def latest_session_bars(bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not bars:
        return []
    last_date = datetime.fromtimestamp(bars[-1].get("t", 0) / 1000, timezone.utc).astimezone(EASTERN).date()
    return [
        b for b in bars
        if datetime.fromtimestamp(b.get("t", 0) / 1000, timezone.utc).astimezone(EASTERN).date() == last_date
    ]


# =========================
# POLYGON CLIENT
# =========================

class Polygon:
    def __init__(self, key: str):
        self.key = key

    def get(self, path: str, params: Optional[Dict[str, Any]] = None, timeout: Optional[int] = None) -> Optional[Dict[str, Any]]:
        if not self.key:
            log("Missing POLYGON_API_KEY")
            return None

        params = dict(params or {})
        params["apiKey"] = self.key

        try:
            r = requests.get(POLYGON_BASE + path, params=params, timeout=timeout or REQUEST_TIMEOUT)
            if r.status_code >= 400:
                log(f"Polygon HTTP {r.status_code} for {path}: {r.text[:220]}")
                return None
            return r.json()
        except requests.Timeout:
            log(f"Polygon timeout for {path}")
            return None
        except Exception as e:
            log(f"Polygon error for {path}: {e}")
            return None

    def daily(self, ticker: str, days: int = 260) -> List[Dict[str, Any]]:
        end = now_et().date()
        start = end - timedelta(days=days * 2)
        data = self.get(
            f"/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}",
            {"adjusted": "true", "sort": "asc", "limit": 5000},
            15,
        )
        return (data or {}).get("results") or []

    def intraday(self, ticker: str, mult: int = 5, days: int = 2) -> List[Dict[str, Any]]:
        end = now_et().date()
        start = end - timedelta(days=days)
        data = self.get(
            f"/v2/aggs/ticker/{ticker}/range/{mult}/minute/{start}/{end}",
            {"adjusted": "true", "sort": "asc", "limit": 5000},
            12,
        )
        return latest_session_bars((data or {}).get("results") or [])

    def options(self, ticker: str, direction: str, min_dte: int, max_dte: int, price: float, limit: int = 100) -> List[Dict[str, Any]]:
        if ticker == "SPX":
            return []

        today = now_et().date()
        contract_type = "call" if direction == "CALL" else "put"

        if direction == "CALL":
            strike_low = max(1, price * 0.88)
            strike_high = price * 1.18
        else:
            strike_low = max(1, price * 0.82)
            strike_high = price * 1.08

        params = {
            "contract_type": contract_type,
            "expiration_date.gte": str(today + timedelta(days=min_dte)),
            "expiration_date.lte": str(today + timedelta(days=max_dte)),
            "strike_price.gte": round(strike_low, 2),
            "strike_price.lte": round(strike_high, 2),
            "limit": limit,
        }

        data = self.get(f"/v3/snapshot/options/{ticker}", params, 15)
        return (data or {}).get("results") or []


# =========================
# METRICS / SCORING
# =========================

def build_metrics(client: Polygon, ticker: str) -> Tuple[Optional[Metrics], List[Dict[str, Any]]]:
    if ticker == "SPX":
        log("SPX left in list but skipped until Polygon Indices entitlement is added.")
        return None, []

    daily = client.daily(ticker)
    if len(daily) < 60:
        log(f"Not enough daily bars for {ticker}")
        return None, []

    closes = [f(x.get("c")) for x in daily]
    highs = [f(x.get("h")) for x in daily]
    lows = [f(x.get("l")) for x in daily]
    volumes = [f(x.get("v")) for x in daily]

    avg20 = sum(volumes[-21:-1]) / min(20, len(volumes[-21:-1])) if len(volumes) > 21 else max(volumes[-1], 1)
    rel_volume = volumes[-1] / avg20 if avg20 else 1.0

    intraday = client.intraday(ticker)

    metrics = Metrics(
        ticker=ticker,
        price=closes[-1],
        prev_close=closes[-2],
        volume=volumes[-1],
        avg_volume_20=avg20,
        rel_volume=rel_volume,
        ema8=ema(closes, 8),
        ema21=ema(closes, 21),
        ema50=ema(closes, 50),
        ema200=ema(closes, 200),
        rsi=rsi(closes),
        atr=atr(highs, lows, closes),
        vwap=vwap_from_bars(intraday),
    )

    return metrics, intraday


def trend_direction(m: Metrics) -> Optional[str]:
    if m.price > m.ema50 > m.ema200:
        return "CALL"
    if m.price < m.ema50 < m.ema200:
        return "PUT"
    return None


def no_chase(m: Metrics, direction: str, max_ext: float = 0.035) -> bool:
    if m.ema21 <= 0:
        return False
    if direction == "CALL":
        return ((m.price - m.ema21) / m.ema21) <= max_ext
    return ((m.ema21 - m.price) / m.ema21) <= max_ext


def grade(score: int) -> str:
    if score >= 85:
        return "A+"
    if score >= 75:
        return "A"
    return "B+"


def score_swing(m: Metrics) -> Tuple[int, Optional[str], List[str]]:
    direction = trend_direction(m)
    if not direction:
        return 0, None, ["trend not clean"]

    score = 55
    reasons = ["clean trend"]

    if direction == "CALL":
        if m.ema21 * 0.985 <= m.price <= m.ema21 * 1.035:
            score += 15
            reasons.append("near EMA21 pullback")
        if 45 <= m.rsi <= 65:
            score += 10
            reasons.append("RSI reset")
        if m.price > m.ema8:
            score += 5
            reasons.append("above EMA8")
    else:
        if m.ema21 * 0.965 <= m.price <= m.ema21 * 1.015:
            score += 15
            reasons.append("bearish EMA21 retest")
        if 35 <= m.rsi <= 55:
            score += 10
            reasons.append("RSI bearish reset")
        if m.price < m.ema8:
            score += 5
            reasons.append("below EMA8")

    if m.rel_volume >= 1.2:
        score += 10
        reasons.append("relative volume confirmed")

    if no_chase(m, direction):
        score += 5
        reasons.append("not extended")

    return min(score, 100), direction, reasons


def score_leap(m: Metrics) -> Tuple[int, Optional[str], List[str]]:
    if not (m.price > m.ema50 > m.ema200):
        return 0, None, ["not a LEAP uptrend"]

    score = 70
    reasons = ["long-term uptrend"]

    if m.price <= m.ema50 * 1.10:
        score += 10
        reasons.append("not extended from EMA50")
    if 45 <= m.rsi <= 68:
        score += 8
        reasons.append("RSI acceptable")
    if m.rel_volume >= 1.0:
        score += 5
        reasons.append("participation normal/strong")

    return min(score, 100), "CALL", reasons


def score_0dte(m: Metrics, bars: List[Dict[str, Any]]) -> Tuple[int, Optional[str], List[str]]:
    if m.ticker not in ZERO_DTE_TICKERS or len(bars) < 6:
        return 0, None, ["0DTE not active or insufficient bars"]

    open_range_bars = bars[:3]
    opening_high = max(f(b.get("h")) for b in open_range_bars)
    opening_low = min(f(b.get("l")) for b in open_range_bars)

    closes = [f(b.get("c")) for b in bars]
    close = closes[-1]
    e8 = ema(closes, 8)
    e21 = ema(closes, min(21, len(closes)))
    vw = m.vwap or vwap_from_bars(bars) or e21

    if close > opening_high and close > vw and e8 >= e21:
        return 88, "CALL", ["opening range breakout", "VWAP support", "EMA8/21 aligned"]
    if close < opening_low and close < vw and e8 <= e21:
        return 88, "PUT", ["opening range breakdown", "VWAP rejection", "EMA8/21 aligned"]
    return 0, None, ["no 0DTE trigger"]


# =========================
# SNIPER + CONFIRMATION
# =========================

def sniper_status(m: Metrics, bars: List[Dict[str, Any]], direction: str, strategy: str) -> Tuple[str, str, List[str]]:
    if not execution_window(strategy):
        return "WATCHLIST - OPEN CONFIRMATION NEEDED", "Wait until approved confirmation window.", ["market not in execution window"]

    if len(bars) < 8:
        return "WAIT - NEED MORE INTRADAY BARS", "Wait for 5-min structure.", ["not enough intraday bars"]

    closes = [f(b.get("c")) for b in bars]
    vols = [f(b.get("v")) for b in bars]
    last = bars[-1]

    close = f(last.get("c"))
    high = f(last.get("h"))
    low = f(last.get("l"))
    vol = f(last.get("v"))

    e8 = ema(closes, 8)
    e21 = ema(closes, min(21, len(closes)))
    vw = m.vwap or vwap_from_bars(bars) or e21

    avgvol = sum(vols[-8:-1]) / max(1, len(vols[-8:-1]))
    vol_ok = vol >= avgvol * 1.10 if avgvol else True

    if not no_chase(m, direction):
        return "EXTENDED - DO NOT ENTER", "Wait for pullback toward EMA21/VWAP.", ["daily price extended from EMA21"]

    if direction == "CALL":
        if close >= vw and close >= e8 and low <= max(vw, e8) * 1.006 and vol_ok:
            return "READY - SNIPER PULLBACK CONFIRMED", f"5-min close above VWAP/EMA8 near {rp(close)}", ["5-min pullback held", "VWAP/EMA8 reclaimed", "volume confirmed"]
        if close > max(e8, e21, vw) and close >= high * 0.995 and vol_ok:
            return "READY - SNIPER BREAKOUT CONFIRMED", f"5-min breakout close near {rp(close)}", ["5-min breakout confirmed", "volume expansion"]
        return "WAIT - WATCH FOR 5-MIN CLOSE ABOVE VWAP/EMA8", f"Trigger above {rp(max(vw, e8))}", ["waiting on bullish sniper candle"]

    if close <= vw and close <= e8 and high >= min(vw, e8) * 0.994 and vol_ok:
        return "READY - SNIPER PUTBACK CONFIRMED", f"5-min close below VWAP/EMA8 near {rp(close)}", ["5-min retest rejected", "VWAP/EMA8 lost", "volume confirmed"]
    if close < min(e8, e21, vw) and close <= low * 1.005 and vol_ok:
        return "READY - SNIPER BREAKDOWN CONFIRMED", f"5-min breakdown close near {rp(close)}", ["5-min breakdown confirmed", "volume expansion"]
    return "WAIT - WATCH FOR 5-MIN CLOSE BELOW VWAP/EMA8", f"Trigger below {rp(min(vw, e8))}", ["waiting on bearish sniper candle"]


def confirmation_gate(status: str, strategy: str, direction: str, m: Metrics, bars: List[Dict[str, Any]]) -> Tuple[str, str, str, str]:
    """
    Final entry gate. It blocks trades until the setup has a confirming candle.
    Dashboard can show A+ watchlist ideas, but alerts only fire when TRADE ALLOWED.
    """
    if not is_market_open():
        return status, "WAIT", "Market closed. Plan only; no entries after-hours/premarket.", "No live market confirmation."

    if not execution_window(strategy):
        return status, "WAIT", "Outside approved option-entry window.", "Wait for 9:45 ET confirmation window."

    ready_statuses = {
        "READY - SNIPER PULLBACK CONFIRMED",
        "READY - SNIPER BREAKOUT CONFIRMED",
        "READY - SNIPER PUTBACK CONFIRMED",
        "READY - SNIPER BREAKDOWN CONFIRMED",
        "RE-ENTRY READY",
    }

    if status not in ready_statuses:
        return status, "DO NOT TRADE", "No sniper confirmation yet.", "Wait for 5-min VWAP/EMA8 confirmation with volume."

    if len(bars) < 8:
        return "WAIT - NEED MORE INTRADAY BARS", "DO NOT TRADE", "Not enough 5-min bars to validate entry.", "Wait for more market structure."

    closes = [f(b.get("c")) for b in bars]
    vols = [f(b.get("v")) for b in bars]
    last = bars[-1]

    close = f(last.get("c"))
    open_ = f(last.get("o"))
    high = f(last.get("h"))
    low = f(last.get("l"))
    vol = f(last.get("v"))

    e8 = ema(closes, 8)
    e21 = ema(closes, min(21, len(closes)))
    vw = m.vwap or vwap_from_bars(bars) or e21

    avgvol = sum(vols[-8:-1]) / max(1, len(vols[-8:-1]))
    vol_ok = vol >= avgvol * 1.10 if avgvol else True

    candle_body = abs(close - open_)
    candle_range = max(high - low, 0.01)
    strong_body = candle_body / candle_range >= 0.45

    if direction == "CALL":
        trigger = f"ENTER only after 5-min candle closes above VWAP/EMA8 ({rp(max(vw, e8))}) with strong body + volume."
        if close >= max(vw, e8) and strong_body and vol_ok and no_chase(m, "CALL"):
            return status, "TRADE ALLOWED", trigger, "Confirmed: VWAP/EMA8 reclaim + strong candle + volume."
        return "WAIT - CONFIRMATION NOT COMPLETE", "DO NOT TRADE", trigger, "Needs close above VWAP/EMA8, strong candle body, and volume."

    trigger = f"ENTER PUT only after 5-min candle closes below VWAP/EMA8 ({rp(min(vw, e8))}) with strong body + volume."
    if close <= min(vw, e8) and strong_body and vol_ok and no_chase(m, "PUT"):
        return status, "TRADE ALLOWED", trigger, "Confirmed: VWAP/EMA8 rejection + strong candle + volume."
    return "WAIT - CONFIRMATION NOT COMPLETE", "DO NOT TRADE", trigger, "Needs close below VWAP/EMA8, strong candle body, and volume."


# =========================
# OPTIONS
# =========================

def option_mid(opt: Dict[str, Any]) -> Optional[float]:
    q = opt.get("last_quote") or {}
    bid = q.get("bid")
    ask = q.get("ask")
    if bid is not None and ask is not None and f(ask) > 0:
        return (f(bid) + f(ask)) / 2
    t = opt.get("last_trade") or {}
    if t.get("price") is not None:
        return f(t.get("price"))
    return None


def option_liquidity(opt: Dict[str, Any], midprice: float, strategy: str) -> Tuple[bool, Optional[float], Optional[int], Optional[int], str]:
    q = opt.get("last_quote") or {}
    bid = f(q.get("bid"))
    ask = f(q.get("ask"))

    spread_pct = ((ask - bid) / midprice) if ask > 0 and bid > 0 and midprice > 0 else None

    day = opt.get("day") or {}
    vol_raw = day.get("volume")
    oi_raw = opt.get("open_interest")

    volume = int(vol_raw) if vol_raw is not None else None
    open_interest = int(oi_raw) if oi_raw is not None else None

    max_spread = 0.18 if strategy == "0DTE" else 0.25

    ok = (
        (spread_pct is None or spread_pct <= max_spread)
        and (open_interest is None or open_interest >= (100 if strategy == "LEAP" else 250))
        and (volume is None or volume >= (1 if strategy == "LEAP" else 10))
    )

    note = "liquidity ok" if ok else f"liquidity warning: spread={spread_pct}, volume={volume}, open_interest={open_interest}"
    return ok, (round(spread_pct, 3) if spread_pct is not None else None), volume, open_interest, note


def choose_option(client: Polygon, ticker: str, direction: str, strategy: str, price: float) -> Optional[OptionPick]:
    if strategy == "0DTE":
        min_dte, max_dte, stop_pct = 0, 1, 0.45
    elif strategy == "LEAP":
        min_dte, max_dte, stop_pct = 120, 365, 0.30
    else:
        min_dte, max_dte, stop_pct = 7, 30, 0.35

    chain = client.options(ticker, direction, min_dte, max_dte, price)
    candidates: List[Tuple[float, Dict[str, Any], float, bool, Optional[float], Optional[int], Optional[int], str]] = []

    for opt in chain:
        details = opt.get("details") or {}
        strike = f(details.get("strike_price"))
        mid = option_mid(opt)

        if not strike or not mid:
            continue

        ok, spread, volume, oi, note = option_liquidity(opt, mid, strategy)

        # Prefer near-ATM/ITM-ish strikes, but penalize poor liquidity.
        distance_penalty = abs(strike - price) / max(price, 1)
        liquidity_penalty = 0 if ok else 0.25
        penalty = distance_penalty + liquidity_penalty

        candidates.append((penalty, opt, mid, ok, spread, volume, oi, note))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0])
    _, opt, mid, ok, spread, volume, oi, note = candidates[0]

    details = opt.get("details") or {}
    expiration = details.get("expiration_date") or ""
    strike = f(details.get("strike_price"))

    try:
        dte = max(0, (datetime.fromisoformat(expiration).date() - now_et().date()).days)
    except Exception:
        dte = max_dte

    risk_per_contract = mid * 100 * stop_pct
    max_contracts = max(1, int(MAX_RISK_PER_TRADE // risk_per_contract)) if risk_per_contract > 0 else 1

    return OptionPick(
        contract=details.get("ticker") or f"{ticker} {strike}{direction[0]}",
        expiration=expiration,
        strike=strike,
        option_type=direction,
        dte=dte,
        estimated_entry=rp(mid),
        stop_pct=stop_pct,
        risk_per_contract=rp(risk_per_contract),
        max_contracts=max_contracts,
        spread_pct=spread,
        volume=volume,
        open_interest=oi,
        liquidity_ok=ok,
        liquidity_note=note,
    )


# =========================
# POSITION SIZING
# =========================

def confidence_sizing(score: int, strategy: str, option: Optional[OptionPick]) -> Tuple[int, int, float, str]:
    """
    Confidence-based sizing:
    92+ = full allowed risk
    88-91 = 70%
    85-87 = 50%
    0DTE capped at 50% until the system proves itself.
    """
    if score >= 92:
        pct = 100
    elif score >= 88:
        pct = 70
    elif score >= 85:
        pct = 50
    else:
        pct = 0

    if strategy == "0DTE":
        pct = min(pct, 50)

    if not option or option.max_contracts <= 0:
        return pct, 0, 0.0, "No position until a liquid option contract is available."

    contracts = max(1, int(option.max_contracts * pct / 100)) if pct > 0 else 0
    contracts = min(contracts, option.max_contracts)

    used_risk = rp(option.risk_per_contract * contracts)
    plan = (
        f"Confidence size: {pct}% of allowed risk | "
        f"Recommended: {contracts} contract(s) | "
        f"Estimated risk: ${used_risk} of ${MAX_RISK_PER_TRADE} max. "
        f"Scale plan: 50% at fast profit, 30% at Target 1, 20% runner when contract count allows."
    )

    return pct, contracts, used_risk, plan


# =========================
# EXIT ENGINE
# =========================

def smart_exit_engine(strategy: str, direction: str, metrics: Optional[Metrics] = None) -> Dict[str, Any]:
    rel_volume = metrics.rel_volume if metrics else 1.0
    r = metrics.rsi if metrics else 50.0
    price = metrics.price if metrics else 0.0
    e8 = metrics.ema8 if metrics else 0.0

    strong_momentum = (
        rel_volume >= 1.5
        and (
            (direction == "CALL" and r >= 58 and price >= e8)
            or (direction == "PUT" and r <= 42 and price <= e8)
        )
    )

    if strategy == "0DTE":
        target2 = "+80% to +100% option gain - only if trend acceleration stays clean" if strong_momentum else "+45% to +55% option gain - lock most gains"
        runner = "Runner trails 5-min EMA8/VWAP; exit on first strong reversal candle" if strong_momentum else "No runner unless price holds VWAP/EMA8 after Target 2"
        return {
            "stop_loss": "Adaptive stop: early failure -10% to -15%; hard stop option -25% to -30% OR failed 5-min VWAP/EMA8 hold",
            "targets": [
                "Fast Profit: +20% option within 30-60 min - trim/protect immediately",
                "Target 1: +25% to +30% option - protect capital",
                f"Target 2: {target2}",
                "Hard exit: 3:30 PM ET",
            ],
            "target_1": "+25% to +30% option gain - trim/protect",
            "target_2": target2,
            "runner_rule": runner,
            "time_stop": "No follow-through after 2-3 five-minute candles = exit/reduce; hard flat by 3:30 PM ET",
            "profit_protection": "If +20% hits quickly, trim/protect and move stop near breakeven; never let a green 0DTE winner turn red",
            "exit_plan": "Adaptive 0DTE exit: take fast money, cut failed entries early, only hold runners during clean momentum.",
            "exit_checklist": [
                "Fast profit: +20% in 30-60 min = trim/protect",
                "Early failure: no follow-through in 2-3 candles = exit -5% to -10% if possible",
                "Technical failure: two rejections at VWAP/EMA8 = exit",
                "Hard stop: option -25% to -30%",
                "Target 2 expands only when volume and trend remain strong",
                "Flat by 3:30 PM ET",
            ],
        }

    if strategy == "LEAP":
        target2 = "+90% to +120% option gain - trend expansion target" if strong_momentum else "+60% to +75% option gain - lock majority"
        runner = "Trail runner under EMA21 while strong; switch to EMA50 on deeper long-term hold" if strong_momentum else "Runner only while daily trend holds EMA21/EMA50"
        return {
            "stop_loss": "Adaptive stop: early thesis failure -10% to -15%; hard stop option -30% OR stock loses EMA200 / long-term thesis breaks",
            "targets": [
                "Fast Profit: +20% option if achieved quickly - protect/trim, especially if market is choppy",
                "Target 1: +35% option - protect capital",
                f"Target 2: {target2}",
                "Runner: long-term hold only if daily trend remains intact",
            ],
            "target_1": "+35% option gain - protect capital / reduce risk",
            "target_2": target2,
            "runner_rule": runner,
            "time_stop": "If thesis does not improve within 2-3 weeks, reassess or exit; if entry fails within 2-3 daily candles, reduce early",
            "profit_protection": "At +35%, protect principal or move stop to breakeven; at fast +20%, consider trimming if the move is news/gap driven",
            "exit_plan": "Adaptive LEAP exit: protect principal early, expand targets only when trend/volume confirm, cut failed thesis before full stop.",
            "exit_checklist": [
                "Fast profit: +20% quickly = trim/protect if move is extended",
                "Early failure: 2-3 daily candles fail to hold EMA21/entry zone = reduce/exit early",
                "Technical failure: two clear EMA21/EMA50 rejections = exit/reassess",
                "Hard stop: option -30% or stock loses EMA200",
                "Target 2 expands to +90%-120% only in strong momentum",
                "Runner requires intact daily/weekly trend",
            ],
        }

    target2 = "+80% to +120% option gain - strong trend target" if strong_momentum else "+60% to +70% option gain - lock majority"
    runner = "Trail under EMA8 while strong; widen to EMA21 only after Target 2" if strong_momentum else "Runner only while daily trend holds EMA21"
    return {
        "stop_loss": "Adaptive stop: early failure -10% to -15%; hard stop option -30% to -35% OR daily close loses EMA21/EMA50 support",
        "targets": [
            "Fast Profit: +20% option within 30-60 min - trim/protect 25%-50%",
            "Target 1: +35% option - protect capital",
            f"Target 2: {target2}",
            "Runner: trail only if trend keeps confirming",
        ],
        "target_1": "+35% option gain - trim/protect and move stop near breakeven",
        "target_2": target2,
        "runner_rule": runner,
        "time_stop": "If trade does not move in 2-3 candles/sessions, exit or reduce before full stop",
        "profit_protection": "If +20% hits quickly, trim/protect; at +35%, move stop near breakeven; never let winner turn red",
        "exit_plan": "Adaptive swing exit: take fast profits when offered, cut no-follow-through entries early, expand targets only in strong momentum.",
        "exit_checklist": [
            "Fast profit: +20% in 30-60 min = trim/protect",
            "No follow-through: 2-3 candles/sessions without progress = exit/reduce",
            "Failure exit: two EMA21 rejections = exit early -10% to -15% if possible",
            "Hard stop: option -30% to -35%",
            "Target 2 expands only with strong volume/trend",
            "Runner trails EMA8/EMA21 depending on strength",
        ],
    }


# =========================
# IDEA BUILDER
# =========================

def make_idea(client: Polygon, m: Metrics, bars: List[Dict[str, Any]], strategy: str) -> Optional[Idea]:
    if strategy == "0DTE":
        score, direction, reasons = score_0dte(m, bars)
        trader_type = "0DTE"
        strategy_name = "SPY/QQQ opening range sniper"
    elif strategy == "LEAP":
        score, direction, reasons = score_leap(m)
        trader_type = "LEAP"
        strategy_name = "Long-term trend pullback"
    else:
        score, direction, reasons = score_swing(m)
        trader_type = "SWING"
        strategy_name = "Pullback / momentum continuation"

    if not direction or score < 85:
        return None

    status, sniper_trigger, sniper_notes = sniper_status(m, bars, direction, strategy)
    opt = choose_option(client, m.ticker, direction, strategy, m.price)

    if opt and not opt.liquidity_ok and status.startswith("READY"):
        status = "WAIT - OPTION LIQUIDITY WARNING"

    status, trade_permission, confirmation_trigger, no_trade_reason = confirmation_gate(status, strategy, direction, m, bars)

    confidence_pct, recommended_contracts, used_risk, position_plan = confidence_sizing(score, strategy, opt)
    if trade_permission != "TRADE ALLOWED":
        recommended_contracts = 0
        used_risk = 0.0

    if direction == "CALL":
        low = m.ema21 * 0.995
        high = m.ema21 * 1.015
    else:
        low = m.ema21 * 0.985
        high = m.ema21 * 1.005

    exit_rules = smart_exit_engine(strategy, direction, m)

    notes = list(reasons) + list(sniper_notes)
    if opt:
        notes.append(opt.liquidity_note)
    else:
        notes.append("option unavailable")

    return Idea(
        ticker=m.ticker,
        grade=grade(score),
        score=score,
        trader_type=trader_type,
        strategy=strategy_name,
        direction=direction,
        status=status,
        trade_permission=trade_permission,
        confirmation_trigger=confirmation_trigger,
        no_trade_reason=no_trade_reason,
        sniper_trigger=sniper_trigger,
        entry_zone=f"Daily pullback zone near EMA21: {rp(m.ema21)}",
        entry_range=f"{rp(min(low, high))} - {rp(max(low, high))}",
        option_contract=opt.contract if opt else f"{m.ticker} {direction} contract unavailable",
        estimated_option_entry=opt.estimated_entry if opt else None,
        dte=opt.dte if opt else None,
        max_contracts=opt.max_contracts if opt else 0,
        recommended_contracts=recommended_contracts,
        confidence_size_pct=confidence_pct,
        max_risk=used_risk,
        position_plan=position_plan,
        exit_plan=exit_rules["exit_plan"],
        stop_loss=exit_rules["stop_loss"],
        targets=exit_rules["targets"],
        target_1=exit_rules["target_1"],
        target_2=exit_rules["target_2"],
        runner_rule=exit_rules["runner_rule"],
        time_stop=exit_rules["time_stop"],
        profit_protection=exit_rules["profit_protection"],
        exit_checklist=exit_rules["exit_checklist"],
        price=rp(m.price),
        rsi=rp(m.rsi),
        rel_volume=round(m.rel_volume, 2),
        notes=notes,
    )


def classify_reentry(idea: Idea, m: Metrics, bars: List[Dict[str, Any]]) -> Idea:
    if idea.status.startswith("READY") or not execution_window(idea.trader_type) or len(bars) < 12:
        return idea

    closes = [f(b.get("c")) for b in bars]
    close = closes[-1]
    e8 = ema(closes, 8)
    vw = m.vwap or vwap_from_bars(bars) or e8

    if idea.direction == "CALL" and close >= max(vw, e8) and no_chase(m, "CALL", 0.045):
        idea.status = "RE-ENTRY READY"
        idea.sniper_trigger = f"Re-entry: 5-min reclaim above VWAP/EMA8 near {rp(close)}"
        idea.notes.append("re-entry confirmed")

    if idea.direction == "PUT" and close <= min(vw, e8) and no_chase(m, "PUT", 0.045):
        idea.status = "RE-ENTRY READY"
        idea.sniper_trigger = f"Re-entry: 5-min rejection below VWAP/EMA8 near {rp(close)}"
        idea.notes.append("re-entry confirmed")

    # Re-check permission after re-entry changes.
    new_status, permission, confirmation, reason = confirmation_gate(idea.status, idea.trader_type, idea.direction, m, bars)
    idea.status = new_status
    idea.trade_permission = permission
    idea.confirmation_trigger = confirmation
    idea.no_trade_reason = reason

    if permission == "TRADE ALLOWED":
        # keep previously calculated recommendation
        if idea.recommended_contracts == 0 and idea.max_contracts > 0:
            rec = max(1, int(idea.max_contracts * idea.confidence_size_pct / 100))
            idea.recommended_contracts = min(rec, idea.max_contracts)
    else:
        idea.recommended_contracts = 0
        idea.max_risk = 0.0

    return idea


# =========================
# ALERTS / DASHBOARD
# =========================

def load_cache() -> set:
    try:
        with open(ALERT_CACHE_FILE, "r", encoding="utf-8") as fh:
            return set(json.load(fh))
    except Exception:
        return set()


def save_cache(cache: set) -> None:
    with open(ALERT_CACHE_FILE, "w", encoding="utf-8") as fh:
        json.dump(sorted(cache), fh)


def alert_key(idea: Idea) -> str:
    return f"{today_key()}:{idea.ticker}:{idea.trader_type}:{idea.direction}:{idea.status}:{idea.option_contract}"


def send_telegram(text: str) -> bool:
    if not SEND_TELEGRAM or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=10,
        )
        if r.status_code < 400:
            log("Telegram alert sent")
            return True
        log(f"Telegram failed HTTP {r.status_code}: {r.text[:160]}")
        return False
    except Exception as e:
        log(f"Telegram error: {e}")
        return False


def send_alerts(ideas: List[Idea]) -> None:
    if not is_market_open():
        log("Market not open. Telegram alerts suppressed; dashboard updated only.")
        return

    allowed_statuses = {
        "READY - SNIPER PULLBACK CONFIRMED",
        "READY - SNIPER BREAKOUT CONFIRMED",
        "READY - SNIPER PUTBACK CONFIRMED",
        "READY - SNIPER BREAKDOWN CONFIRMED",
        "RE-ENTRY READY",
    }

    cache = load_cache()
    changed = False

    for idea in ideas:
        if idea.grade != "A+":
            continue
        if idea.status not in allowed_statuses:
            continue
        if idea.trade_permission != "TRADE ALLOWED":
            continue
        if idea.recommended_contracts <= 0:
            continue

        key = alert_key(idea)
        if key in cache:
            continue

        text = (
            f"🔥 APEX A+ {idea.trader_type} ALERT\n"
            f"Ticker: {idea.ticker}\n"
            f"Direction: {idea.direction}\n"
            f"Status: {idea.status}\n"
            f"Permission: {idea.trade_permission}\n"
            f"Trigger: {idea.confirmation_trigger}\n"
            f"Entry Range: {idea.entry_range}\n"
            f"Option: {idea.option_contract}\n"
            f"Est Entry: {idea.estimated_option_entry}\n"
            f"Recommended Contracts: {idea.recommended_contracts}\n"
            f"Confidence Size: {idea.confidence_size_pct}%\n"
            f"Risk: ${idea.max_risk}\n"
            f"Stop: {idea.stop_loss}\n"
            f"Targets: {', '.join(idea.targets)}"
        )

        if send_telegram(text):
            cache.add(key)
            changed = True

    if changed:
        save_cache(cache)


def push_github(payload: Dict[str, Any]) -> None:
    if not GITHUB_TOKEN or not GITHUB_REPO:
        log("GitHub dashboard push not configured.")
        return

    api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_DASHBOARD_PATH}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

    try:
        old = requests.get(api, headers=headers, params={"ref": GITHUB_BRANCH}, timeout=12)
        sha = old.json().get("sha") if old.status_code == 200 else None

        body = {
            "message": f"Update dashboard {payload.get('updated_at')}",
            "content": base64.b64encode(json.dumps(payload, indent=2).encode()).decode(),
            "branch": GITHUB_BRANCH,
        }
        if sha:
            body["sha"] = sha

        r = requests.put(api, headers=headers, json=body, timeout=15)

        if r.status_code in (200, 201):
            log(f"Dashboard pushed to GitHub: {GITHUB_REPO}/{GITHUB_DASHBOARD_PATH}")
        else:
            log(f"GitHub push failed HTTP {r.status_code}: {r.text[:220]}")
    except Exception as e:
        log(f"GitHub push error: {e}")


# =========================
# MAIN SCAN
# =========================

def run_scan() -> int:
    log("Apex Engine v2.3 starting — Position Sizing + Confirmation Triggers active, Polygon-only, Benzinga disabled.")
    log(f"Session: {session_name()} | Account size: {ACCOUNT_SIZE} | Max risk/trade: {MAX_RISK_PER_TRADE}")

    client = Polygon(POLYGON_API_KEY)
    ideas: List[Idea] = []

    for ticker in TICKERS:
        log(f"Scanning {ticker}...")
        metrics, bars = build_metrics(client, ticker)
        if not metrics:
            continue

        strategy_order = ["0DTE", "SWING", "LEAP"] if ticker in ZERO_DTE_TICKERS else ["SWING", "LEAP"]

        best: Optional[Idea] = None
        for strategy in strategy_order:
            idea = make_idea(client, metrics, bars, strategy)
            if not idea:
                continue
            idea = classify_reentry(idea, metrics, bars)
            if not best or idea.score > best.score:
                best = idea

        if best:
            ideas.append(best)
            log(
                f"{best.grade} {best.ticker} {best.trader_type} {best.direction} "
                f"{best.status} permission={best.trade_permission} score={best.score} "
                f"rec_contracts={best.recommended_contracts} option={best.option_contract}"
            )

    ideas.sort(
        key=lambda x: (
            x.trade_permission == "TRADE ALLOWED",
            x.status.startswith("READY") or x.status == "RE-ENTRY READY",
            x.score,
        ),
        reverse=True,
    )

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "POLYGON_ONLY_BENZINGA_DISABLED_V2_3_POSITION_CONFIRMATION",
        "session": session_name(),
        "account_size": ACCOUNT_SIZE,
        "max_risk_per_trade": MAX_RISK_PER_TRADE,
        "ideas": [asdict(i) for i in ideas],
    }

    with open(DASHBOARD_FILE, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    push_github(payload)
    send_alerts(ideas)

    log(f"Scan complete. Qualified ideas: {len(ideas)}")
    return 0


if __name__ == "__main__":
    sys.exit(run_scan())
