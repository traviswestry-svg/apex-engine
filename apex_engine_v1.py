#!/usr/bin/env python3
"""
APEX ENGINE v1.7
Polygon-only multi-strategy options scanner with:
- Open Confirmation Engine
- Option liquidity/spread filter
- SPY/QQQ 0DTE sniper mode
- Swing + LEAP scanner
- Re-entry engine
- Telegram A+ alerts only
- Dashboard JSON + optional GitHub push for Netlify
- Benzinga disabled
"""
from __future__ import annotations

import base64
import json
import math
import os
import statistics
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone, date, time
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests

# =============================
# CONFIG
# =============================
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

ACCOUNT_SIZE = float(os.getenv("ACCOUNT_SIZE", "60000"))
MAX_RISK_PER_TRADE = float(os.getenv("MAX_RISK_PER_TRADE", "750"))
SEND_TELEGRAM = os.getenv("SEND_TELEGRAM", "true").lower() == "true"

DASHBOARD_FILE = os.getenv("DASHBOARD_FILE", "dashboard.json")
ALERT_CACHE_FILE = os.getenv("ALERT_CACHE_FILE", "sent_alerts.json")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "12"))

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.getenv("GITHUB_REPO", "").strip()
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main").strip()
GITHUB_DASHBOARD_PATH = os.getenv("GITHUB_DASHBOARD_PATH", "dashboard.json").strip()

POLYGON_BASE = "https://api.polygon.io"
EASTERN = ZoneInfo("America/New_York")

TICKERS = [
    "SPY", "QQQ", "SPX", "NVDA", "TSLA", "META", "MSFT", "AAPL",
    "AMZN", "COIN", "AMD", "NFLX", "PLTR", "SMH", "QCOM", "NBIS"
]
ZERO_DTE_TICKERS = {"SPY", "QQQ"}

# Open-confirmation guards
SWING_CONFIRM_TIME = time(9, 35)
ZERO_DTE_START_TIME = time(9, 45)
ZERO_DTE_END_TIME = time(15, 30)

# Liquidity gates
LIQUIDITY_RULES = {
    "0DTE": {"max_spread": 0.12, "min_oi": 500, "min_vol": 50},
    "SWING": {"max_spread": 0.15, "min_oi": 300, "min_vol": 10},
    "LEAP": {"max_spread": 0.20, "min_oi": 100, "min_vol": 0},
}

# =============================
# MODELS
# =============================
@dataclass
class TradeIdea:
    ticker: str
    grade: str
    score: float
    trader_type: str
    strategy: str
    direction: str
    status: str
    entry_zone: str
    exit_plan: str
    stop_loss: str
    targets: List[str]
    option_contract: str
    estimated_option_entry: float
    dte: int
    max_contracts: int
    max_risk: float
    price: float
    rsi: float
    rel_volume: float
    market_session: str
    liquidity_status: str
    notes: List[str]
    timestamp: str

# =============================
# UTILITIES
# =============================
def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def now_et() -> datetime:
    return datetime.now(EASTERN)


def market_session() -> str:
    n = now_et()
    if n.weekday() >= 5:
        return "CLOSED_WEEKEND"
    if n.time() < time(9, 30):
        return "PREMARKET"
    if n.time() <= time(16, 0):
        return "MARKET_OPEN"
    return "AFTER_HOURS"


def is_market_open() -> bool:
    return market_session() == "MARKET_OPEN"


def can_confirm_swing() -> bool:
    n = now_et()
    return is_market_open() and n.time() >= SWING_CONFIRM_TIME


def can_confirm_zero_dte() -> bool:
    n = now_et()
    return is_market_open() and ZERO_DTE_START_TIME <= n.time() <= ZERO_DTE_END_TIME


def log(msg: str) -> None:
    print(msg, flush=True)


def load_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: str, data: Any) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log(f"Could not save {path}: {e}")


def polygon_get(path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if params is None:
        params = {}
    if not POLYGON_API_KEY:
        return None
    safe_path = path
    params["apiKey"] = POLYGON_API_KEY
    try:
        r = requests.get(f"{POLYGON_BASE}{path}", params=params, timeout=REQUEST_TIMEOUT)
        if r.status_code in (401, 403):
            log(f"Polygon not authorized for {safe_path}. Skipping.")
            return None
        if r.status_code == 404:
            log(f"Polygon 404 for {safe_path}. Skipping.")
            return None
        if r.status_code >= 400:
            log(f"Polygon HTTP {r.status_code} for {safe_path}: {r.text[:160]}")
            return None
        return r.json()
    except requests.exceptions.Timeout:
        log(f"Polygon timeout for {safe_path}. Skipping.")
        return None
    except Exception as e:
        log(f"Polygon request failed for {safe_path}: {e}")
        return None

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
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def rsi(values: List[float], period: int = 14) -> float:
    if len(values) <= period:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(values)):
        ch = values[i] - values[i - 1]
        gains.append(max(ch, 0))
        losses.append(abs(min(ch, 0)))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(bars: List[Dict[str, Any]], period: int = 14) -> float:
    if len(bars) < 2:
        return 0.0
    trs = []
    for i in range(1, len(bars)):
        h = float(bars[i]["h"])
        l = float(bars[i]["l"])
        pc = float(bars[i-1]["c"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-period:]) / min(period, len(trs)) if trs else 0.0

# =============================
# DATA FETCH
# =============================
def get_daily_bars(ticker: str, days: int = 260) -> List[Dict[str, Any]]:
    end = today_utc()
    start = end - timedelta(days=420)
    data = polygon_get(
        f"/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}",
        {"adjusted": "true", "sort": "asc", "limit": 5000},
    )
    bars = data.get("results", []) if data else []
    return bars[-days:]


def get_intraday_bars(ticker: str) -> List[Dict[str, Any]]:
    end = today_utc()
    start = end - timedelta(days=5)
    data = polygon_get(
        f"/v2/aggs/ticker/{ticker}/range/5/minute/{start}/{end}",
        {"adjusted": "true", "sort": "asc", "limit": 5000},
    )
    return data.get("results", []) if data else []

# =============================
# OPTIONS
# =============================
def expiration_for_dte(target_dte: int) -> str:
    return (today_utc() + timedelta(days=target_dte)).isoformat()


def contract_type_for_direction(direction: str) -> str:
    return "call" if direction.upper() == "CALL" else "put"


def option_mid_price(snapshot: Optional[Dict[str, Any]]) -> float:
    if not snapshot:
        return 0.0
    quote = snapshot.get("last_quote") or {}
    bid = float(quote.get("bid", 0) or 0)
    ask = float(quote.get("ask", 0) or 0)
    if bid > 0 and ask > 0:
        return round((bid + ask) / 2, 2)
    trade = snapshot.get("last_trade") or {}
    return round(float(trade.get("price", 0) or 0), 2)


def option_liquidity(snapshot: Optional[Dict[str, Any]], trader_type: str) -> Tuple[bool, str]:
    if not snapshot:
        return False, "NO OPTION SNAPSHOT"
    quote = snapshot.get("last_quote") or {}
    bid = float(quote.get("bid", 0) or 0)
    ask = float(quote.get("ask", 0) or 0)
    mid = (bid + ask) / 2 if bid > 0 and ask > 0 else 0
    spread_pct = ((ask - bid) / mid) if mid > 0 else 9.99
    oi = int(snapshot.get("open_interest") or 0)
    day = snapshot.get("day") or {}
    vol = int(day.get("volume") or 0)
    rule = LIQUIDITY_RULES.get(trader_type, LIQUIDITY_RULES["SWING"])
    ok = bid > 0 and ask > 0 and spread_pct <= rule["max_spread"] and oi >= rule["min_oi"] and vol >= rule["min_vol"]
    return ok, f"spread={round(spread_pct*100,1)}%, OI={oi}, vol={vol}, bid={bid}, ask={ask}"


def option_symbol(snapshot: Optional[Dict[str, Any]], ticker: str, direction: str, dte: int, price: float) -> str:
    if not snapshot:
        strike = round(price / 5) * 5
        return f"{ticker} {strike}{'C' if direction == 'CALL' else 'P'} {dte}DTE APPROX"
    details = snapshot.get("details", {})
    sym = details.get("ticker") or ""
    strike = details.get("strike_price", "?")
    exp = details.get("expiration_date", "?")
    typ = details.get("contract_type", direction.lower())
    return f"{sym or ticker} {exp} {strike} {typ.upper()}"


def get_option_snapshot(ticker: str, direction: str, target_dte: int, underlying_price: float, trader_type: str) -> Optional[Dict[str, Any]]:
    exp = expiration_for_dte(target_dte)
    contract_type = contract_type_for_direction(direction)
    params = {
        "contract_type": contract_type,
        "expiration_date": exp,
        "limit": 80,
        "sort": "details.strike_price",
    }
    data = polygon_get(f"/v3/snapshot/options/{ticker}", params)
    if not data or not data.get("results"):
        return None
    options = data["results"]

    def strike(o: Dict[str, Any]) -> float:
        return float(o.get("details", {}).get("strike_price") or 0)

    if direction.upper() == "CALL":
        candidates = [o for o in options if strike(o) >= underlying_price * 0.97]
    else:
        candidates = [o for o in options if strike(o) <= underlying_price * 1.03]
    candidates = candidates or options

    liquid = [o for o in candidates if option_liquidity(o, trader_type)[0]]
    pool = liquid or candidates
    return min(pool, key=lambda o: abs(strike(o) - underlying_price))


def size_position(opt_price: float, stop_pct: float) -> Tuple[int, float]:
    risk_per_contract = opt_price * 100 * stop_pct
    if risk_per_contract <= 0:
        return 0, 0.0
    contracts = math.floor(MAX_RISK_PER_TRADE / risk_per_contract)
    contracts = max(1, contracts)
    return contracts, round(contracts * risk_per_contract, 2)

# =============================
# STRATEGY LOGIC
# =============================
def grade(score: float) -> str:
    if score >= 88:
        return "A+"
    if score >= 78:
        return "A"
    if score >= 70:
        return "B+"
    return "B"


def apply_guards(idea: TradeIdea, liquidity_ok: bool) -> TradeIdea:
    sess = market_session()
    idea.market_session = sess
    if not liquidity_ok:
        idea.status = "WAIT - OPTION LIQUIDITY"
        idea.notes.append("Option liquidity filter did not pass. Do not force the fill.")
    if sess != "MARKET_OPEN":
        idea.status = "WATCHLIST - OPEN CONFIRMATION NEEDED"
        idea.entry_zone = "Pending open confirmation - do not use after-hours price as exact entry"
        idea.notes.append("After-hours/premarket guard active: exact entries and option prices are not trusted.")
    elif idea.trader_type == "SWING" and not can_confirm_swing() and idea.status == "READY":
        idea.status = "WAIT - OPEN CONFIRMATION"
        idea.notes.append("Swing confirmation delayed until after 9:35 ET.")
    elif idea.trader_type == "0DTE" and not can_confirm_zero_dte():
        idea.status = "WAIT - 0DTE CONFIRMATION WINDOW"
        idea.notes.append("0DTE sniper disabled until 9:45 ET and stopped after 3:30 ET.")
    return idea


def classify_swing(ticker: str, bars: List[Dict[str, Any]]) -> Optional[TradeIdea]:
    closes = [float(b["c"]) for b in bars]
    vols = [float(b.get("v", 0)) for b in bars]
    if len(closes) < 60:
        return None
    price = closes[-1]
    ema8, ema21, ema50 = ema(closes, 8), ema(closes, 21), ema(closes, 50)
    rs = rsi(closes)
    avgv = statistics.mean(vols[-30:-1]) if len(vols) > 31 else max(vols[-1], 1)
    rv = round(vols[-1] / avgv, 2) if avgv else 1.0
    at = atr(bars)

    direction = "CALL" if price > ema50 else "PUT"
    score = 0
    notes: List[str] = []
    if direction == "CALL" and price > ema21 > ema50:
        score += 24; notes.append("Bull trend: price above EMA21/EMA50")
    if direction == "PUT" and price < ema21 < ema50:
        score += 24; notes.append("Bear trend: price below EMA21/EMA50")
    if abs(price - ema21) / price <= 0.025:
        score += 24; notes.append("Entry near EMA21 pullback zone")
    elif abs(price - ema50) / price <= 0.025:
        score += 18; notes.append("Entry near EMA50 pullback zone")
    if 45 <= rs <= 66:
        score += 16; notes.append("RSI reset / controlled momentum")
    if rv >= 1.15:
        score += 14; notes.append("Relative volume expansion")
    if price > ema8 and direction == "CALL":
        score += 10; notes.append("Short-term momentum confirmation")
    if price < ema8 and direction == "PUT":
        score += 10; notes.append("Short-term bearish confirmation")
    score = min(score, 100)
    if grade(score) != "A+":
        return None

    status = "READY" if abs(price - ema21) / price <= 0.012 else "WAIT"
    if status == "WAIT":
        notes.append("A+ watchlist only: wait for price to touch entry zone")

    dte = 14
    snap = get_option_snapshot(ticker, direction, dte, price, "SWING")
    liq_ok, liq_status = option_liquidity(snap, "SWING")
    opt_price = option_mid_price(snap) or max(round(price * 0.025, 2), 0.5)
    contracts, max_risk = size_position(opt_price, 0.35)
    zone_low = round(min(ema21, price) - at * 0.15, 2)
    zone_high = round(max(ema21, price) + at * 0.15, 2)

    idea = TradeIdea(
        ticker=ticker, grade="A+", score=score, trader_type="SWING", strategy="EMA21 pullback continuation",
        direction=direction, status=status, entry_zone=f"{zone_low} - {zone_high}",
        exit_plan="Scale at +35% / +70%; close if trend fails", stop_loss="Option -35% or stock closes beyond EMA21/EMA50 zone",
        targets=["+35% option", "+70% option", "trail runner if momentum expands"],
        option_contract=option_symbol(snap, ticker, direction, dte, price), estimated_option_entry=opt_price,
        dte=dte, max_contracts=contracts, max_risk=max_risk, price=round(price, 2), rsi=round(rs, 1), rel_volume=rv,
        market_session=market_session(), liquidity_status=liq_status, notes=notes, timestamp=now_utc_iso()
    )
    return apply_guards(idea, liq_ok)


def classify_zero_dte(ticker: str, intraday: List[Dict[str, Any]]) -> Optional[TradeIdea]:
    if ticker not in ZERO_DTE_TICKERS or len(intraday) < 10:
        return None
    if not can_confirm_zero_dte():
        # Do not generate 0DTE ideas before confirmation window or after 3:30.
        return None
    closes = [float(b["c"]) for b in intraday]
    price = closes[-1]
    ema8, ema21 = ema(closes, 8), ema(closes, 21)
    rs = rsi(closes)
    vols = [float(b.get("v", 0)) for b in intraday]
    rv = round(vols[-1] / (statistics.mean(vols[-20:-1]) or 1), 2) if len(vols) > 21 else 1.0
    first3 = intraday[:3]
    or_high = max(float(b["h"]) for b in first3)
    or_low = min(float(b["l"]) for b in first3)

    direction = None
    if price > or_high and price > ema8 > ema21 and rs > 55 and rv > 1.1:
        direction = "CALL"
    elif price < or_low and price < ema8 < ema21 and rs < 45 and rv > 1.1:
        direction = "PUT"
    else:
        return None
    if 48 <= rs <= 52:
        return None

    dte = 0
    snap = get_option_snapshot(ticker, direction, dte, price, "0DTE")
    liq_ok, liq_status = option_liquidity(snap, "0DTE")
    opt_price = option_mid_price(snap) or max(round(price * 0.008, 2), 0.3)
    contracts, max_risk = size_position(opt_price, 0.50)
    notes = ["0DTE sniper: opening range break confirmed", "EMA8/21 trend aligned", "Volume expanding"]

    idea = TradeIdea(
        ticker=ticker, grade="A+", score=90, trader_type="0DTE", strategy="Opening range sniper",
        direction=direction, status="READY", entry_zone=f"Break {'above' if direction=='CALL' else 'below'} OR level: {round(or_high if direction=='CALL' else or_low, 2)}",
        exit_plan="Take profit fast; no averaging down", stop_loss="Option -50% or failed OR break",
        targets=["+25% option", "+50% option", "close before EOD"],
        option_contract=option_symbol(snap, ticker, direction, dte, price), estimated_option_entry=opt_price,
        dte=dte, max_contracts=contracts, max_risk=max_risk, price=round(price, 2), rsi=round(rs, 1), rel_volume=rv,
        market_session=market_session(), liquidity_status=liq_status, notes=notes, timestamp=now_utc_iso()
    )
    return apply_guards(idea, liq_ok)


def classify_leap(ticker: str, bars: List[Dict[str, Any]]) -> Optional[TradeIdea]:
    closes = [float(b["c"]) for b in bars]
    if len(closes) < 220:
        return None
    price = closes[-1]
    ema50, ema200 = ema(closes, 50), ema(closes, 200)
    high_252 = max(closes[-252:])
    drawdown = (high_252 - price) / high_252 if high_252 else 0
    rs = rsi(closes)
    if not (price > ema200 and ema50 > ema200 and 0.08 <= drawdown <= 0.35 and rs < 60):
        return None

    direction, dte = "CALL", 180
    snap = get_option_snapshot(ticker, direction, dte, price, "LEAP")
    liq_ok, liq_status = option_liquidity(snap, "LEAP")
    opt_price = option_mid_price(snap) or max(round(price * 0.12, 2), 1.0)
    contracts, max_risk = size_position(opt_price, 0.30)
    notes = ["LEAP candidate: price above EMA200", "Pullback from 52-week high", "Longer-term trend intact"]

    idea = TradeIdea(
        ticker=ticker, grade="A+", score=88, trader_type="LEAP", strategy="Long-term trend pullback",
        direction=direction, status="READY", entry_zone=f"Long-term pullback zone near {round(price,2)}",
        exit_plan="Scale over weeks/months; protect capital if thesis breaks", stop_loss="Option -30% or stock loses EMA200",
        targets=["+40% option", "+80% option", "trend hold for runner"],
        option_contract=option_symbol(snap, ticker, direction, dte, price), estimated_option_entry=opt_price,
        dte=dte, max_contracts=contracts, max_risk=max_risk, price=round(price,2), rsi=round(rs,1), rel_volume=1.0,
        market_session=market_session(), liquidity_status=liq_status, notes=notes, timestamp=now_utc_iso()
    )
    return apply_guards(idea, liq_ok)


def classify_reentry(base: TradeIdea, bars: List[Dict[str, Any]]) -> Optional[TradeIdea]:
    closes = [float(b["c"]) for b in bars]
    if len(closes) < 60 or base.status != "WAIT":
        return None
    price = closes[-1]
    ema21 = ema(closes, 21)
    rs = rsi(closes)
    if abs(price - ema21) / price <= 0.01 and 45 <= rs <= 62:
        base.status = "RE-ENTRY READY"
        base.strategy = base.strategy + " + re-entry trigger"
        base.notes.append("A+ RE-ENTRY READY: pullback touched EMA21 with RSI reset")
        return apply_guards(base, "spread=" in base.liquidity_status and "999" not in base.liquidity_status)
    return None


def scan_ticker(ticker: str) -> List[TradeIdea]:
    ideas: List[TradeIdea] = []
    log(f"Scanning {ticker}...")
    if ticker == "SPX":
        log("SPX left in list but skipped until Polygon Indices entitlement is added.")
        return ideas
    daily = get_daily_bars(ticker)
    if len(daily) < 60:
        return ideas
    if ticker in ZERO_DTE_TICKERS:
        intraday = get_intraday_bars(ticker)
        zdte = classify_zero_dte(ticker, intraday)
        if zdte:
            ideas.append(zdte)
    swing = classify_swing(ticker, daily)
    if swing:
        re = classify_reentry(swing, daily)
        ideas.append(re or swing)
    leap = classify_leap(ticker, daily)
    if leap:
        ideas.append(leap)
    return ideas

# =============================
# ALERTS + DASHBOARD PUSH
# =============================
def load_alert_cache() -> Dict[str, Any]:
    data = load_json(ALERT_CACHE_FILE, {})
    if data.get("date") != today_utc().isoformat():
        return {"date": today_utc().isoformat(), "sent": {}}
    return data


def save_alert_cache(cache: Dict[str, Any]) -> None:
    save_json(ALERT_CACHE_FILE, cache)


def alert_key(idea: TradeIdea) -> str:
    return f"{idea.ticker}:{idea.trader_type}:{idea.direction}:{idea.status}:{idea.option_contract}:{today_utc().isoformat()}"


def format_alert(idea: TradeIdea) -> str:
    return "\n".join([
        f"🔥 APEX A+ ALERT: {idea.ticker}",
        f"Type: {idea.trader_type}",
        f"Direction: {idea.direction}",
        f"Status: {idea.status}",
        f"Score: {idea.score}/100",
        f"Market: {idea.market_session}",
        f"Liquidity: {idea.liquidity_status}",
        "",
        f"Entry Zone: {idea.entry_zone}",
        f"Option: {idea.option_contract}",
        f"Est Entry: ${idea.estimated_option_entry}",
        f"Contracts: {idea.max_contracts}",
        f"Max Risk: ${idea.max_risk}",
        "",
        f"Stop: {idea.stop_loss}",
        "Targets: " + ", ".join(idea.targets),
        "",
        "Notes: " + " | ".join(idea.notes[:5]),
    ])


def send_telegram(message: str) -> bool:
    if not SEND_TELEGRAM:
        return False
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram not configured. Skipping alert.")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=15)
        if r.status_code >= 400:
            log(f"Telegram failed HTTP {r.status_code}: {r.text[:160]}")
            return False
        return True
    except Exception as e:
        log(f"Telegram error: {e}")
        return False


def alert_ideas(ideas: List[TradeIdea]) -> None:
    cache = load_alert_cache()
    sent = cache.setdefault("sent", {})
    changed = False
    for idea in ideas:
        if idea.grade != "A+" or idea.status not in {"READY", "RE-ENTRY READY"}:
            continue
        if idea.market_session != "MARKET_OPEN":
            continue
        if not idea.liquidity_status.startswith("spread="):
            continue
        key = alert_key(idea)
        if sent.get(key):
            continue
        if send_telegram(
