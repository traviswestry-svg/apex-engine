from __future__ import annotations

import os
import json
import time
import threading
import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import Flask, jsonify, render_template_string

VERSION = "2.4_RENDER_WEB_DASHBOARD"

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

ACCOUNT_SIZE = float(os.getenv("ACCOUNT_SIZE", "60000"))
MAX_RISK_PER_TRADE = float(os.getenv("MAX_RISK_PER_TRADE", "750"))
SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))

TICKERS = [
    "SPY", "QQQ", "SPX",
    "NVDA", "TSLA", "META", "MSFT", "AAPL", "AMZN",
    "COIN", "AMD", "NFLX", "PLTR", "SMH", "QCOM", "NBIS"
]

app = Flask(__name__)

STATE: Dict[str, Any] = {
    "updated_at": None,
    "updated_at_et": None,
    "mode": VERSION,
    "account_size": ACCOUNT_SIZE,
    "max_risk_per_trade": MAX_RISK_PER_TRADE,
    "session": "STARTING",
    "ideas": [],
    "last_scan_status": "Starting scanner...",
    "last_error": None,
}

SENT_ALERTS: set[str] = set()


def now_et() -> dt.datetime:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        return dt.datetime.utcnow() - dt.timedelta(hours=4)


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


def valid_0dte_window() -> bool:
    n = now_et()
    minutes = n.hour * 60 + n.minute
    return 9 * 60 + 45 <= minutes <= 15 * 60 + 30


def safe_get_json(url: str, params: Optional[dict] = None, timeout: int = 15) -> Optional[dict]:
    params = params or {}
    if POLYGON_API_KEY:
        params["apiKey"] = POLYGON_API_KEY
    try:
        r = requests.get(url, params=params, timeout=timeout)
        if r.status_code != 200:
            print(f"HTTP {r.status_code} for {url}: {r.text[:220]}")
            return None
        return r.json()
    except Exception as e:
        print(f"Request failed {url}: {e}")
        return None


def ema(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
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
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def rel_volume(volumes: List[float], period: int = 20) -> float:
    if len(volumes) < period + 1:
        return 1.0
    avg = sum(volumes[-period-1:-1]) / period
    return volumes[-1] / avg if avg else 1.0


def get_daily_bars(ticker: str, days: int = 260) -> List[dict]:
    if ticker == "SPX":
        return []
    end = now_et().date()
    start = end - dt.timedelta(days=days * 2)
    url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}"
    data = safe_get_json(url, params={"adjusted": "true", "sort": "asc", "limit": 5000}, timeout=20)
    return data.get("results", []) if data else []


def get_intraday_bars(ticker: str, multiplier: int = 5, limit_days: int = 3) -> List[dict]:
    if ticker == "SPX":
        return []
    end = now_et().date()
    start = end - dt.timedelta(days=limit_days)
    url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/{multiplier}/minute/{start}/{end}"
    data = safe_get_json(url, params={"adjusted": "true", "sort": "asc", "limit": 5000}, timeout=15)
    return data.get("results", []) if data else []


def option_expiration_target(trader_type: str) -> Tuple[int, int]:
    if trader_type == "0DTE":
        return (0, 2)
    if trader_type == "SWING":
        return (7, 35)
    return (90, 365)


def estimated_delta(direction: str, strike: float, price: float) -> float:
    m = (price - strike) / price
    if direction == "CALL":
        return max(0.25, min(0.85, 0.55 + m * 4))
    return max(0.25, min(0.85, 0.55 - m * 4))


def pick_option_contract(ticker: str, direction: str, trader_type: str, price: float) -> Optional[dict]:
    if ticker == "SPX":
        return None

    contract_type = "call" if direction == "CALL" else "put"
    min_dte, max_dte = option_expiration_target(trader_type)
    today = now_et().date()

    url = f"https://api.polygon.io/v3/snapshot/options/{ticker}"
    data = safe_get_json(url, params={"contract_type": contract_type, "limit": 250}, timeout=20)
    if not data or "results" not in data:
        return None

    candidates = []
    for item in data.get("results", []):
        details = item.get("details", {})
        exp = details.get("expiration_date")
        strike = details.get("strike_price")
        opt_ticker = details.get("ticker")
        if not exp or strike is None or not opt_ticker:
            continue
        try:
            exp_date = dt.date.fromisoformat(exp)
        except Exception:
            continue
        dte = (exp_date - today).days
        if dte < min_dte or dte > max_dte:
            continue

        quote = item.get("last_quote") or {}
        bid = quote.get("bid")
        ask = quote.get("ask")
        day = item.get("day") or {}
        last_trade = item.get("last_trade") or {}
        fallback = last_trade.get("price") or day.get("close")

        if bid is None or ask is None or bid <= 0 or ask <= 0:
            if not fallback:
                continue
            mid = float(fallback)
            bid = round(mid * 0.95, 2)
            ask = round(mid * 1.05, 2)
        else:
            bid = float(bid)
            ask = float(ask)
            mid = (bid + ask) / 2

        if mid <= 0:
            continue
        spread_pct = (ask - bid) / mid
        oi = item.get("open_interest") or 0
        vol = day.get("volume") or 0

        if spread_pct > 0.25:
            continue
        if trader_type != "0DTE" and oi < 50:
            continue

        greeks = item.get("greeks") or {}
        delta = abs(greeks.get("delta") or estimated_delta(direction, float(strike), price))
        delta_target = 0.7 if trader_type == "LEAP" else (0.6 if trader_type == "SWING" else 0.5)
        strike_dist = abs(float(strike) - price) / price
        rank = abs(delta - delta_target) * 10 + strike_dist * 10 + spread_pct * 4 - min(oi, 2000) / 10000 - min(vol, 1000) / 10000

        candidates.append({
            "ticker": opt_ticker,
            "label": f"{opt_ticker} {exp} {float(strike):g} {direction}",
            "expiration": exp,
            "strike": float(strike),
            "dte": dte,
            "bid": round(float(bid), 2),
            "ask": round(float(ask), 2),
            "mid": round(float(mid), 2),
            "spread_pct": round(float(spread_pct), 3),
            "open_interest": oi,
            "volume": vol,
            "rank": rank,
        })

    if not candidates:
        return None
    candidates.sort(key=lambda x: x["rank"])
    return candidates[0]


def confidence_size_pct(score: float) -> int:
    if score >= 92:
        return 100
    if score >= 88:
        return 70
    return 50


def position_contracts(option_price: float, score: float) -> int:
    if option_price <= 0:
        return 0
    allowed_risk = MAX_RISK_PER_TRADE * (confidence_size_pct(score) / 100)
    risk_per_contract = option_price * 100 * 0.30
    return max(0, int(allowed_risk // risk_per_contract)) if risk_per_contract > 0 else 0


def position_plan(contracts: int) -> str:
    if contracts <= 0:
        return "No position."
    if contracts == 1:
        return "1 contract: take full/most at fast profit or Target 1; no partials."
    if contracts == 2:
        return "2 contracts: sell 1 at +20%/+35%, trail 1 runner."
    return "50% fast profit +20%, 30% Target 1 +35%, 20% runner."


def adaptive_exit_plan(trader_type: str, score: float) -> dict:
    strong = score >= 92
    if trader_type == "0DTE":
        return {
            "target_1": "+25% to +30% option - protect capital",
            "target_2": "+45% to +55% option gain - lock most gains",
            "fast_profit": "+20% option within 30-60 min - trim/protect immediately",
            "runner_rule": "Trail only while 5-min trend confirms.",
            "profit_protection": "After fast profit, move stop to breakeven.",
            "time_stop": "Hard exit by 3:30 PM ET.",
            "stop_loss": "Adaptive stop: early failure -10% to -15%; hard stop option -25% to -30% OR failed 5-min VWAP/EMA8 hold.",
            "targets": ["Fast Profit: +20%", "Target 1: +25% to +30%", "Target 2: +45% to +55%", "Hard exit: 3:30 PM ET"]
        }
    target2 = "+80% to +120% option gain - trend strong" if strong else "+60% to +70% option gain - lock majority"
    return {
        "target_1": "+35% option - protect capital",
        "target_2": target2,
        "fast_profit": "+20% option if achieved quickly - protect/trim, especially if market is choppy",
        "runner_rule": "Trail under EMA21 if trend remains intact." if strong else "Trail only if trend keeps confirming.",
        "profit_protection": "After +20% to +35%, reduce risk or move stop toward breakeven.",
        "time_stop": "If no follow-through in 2-3 candles/sessions, exit or reduce.",
        "stop_loss": "Adaptive stop: early thesis failure -10% to -15%; hard stop option -30% OR stock loses EMA200 / long-term thesis breaks" if trader_type == "LEAP" else "Adaptive stop: early failure -10% to -15%; hard stop option -30% to -35% OR daily close loses EMA21/EMA50 support",
        "targets": ["Fast Profit: +20%", "Target 1: +35%", f"Target 2: {target2}", "Runner: trail only if trend keeps confirming"]
    }


def sniper_confirmation(ticker: str, price: float, direction: str, daily_ema21: float, intraday: List[dict], trader_type: str) -> Tuple[str, str]:
    if session_status() != "MARKET_OPEN":
        return "WATCHLIST - OPEN CONFIRMATION NEEDED", "Market closed; wait for open confirmation."
    if trader_type == "0DTE" and not valid_0dte_window():
        return "WAIT - 0DTE WINDOW NOT ACTIVE", "0DTE requires 9:45-3:30 ET."
    if len(intraday) < 10:
        return "WAIT - INSUFFICIENT INTRADAY DATA", "Need more 5-min candles."

    closes = [float(x["c"]) for x in intraday]
    vols = [float(x.get("v", 0)) for x in intraday]
    e8 = ema(closes, 8)
    rv = rel_volume(vols, 10)
    last = intraday[-1]
    o, c, h, l = float(last["o"]), float(last["c"]), float(last["h"]), float(last["l"])
    if not e8:
        return "WAIT - NEED MORE DATA", "EMA8 not ready."

    vwap = sum(closes[-20:]) / min(len(closes), 20)
    if direction == "CALL":
        near_zone = c <= daily_ema21 * 1.025
        reclaim = c > e8 and c > vwap
        strong = c > o and (c - o) > max((h - l) * 0.35, 0.01)
        if near_zone and reclaim and strong and rv >= 1.1:
            return "READY - SNIPER PULLBACK CONFIRMED", "5-min close above VWAP/EMA8 with volume."
        if c > daily_ema21 * 1.035:
            return "EXTENDED - DO NOT CHASE", "Price too extended from EMA21."
        return "WAIT - WATCH FOR 5-MIN CLOSE ABOVE VWAP/EMA8", "Need 5-min reclaim and volume."

    near_zone = c >= daily_ema21 * 0.975
    reject = c < e8 and c < vwap
    strong = o > c and (o - c) > max((h - l) * 0.35, 0.01)
    if near_zone and reject and strong and rv >= 1.1:
        return "READY - SNIPER PUTBACK CONFIRMED", "5-min close below VWAP/EMA8 with volume."
    if c < daily_ema21 * 0.965:
        return "EXTENDED - DO NOT CHASE PUT", "Price too extended below EMA21."
    return "WAIT - WATCH FOR 5-MIN CLOSE BELOW VWAP/EMA8", "Need 5-min rejection and volume."


def confirmation_text(direction: str, trader_type: str) -> str:
    if trader_type == "0DTE":
        return "5-min close through VWAP/EMA8 after 9:45 ET, volume expansion, no chase."
    if direction == "CALL":
        return "Price reclaims EMA21/VWAP, strong green candle, relative volume confirms."
    return "Price rejects EMA21/VWAP, strong red candle, relative volume confirms."


def analyze_ticker(ticker: str) -> Optional[dict]:
    daily = get_daily_bars(ticker)
    if len(daily) < 60:
        if ticker == "SPX":
            print("SPX skipped until Polygon Indices entitlement is added.")
        return None

    closes = [float(x["c"]) for x in daily]
    volumes = [float(x.get("v", 0)) for x in daily]
    price = closes[-1]
    ema21 = ema(closes, 21)
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200) or ema50
    current_rsi = rsi(closes, 14)
    rv = rel_volume(volumes, 20)

    if not all([ema21, ema50, ema200, current_rsi]):
        return None

    bullish = price > ema50 and ema50 >= ema200
    bearish = price < ema50 and ema50 <= ema200
    if not bullish and not bearish:
        return None
    direction = "CALL" if bullish else "PUT"

    if ticker in ["SPY", "QQQ"] and valid_0dte_window():
        trader_type = "0DTE"
        strategy = "SPY/QQQ opening range sniper"
    elif bullish and price > ema200 and current_rsi >= 50:
        trader_type = "SWING"
        strategy = "Pullback / momentum continuation"
    elif price > ema200 and current_rsi >= 45:
        trader_type = "LEAP"
        strategy = "Long-term trend pullback"
    else:
        return None

    score = 70
    score += 6
    if abs(price - ema21) / ema21 <= 0.035:
        score += 8
    if rv >= 1.1:
        score += 4
    if 45 <= current_rsi <= 68:
        score += 6
    if trader_type == "0DTE":
        score += 3
    if score < 85:
        return None

    intraday = get_intraday_bars(ticker, 5, 3)
    status, trigger = sniper_confirmation(ticker, price, direction, ema21, intraday, trader_type)

    sess = session_status()
    if sess != "MARKET_OPEN":
        status = "WATCHLIST - OPEN CONFIRMATION NEEDED"
        trade_permission = "DO NOT TRADE"
        no_trade_reason = "Market not open; use as planning only."
    else:
        trade_permission = "TRUE" if status.startswith("READY") else "DO NOT TRADE"
        no_trade_reason = "" if trade_permission == "TRUE" else "Waiting for confirmation trigger."

    option = pick_option_contract(ticker, direction, trader_type, price)
    if not option:
        return None

    contracts = position_contracts(option.get("ask") or option.get("mid") or 0, score)
    if contracts <= 0:
        return None

    idea = {
        "ticker": ticker,
        "grade": "A+",
        "score": score,
        "trader_type": trader_type,
        "strategy": strategy,
        "direction": direction,
        "status": status,
        "trade_permission": trade_permission,
        "no_trade_reason": no_trade_reason,
        "sniper_trigger": trigger,
        "confirmation_trigger": confirmation_text(direction, trader_type),
        "entry_zone": f"Daily pullback zone near EMA21: {ema21:.2f}",
        "entry_range": f"{ema21 * 0.995:.2f} - {ema21 * 1.01:.2f}",
        "option_contract": option["label"],
        "option_ticker": option.get("ticker"),
        "estimated_option_entry": round(option.get("mid", 0), 2),
        "recommended_contracts": contracts,
        "confidence_size_pct": confidence_size_pct(score),
        "position_plan": position_plan(contracts),
        "price": round(price, 2),
        "ema21": round(ema21, 2),
        "ema50": round(ema50, 2),
        "ema200": round(ema200, 2),
        "rsi": round(current_rsi, 1),
        "rel_volume": round(rv, 2),
    }
    idea.update(adaptive_exit_plan(trader_type, score))
    return idea


def send_telegram(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"Telegram failed: {e}")
        return False


def maybe_alert(idea: dict) -> None:
    if session_status() != "MARKET_OPEN":
        return
    if idea.get("trade_permission") != "TRUE" or not idea.get("status", "").startswith("READY"):
        return
    key = f"{now_et().date()}-{idea['ticker']}-{idea['direction']}-{idea.get('option_ticker')}"
    if key in SENT_ALERTS:
        return
    text = (
        f"🚨 APEX A+ TRADE READY\n\n"
        f"Ticker: {idea['ticker']}\nType: {idea['trader_type']}\nDirection: {idea['direction']}\n"
        f"Status: {idea['status']}\nOption: {idea['option_contract']}\nContracts: {idea['recommended_contracts']}\n"
        f"Entry: {idea['entry_range']}\nFast Profit: {idea['fast_profit']}\nTarget 1: {idea['target_1']}\nStop: {idea['stop_loss']}"
    )
    if send_telegram(text):
        SENT_ALERTS.add(key)


def run_scan_once() -> None:
    print(f"🔥 APEX ENGINE VERSION {VERSION} LIVE - RENDER WEB DASHBOARD 🔥")
    print(f"Session: {session_status()} | Account: {ACCOUNT_SIZE} | Max risk: {MAX_RISK_PER_TRADE}")
    ideas = []
    for ticker in TICKERS:
        print(f"Scanning {ticker}...")
        try:
            idea = analyze_ticker(ticker)
            if idea:
                ideas.append(idea)
                maybe_alert(idea)
        except Exception as e:
            print(f"Error scanning {ticker}: {e}")

    ideas.sort(key=lambda x: (x.get("trade_permission") == "TRUE", x.get("score", 0)), reverse=True)
    STATE.update({
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "updated_at_et": now_et().strftime("%Y-%m-%d %I:%M:%S %p ET"),
        "mode": VERSION,
        "account_size": ACCOUNT_SIZE,
        "max_risk_per_trade": MAX_RISK_PER_TRADE,
        "session": session_status(),
        "ideas": ideas,
        "last_scan_status": f"Scan complete. Qualified ideas: {len(ideas)}",
        "last_error": None,
    })

    print(STATE["last_scan_status"])
    for i in ideas:
        print(f"{i['grade']} {i['ticker']} {i['trader_type']} {i['direction']} {i['status']} permission={i['trade_permission']} score={i['score']} rec_contracts={i['recommended_contracts']} option={i['option_contract']}")


def scanner_loop() -> None:
    time.sleep(3)
    while True:
        try:
            run_scan_once()
        except Exception as e:
            STATE["last_error"] = str(e)
            STATE["last_scan_status"] = "Scan failed"
            print(f"Fatal scan error: {e}")
        time.sleep(SCAN_INTERVAL_SECONDS)


HTML = """
<!DOCTYPE html>
<html>
<head>
<title>Apex Engine Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta http-equiv="refresh" content="60">
<style>
body{margin:0;font-family:Arial,sans-serif;background:#0f172a;color:white}.wrap{padding:18px;max-width:1100px;margin:auto}h1{color:#22c55e;font-size:32px;margin-bottom:8px}.meta{color:#cbd5e1;margin-bottom:18px;font-size:14px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}.card{background:#1e293b;border-left:6px solid #22c55e;border-radius:12px;padding:16px;box-shadow:0 6px 18px rgba(0,0,0,.25)}.top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.ticker{font-size:26px;font-weight:800}.grade{color:#22c55e}.badge{display:inline-block;padding:4px 8px;border-radius:999px;background:#334155;color:#e2e8f0;font-size:12px;margin:2px 4px 2px 0}.ready{background:#14532d;color:#bbf7d0}.wait{background:#713f12;color:#fde68a}.no{background:#7f1d1d;color:#fecaca}.section{margin-top:12px;line-height:1.35}.label{color:#94a3b8;font-size:12px;text-transform:uppercase;letter-spacing:.05em}.value{font-size:15px}.small{font-size:13px;color:#cbd5e1}.empty{background:#1e293b;border-radius:12px;padding:18px;color:#cbd5e1}
</style>
</head>
<body>
<div class="wrap">
<h1>Apex Engine Dashboard</h1>
<div class="meta">Version: {{ data.mode }} | Session: {{ data.session }} | Updated: {{ data.updated_at_et or data.updated_at }} | {{ data.last_scan_status }}</div>
{% if data.ideas|length == 0 %}<div class="empty">No valid A+ tradeable setups right now. No valid contract = hidden.</div>{% endif %}
<div class="grid">
{% for idea in data.ideas %}
{% set status_class = 'ready' if idea.trade_permission == 'TRUE' else ('wait' if 'WAIT' in idea.status or 'WATCHLIST' in idea.status else 'no') %}
<div class="card">
<div class="top"><div><div class="ticker">{{ idea.ticker }} <span class="grade">{{ idea.grade }}</span></div><span class="badge">{{ idea.trader_type }}</span><span class="badge">{{ idea.direction }}</span><span class="badge {{ status_class }}">{{ idea.status }}</span></div><div class="small">Score: {{ idea.score }}</div></div>
<div class="section"><div class="label">Strategy</div><div class="value">{{ idea.strategy }}</div></div>
<div class="section"><div class="label">Trade Permission</div><div class="value">{{ idea.trade_permission }}</div></div>
{% if idea.no_trade_reason %}<div class="section"><div class="label">No Trade Reason</div><div class="value">{{ idea.no_trade_reason }}</div></div>{% endif %}
<div class="section"><div class="label">Entry Range</div><div class="value">{{ idea.entry_range }}</div></div>
<div class="section"><div class="label">Sniper Trigger</div><div class="value">{{ idea.sniper_trigger }}</div></div>
<div class="section"><div class="label">Option</div><div class="value">{{ idea.option_contract }}</div></div>
<div class="section"><div class="label">Recommended Contracts</div><div class="value">{{ idea.recommended_contracts }} | Confidence Size: {{ idea.confidence_size_pct }}%</div></div>
<div class="section"><div class="label">Position Plan</div><div class="value">{{ idea.position_plan }}</div></div>
<div class="section"><div class="label">Targets</div><div class="value">{% for t in idea.targets %}• {{ t }}<br>{% endfor %}</div></div>
<div class="section"><div class="label">Stop</div><div class="value">{{ idea.stop_loss }}</div></div>
<div class="section"><div class="label">Time Stop</div><div class="value">{{ idea.time_stop }}</div></div>
</div>
{% endfor %}
</div></div></body></html>
"""

@app.route("/")
def dashboard():
    return render_template_string(HTML, data=STATE)

@app.route("/dashboard.json")
def dashboard_json():
    return jsonify(STATE)

@app.route("/health")
def health():
    return jsonify({"ok": True, "mode": VERSION, "updated_at": STATE.get("updated_at")})
@app.route("/test-telegram")
def test_telegram():
    ok = send_telegram("🚨 TEST ALERT: Apex Engine Telegram is working")
    return {"success": ok}
if __name__ == "__main__":
    print(f"Starting Apex Engine web dashboard {VERSION}")
    t = threading.Thread(target=scanner_loop, daemon=True)
    t.start()
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
