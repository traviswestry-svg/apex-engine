"""
Apex Engine v1 - Render-ready multi-strategy options scanner

Purpose:
- Multi-stock scanner for Swing, 0DTE, and LEAP setups
- Polygon for market/options data
- Benzinga for news/catalysts/unusual options activity
- Telegram alerts only; manual execution in Power E*TRADE
- Outputs qualified tickers only. If not classified, it is omitted.

Environment variables required:
- POLYGON_API_KEY
- BENZINGA_API_KEY
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID

Optional environment variables:
- SCAN_TICKERS: comma-separated tickers
- DASHBOARD_OUTPUT_PATH: default dashboard_data.json
- ALERT_LOG_PATH: default sent_alerts.json
- MAX_RISK_PER_TRADE: default 750
- MIN_SCORE: default 75
- SEND_TELEGRAM: true/false, default true

Run:
python apex_engine_v1.py
"""

from __future__ import annotations

import json
import math
import os
import statistics
import time
from dataclasses import dataclass, asdict
from datetime import datetime, date, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests


# =========================
# Configuration
# =========================

DEFAULT_TICKERS = [
    "SPX", "SPY", "QQQ", "NVDA", "TSLA", "META", "MSFT", "AAPL", "AMZN",
    "COIN", "AMD", "NFLX", "PLTR", "SMH", "QCOM", "NBIS"
]

SWING_DTE_RANGE = (7, 30)
ZERO_DTE_RANGE = (0, 1)
LEAP_DTE_RANGE = (90, 365)

MAX_RISK_PER_TRADE = float(os.getenv("MAX_RISK_PER_TRADE", "750"))
MIN_SCORE = float(os.getenv("MIN_SCORE", "75"))
SEND_TELEGRAM = os.getenv("SEND_TELEGRAM", "true").lower() == "true"

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "")
BENZINGA_API_KEY = os.getenv("BENZINGA_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

DASHBOARD_OUTPUT_PATH = os.getenv("DASHBOARD_OUTPUT_PATH", "dashboard_data.json")
ALERT_LOG_PATH = os.getenv("ALERT_LOG_PATH", "sent_alerts.json")

SCAN_TICKERS = [
    t.strip().upper() for t in os.getenv("SCAN_TICKERS", ",".join(DEFAULT_TICKERS)).split(",") if t.strip()
]

POLYGON_BASE = "https://api.polygon.io"
BENZINGA_BASE = "https://api.benzinga.com/api/v2"


# =========================
# Data models
# =========================

@dataclass
class TechnicalSnapshot:
    ticker: str
    price: float
    prev_close: float
    change_pct: float
    volume: float
    rel_volume: float
    sma_20: float
    sma_50: float
    sma_200: float
    ema_8: float
    ema_21: float
    ema_50: float
    rsi_14: float
    atr_14: float
    trend: str


@dataclass
class OptionCandidate:
    ticker: str
    option_symbol: str
    option_type: str
    strike: float
    expiration_date: str
    dte: int
    bid: float
    ask: float
    mid: float
    delta: Optional[float]
    gamma: Optional[float]
    iv: Optional[float]
    open_interest: Optional[int]
    volume: Optional[int]
    liquidity_score: float


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
    option_contract: str
    expiration: str
    dte: int
    estimated_option_entry: float
    stop_loss: str
    targets: List[str]
    max_contracts: int
    max_risk: float
    technical_score: float
    options_score: float
    catalyst_score: float
    market_context_score: float
    notes: List[str]
    timestamp: str


# =========================
# Utility functions
# =========================

def now_et_iso() -> str:
    # Render usually runs UTC. Timestamp retained in UTC for consistency.
    return datetime.now(timezone.utc).isoformat()


def safe_get(url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 20) -> Optional[Dict[str, Any]]:
    try:
        r = requests.get(url, params=params, timeout=timeout)
        if r.status_code >= 400:
            print(f"HTTP {r.status_code} for {url}: {r.text[:300]}")
            return None
        return r.json()
    except Exception as e:
        print(f"Request failed: {url} -> {e}")
        return None


def ema(values: List[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2 / (period + 1)
    result = values[0]
    for v in values[1:]:
        result = v * k + result * (1 - k)
    return result


def sma(values: List[float], period: int) -> float:
    if len(values) < period:
        return statistics.mean(values) if values else 0.0
    return statistics.mean(values[-period:])


def rsi(values: List[float], period: int = 14) -> float:
    if len(values) <= period:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))
    avg_gain = statistics.mean(gains[-period:]) if gains[-period:] else 0
    avg_loss = statistics.mean(losses[-period:]) if losses[-period:] else 0
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
    return statistics.mean(trs[-period:]) if trs else 0.0


def grade_from_score(score: float) -> str:
    if score >= 90:
        return "A+"
    if score >= 82:
        return "A"
    if score >= 75:
        return "B+"
    return "B"


def dte_from_expiration(expiration_date: str) -> int:
    try:
        exp = datetime.strptime(expiration_date, "%Y-%m-%d").date()
        return max((exp - date.today()).days, 0)
    except Exception:
        return 999


def load_alert_log() -> Dict[str, Any]:
    if not os.path.exists(ALERT_LOG_PATH):
        return {}
    try:
        with open(ALERT_LOG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_alert_log(log: Dict[str, Any]) -> None:
    with open(ALERT_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)


def already_alerted_today(key: str) -> bool:
    log = load_alert_log()
    today = date.today().isoformat()
    return log.get(key) == today


def mark_alerted_today(key: str) -> None:
    log = load_alert_log()
    log[key] = date.today().isoformat()
    save_alert_log(log)


# =========================
# Polygon data functions
# =========================

def polygon_ticker_for_price(ticker: str) -> str:
    # Polygon index ticker for SPX is I:SPX. Options chain may use SPX contracts differently.
    if ticker == "SPX":
        return "I:SPX"
    return ticker


def get_daily_bars(ticker: str, days: int = 260) -> Optional[List[Dict[str, Any]]]:
    poly_ticker = polygon_ticker_for_price(ticker)
    end = date.today()
    start = end - timedelta(days=days * 2)
    url = f"{POLYGON_BASE}/v2/aggs/ticker/{poly_ticker}/range/1/day/{start}/{end}"
    params = {
        "adjusted": "true",
        "sort": "asc",
        "limit": 5000,
        "apiKey": POLYGON_API_KEY,
    }
    data = safe_get(url, params=params)
    if not data or "results" not in data:
        return None
    return data["results"][-days:]


def build_technical_snapshot(ticker: str) -> Optional[TechnicalSnapshot]:
    bars = get_daily_bars(ticker)
    if not bars or len(bars) < 60:
        print(f"Not enough bars for {ticker}")
        return None

    closes = [float(b["c"]) for b in bars]
    highs = [float(b["h"]) for b in bars]
    lows = [float(b["l"]) for b in bars]
    vols = [float(b.get("v", 0)) for b in bars]

    price = closes[-1]
    prev_close = closes[-2]
    change_pct = ((price - prev_close) / prev_close) * 100 if prev_close else 0
    avg_vol_20 = statistics.mean(vols[-21:-1]) if len(vols) > 21 else statistics.mean(vols[:-1])
    rel_volume = vols[-1] / avg_vol_20 if avg_vol_20 else 1

    ema8 = ema(closes[-80:], 8)
    ema21 = ema(closes[-100:], 21)
    ema50 = ema(closes[-140:], 50)
    sma20 = sma(closes, 20)
    sma50 = sma(closes, 50)
    sma200 = sma(closes, 200)
    rsi14 = rsi(closes, 14)
    atr14 = atr(highs, lows, closes, 14)

    if ema21 > ema50 > sma200 and price > ema21:
        trend = "STRONG_BULL"
    elif ema21 > ema50 and price > ema50:
        trend = "BULL"
    elif ema21 < ema50 < sma200 and price < ema21:
        trend = "STRONG_BEAR"
    elif ema21 < ema50 and price < ema50:
        trend = "BEAR"
    else:
        trend = "MIXED"

    return TechnicalSnapshot(
        ticker=ticker,
        price=price,
        prev_close=prev_close,
        change_pct=change_pct,
        volume=vols[-1],
        rel_volume=rel_volume,
        sma_20=sma20,
        sma_50=sma50,
        sma_200=sma200,
        ema_8=ema8,
        ema_21=ema21,
        ema_50=ema50,
        rsi_14=rsi14,
        atr_14=atr14,
        trend=trend,
    )


def get_option_chain_snapshot(ticker: str, contract_type: Optional[str] = None, expiration_date: Optional[str] = None) -> List[Dict[str, Any]]:
    # For SPX index options, Polygon access/entitlements may differ. This function attempts normal endpoint.
    underlying = ticker
    url = f"{POLYGON_BASE}/v3/snapshot/options/{underlying}"
    params: Dict[str, Any] = {
        "limit": 250,
        "apiKey": POLYGON_API_KEY,
    }
    if contract_type:
        params["contract_type"] = contract_type
    if expiration_date:
        params["expiration_date"] = expiration_date

    results: List[Dict[str, Any]] = []
    while url:
        data = safe_get(url, params=params)
        if not data:
            break
        results.extend(data.get("results", []))
        next_url = data.get("next_url")
        if next_url:
            url = next_url
            params = {"apiKey": POLYGON_API_KEY}
        else:
            break
        if len(results) >= 1000:
            break
    return results


def extract_option_candidate(raw: Dict[str, Any], ticker: str) -> Optional[OptionCandidate]:
    details = raw.get("details", {}) or {}
    greeks = raw.get("greeks", {}) or {}
    day = raw.get("day", {}) or {}
    quote = raw.get("last_quote", {}) or {}

    exp = details.get("expiration_date")
    strike = details.get("strike_price")
    opt_type = details.get("contract_type")
    symbol = details.get("ticker")
    if not exp or strike is None or not opt_type or not symbol:
        return None

    bid = float(quote.get("bid", 0) or 0)
    ask = float(quote.get("ask", 0) or 0)
    close = float(day.get("close", 0) or 0)
    mid = (bid + ask) / 2 if bid > 0 and ask > 0 else close
    if mid <= 0:
        return None

    spread_pct = ((ask - bid) / mid) if bid > 0 and ask > 0 and mid > 0 else 0.50
    open_interest = raw.get("open_interest")
    volume = int(day.get("volume", 0) or 0)
    oi_val = int(open_interest or 0)
    liquidity_score = max(0, 100 - spread_pct * 200) + min(volume / 10, 25) + min(oi_val / 100, 25)
    liquidity_score = min(liquidity_score, 100)

    return OptionCandidate(
        ticker=ticker,
        option_symbol=symbol,
        option_type=opt_type.upper(),
        strike=float(strike),
        expiration_date=exp,
        dte=dte_from_expiration(exp),
        bid=bid,
        ask=ask,
        mid=round(mid, 2),
        delta=greeks.get("delta"),
        gamma=greeks.get("gamma"),
        iv=raw.get("implied_volatility"),
        open_interest=open_interest,
        volume=volume,
        liquidity_score=round(liquidity_score, 1),
    )


def find_best_option(
    ticker: str,
    direction: str,
    dte_range: Tuple[int, int],
    target_delta_range: Tuple[float, float],
) -> Optional[OptionCandidate]:
    contract_type = "call" if direction == "CALL" else "put"
    raw_chain = get_option_chain_snapshot(ticker, contract_type=contract_type)
    candidates: List[OptionCandidate] = []
    for raw in raw_chain:
        c = extract_option_candidate(raw, ticker)
        if not c:
            continue
        if not (dte_range[0] <= c.dte <= dte_range[1]):
            continue
        if c.delta is not None:
            abs_delta = abs(float(c.delta))
            if not (target_delta_range[0] <= abs_delta <= target_delta_range[1]):
                continue
        if c.liquidity_score < 40:
            continue
        candidates.append(c)

    if not candidates:
        return None

    def sort_key(c: OptionCandidate) -> Tuple[float, float, float]:
        delta_score = 0
        if c.delta is not None:
            midpoint = (target_delta_range[0] + target_delta_range[1]) / 2
            delta_score = -abs(abs(float(c.delta)) - midpoint)
        return (c.liquidity_score, delta_score, -c.mid)

    return sorted(candidates, key=sort_key, reverse=True)[0]


# =========================
# Benzinga functions
# =========================

def get_benzinga_news(ticker: str) -> List[Dict[str, Any]]:
    if not BENZINGA_API_KEY:
        return []
    url = f"{BENZINGA_BASE}/news"
    params = {
        "token": BENZINGA_API_KEY,
        "tickers": ticker,
        "displayOutput": "full",
        "pageSize": 10,
    }
    data = safe_get(url, params=params)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("data", []) or data.get("news", []) or []
    return []


def get_benzinga_uoa(ticker: str) -> List[Dict[str, Any]]:
    if not BENZINGA_API_KEY:
        return []
    # Endpoint path may vary by subscription. This is the documented calendar option activity pattern.
    url = f"{BENZINGA_BASE}/calendar/options_activity"
    params = {
        "token": BENZINGA_API_KEY,
        "parameters[tickers]": ticker,
        "pagesize": 20,
    }
    data = safe_get(url, params=params)
    if isinstance(data, dict):
        return data.get("option_activity", []) or data.get("data", []) or []
    if isinstance(data, list):
        return data
    return []


def score_catalyst(ticker: str) -> Tuple[float, List[str]]:
    score = 0.0
    notes: List[str] = []
    news = get_benzinga_news(ticker)
    uoa = get_benzinga_uoa(ticker)

    if news:
        score += min(len(news) * 5, 25)
        latest_titles = []
        for item in news[:3]:
            title = item.get("title") or item.get("headline")
            if title:
                latest_titles.append(title[:120])
        if latest_titles:
            notes.append("News: " + " | ".join(latest_titles))

    if uoa:
        score += min(len(uoa) * 4, 25)
        bullish = 0
        bearish = 0
        for item in uoa[:10]:
            sentiment = str(item.get("sentiment", "")).lower()
            put_call = str(item.get("put_call", item.get("option_type", ""))).lower()
            if "bull" in sentiment or put_call == "call":
                bullish += 1
            if "bear" in sentiment or put_call == "put":
                bearish += 1
        if bullish or bearish:
            notes.append(f"Benzinga UOA: bullish={bullish}, bearish={bearish}")

    return min(score, 100), notes


# =========================
# Scoring and strategy logic
# =========================

def score_technical(ts: TechnicalSnapshot, strategy: str) -> Tuple[float, str, List[str]]:
    notes: List[str] = []
    score = 0.0
    direction = "CALL"

    bullish = ts.trend in ("STRONG_BULL", "BULL")
    bearish = ts.trend in ("STRONG_BEAR", "BEAR")

    if bullish:
        direction = "CALL"
        score += 30 if ts.trend == "STRONG_BULL" else 22
    elif bearish:
        direction = "PUT"
        score += 30 if ts.trend == "STRONG_BEAR" else 22
    else:
        score += 8
        notes.append("Trend mixed; requires stronger catalyst/option confirmation.")

    # Pullback/re-entry logic for swing and leaps
    if strategy in ("SWING", "LEAP"):
        if direction == "CALL":
            distance_to_ema21 = abs(ts.price - ts.ema_21) / ts.price
            distance_to_ema50 = abs(ts.price - ts.ema_50) / ts.price
            if distance_to_ema21 <= 0.025:
                score += 25
                notes.append("Bullish pullback near EMA21.")
            elif distance_to_ema50 <= 0.035:
                score += 18
                notes.append("Bullish pullback near EMA50.")
            if 42 <= ts.rsi_14 <= 63:
                score += 18
                notes.append("RSI reset supports swing entry.")
            elif ts.rsi_14 > 70:
                score -= 10
                notes.append("RSI extended; avoid chasing.")
        else:
            distance_to_ema21 = abs(ts.price - ts.ema_21) / ts.price
            distance_to_ema50 = abs(ts.price - ts.ema_50) / ts.price
            if distance_to_ema21 <= 0.025 or distance_to_ema50 <= 0.035:
                score += 20
                notes.append("Bearish pullback/retest zone near moving averages.")
            if 37 <= ts.rsi_14 <= 58:
                score += 15
                notes.append("RSI reset supports bearish swing.")

    # 0DTE logic: momentum and volume-heavy
    if strategy == "0DTE":
        if abs(ts.change_pct) >= 0.5:
            score += 22
            notes.append("Market/index movement supports intraday momentum.")
        if ts.rel_volume >= 1.2:
            score += 20
            notes.append("Relative volume supports 0DTE interest.")
        if ts.price > ts.ema_8 > ts.ema_21:
            direction = "CALL"
            score += 20
            notes.append("Short-term trend favors calls.")
        elif ts.price < ts.ema_8 < ts.ema_21:
            direction = "PUT"
            score += 20
            notes.append("Short-term trend favors puts.")

    if ts.rel_volume >= 1.2:
        score += 12
    if ts.rel_volume >= 1.8:
        score += 8
        notes.append("High relative volume.")

    return max(0, min(score, 100)), direction, notes


def score_option(candidate: Optional[OptionCandidate]) -> Tuple[float, List[str]]:
    if not candidate:
        return 0.0, ["No suitable option contract found."]
    score = candidate.liquidity_score
    notes = [
        f"Selected {candidate.option_symbol}: mid={candidate.mid}, delta={candidate.delta}, IV={candidate.iv}, OI={candidate.open_interest}, vol={candidate.volume}."
    ]
    if candidate.mid <= 0:
        return 0.0, notes
    if candidate.bid > 0 and candidate.ask > 0:
        spread_pct = (candidate.ask - candidate.bid) / candidate.mid
        if spread_pct > 0.18:
            score -= 20
            notes.append("Wide bid/ask spread; use limit orders only.")
    return max(0, min(score, 100)), notes


def market_context_score(ts: TechnicalSnapshot) -> Tuple[float, List[str]]:
    score = 60.0
    notes: List[str] = []
    if ts.rel_volume >= 1.2:
        score += 15
    if abs(ts.change_pct) >= 1.0:
        score += 10
    if ts.trend in ("STRONG_BULL", "STRONG_BEAR"):
        score += 15
    return min(score, 100), notes


def determine_entry_zone(ts: TechnicalSnapshot, direction: str, strategy: str) -> str:
    if strategy == "0DTE":
        if direction == "CALL":
            return f"Trigger above {round(ts.price + ts.atr_14 * 0.15, 2)}; avoid if price loses EMA8."
        return f"Trigger below {round(ts.price - ts.atr_14 * 0.15, 2)}; avoid if price reclaims EMA8."
    if direction == "CALL":
        low = min(ts.ema_21, ts.price)
        high = max(ts.ema_21, ts.price)
        return f"{round(low, 2)} - {round(high, 2)} pullback/reclaim zone"
    low = min(ts.ema_21, ts.price)
    high = max(ts.ema_21, ts.price)
    return f"{round(low, 2)} - {round(high, 2)} rejection/retest zone"


def position_size(option_mid: float, stop_pct: float) -> int:
    if option_mid <= 0 or stop_pct <= 0:
        return 0
    risk_per_contract = option_mid * 100 * stop_pct
    return max(1, int(MAX_RISK_PER_TRADE // risk_per_contract)) if risk_per_contract <= MAX_RISK_PER_TRADE else 1


def build_trade_idea(ticker: str, ts: TechnicalSnapshot, strategy: str) -> Optional[TradeIdea]:
    tech_score, direction, tech_notes = score_technical(ts, strategy)
    catalyst, catalyst_notes = score_catalyst(ticker)
    context, context_notes = market_context_score(ts)

    if strategy == "SWING":
        dte_range = SWING_DTE_RANGE
        delta_range = (0.55, 0.75)
        stop_pct = 0.35
        targets = ["+35% option value", "+70% option value", "Trail remainder if trend expands"]
        strategy_name = "Pullback continuation / breakout re-entry"
    elif strategy == "0DTE":
        dte_range = ZERO_DTE_RANGE
        delta_range = (0.45, 0.65)
        stop_pct = 0.45
        targets = ["+25% option value", "+50% option value", "Hard exit before close"]
        strategy_name = "0DTE momentum / opening-range continuation"
    else:
        dte_range = LEAP_DTE_RANGE
        delta_range = (0.65, 0.85)
        stop_pct = 0.25
        targets = ["+25% partial", "+50% partial", "Hold core while trend remains above EMA50"]
        strategy_name = "LEAP accumulation on institutional trend"

    option = find_best_option(ticker, direction, dte_range, delta_range)
    options_score, option_notes = score_option(option)

    # Weighting based on user's priorities: Swing first, 0DTE second, LEAP third.
    if strategy == "SWING":
        total = tech_score * 0.40 + options_score * 0.25 + catalyst * 0.20 + context * 0.15
    elif strategy == "0DTE":
        total = tech_score * 0.45 + options_score * 0.25 + catalyst * 0.10 + context * 0.20
    else:
        total = tech_score * 0.35 + options_score * 0.20 + catalyst * 0.25 + context * 0.20

    if total < MIN_SCORE or not option:
        return None

    contracts = position_size(option.mid, stop_pct)
    entry_zone = determine_entry_zone(ts, direction, strategy)

    return TradeIdea(
        ticker=ticker,
        grade=grade_from_score(total),
        score=round(total, 1),
        trader_type=strategy,
        strategy=strategy_name,
        direction=direction,
        status="READY" if total >= 82 else "WATCH",
        entry_zone=entry_zone,
        option_contract=option.option_symbol,
        expiration=option.expiration_date,
        dte=option.dte,
        estimated_option_entry=option.mid,
        stop_loss=f"-{int(stop_pct * 100)}% option value or invalidation of entry zone",
        targets=targets,
        max_contracts=contracts,
        max_risk=MAX_RISK_PER_TRADE,
        technical_score=round(tech_score, 1),
        options_score=round(options_score, 1),
        catalyst_score=round(catalyst, 1),
        market_context_score=round(context, 1),
        notes=tech_notes + catalyst_notes + context_notes + option_notes,
        timestamp=now_et_iso(),
    )


def scan_ticker(ticker: str) -> List[TradeIdea]:
    ts = build_technical_snapshot(ticker)
    if not ts:
        return []

    strategies: List[str] = []
    if ticker in ("SPX", "SPY", "QQQ"):
        strategies.append("0DTE")
    strategies.extend(["SWING", "LEAP"])

    ideas: List[TradeIdea] = []
    for strategy in strategies:
        try:
            idea = build_trade_idea(ticker, ts, strategy)
            if idea:
                ideas.append(idea)
        except Exception as e:
            print(f"Failed {ticker} {strategy}: {e}")
    return ideas


def format_alert(idea: TradeIdea) -> str:
    notes = "\n".join([f"- {n}" for n in idea.notes[:5]])
    return (
        f"🔥 APEX ENGINE {idea.grade} SETUP\n"
        f"Ticker: {idea.ticker}\n"
        f"Type: {idea.trader_type}\n"
        f"Direction: {idea.direction}\n"
        f"Score: {idea.score}\n"
        f"Strategy: {idea.strategy}\n"
        f"Entry: {idea.entry_zone}\n"
        f"Option: {idea.option_contract}\n"
        f"Expiration: {idea.expiration} ({idea.dte} DTE)\n"
        f"Estimated Entry: ${idea.estimated_option_entry}\n"
        f"Stop: {idea.stop_loss}\n"
        f"Targets: {', '.join(idea.targets)}\n"
        f"Max Contracts: {idea.max_contracts}\n"
        f"Max Risk: ${idea.max_risk:.0f}\n"
        f"Status: {idea.status}\n"
        f"\nNotes:\n{notes}"
    )


def send_telegram_alert(message: str) -> bool:
    if not SEND_TELEGRAM:
        print("SEND_TELEGRAM=false; alert skipped.")
        return False
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram token/chat ID missing; alert skipped.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code >= 400:
            print(f"Telegram failed: {r.status_code} {r.text}")
            return False
        return True
    except Exception as e:
        print(f"Telegram error: {e}")
        return False


def run_scan() -> List[TradeIdea]:
    if not POLYGON_API_KEY:
        raise RuntimeError("POLYGON_API_KEY is required")

    all_ideas: List[TradeIdea] = []
    for ticker in SCAN_TICKERS:
        print(f"Scanning {ticker}...")
        ideas = scan_ticker(ticker)
        all_ideas.extend(ideas)
        time.sleep(0.25)  # gentle pacing for API limits

    # Qualified output only, sorted by score.
    all_ideas = sorted(all_ideas, key=lambda x: x.score, reverse=True)

    output = {
        "generated_at": now_et_iso(),
        "risk_model": {
            "capital_base": 60000,
            "max_risk_per_trade": MAX_RISK_PER_TRADE,
            "execution": "manual_power_etrade",
        },
        "ideas": [asdict(i) for i in all_ideas],
    }
    with open(DASHBOARD_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    for idea in all_ideas:
        # Alert only once per day for the same ticker/strategy/direction/contract.
        alert_key = f"{idea.ticker}:{idea.trader_type}:{idea.direction}:{idea.option_contract}"
        if idea.grade in ("A+", "A") and not already_alerted_today(alert_key):
            sent = send_telegram_alert(format_alert(idea))
            if sent or not SEND_TELEGRAM:
                mark_alerted_today(alert_key)

    return all_ideas


if __name__ == "__main__":
    ideas = run_scan()
    print(f"Scan complete. Qualified ideas: {len(ideas)}")
    for idea in ideas[:10]:
        print(f"{idea.grade} {idea.ticker} {idea.trader_type} {idea.direction} score={idea.score} option={idea.option_contract}")
