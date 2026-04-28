#!/usr/bin/env python3
"""
Apex Engine v1.3 - Polygon Only
Render-ready multi-stock scanner for Swing, 0DTE, and LEAP option ideas.

Benzinga is disabled in this version.
Data source:
- Polygon: stock aggregates + options chain snapshots
- Telegram: alerts

Output:
- Qualified tickers only. No "NO TRADE" output.
- Alerts only; manual execution in Power E*TRADE.

Environment variables required:
POLYGON_API_KEY
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
MAX_RISK_PER_TRADE=750
ACCOUNT_SIZE=60000
"""

import os
import json
import math
import hashlib
import datetime as dt
from dataclasses import dataclass, asdict
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

DASHBOARD_FILE = os.getenv("DASHBOARD_FILE", "dashboard_data.json")
ALERT_CACHE_FILE = os.getenv("ALERT_CACHE_FILE", "sent_alerts.json")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))

POLYGON_BASE = "https://api.polygon.io"

TICKERS = [
    "SPY", "QQQ", "SPX", "NVDA", "TSLA", "META", "MSFT", "AAPL",
    "AMZN", "COIN", "AMD", "NFLX", "PLTR", "SMH", "QCOM", "NBIS"
]

ZERO_DTE_TICKERS = {"SPY", "QQQ", "SPX"}

MIN_SWING_SCORE = 72
MIN_ZERO_DTE_SCORE = 78
MIN_LEAP_SCORE = 75

# =============================
# DATA MODELS
# =============================
@dataclass
class TechnicalSnapshot:
    ticker: str
    price: float
    prev_close: float
    change_pct: float
    volume: float
    rel_volume: float
    ema8: float
    ema21: float
    ema50: float
    sma20: float
    sma50: float
    sma200: float
    rsi14: float
    atr14: float
    high_52w: float
    low_52w: float
    trend: str


@dataclass
class OptionPick:
    symbol: str
    contract_type: str
    strike: float
    expiration: str
    dte: int
    bid: float
    ask: float
    mid: float
    delta: Optional[float]
    gamma: Optional[float]
    iv: Optional[float]
    volume: int
    open_interest: int
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
    market_context_score: float
    notes: List[str]
    timestamp: str

# =============================
# HELPERS
# =============================
def log(message: str) -> None:
    print(message, flush=True)


def now_utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def mask_url(url: str) -> str:
    # Never print API keys or query strings.
    return url.split("?")[0]


def safe_get(url: str, params: Optional[Dict[str, Any]] = None, timeout: int = REQUEST_TIMEOUT) -> Optional[Any]:
    try:
        r = requests.get(url, params=params or {}, timeout=timeout)
        if r.status_code >= 400:
            log(f"HTTP {r.status_code} for {mask_url(url)}: {r.text[:250]}")
            return None
        try:
            return r.json()
        except Exception:
            log(f"Non-JSON response for {mask_url(url)}")
            return None
    except requests.exceptions.Timeout:
        log(f"Request timeout for {mask_url(url)}")
        return None
    except Exception as e:
        log(f"Request failed for {mask_url(url)}: {e}")
        return None


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


def ema(values: List[float], period: int) -> float:
    if not values:
        return 0.0
    if len(values) < period:
        period = len(values)
    k = 2 / (period + 1)
    result = values[-period]
    for v in values[-period + 1:]:
        result = v * k + result * (1 - k)
    return result


def sma(values: List[float], period: int) -> float:
    if not values:
        return 0.0
    if len(values) < period:
        return sum(values) / len(values)
    return sum(values[-period:]) / period


def rsi(values: List[float], period: int = 14) -> float:
    if len(values) <= period:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0.0))
        losses.append(abs(min(change, 0.0)))
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
        trs.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    if not trs:
        return 0.0
    return sum(trs[-period:]) / min(period, len(trs))


def grade_from_score(score: float) -> str:
    if score >= 90:
        return "A+"
    if score >= 82:
        return "A"
    if score >= 75:
        return "B+"
    return "B"


def dte(expiration: str) -> int:
    try:
        exp = dt.datetime.strptime(expiration, "%Y-%m-%d").date()
        return max((exp - dt.date.today()).days, 0)
    except Exception:
        return 999


def friday_dates(min_dte: int, max_dte: int, limit: int = 4) -> List[str]:
    today = dt.date.today()
    dates = []
    for days in range(min_dte, max_dte + 1):
        candidate = today + dt.timedelta(days=days)
        if candidate.weekday() == 4:  # Friday
            dates.append(candidate.isoformat())
        if len(dates) >= limit:
            break
    if not dates:
        target = today + dt.timedelta(days=min_dte)
        dates.append(target.isoformat())
    return dates


def monthly_dates(min_dte: int, max_dte: int, limit: int = 5) -> List[str]:
    today = dt.date.today()
    dates = []
    for days in range(min_dte, max_dte + 1):
        candidate = today + dt.timedelta(days=days)
        # Prefer Friday monthly expirations. This is not perfect, but it limits data pulls.
        if candidate.weekday() == 4 and 15 <= candidate.day <= 21:
            dates.append(candidate.isoformat())
        if len(dates) >= limit:
            break
    return dates or friday_dates(min_dte, max_dte, limit=limit)

# =============================
# POLYGON FUNCTIONS
# =============================
def polygon_price_ticker(ticker: str) -> str:
    return "I:SPX" if ticker == "SPX" else ticker


def polygon_options_underlying(ticker: str) -> str:
    # Polygon index option support varies by plan. Keep SPX as SPX and fail safely if not entitled.
    return ticker


def get_daily_bars(ticker: str, days: int = 260) -> Optional[List[Dict[str, Any]]]:
    if not POLYGON_API_KEY:
        log("Missing POLYGON_API_KEY")
        return None
    end = dt.date.today()
    start = end - dt.timedelta(days=days * 2)
    url = f"{POLYGON_BASE}/v2/aggs/ticker/{polygon_price_ticker(ticker)}/range/1/day/{start}/{end}"
    params = {
        "adjusted": "true",
        "sort": "asc",
        "limit": 5000,
        "apiKey": POLYGON_API_KEY,
    }
    data = safe_get(url, params=params)
    if not isinstance(data, dict) or "results" not in data:
        return None
    return data["results"][-days:]


def build_technical_snapshot(ticker: str) -> Optional[TechnicalSnapshot]:
    bars = get_daily_bars(ticker)
    if not bars or len(bars) < 60:
        log(f"Not enough daily bars for {ticker}")
        return None

    closes = [float(b["c"]) for b in bars]
    highs = [float(b["h"]) for b in bars]
    lows = [float(b["l"]) for b in bars]
    vols = [float(b.get("v", 0)) for b in bars]

    price = closes[-1]
    prev_close = closes[-2]
    change_pct = ((price - prev_close) / prev_close) * 100 if prev_close else 0.0
    avg_vol_20 = sma(vols[:-1], 20) if len(vols) > 21 else sma(vols, min(20, len(vols)))
    rel_volume = vols[-1] / avg_vol_20 if avg_vol_20 else 1.0

    ema8 = ema(closes, 8)
    ema21 = ema(closes, 21)
    ema50 = ema(closes, 50)
    sma20 = sma(closes, 20)
    sma50 = sma(closes, 50)
    sma200 = sma(closes, 200)
    rsi14 = rsi(closes, 14)
    atr14 = atr(highs, lows, closes, 14)
    high_52w = max(highs[-252:]) if len(highs) >= 252 else max(highs)
    low_52w = min(lows[-252:]) if len(lows) >= 252 else min(lows)

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
        price=round(price, 4),
        prev_close=round(prev_close, 4),
        change_pct=round(change_pct, 2),
        volume=vols[-1],
        rel_volume=round(rel_volume, 2),
        ema8=round(ema8, 4),
        ema21=round(ema21, 4),
        ema50=round(ema50, 4),
        sma20=round(sma20, 4),
        sma50=round(sma50, 4),
        sma200=round(sma200, 4),
        rsi14=round(rsi14, 2),
        atr14=round(atr14, 4),
        high_52w=round(high_52w, 4),
        low_52w=round(low_52w, 4),
        trend=trend,
    )


def extract_option_pick(raw: Dict[str, Any], tech: TechnicalSnapshot) -> Optional[OptionPick]:
    details = raw.get("details", {}) or {}
    day = raw.get("day", {}) or {}
    greeks = raw.get("greeks", {}) or {}
    quote = raw.get("last_quote", {}) or {}

    symbol = details.get("ticker") or raw.get("ticker")
    contract_type = details.get("contract_type")
    strike = details.get("strike_price")
    expiration = details.get("expiration_date")
    if not symbol or not contract_type or strike is None or not expiration:
        return None

    bid = float(quote.get("bid", 0) or 0)
    ask = float(quote.get("ask", 0) or 0)
    close_price = float(day.get("close", 0) or 0)
    mid = (bid + ask) / 2 if bid > 0 and ask > 0 else close_price
    if mid <= 0:
        return None

    volume = int(day.get("volume", 0) or raw.get("volume", 0) or 0)
    open_interest = int(raw.get("open_interest", 0) or 0)
    spread_pct = ((ask - bid) / mid) if bid > 0 and ask > 0 and mid > 0 else 0.50
    liquidity_score = max(0, min(100, (open_interest / 1000) * 35 + (volume / 500) * 35 + max(0, 30 - spread_pct * 100)))

    return OptionPick(
        symbol=symbol,
        contract_type=str(contract_type),
        strike=float(strike),
        expiration=str(expiration),
        dte=dte(str(expiration)),
        bid=round(bid, 2),
        ask=round(ask, 2),
        mid=round(mid, 2),
        delta=greeks.get("delta"),
        gamma=greeks.get("gamma"),
        iv=raw.get("implied_volatility"),
        volume=volume,
        open_interest=open_interest,
        liquidity_score=round(liquidity_score, 2),
    )


def get_option_candidates(ticker: str, direction: str, expirations: List[str], limit_per_exp: int = 250) -> List[OptionPick]:
    if not POLYGON_API_KEY:
        return []
    contract_type = "call" if direction == "CALL" else "put"
    underlying = polygon_options_underlying(ticker)
    candidates: List[OptionPick] = []

    for exp in expirations:
        url = f"{POLYGON_BASE}/v3/snapshot/options/{underlying}"
        params = {
            "apiKey": POLYGON_API_KEY,
            "expiration_date": exp,
            "contract_type": contract_type,
            "limit": limit_per_exp,
        }
        data = safe_get(url, params=params, timeout=REQUEST_TIMEOUT)
        if not isinstance(data, dict):
            continue
        results = data.get("results") or []
        for raw in results:
            pick = extract_option_pick(raw, None)  # tech unused here
            if pick:
                candidates.append(pick)
    return candidates


def select_best_option(ticker: str, tech: TechnicalSnapshot, direction: str, strategy: str) -> Optional[OptionPick]:
    if strategy == "0DTE":
        expirations = [dt.date.today().isoformat()]
        target_delta = 0.50
    elif strategy == "LEAP":
        expirations = monthly_dates(90, 365, limit=5)
        target_delta = 0.70
    else:
        expirations = friday_dates(7, 30, limit=4)
        target_delta = 0.62

    candidates = get_option_candidates(ticker, direction, expirations)
    if not candidates:
        log(f"No option candidates for {ticker} {strategy} {direction}")
        return None

    desired_abs_delta = target_delta
    def score_option(o: OptionPick) -> float:
        if o.delta is not None:
            delta_score = max(0, 100 - abs(abs(float(o.delta)) - desired_abs_delta) * 180)
        else:
            # Fallback: prefer slightly ITM/ATM if no greeks.
            moneyness = abs(o.strike - tech.price) / max(tech.price, 1)
            delta_score = max(0, 100 - moneyness * 500)
        liq = o.liquidity_score
        spread_penalty = 0
        if o.bid > 0 and o.ask > 0:
            spread_penalty = min(25, ((o.ask - o.bid) / max(o.mid, 0.01)) * 100)
        return delta_score * 0.60 + liq * 0.40 - spread_penalty

    candidates = [o for o in candidates if o.mid > 0]
    if not candidates:
        return None
    return sorted(candidates, key=score_option, reverse=True)[0]

# =============================
# SCORING
# =============================
def direction_from_trend(tech: TechnicalSnapshot) -> Optional[str]:
    if tech.trend in {"STRONG_BULL", "BULL"}:
        return "CALL"
    if tech.trend in {"STRONG_BEAR", "BEAR"}:
        return "PUT"
    return None


def score_swing(tech: TechnicalSnapshot) -> Tuple[float, Optional[str], List[str]]:
    direction = direction_from_trend(tech)
    notes: List[str] = []
    if not direction:
        return 0, None, notes

    score = 0.0
    if tech.trend in {"STRONG_BULL", "STRONG_BEAR"}:
        score += 28
        notes.append(f"Trend: {tech.trend}")
    else:
        score += 20
        notes.append(f"Trend: {tech.trend}")

    # Pullback quality.
    distance_to_ema21 = abs(tech.price - tech.ema21) / max(tech.price, 1) * 100
    distance_to_ema50 = abs(tech.price - tech.ema50) / max(tech.price, 1) * 100
    if distance_to_ema21 <= 2.5:
        score += 22
        notes.append("Pullback/retest near EMA21")
    elif distance_to_ema50 <= 3.5:
        score += 17
        notes.append("Deeper pullback/retest near EMA50")
    else:
        score += 8
        notes.append("Not at ideal pullback zone")

    if direction == "CALL" and 42 <= tech.rsi14 <= 68:
        score += 18
        notes.append("RSI supports bullish swing")
    elif direction == "PUT" and 32 <= tech.rsi14 <= 58:
        score += 18
        notes.append("RSI supports bearish swing")
    else:
        score += 6
        notes.append("RSI not ideal")

    if tech.rel_volume >= 1.2:
        score += 14
        notes.append(f"Relative volume {tech.rel_volume}x")
    elif tech.rel_volume >= 0.8:
        score += 8

    # Avoid extended entries.
    if abs(tech.price - tech.ema8) / max(tech.price, 1) * 100 <= 4:
        score += 10
    else:
        notes.append("Extension risk present")

    return min(score, 100), direction, notes


def score_zero_dte(tech: TechnicalSnapshot) -> Tuple[float, Optional[str], List[str]]:
    direction = direction_from_trend(tech)
    notes: List[str] = []
    if not direction:
        return 0, None, notes
    score = 0.0

    if tech.ticker in ZERO_DTE_TICKERS:
        score += 20
    else:
        return 0, None, notes

    if tech.trend in {"STRONG_BULL", "STRONG_BEAR"}:
        score += 24
        notes.append(f"0DTE trend bias: {tech.trend}")
    else:
        score += 12

    if tech.rel_volume >= 1.3:
        score += 18
        notes.append(f"Volume expansion {tech.rel_volume}x")
    elif tech.rel_volume >= 1.0:
        score += 10

    if abs(tech.change_pct) >= 0.35:
        score += 18
        notes.append(f"Directional move {tech.change_pct}%")

    if direction == "CALL" and tech.rsi14 > 55:
        score += 14
    elif direction == "PUT" and tech.rsi14 < 45:
        score += 14
    else:
        score += 4
        notes.append("RSI momentum not ideal for 0DTE")

    score += 6  # base liquidity assumption for index ETF/index products
    return min(score, 100), direction, notes


def score_leap(tech: TechnicalSnapshot) -> Tuple[float, Optional[str], List[str]]:
    direction = "CALL" if tech.price > tech.sma200 and tech.ema50 > tech.sma200 else None
    notes: List[str] = []
    if not direction:
        return 0, None, notes
    score = 0.0

    if tech.trend in {"STRONG_BULL", "BULL"}:
        score += 28
        notes.append("Long-term trend supports LEAP")

    drawdown_from_high = (tech.high_52w - tech.price) / max(tech.high_52w, 1) * 100
    if 5 <= drawdown_from_high <= 25:
        score += 24
        notes.append(f"Constructive pullback from 52w high: {drawdown_from_high:.1f}%")
    elif drawdown_from_high < 5:
        score += 10
        notes.append("Near highs; wait for better LEAP entry if possible")
    else:
        score += 12
        notes.append("Deep discount but higher risk")

    if 45 <= tech.rsi14 <= 65:
        score += 18
    elif tech.rsi14 < 70:
        score += 10

    if tech.price > tech.sma50 > tech.sma200:
        score += 18
    if tech.rel_volume >= 0.9:
        score += 8

    return min(score, 100), direction, notes


def option_score(option: Optional[OptionPick]) -> float:
    if not option:
        return 0
    score = 35
    score += min(30, option.liquidity_score * 0.30)
    if option.delta is not None:
        score += 15
    if option.iv is not None:
        score += 8
    if option.bid > 0 and option.ask > 0:
        spread = (option.ask - option.bid) / max(option.mid, 0.01)
        if spread <= 0.12:
            score += 12
        elif spread <= 0.25:
            score += 6
    return min(score, 100)


def build_entry_zone(tech: TechnicalSnapshot, direction: str, strategy: str) -> str:
    if strategy == "0DTE":
        if direction == "CALL":
            return f"Trigger above {round(max(tech.price, tech.ema8), 2)}; avoid chase if extended > 1 ATR"
        return f"Trigger below {round(min(tech.price, tech.ema8), 2)}; avoid chase if extended > 1 ATR"
    if strategy == "LEAP":
        return f"Scale near {round(tech.ema50, 2)}-{round(tech.ema21, 2)} or on confirmed weekly support"
    return f"Ideal pullback zone {round(tech.ema21, 2)}-{round(tech.ema50, 2)}"


def risk_model(option: OptionPick, strategy: str) -> Tuple[str, List[str], int, float]:
    stop_pct = 0.50 if strategy == "0DTE" else 0.40 if strategy == "SWING" else 0.30
    risk_per_contract = option.mid * stop_pct * 100
    contracts = max(1, math.floor(MAX_RISK_PER_TRADE / risk_per_contract)) if risk_per_contract > 0 else 0
    max_risk = round(contracts * risk_per_contract, 2)
    stop_text = f"Stop if option falls {int(stop_pct * 100)}% from entry (~${round(option.mid * (1 - stop_pct), 2)})"
    if strategy == "0DTE":
        targets = [f"+30% (${round(option.mid * 1.30, 2)})", f"+60% (${round(option.mid * 1.60, 2)})"]
    elif strategy == "LEAP":
        targets = ["Scale +25%", "Scale +50%", "Hold runner while weekly trend holds"]
    else:
        targets = [f"+40% (${round(option.mid * 1.40, 2)})", f"+80% (${round(option.mid * 1.80, 2)})"]
    return stop_text, targets, contracts, max_risk


def make_idea(ticker: str, tech: TechnicalSnapshot, strategy: str, base_score: float, direction: str, notes: List[str]) -> Optional[TradeIdea]:
    option = select_best_option(ticker, tech, direction, strategy)
    if not option:
        return None

    opt_score = option_score(option)
    market_context_score = 70 if ticker in {"SPY", "QQQ", "SPX"} else 60
    total_score = round(base_score * 0.68 + opt_score * 0.24 + market_context_score * 0.08, 2)

    threshold = MIN_ZERO_DTE_SCORE if strategy == "0DTE" else MIN_LEAP_SCORE if strategy == "LEAP" else MIN_SWING_SCORE
    if total_score < threshold:
        return None

    stop, targets, contracts, max_risk = risk_model(option, strategy)
    if contracts <= 0:
        return None

    option_contract = f"{option.symbol} | {option.expiration} {option.strike:g} {option.contract_type.upper()} | mid ${option.mid}"
    status = "READY" if total_score >= 82 else "WATCH"

    return TradeIdea(
        ticker=ticker,
        grade=grade_from_score(total_score),
        score=total_score,
        trader_type=strategy,
        strategy=("Pullback continuation" if strategy == "SWING" else "0DTE momentum" if strategy == "0DTE" else "LEAP accumulation"),
        direction=direction,
        status=status,
        entry_zone=build_entry_zone(tech, direction, strategy),
        option_contract=option_contract,
        expiration=option.expiration,
        dte=option.dte,
        estimated_option_entry=option.mid,
        stop_loss=stop,
        targets=targets,
        max_contracts=contracts,
        max_risk=max_risk,
        technical_score=round(base_score, 2),
        options_score=round(opt_score, 2),
        market_context_score=round(market_context_score, 2),
        notes=notes + [f"Option liquidity score {option.liquidity_score}", "Benzinga disabled: Polygon-only mode"],
        timestamp=now_utc_iso(),
    )


def scan_ticker(ticker: str) -> List[TradeIdea]:
    log(f"Scanning {ticker}...")
    tech = build_technical_snapshot(ticker)
    if not tech:
        return []

    ideas: List[TradeIdea] = []

    # Priority 1: Swing
    swing_score, swing_dir, swing_notes = score_swing(tech)
    if swing_dir and swing_score >= MIN_SWING_SCORE:
        idea = make_idea(ticker, tech, "SWING", swing_score, swing_dir, swing_notes)
        if idea:
            ideas.append(idea)

    # Priority 2: 0DTE for SPX/SPY/QQQ only
    if ticker in ZERO_DTE_TICKERS:
        z_score, z_dir, z_notes = score_zero_dte(tech)
        if z_dir and z_score >= MIN_ZERO_DTE_SCORE:
            idea = make_idea(ticker, tech, "0DTE", z_score, z_dir, z_notes)
            if idea:
                ideas.append(idea)

    # Priority 3: LEAP
    leap_score, leap
