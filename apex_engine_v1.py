#!/usr/bin/env python3
"""
Apex Engine v1.2
Render-ready multi-stock scanner for Swing, 0DTE, and LEAP options ideas.

Data:
- Polygon: stock aggregates + options snapshot
- Benzinga: news + unusual options activity
- Telegram: alerts

Important:
- Qualified tickers only. No "NO TRADE" output.
- Alerts only; manual execution in Power E*TRADE.
"""

import os
import json
import math
import time
import hashlib
import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

import requests

# =============================
# CONFIG
# =============================
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "").strip()
BENZINGA_API_KEY = os.getenv("BENZINGA_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

ACCOUNT_SIZE = float(os.getenv("ACCOUNT_SIZE", "60000"))
MAX_RISK_PER_TRADE = float(os.getenv("MAX_RISK_PER_TRADE", "750"))

DASHBOARD_FILE = os.getenv("DASHBOARD_FILE", "dashboard_data.json")
ALERT_CACHE_FILE = os.getenv("ALERT_CACHE_FILE", "sent_alerts.json")

# Multi-stock scanner universe
TICKERS = [
    "SPY", "QQQ", "SPX", "NVDA", "TSLA", "META", "MSFT", "AAPL",
    "AMZN", "COIN", "AMD", "NFLX", "PLTR", "SMH", "QCOM", "NBIS"
]

ZERO_DTE_TICKERS = {"SPY", "QQQ", "SPX"}

# Strategy thresholds
MIN_SWING_SCORE = 72
MIN_ZERO_DTE_SCORE = 78
MIN_LEAP_SCORE = 75

REQUEST_TIMEOUT = 20

# =============================
# HELPERS
# =============================
def log(msg: str) -> None:
    print(msg, flush=True)


def today_et() -> dt.date:
    # Render runs UTC. This is good enough for date keys.
    return dt.datetime.utcnow().date()


def safe_get(url: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None, timeout: int = REQUEST_TIMEOUT) -> Optional[Any]:
    try:
        r = requests.get(url, params=params or {}, headers=headers or {}, timeout=timeout)
        if r.status_code >= 400:
            log(f"HTTP {r.status_code} for {r.url}: {r.text[:300]}")
            return None
        try:
            return r.json()
        except Exception:
            log(f"Request failed: {r.url} -> non-JSON response: {r.text[:300]}")
            return None
    except requests.exceptions.Timeout:
        log(f"Request timeout: {url}")
        return None
    except Exception as e:
        log(f"Request failed: {url} -> {e}")
        return None


def load_json_file(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json_file(path: str, data: Any) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log(f"Could not save {path}: {e}")


def pct_change(a: float, b: float) -> float:
    if not a:
        return 0.0
    return ((b - a) / a) * 100.0


def ema(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    e = values[-period]
    for price in values[-period + 1:]:
        e = price * k + e * (1 - k)
    return e


def rsi(values: List[float], period: int = 14) -> Optional[float]:
    if len(values) < period + 1:
        return None
    gains, losses = [], []
    for i in range(-period, 0):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def average(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def normalize_ticker_for_polygon(ticker: str) -> str:
    # Polygon indices may vary by subscription. SPX options are complex.
    # For early engine stability, use SPY proxy for SPX technicals unless index entitlement exists.
    if ticker == "SPX":
        return "SPY"
    return ticker

# =============================
# POLYGON DATA
# =============================
def polygon_daily_bars(ticker: str, days: int = 260) -> List[Dict[str, Any]]:
    if not POLYGON_API_KEY:
        log("Missing POLYGON_API_KEY")
        return []

    poly_ticker = normalize_ticker_for_polygon(ticker)
    end = today_et()
    start = end - dt.timedelta(days=days + 30)
    url = f"https://api.polygon.io/v2/aggs/ticker/{poly_ticker}/range/1/day/{start}/{end}"
    params = {
        "adjusted": "true",
        "sort": "asc",
        "limit": 5000,
        "apiKey": POLYGON_API_KEY,
    }
    data = safe_get(url, params=params)
    if not data or data.get("status") not in {"OK", "DELAYED"}:
        return []
    return data.get("results", []) or []


def polygon_intraday_bars(ticker: str, minutes: int = 5, days_back: int = 2) -> List[Dict[str, Any]]:
    if not POLYGON_API_KEY:
        return []
    poly_ticker = normalize_ticker_for_polygon(ticker)
    end = today_et()
    start = end - dt.timedelta(days=days_back)
    url = f"https://api.polygon.io/v2/aggs/ticker/{poly_ticker}/range/{minutes}/minute/{start}/{end}"
    params = {
        "adjusted": "true",
        "sort": "asc",
        "limit": 5000,
        "apiKey": POLYGON_API_KEY,
    }
    data = safe_get(url, params=params)
    if not data or data.get("status") not in {"OK", "DELAYED"}:
        return []
    return data.get("results", []) or []


def polygon_options_snapshot(ticker: str, dte_min: int, dte_max: int, limit: int = 100) -> List[Dict[str, Any]]:
    """Fetch a filtered options snapshot to avoid pulling huge full chains/timeouts."""
    if not POLYGON_API_KEY:
        return []

    # SPX option snapshot entitlement/symbols can vary. Start stable with SPY proxy for 0DTE.
    underlying = "SPY" if ticker == "SPX" else ticker
    today = today_et()
    exp_gte = today + dt.timedelta(days=dte_min)
    exp_lte = today + dt.timedelta(days=dte_max)

    url = f"https://api.polygon.io/v3/snapshot/options/{underlying}"
    params = {
        "apiKey": POLYGON_API_KEY,
        "limit": limit,
        "expiration_date.gte": str(exp_gte),
        "expiration_date.lte": str(exp_lte),
        "sort": "expiration_date",
        "order": "asc",
    }

    results: List[Dict[str, Any]] = []
    data = safe_get(url, params=params, timeout=REQUEST_TIMEOUT)
    if not data:
        return []
    results.extend(data.get("results", []) or [])
    return results

# =============================
# BENZINGA DATA
# =============================
import xml.etree.ElementTree as ET

def parse_benzinga_response(r):
    try:
        return r.json()
    except:
        try:
            root = ET.fromstring(r.text)
            data = []
            for item in root.findall(".//item"):
                entry = {}
                for child in item:
                    entry[child.tag] = child.text
                data.append(entry)
            return data
        except:
            return []

# Benzinga News
def get_benzinga_news():
    url = "https://api.benzinga.com/api/v2/news"
    headers = {"Accept": "application/json"}
    params = {"token": BENZINGA_API_KEY}

    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        return parse_benzinga_response(r)
    except Exception as e:
        print(f"Benzinga news error: {e}")
        return []

# Benzinga Option Activity
def get_benzinga_options_activity():
    url = "https://api.benzinga.com/api/v1/signal/option_activity"
    headers = {"Accept": "application/json"}
    params = {"token": BENZINGA_API_KEY}

    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        return parse_benzinga_response(r)
    except Exception as e:
        print(f"Benzinga options error: {e}")
        return []
# =============================
# SCORING
# =============================
def technical_snapshot(ticker: str) -> Optional[Dict[str, Any]]:
    bars = polygon_daily_bars(ticker)
    if len(bars) < 60:
        return None

    closes = [float(b["c"]) for b in bars if "c" in b]
    volumes = [float(b.get("v", 0)) for b in bars]
    highs = [float(b.get("h", 0)) for b in bars]
    lows = [float(b.get("l", 0)) for b in bars]

    price = closes[-1]
    ema8 = ema(closes, 8)
    ema21 = ema(closes, 21)
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200) if len(closes) >= 200 else None
    rsival = rsi(closes, 14)
    avg_vol20 = average(volumes[-21:-1])
    rel_vol = volumes[-1] / avg_vol20 if avg_vol20 else 0.0

    atr14_values = []
    for i in range(-14, 0):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        atr14_values.append(tr)
    atr = average(atr14_values)

    return {
        "ticker": ticker,
        "price": price,
        "ema8": ema8,
        "ema21": ema21,
        "ema50": ema50,
        "ema200": ema200,
        "rsi": rsival,
        "rel_volume": rel_vol,
        "atr": atr,
        "day_change_pct": pct_change(closes[-2], closes[-1]) if len(closes) > 1 else 0,
        "high_20": max(highs[-20:]),
        "low_20": min(lows[-20:]),
        "closes": closes,
    }


def score_catalyst(news: List[Dict[str, Any]], activity: List[Dict[str, Any]]) -> Tuple[int, List[str]]:
    score = 0
    notes: List[str] = []

    if news:
        score += min(15, len(news) * 3)
        titles = []
        for item in news[:2]:
            title = item.get("title") or item.get("headline") or "Benzinga headline"
            titles.append(str(title)[:120])
        if titles:
            notes.append("News: " + " | ".join(titles))

    bullish_flow = 0
    bearish_flow = 0
    for item in activity[:25]:
        txt = json.dumps(item).lower()
        if "call" in txt and any(x in txt for x in ["sweep", "ask", "bull", "buy"]):
            bullish_flow += 1
        if "put" in txt and any(x in txt for x in ["sweep", "ask", "bear", "buy"]):
            bearish_flow += 1

    if bullish_flow:
        score += min(15, bullish_flow * 3)
        notes.append(f"Bullish UOA count: {bullish_flow}")
    if bearish_flow:
        score -= min(10, bearish_flow * 2)
        notes.append(f"Bearish UOA count: {bearish_flow}")

    return max(0, min(25, score)), notes


def choose_option_contract(ticker: str, direction: str, strategy: str, price: float) -> Optional[Dict[str, Any]]:
    if strategy == "0DTE":
        dte_min, dte_max = 0, 1
        target_delta_low, target_delta_high = 0.45, 0.70
    elif strategy == "LEAP":
        dte_min, dte_max = 90, 365
        target_delta_low, target_delta_high = 0.65, 0.85
    else:
        dte_min, dte_max = 7, 30
        target_delta_low, target_delta_high = 0.55, 0.75

    chain = polygon_options_snapshot(ticker, dte_min, dte_max, limit=150)
    if not chain:
        return None

    call_put = "call" if direction == "CALL" else "put"
    best = None
    best_score = -999

    for c in chain:
        details = c.get("details", {}) or {}
        if str(details.get("contract_type", "")).lower() != call_put:
            continue

        greeks = c.get("greeks", {}) or {}
        delta = greeks.get("delta")
        if delta is None:
            continue
        delta_abs = abs(float(delta))
        if not (target_delta_low <= delta_abs <= target_delta_high):
            continue

        strike = float(details.get("strike_price", 0) or 0)
        exp = details.get("expiration_date")
        day = c.get("day", {}) or {}
        quote = c.get("last_quote", {}) or {}
        last_trade = c.get("last_trade", {}) or {}

        # Prefer mid, then last, then close.
        bid = float(quote.get("bid", 0) or 0)
        ask = float(quote.get("ask", 0) or 0)
        mid = (bid + ask) / 2 if bid and ask else 0
        last_price = float(last_trade.get("price", 0) or day.get("close", 0) or mid or 0)
        opt_price = mid or last_price
        if opt_price <= 0:
            continue

        oi = float(c.get("open_interest", 0) or 0)
        vol = float(day.get("volume", 0) or 0)
        spread_pct = ((ask - bid) / mid) * 100 if mid and ask and bid else 99

        # Liquidity + delta + spread selection.
        liquidity_score = min(30, math.log10(max(oi + vol, 1)) * 10)
        delta_score = 20 - abs(delta_abs - ((target_delta_low + target_delta_high) / 2)) * 100
        spread_score = max(0, 20 - spread_pct)
        strike_score = max(0, 20 - abs(strike - price) / max(price, 1) * 100)
        s = liquidity_score + delta_score + spread_score + strike_score

        if s > best_score:
            best_score = s
            best = {
                "symbol": details.get("ticker"),
                "strike": strike,
                "expiration": exp,
                "type": call_put.upper(),
                "delta": round(delta_abs, 2),
                "bid": round(bid, 2),
                "ask": round(ask, 2),
                "mid": round(mid, 2),
                "price": round(opt_price, 2),
                "open_interest": int(oi),
                "volume": int(vol),
                "spread_pct": round(spread_pct, 1),
            }

    return best


def position_size(option_price: float, stop_pct: float) -> Dict[str, Any]:
    risk_per_contract = option_price * 100 * stop_pct
    contracts = int(MAX_RISK_PER_TRADE // risk_per_contract) if risk_per_contract > 0 else 0
    return {
        "max_contracts": max(0, contracts),
        "risk_per_contract": round(risk_per_contract, 2),
        "max_risk": round(min(MAX_RISK_PER_TRADE, contracts * risk_per_contract), 2),
    }


def classify_setups(ticker: str, tech: Dict[str, Any], catalyst_score: int, catalyst_notes: List[str]) -> List[Dict[str, Any]]:
    ideas: List[Dict[str, Any]] = []
    price = tech["price"]
    ema8v, ema21v, ema50v, ema200v = tech["ema8"], tech["ema21"], tech["ema50"], tech["ema200"]
    rsival = tech["rsi"] or 50
    relvol = tech["rel_volume"]
    atr = tech["atr"]

    bullish_trend = ema8v and ema21v and ema50v and price > ema21v > ema50v
    long_trend = bullish_trend and (ema200v is None or price > ema200v)
    pullback_zone = ema21v and abs(price - ema21v) / price <= 0.035
    not_overheated = rsival < 68
    reset_good = 42 <= rsival <= 62
    volume_ok = relvol >= 0.90

    # Swing first: your primary edge.
    swing_score = 0
    swing_score += 25 if long_trend else 0
    swing_score += 20 if pullback_zone else 0
    swing_score += 15 if reset_good else 0
    swing_score += 10 if volume_ok else 0
    swing_score += catalyst_score

    if swing_score >= MIN_SWING_SCORE:
        direction = "CALL"
        opt = choose_option_contract(ticker, direction, "SWING", price)
        stop_pct = 0.40
        pos = position_size(opt["price"], stop_pct) if opt else {"max_contracts": 0, "risk_per_contract": 0, "max_risk": 0}
        ideas.append({
            "ticker": ticker,
            "grade": "A+" if swing_score >= 85 else "A",
            "score": round(swing_score, 1),
            "trader_type": "Swing Trader",
            "strategy": "Pullback continuation",
            "direction": direction,
            "stock_price": round(price, 2),
            "entry_zone": f"{round(ema21v - atr * 0.25, 2)} - {round(ema21v + atr * 0.35, 2)}" if ema21v else "Market confirmation required",
            "stop_strategy": "Exit if option loses 40% or stock closes below EMA21/EMA50 support",
            "targets": "+40% first target / +80% second target",
            "option": opt,
            "position": pos,
            "notes": catalyst_notes,
        })

    # 0DTE only for SPX/SPY/QQQ.
    if ticker in ZERO_DTE_TICKERS:
        intraday = polygon_intraday_bars(ticker, minutes=5, days_back=2)
        zero_score = 0
        if intraday and len(intraday) >= 10:
            closes = [float(b["c"]) for b in intraday]
            vols = [float(b.get("v", 0)) for b in intraday]
            intraday_ema8 = ema(closes, 8)
            intraday_ema21 = ema(closes, 21) or intraday_ema8
            momentum = closes[-1] > (intraday_ema8 or closes[-1]) > (intraday_ema21 or closes[-1])
            vol_spike = vols[-1] > average(vols[-10:-1]) * 1.25 if len(vols) > 12 else False
            zero_score += 30 if momentum else 0
            zero_score += 20 if vol_spike else 0
            zero_score += 15 if relvol >= 1.0 else 0
            zero_score += 15 if not_overheated else 0
            zero_score += min(15, catalyst_score)

            if zero_score >= MIN_ZERO_DTE_SCORE:
                direction = "CALL"
                opt = choose_option_contract(ticker, direction, "0DTE", price)
                stop_pct = 0.50
                pos = position_size(opt["price"], stop_pct) if opt else {"max_contracts": 0, "risk_per_contract": 0, "max_risk": 0}
                ideas.append({
                    "ticker": ticker,
                    "grade": "A+" if zero_score >= 88 else "A",
                    "score": round(zero_score, 1),
                    "trader_type": "0DTE Day Trader",
                    "strategy": "Momentum / opening range continuation",
                    "direction": direction,
                    "stock_price": round(price, 2),
                    "entry_zone": "Enter only after 5-minute confirmation above VWAP/ORB high",
                    "stop_strategy": "Exit if option loses 50% or price loses VWAP/ORB reclaim",
                    "targets": "+30% scalp / +60% runner",
                    "option": opt,
                    "position": pos,
                    "notes": catalyst_notes,
                })

    # LEAP third: lower-stress capital growth.
    leap_score = 0
    discount_from_20_high = pct_change(tech["high_20"], price)
    leap_score += 30 if long_trend else 0
    leap_score += 15 if -12 <= discount_from_20_high <= -2 else 0
    leap_score += 15 if 40 <= rsival <= 60 else 0
    leap_score += catalyst_score
    leap_score += 10 if relvol >= 0.8 else 0

    if leap_score >= MIN_LEAP_SCORE:
        direction = "CALL"
        opt = choose_option_contract(ticker, direction, "LEAP", price)
        stop_pct = 0.30
        pos = position_size(opt["price"], stop_pct) if opt else {"max_contracts": 0, "risk_per_contract": 0, "max_risk": 0}
        ideas.append({
            "ticker": ticker,
            "grade": "A+" if leap_score >= 88 else "A",
            "score": round(leap_score, 1),
            "trader_type": "LEAP Investor",
            "strategy": "Long-term trend pullback",
            "direction": direction,
            "stock_price": round(price, 2),
            "entry_zone": f"Accumulate near {round(ema50v, 2)} or confirmed support" if ema50v else "Wait for support confirmation",
            "stop_strategy": "Exit only if long-term trend breaks or thesis changes",
            "targets": "Scale at +50% / +100% or reassess monthly",
            "option": opt,
            "position": pos,
            "notes": catalyst_notes,
        })

    return ideas

# =============================
# ALERTS
# =============================
def alert_key(idea: Dict[str, Any]) -> str:
    raw = f"{today_et()}|{idea.get('ticker')}|{idea.get('trader_type')}|{idea.get('strategy')}|{idea.get('direction')}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def format_telegram_alert(idea: Dict[str, Any]) -> str:
    opt = idea.get("option") or {}
    pos = idea.get("position") or {}
    notes = idea.get("notes") or []

    option_line = "Option: Not selected"
    if opt:
        option_line = (
            f"Option: {opt.get('symbol')} | {opt.get('type')} {opt.get('strike')} | "
            f"Exp {opt.get('expiration')} | Mid ${opt.get('mid')} | Delta {opt.get('delta')}"
        )

    notes_line = "\n".join([f"- {n}" for n in notes[:3]]) if notes else "- No major catalyst note"

    return (
        f"🚨 APEX ENGINE {idea.get('grade')} SETUP\n"
        f"Ticker: {idea.get('ticker')}\n"
        f"Trader Type: {idea.get('trader_type')}\n"
        f"Strategy: {idea.get('strategy')}\n"
        f"Direction: {idea.get('direction')}\n"
        f"Score: {idea.get('score')}\n"
        f"Stock Price: ${idea.get('stock_price')}\n\n"
        f"ENTRY:\n{idea.get('entry_zone')}\n\n"
        f"{option_line}\n"
        f"Max Contracts: {pos.get('max_contracts', 0)}\n"
        f"Risk/Contract: ${pos.get('risk_per_contract', 0)}\n"
        f"Max Risk: ${pos.get('max_risk', 0)}\n\n"
        f"STOP:\n{idea.get('stop_strategy')}\n\n"
        f"TARGETS:\n{idea.get('targets')}\n\n"
        f"NOTES:\n{notes_line}"
    )


def send_telegram(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram token/chat id not set. Skipping alert.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    data = safe_get(url, params=payload, timeout=15)
    return bool(data and data.get("ok"))

# =============================
# MAIN
# =============================
def run_scan() -> List[Dict[str, Any]]:
    log("Apex Engine started")
    log(f"Account size: {ACCOUNT_SIZE} | Max risk/trade: {MAX_RISK_PER_TRADE}")

    all_ideas: List[Dict[str, Any]] = []

    for ticker in TICKERS:
        log(f"Scanning {ticker}...")
        tech = technical_snapshot(ticker)
        if not tech:
            continue

        news = benzinga_news(ticker)
        activity = benzinga_option_activity(ticker)
        catalyst_score, catalyst_notes = score_catalyst(news, activity)
        ideas = classify_setups(ticker, tech, catalyst_score, catalyst_notes)
        all_ideas.extend(ideas)
        time.sleep(0.2)

    # Only output qualified ideas. No NO TRADE records.
    all_ideas.sort(key=lambda x: x.get("score", 0), reverse=True)
    save_json_file(DASHBOARD_FILE, {"updated_at": dt.datetime.utcnow().isoformat(), "ideas": all_ideas})

    sent_cache = load_json_file(ALERT_CACHE_FILE, {})
    day_key = str(today_et())
    sent_today = set(sent_cache.get(day_key, []))

    for idea in all_ideas:
        key = alert_key(idea)
        if key in sent_today:
            continue
        if idea.get("grade") == "A+":
            ok = send_telegram(format_telegram_alert(idea))
            if ok:
                log(f"Telegram alert sent: {idea.get('ticker')} {idea.get('trader_type')}")
                sent_today.add(key)

    sent_cache[day_key] = sorted(list(sent_today))
    save_json_file(ALERT_CACHE_FILE, sent_cache)

    log(f"Scan complete. Qualified ideas: {len(all_ideas)}")
    return all_ideas


if __name__ == "__main__":
    try:
        run_scan()
    except Exception as e:
        log(f"Fatal error: {e}")
        raise
