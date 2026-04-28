#!/usr/bin/env python3
"""
APEX ENGINE v1.6 - Polygon-only options decision engine + Netlify dashboard sync

Features:
- Multi-stock scanner: swing, 0DTE SPY/QQQ sniper, LEAP candidate mode
- Re-entry engine
- A+ Telegram alerts only
- Duplicate alert protection by day
- Writes dashboard.json locally
- Optional GitHub push to apex-dashboard repo so Netlify auto-updates
- Benzinga disabled
- SPX remains in ticker list but is safely skipped until Polygon Indices is added

Required Render env vars:
POLYGON_API_KEY
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
ACCOUNT_SIZE=60000
MAX_RISK_PER_TRADE=750

Optional dashboard sync env vars:
GITHUB_TOKEN=ghp_xxx
GITHUB_REPO=yourusername/apex-dashboard
GITHUB_BRANCH=main
GITHUB_DASHBOARD_PATH=dashboard.json
"""

from __future__ import annotations

import base64
import json
import math
import os
import statistics
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone, date
from typing import Any, Dict, List, Optional, Tuple

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
MIN_GRADE = os.getenv("MIN_GRADE", "A+").upper()

DASHBOARD_FILE = os.getenv("DASHBOARD_FILE", "dashboard.json")
ALERT_CACHE_FILE = os.getenv("ALERT_CACHE_FILE", "sent_alerts.json")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "12"))

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.getenv("GITHUB_REPO", "").strip()  # username/apex-dashboard
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main").strip()
GITHUB_DASHBOARD_PATH = os.getenv("GITHUB_DASHBOARD_PATH", "dashboard.json").strip()

POLYGON_BASE = "https://api.polygon.io"

TICKERS = [
    "SPY", "QQQ", "SPX", "NVDA", "TSLA", "META", "MSFT", "AAPL",
    "AMZN", "COIN", "AMD", "NFLX", "PLTR", "SMH", "QCOM", "NBIS"
]
ZERO_DTE_TICKERS = {"SPY", "QQQ"}  # SPX skipped until Polygon Indices entitlement

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
    notes: List[str]
    timestamp: str

# =============================
# UTILITIES
# =============================
def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
            log(f"Polygon HTTP {r.status_code} for {path}: {r.text[:160]}")
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
        h, l, pc = float(bars[i]["h"]), float(bars[i]["l"]), float(bars[i-1]["c"])
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


def next_expiration_for_dte(target_dte: int) -> str:
    d = today_utc() + timedelta(days=target_dte)
    return d.isoformat()


def contract_type_for_direction(direction: str) -> str:
    return "call" if direction.upper() == "CALL" else "put"


def get_option_snapshot(ticker: str, direction: str, target_dte: int, underlying_price: float) -> Optional[Dict[str, Any]]:
    """Fetch a small filtered options chain from Polygon and select nearest useful contract."""
    exp = next_expiration_for_dte(target_dte)
    contract_type = contract_type_for_direction(direction)
    params = {
        "contract_type": contract_type,
        "expiration_date": exp,
        "limit": 40,
        "sort": "details.strike_price",
    }
    data = polygon_get(f"/v3/snapshot/options/{ticker}", params)
    if not data or not data.get("results"):
        return None
    options = data["results"]
    # Choose ATM/near ITM. For calls: nearest strike >= price. For puts: nearest strike <= price.
    def strike(o: Dict[str, Any]) -> float:
        return float(o.get("details", {}).get("strike_price") or 0)
    if direction.upper() == "CALL":
        candidates = [o for o in options if strike(o) >= underlying_price * 0.98]
    else:
        candidates = [o for o in options if strike(o) <= underlying_price * 1.02]
    candidates = candidates or options
    return min(candidates, key=lambda o: abs(strike(o) - underlying_price))


def option_mid_price(snapshot: Optional[Dict[str, Any]]) -> float:
    if not snapshot:
        return 0.0
    quote = snapshot.get("last_quote") or {}
    bid = float(quote.get("bid", 0) or 0)
    ask = float(quote.get("ask", 0) or 0)
    if bid > 0 and ask > 0:
        return round((bid + ask) / 2, 2)
    trade = snapshot.get("last_trade") or {}
    price = float(trade.get("price", 0) or 0)
    return round(price, 2)


def option_symbol(snapshot: Optional[Dict[str, Any]], ticker: str, direction: str, dte: int, price: float) -> str:
    if not snapshot:
        # fallback approximation
        strike = round(price / 5) * 5
        return f"{ticker} {strike}{'C' if direction == 'CALL' else 'P'} {dte}DTE"
    details = snapshot.get("details", {})
    sym = details.get("ticker") or ""
    strike = details.get("strike_price", "?")
    exp = details.get("expiration_date", "?")
    typ = details.get("contract_type", direction.lower())
    return f"{sym or ticker} {exp} {strike} {typ.upper()}"

# =============================
# SCORING AND STRATEGY
# =============================
def grade(score: float) -> str:
    if score >= 88:
        return "A+"
    if score >= 78:
        return "A"
    if score >= 70:
        return "B+"
    return "B"


def classify_swing(ticker: str, bars: List[Dict[str, Any]]) -> Optional[TradeIdea]:
    closes = [float(b["c"]) for b in bars]
    vols = [float(b.get("v", 0)) for b in bars]
    if len(closes) < 60:
        return None
    price = closes[-1]
    ema8, ema21, ema50, ema200 = ema(closes, 8), ema(closes, 21), ema(closes, 50), ema(closes, 200)
    rs = rsi(closes)
    avgv = statistics.mean(vols[-30:-1]) if len(vols) > 31 else max(vols[-1], 1)
    rv = round(vols[-1] / avgv, 2) if avgv else 1.0
    at = atr(bars)

    direction = "CALL" if price > ema50 else "PUT"
    score = 0
    notes = []

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
    g = grade(score)
    if g != "A+":
        return None

    near_ema21 = abs(price - ema21) / price <= 0.012
    status = "READY" if near_ema21 else "WAIT"
    if status != "READY":
        # dashboard can still show A+ WAIT, but Telegram will not alert
        notes.append("A+ watchlist only: wait for price to touch entry zone")

    dte = 14
    snap = get_option_snapshot(ticker, direction, dte, price)
    opt_price = option_mid_price(snap) or max(round(price * 0.025, 2), 0.5)
    stop_pct = 0.35
    risk_per_contract = opt_price * 100 * stop_pct
    contracts = max(1, math.floor(MAX_RISK_PER_TRADE / risk_per_contract)) if risk_per_contract > 0 else 1
    max_risk = round(contracts * risk_per_contract, 2)
    zone_low = round(min(ema21, price) - at * 0.15, 2)
    zone_high = round(max(ema21, price) + at * 0.15, 2)

    return TradeIdea(
        ticker=ticker, grade=g, score=score, trader_type="SWING", strategy="EMA21 pullback continuation",
        direction=direction, status=status, entry_zone=f"{zone_low} - {zone_high}",
        exit_plan="Scale at +35% / +70%; close if trend fails", stop_loss="Option -35% or stock closes beyond EMA21/EMA50 zone",
        targets=["+35% option", "+70% option", "trail runner if momentum expands"],
        option_contract=option_symbol(snap, ticker, direction, dte, price), estimated_option_entry=opt_price,
        dte=dte, max_contracts=contracts, max_risk=max_risk, price=round(price, 2), rsi=round(rs, 1), rel_volume=rv,
        notes=notes, timestamp=now_utc_iso()
    )


def classify_zero_dte(ticker: str, daily: List[Dict[str, Any]], intraday: List[Dict[str, Any]]) -> Optional[TradeIdea]:
    if ticker not in ZERO_DTE_TICKERS or len(intraday) < 10 or len(daily) < 60:
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

    score = 90
    notes = ["0DTE sniper: opening range break confirmed", "EMA8/21 trend aligned", "Volume expanding"]
    if 48 <= rs <= 52:
        return None

    dte = 0
    snap = get_option_snapshot(ticker, direction, dte, price)
    opt_price = option_mid_price(snap) or max(round(price * 0.008, 2), 0.3)
    stop_pct = 0.50
    risk_per_contract = opt_price * 100 * stop_pct
    contracts = max(1, math.floor(MAX_RISK_PER_TRADE / risk_per_contract)) if risk_per_contract > 0 else 1
    max_risk = round(contracts * risk_per_contract, 2)

    return TradeIdea(
        ticker=ticker, grade="A+", score=score, trader_type="0DTE", strategy="Opening range sniper",
        direction=direction, status="READY", entry_zone=f"Break {'above' if direction=='CALL' else 'below'} OR level: {round(or_high if direction=='CALL' else or_low, 2)}",
        exit_plan="Take profit fast; no averaging down", stop_loss="Option -50% or failed OR break",
        targets=["+25% option", "+50% option", "close before EOD"],
        option_contract=option_symbol(snap, ticker, direction, dte, price), estimated_option_entry=opt_price,
        dte=dte, max_contracts=contracts, max_risk=max_risk, price=round(price, 2), rsi=round(rs, 1), rel_volume=rv,
        notes=notes, timestamp=now_utc_iso()
    )


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

    score = 88
    direction = "CALL"
    dte = 180
    snap = get_option_snapshot(ticker, direction, dte, price)
    opt_price = option_mid_price(snap) or max(round(price * 0.12, 2), 1.0)
    stop_pct = 0.30
    risk_per_contract = opt_price * 100 * stop_pct
    contracts = max(1, math.floor(MAX_RISK_PER_TRADE / risk_per_contract)) if risk_per_contract > 0 else 1
    max_risk = round(contracts * risk_per_contract, 2)

    return TradeIdea(
        ticker=ticker, grade="A+", score=score, trader_type="LEAP", strategy="Long-term trend pullback",
        direction=direction, status="READY", entry_zone=f"Long-term pullback zone near {round(price,2)}",
        exit_plan="Scale over weeks/months; protect capital if thesis breaks", stop_loss="Option -30% or stock loses EMA200",
        targets=["+40% option", "+80% option", "trend hold for runner"],
        option_contract=option_symbol(snap, ticker, direction, dte, price), estimated_option_entry=opt_price,
        dte=dte, max_contracts=contracts, max_risk=max_risk, price=round(price,2), rsi=round(rs,1), rel_volume=1.0,
        notes=["LEAP candidate: price above EMA200", "Pullback from 52-week high", "Longer-term trend intact"], timestamp=now_utc_iso()
    )


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
        return base
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
    intraday = get_intraday_bars(ticker) if ticker in ZERO_DTE_TICKERS else []

    zdte = classify_zero_dte(ticker, daily, intraday)
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
# TELEGRAM + DASHBOARD SYNC
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
    cache = load_alert_cache()
    sent = cache.setdefault("sent", {})
    changed = False
    for idea in ideas:
        if idea.grade != "A+" or idea.status not in {"READY", "RE-ENTRY READY"}:
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
        payload = {
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
    log("Apex Engine v1.6 starting — Polygon-only. Benzinga disabled. Netlify dashboard sync ready.")
    log(f"Account size: {ACCOUNT_SIZE} | Max risk/trade: {MAX_RISK_PER_TRADE}")
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
        "mode": "POLYGON_ONLY_BENZINGA_DISABLED_V1_6",
        "account_size": ACCOUNT_SIZE,
        "max_risk_per_trade": MAX_RISK_PER_TRADE,
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
