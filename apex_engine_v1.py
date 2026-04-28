#!/usr/bin/env python3
"""
APEX ENGINE v1.9 - Polygon-only trading decision engine

What this version adds:
- Optimized entry engine: pullback confirmation, breakout confirmation, no-chase filter
- Open confirmation engine: after-hours / premarket = watchlist only
- 0DTE SPY/QQQ sniper: only 9:45 AM ET to 3:30 PM ET
- Option liquidity filter: spread, open interest, volume checks when Polygon provides them
- A+ Telegram alerts only when market is open and status is READY / RE-ENTRY READY
- Dashboard JSON push to GitHub for Netlify dashboard
- Benzinga disabled
- SPX safely skipped until Polygon Indices entitlement is added

Required Render environment variables:
POLYGON_API_KEY
ACCOUNT_SIZE=60000
MAX_RISK_PER_TRADE=750

Optional alert variables:
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
SEND_TELEGRAM=true

Optional dashboard sync variables:
GITHUB_TOKEN=ghp_xxx
GITHUB_REPO=yourusername/apex-dashboard
GITHUB_BRANCH=main
GITHUB_DASHBOARD_PATH=dashboard.json
"""
print("🔥 FORCE NEW BUILD v2.1 🔥")
from __future__ import annotations

import base64
import json
import math
import os
import statistics
from dataclasses import dataclass, asdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional
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
ET = ZoneInfo("America/New_York")

TICKERS = [
    "SPY", "QQQ", "SPX", "NVDA", "TSLA", "META", "MSFT", "AAPL",
    "AMZN", "COIN", "AMD", "NFLX", "PLTR", "SMH", "QCOM", "NBIS"
]
ZERO_DTE_TICKERS = {"SPY", "QQQ"}

# Liquidity thresholds. These are protective, not absolute.
MAX_SPREAD_PCT_SWING = 0.18
MAX_SPREAD_PCT_0DTE = 0.12
MIN_OPEN_INTEREST_SWING = 100
MIN_OPEN_INTEREST_0DTE = 250
MIN_OPTION_VOLUME_SWING = 10
MIN_OPTION_VOLUME_0DTE = 25

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
    entry_trigger: str
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
    spread_pct: Optional[float]
    option_volume: Optional[int]
    open_interest: Optional[int]
    market_session: str
    notes: List[str]
    timestamp: str

# =============================
# UTILITIES
# =============================
def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def now_et() -> datetime:
    return datetime.now(ET)


def today_et() -> date:
    return now_et().date()


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


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


def market_session() -> str:
    n = now_et()
    if n.weekday() >= 5:
        return "CLOSED"
    if time(9, 30) <= n.time() <= time(16, 0):
        return "MARKET_OPEN"
    if time(4, 0) <= n.time() < time(9, 30):
        return "PREMARKET"
    return "AFTER_HOURS"


def is_market_open() -> bool:
    return market_session() == "MARKET_OPEN"


def is_open_confirmation_window() -> bool:
    n = now_et()
    return n.weekday() < 5 and time(9, 45) <= n.time() <= time(15, 30)


def is_zero_dte_window() -> bool:
    n = now_et()
    return n.weekday() < 5 and time(9, 45) <= n.time() <= time(15, 30)


def polygon_get(path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if params is None:
        params = {}
    params["apiKey"] = POLYGON_API_KEY
    url = f"{POLYGON_BASE}{path}"
    try:
        r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        if r.status_code in (401, 403):
            log(f"Polygon not authorized for {path}. Skipping.")
            return None
        if r.status_code == 404:
            log(f"Polygon 404 for {path}. Skipping.")
            return None
        if r.status_code >= 400:
            log(f"Polygon HTTP {r.status_code} for {path}: {r.text[:180]}")
            return None
        return r.json()
    except requests.exceptions.Timeout:
        log(f"Polygon timeout for {path}. Skipping.")
        return None
    except Exception as e:
        log(f"Polygon request failed for {path}: {e}")
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
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))
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
        h, l, pc = float(bars[i]["h"]), float(bars[i]["l"]), float(bars[i - 1]["c"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-period:]) / min(period, len(trs)) if trs else 0.0

# =============================
# DATA FETCH
# =============================
def get_daily_bars(ticker: str, days: int = 260) -> List[Dict[str, Any]]:
    end = today_utc()
    start = end - timedelta(days=430)
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


def expiration_for_target_dte(target_dte: int) -> str:
    # Polygon snapshot supports exact expiration_date. If no contracts exist on the exact date, we fallback gracefully.
    return (today_utc() + timedelta(days=target_dte)).isoformat()


def contract_type_for_direction(direction: str) -> str:
    return "call" if direction.upper() == "CALL" else "put"


def get_option_snapshot(ticker: str, direction: str, target_dte: int, underlying_price: float) -> Optional[Dict[str, Any]]:
    contract_type = contract_type_for_direction(direction)
    exp = expiration_for_target_dte(target_dte)
    params = {
        "contract_type": contract_type,
        "expiration_date": exp,
        "limit": 50,
    }
    data = polygon_get(f"/v3/snapshot/options/{ticker}", params)
    if not data or not data.get("results"):
        # Fallback without expiration filter so the engine does not fail if exact DTE date has no chain.
        params = {"contract_type": contract_type, "limit": 50}
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
    return min(candidates, key=lambda o: abs(strike(o) - underlying_price))


def option_mid_price(snapshot: Optional[Dict[str, Any]], fallback: float) -> float:
    if not snapshot:
        return round(fallback, 2)
    quote = snapshot.get("last_quote") or {}
    bid = float(quote.get("bid", 0) or 0)
    ask = float(quote.get("ask", 0) or 0)
    if bid > 0 and ask > 0:
        return round((bid + ask) / 2, 2)
    trade = snapshot.get("last_trade") or {}
    price = float(trade.get("price", 0) or 0)
    return round(price or fallback, 2)


def option_symbol(snapshot: Optional[Dict[str, Any]], ticker: str, direction: str, dte: int, price: float) -> str:
    if not snapshot:
        strike = round(price / 5) * 5
        return f"{ticker} {strike}{'C' if direction == 'CALL' else 'P'} {dte}DTE"
    details = snapshot.get("details", {})
    sym = details.get("ticker") or ""
    strike = details.get("strike_price", "?")
    exp = details.get("expiration_date", f"{dte}DTE")
    typ = details.get("contract_type", direction.lower())
    return f"{sym or ticker} {exp} {strike} {typ.upper()}"


def option_liquidity(snapshot: Optional[Dict[str, Any]], trader_type: str) -> Dict[str, Optional[float]]:
    if not snapshot:
        return {"ok": None, "spread_pct": None, "volume": None, "open_interest": None, "note": "No live option snapshot; fallback pricing used"}

    quote = snapshot.get("last_quote") or {}
    bid = float(quote.get("bid", 0) or 0)
    ask = float(quote.get("ask", 0) or 0)
    mid = (bid + ask) / 2 if bid > 0 and ask > 0 else 0
    spread_pct = round((ask - bid) / mid, 3) if mid > 0 and ask >= bid else None
    volume = snapshot.get("day", {}).get("volume")
    oi = snapshot.get("open_interest")

    max_spread = MAX_SPREAD_PCT_0DTE if trader_type == "0DTE" else MAX_SPREAD_PCT_SWING
    min_oi = MIN_OPEN_INTEREST_0DTE if trader_type == "0DTE" else MIN_OPEN_INTEREST_SWING
    min_vol = MIN_OPTION_VOLUME_0DTE if trader_type == "0DTE" else MIN_OPTION_VOLUME_SWING

    checks = []
    if spread_pct is not None:
        checks.append(spread_pct <= max_spread)
    if oi is not None:
        checks.append(int(oi) >= min_oi)
    if volume is not None:
        checks.append(int(volume) >= min_vol)

    ok = all(checks) if checks else None
    note = "Option liquidity passed" if ok else "Option liquidity warning: confirm bid/ask and volume in Power E*TRADE"
    return {"ok": ok, "spread_pct": spread_pct, "volume": volume, "open_interest": oi, "note": note}

# =============================
# ENTRY AND SCORING
# =============================
def grade(score: float) -> str:
    if score >= 88:
        return "A+"
    if score >= 78:
        return "A"
    if score >= 70:
        return "B+"
    return "B"


def refined_entry_status(price: float, ema8_val: float, ema21_val: float, rel_volume: float, direction: str) -> str:
    if not is_open_confirmation_window():
        return "WATCHLIST - OPEN CONFIRMATION NEEDED"

    if direction == "CALL":
        extension = (price - ema21_val) / ema21_val if ema21_val else 0
        if 0 <= extension <= 0.012:
            return "READY - PULLBACK CONFIRMED"
        if price > ema8_val and rel_volume >= 1.5 and extension <= 0.03:
            return "READY - BREAKOUT CONFIRMED"
        if 0.012 < extension <= 0.03:
            return "WAIT - WATCH FOR DIP"
        return "EXTENDED - DO NOT ENTER"

    extension = (ema21_val - price) / ema21_val if ema21_val else 0
    if 0 <= extension <= 0.012:
        return "READY - PULLBACK CONFIRMED"
    if price < ema8_val and rel_volume >= 1.5 and extension <= 0.03:
        return "READY - BREAKDOWN CONFIRMED"
    if 0.012 < extension <= 0.03:
        return "WAIT - WATCH FOR BOUNCE"
    return "EXTENDED - DO NOT ENTER"


def apply_liquidity_to_status(status: str, liq: Dict[str, Optional[float]]) -> str:
    if not status.startswith("READY") and status != "RE-ENTRY READY":
        return status
    if liq["ok"] is False:
        return "WAIT - OPTION LIQUIDITY CHECK"
    return status


def position_size(opt_price: float, stop_pct: float) -> tuple[int, float]:
    risk_per_contract = max(opt_price, 0.01) * 100 * stop_pct
    contracts = max(1, math.floor(MAX_RISK_PER_TRADE / risk_per_contract))
    return contracts, round(contracts * risk_per_contract, 2)

# =============================
# CLASSIFIERS
# =============================
def classify_swing(ticker: str, bars: List[Dict[str, Any]]) -> Optional[TradeIdea]:
    closes = [float(b["c"]) for b in bars]
    vols = [float(b.get("v", 0)) for b in bars]
    if len(closes) < 60:
        return None

    price = closes[-1]
    ema8_val = ema(closes, 8)
    ema21_val = ema(closes, 21)
    ema50_val = ema(closes, 50)
    rs = rsi(closes)
    avgv = statistics.mean(vols[-30:-1]) if len(vols) > 31 else max(vols[-1], 1)
    rv = round(vols[-1] / avgv, 2) if avgv else 1.0
    at = atr(bars)

    direction = "CALL" if price > ema50_val else "PUT"
    score = 0
    notes: List[str] = []

    if direction == "CALL" and price > ema21_val > ema50_val:
        score += 24; notes.append("Bull trend: price above EMA21/EMA50")
    if direction == "PUT" and price < ema21_val < ema50_val:
        score += 24; notes.append("Bear trend: price below EMA21/EMA50")
    if abs(price - ema21_val) / price <= 0.025:
        score += 26; notes.append("Near EMA21 entry zone")
    elif abs(price - ema50_val) / price <= 0.025:
        score += 18; notes.append("Near EMA50 entry zone")
    if 45 <= rs <= 66:
        score += 16; notes.append("RSI controlled / reset")
    if rv >= 1.15:
        score += 14; notes.append("Relative volume expansion")
    if (direction == "CALL" and price > ema8_val) or (direction == "PUT" and price < ema8_val):
        score += 10; notes.append("Short-term EMA8 momentum aligned")

    score = min(score, 100)
    if grade(score) != "A+":
        return None

    status = refined_entry_status(price, ema8_val, ema21_val, rv, direction)
    dte = 14
    snap = get_option_snapshot(ticker, direction, dte, price)
    fallback = max(round(price * 0.025, 2), 0.50)
    opt_price = option_mid_price(snap, fallback)
    liq = option_liquidity(snap, "SWING")
    status = apply_liquidity_to_status(status, liq)
    contracts, max_risk = position_size(opt_price, 0.35)

    zone_low = round(min(ema21_val, price) - at * 0.15, 2)
    zone_high = round(max(ema21_val, price) + at * 0.15, 2)

    if liq.get("note"):
        notes.append(str(liq["note"]))

    return TradeIdea(
        ticker=ticker, grade="A+", score=score, trader_type="SWING", strategy="EMA21 pullback / confirmed breakout",
        direction=direction, status=status, entry_zone=f"{zone_low} - {zone_high}",
        entry_trigger="Enter only when status is READY during market hours; do not chase outside entry zone",
        exit_plan="Scale at +35% / +70%; close if trend fails", stop_loss="Option -35% or stock closes beyond EMA21/EMA50 zone",
        targets=["+35% option", "+70% option", "trail runner if momentum expands"],
        option_contract=option_symbol(snap, ticker, direction, dte, price), estimated_option_entry=opt_price,
        dte=dte, max_contracts=contracts, max_risk=max_risk, price=round(price, 2), rsi=round(rs, 1), rel_volume=rv,
        spread_pct=liq.get("spread_pct"), option_volume=liq.get("volume"), open_interest=liq.get("open_interest"),
        market_session=market_session(), notes=notes, timestamp=now_utc_iso()
    )


def classify_zero_dte(ticker: str, intraday: List[Dict[str, Any]]) -> Optional[TradeIdea]:
    if ticker not in ZERO_DTE_TICKERS or len(intraday) < 10:
        return None
    if not is_zero_dte_window():
        return None

    closes = [float(b["c"]) for b in intraday]
    price = closes[-1]
    ema8_val, ema21_val = ema(closes, 8), ema(closes, 21)
    rs = rsi(closes)
    vols = [float(b.get("v", 0)) for b in intraday]
    rv = round(vols[-1] / (statistics.mean(vols[-20:-1]) or 1), 2) if len(vols) > 21 else 1.0

    first3 = intraday[:3]
    or_high = max(float(b["h"]) for b in first3)
    or_low = min(float(b["l"]) for b in first3)

    direction: Optional[str] = None
    if price > or_high and price > ema8_val > ema21_val and rs > 55 and rv > 1.15:
        direction = "CALL"
    elif price < or_low and price < ema8_val < ema21_val and rs < 45 and rv > 1.15:
        direction = "PUT"
    else:
        return None

    if 45 <= rs <= 55:
        return None

    dte = 0
    snap = get_option_snapshot(ticker, direction, dte, price)
    opt_price = option_mid_price(snap, max(round(price * 0.008, 2), 0.30))
    liq = option_liquidity(snap, "0DTE")
    status = apply_liquidity_to_status("READY - 0DTE SNIPER CONFIRMED", liq)
    contracts, max_risk = position_size(opt_price, 0.50)

    notes = ["0DTE sniper: opening range break confirmed", "EMA8/21 trend aligned", "Volume expanding"]
    if liq.get("note"):
        notes.append(str(liq["note"]))

    return TradeIdea(
        ticker=ticker, grade="A+", score=90, trader_type="0DTE", strategy="Opening range sniper",
        direction=direction, status=status,
        entry_zone=f"Break {'above' if direction == 'CALL' else 'below'} OR level: {round(or_high if direction == 'CALL' else or_low, 2)}",
        entry_trigger="Only enter while 0DTE window is active and spread is tight",
        exit_plan="Take profit fast; no averaging down", stop_loss="Option -50% or failed OR break",
        targets=["+25% option", "+50% option", "close before EOD"],
        option_contract=option_symbol(snap, ticker, direction, dte, price), estimated_option_entry=opt_price,
        dte=dte, max_contracts=contracts, max_risk=max_risk, price=round(price, 2), rsi=round(rs, 1), rel_volume=rv,
        spread_pct=liq.get("spread_pct"), option_volume=liq.get("volume"), open_interest=liq.get("open_interest"),
        market_session=market_session(), notes=notes, timestamp=now_utc_iso()
    )


def classify_leap(ticker: str, bars: List[Dict[str, Any]]) -> Optional[TradeIdea]:
    closes = [float(b["c"]) for b in bars]
    if len(closes) < 220:
        return None
    price = closes[-1]
    ema50_val = ema(closes, 50)
    ema200_val = ema(closes, 200)
    high_252 = max(closes[-252:])
    drawdown = (high_252 - price) / high_252 if high_252 else 0
    rs = rsi(closes)

    if not (price > ema200_val and ema50_val > ema200_val and 0.08 <= drawdown <= 0.35 and rs < 62):
        return None

    direction = "CALL"
    dte = 180
    snap = get_option_snapshot(ticker, direction, dte, price)
    opt_price = option_mid_price(snap, max(round(price * 0.12, 2), 1.0))
    liq = option_liquidity(snap, "LEAP")
    status = "READY - LONG TERM SETUP" if is_market_open() else "WATCHLIST - OPEN CONFIRMATION NEEDED"
    status = apply_liquidity_to_status(status, liq)
    contracts, max_risk = position_size(opt_price, 0.30)

    notes = ["LEAP candidate: price above EMA200", "Pullback from 52-week high", "Longer-term trend intact"]
    if liq.get("note"):
        notes.append(str(liq["note"]))

    return TradeIdea(
        ticker=ticker, grade="A+", score=88, trader_type="LEAP", strategy="Long-term trend pullback",
        direction=direction, status=status, entry_zone=f"Long-term pullback zone near {round(price, 2)}",
        entry_trigger="Confirm thesis and liquidity during market hours before entry",
        exit_plan="Scale over weeks/months; protect capital if thesis breaks", stop_loss="Option -30% or stock loses EMA200",
        targets=["+40% option", "+80% option", "trend hold for runner"],
        option_contract=option_symbol(snap, ticker, direction, dte, price), estimated_option_entry=opt_price,
        dte=dte, max_contracts=contracts, max_risk=max_risk, price=round(price, 2), rsi=round(rs, 1), rel_volume=1.0,
        spread_pct=liq.get("spread_pct"), option_volume=liq.get("volume"), open_interest=liq.get("open_interest"),
        market_session=market_session(), notes=notes, timestamp=now_utc_iso()
    )


def classify_reentry(base: TradeIdea, bars: List[Dict[str, Any]]) -> TradeIdea:
    closes = [float(b["c"]) for b in bars]
    if len(closes) < 60:
        return base
    price = closes[-1]
    ema21_val = ema(closes, 21)
    rs = rsi(closes)
    if is_open_confirmation_window() and abs(price - ema21_val) / price <= 0.01 and 45 <= rs <= 62:
        base.status = "RE-ENTRY READY"
        base.strategy += " + re-entry trigger"
        base.entry_trigger = "Re-entry: pullback touched EMA21 with RSI reset"
        base.notes.append("A+ RE-ENTRY READY: pullback touched EMA21 with RSI reset")
    return base


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
        ideas.append(classify_reentry(swing, daily))

    leap = classify_leap(ticker, daily)
    if leap:
        ideas.append(leap)

    return ideas

# =============================
# TELEGRAM + DASHBOARD SYNC
# =============================
def load_alert_cache() -> Dict[str, Any]:
    data = load_json(ALERT_CACHE_FILE, {})
    if data.get("date") != today_et().isoformat():
        return {"date": today_et().isoformat(), "sent": {}}
    return data


def save_alert_cache(cache: Dict[str, Any]) -> None:
    save_json(ALERT_CACHE_FILE, cache)


def alert_key(idea: TradeIdea) -> str:
    return f"{idea.ticker}:{idea.trader_type}:{idea.direction}:{idea.status}:{idea.option_contract}:{today_et().isoformat()}"


def is_alertable_status(status: str) -> bool:
    return status.startswith("READY") or status == "RE-ENTRY READY"


def format_alert(idea: TradeIdea) -> str:
    return "\n".join([
        f"🔥 APEX A+ ALERT: {idea.ticker}",
        f"Type: {idea.trader_type}",
        f"Direction: {idea.direction}",
        f"Status: {idea.status}",
        f"Score: {idea.score}/100",
        "",
        f"Entry Zone: {idea.entry_zone}",
        f"Entry Trigger: {idea.entry_trigger}",
        f"Option: {idea.option_contract}",
        f"Est Entry: ${idea.estimated_option_entry}",
        f"Contracts: {idea.max_contracts}",
        f"Max Risk: ${idea.max_risk}",
        "",
        f"Stop: {idea.stop_loss}",
        "Targets: " + ", ".join(idea.targets),
        "",
        "Notes: " + " | ".join(idea.notes[:4]),
    ])


def send_telegram(message: str) -> bool:
    if not SEND_TELEGRAM:
        log("Telegram disabled by SEND_TELEGRAM=false.")
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
    if not is_market_open():
        log("Market not open. Telegram alerts suppressed; dashboard updated only.")
        return

    cache = load_alert_cache()
    sent = cache.setdefault("sent", {})
    changed = False

    for idea in ideas:
        if idea.grade != "A+" or not is_alertable_status(idea.status):
            continue
        key = alert_key(idea)
        if sent.get(key):
            continue
        if send_telegram(format_alert(idea)):
            sent[key] = now_utc_iso()
            changed = True

    if changed:
        save_alert_cache(cache)


def push_dashboard_to_github(data: Dict[str, Any]) -> bool:
    if not GITHUB_TOKEN or not GITHUB_REPO:
        log("GitHub dashboard sync not configured. Skipping push.")
        return False

    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_DASHBOARD_PATH}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        sha = None
        existing = requests.get(api_url, headers=headers, params={"ref": GITHUB_BRANCH}, timeout=15)
        if existing.status_code == 200:
            sha = existing.json().get("sha")
        elif existing.status_code != 404:
            log(f"GitHub read failed HTTP {existing.status_code}: {existing.text[:200]}")
            return False

        content = json.dumps(data, indent=2) + "\n"
        payload: Dict[str, Any] = {
            "message": f"Update Apex dashboard {now_utc_iso()}",
            "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
            "branch": GITHUB_BRANCH,
        }
        if sha:
            payload["sha"] = sha

        resp = requests.put(api_url, headers=headers, json=payload, timeout=20)
        if resp.status_code in (200, 201):
            log(f"Dashboard pushed to GitHub: {GITHUB_REPO}/{GITHUB_DASHBOARD_PATH}")
            return True
        log(f"GitHub push failed HTTP {resp.status_code}: {resp.text[:250]}")
        return False
    except Exception as e:
        log(f"GitHub push error: {e}")
        return False

# =============================
# MAIN
# =============================
def main() -> None:
    log("Apex Engine v1.9 starting — entry optimized, Polygon-only, Benzinga disabled.")
    log(f"Session: {market_session()} | Account size: {ACCOUNT_SIZE} | Max risk/trade: {MAX_RISK_PER_TRADE}")

    if not POLYGON_API_KEY:
        log("Missing POLYGON_API_KEY. Add it in Render Environment.")
        return

    all_ideas: List[TradeIdea] = []
    for ticker in TICKERS:
        try:
            all_ideas.extend(scan_ticker(ticker))
        except Exception as e:
            log(f"Error scanning {ticker}: {e}")

    all_ideas.sort(key=lambda x: x.score, reverse=True)

    dashboard = {
        "updated_at": now_utc_iso(),
        "mode": "POLYGON_ONLY_BENZINGA_DISABLED_V1_9_ENTRY_OPTIMIZED",
        "market_session": market_session(),
        "account_size": ACCOUNT_SIZE,
        "max_risk_per_trade": MAX_RISK_PER_TRADE,
        "rules": {
            "after_hours": "watchlist only",
            "0dte_window_et": "09:45-15:30",
            "alerts": "A+ only, market open only, READY/RE-ENTRY READY only",
            "risk_model": "$750 max stop-loss risk per trade",
        },
        "ideas": [asdict(i) for i in all_ideas],
    }

    save_json(DASHBOARD_FILE, dashboard)
    push_dashboard_to_github(dashboard)
    alert_ideas(all_ideas)

    log(f"Scan complete. Qualified ideas: {len(all_ideas)}")
    for idea in all_ideas[:10]:
        log(f"{idea.grade} {idea.ticker} {idea.trader_type} {idea.direction} {idea.status} score={idea.score} option={idea.option_contract}")


if __name__ == "__main__":
    main()
