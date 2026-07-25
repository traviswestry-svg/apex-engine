"""APEX Trade Director Phase 38 — Institutional Intent & Flow Persistence.

Probabilistic, advisory-only interpretation of large option orders. The engine does
not assume calls are bullish or puts are bearish. It scores likely intent, present
relevance, expiration relevance, and Momentum Burst impact from supplied context.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

DB_PATH = Path(os.getenv("APEX_INSTITUTIONAL_INTENT_DB", "apex_institutional_intent.db"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _upper(value: Any, default: str = "UNKNOWN") -> str:
    text = str(value or default).strip().upper()
    return text or default


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS institutional_intent_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at TEXT NOT NULL,
          order_fingerprint TEXT NOT NULL,
          symbol TEXT NOT NULL,
          option_type TEXT NOT NULL,
          expiration TEXT,
          trade_age_minutes REAL,
          likely_intent TEXT NOT NULL,
          intent_confidence REAL NOT NULL,
          persistence_score REAL NOT NULL,
          expiration_relevance REAL NOT NULL,
          current_influence TEXT NOT NULL,
          momentum_impact TEXT NOT NULL,
          directional_value REAL NOT NULL,
          payload_json TEXT NOT NULL,
          result_json TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_intent_fingerprint
          ON institutional_intent_events(order_fingerprint);
        CREATE INDEX IF NOT EXISTS idx_intent_created
          ON institutional_intent_events(created_at DESC);
        """
    )
    return con


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _days_to_expiration(expiration: Any, now: datetime) -> Optional[float]:
    dt = _parse_dt(expiration)
    if dt is None:
        try:
            dt = datetime.fromisoformat(str(expiration)).replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None
    return max(0.0, (dt - now).total_seconds() / 86400.0)


def _trade_age_minutes(order: Mapping[str, Any], now: datetime) -> float:
    explicit = order.get("trade_age_minutes")
    if explicit is not None:
        return max(0.0, _num(explicit))
    ts = _parse_dt(order.get("trade_time") or order.get("timestamp") or order.get("created_at"))
    return max(0.0, (now - ts).total_seconds() / 60.0) if ts else 0.0


def expiration_bucket(dte: Optional[float]) -> str:
    if dte is None:
        return "UNKNOWN"
    if dte <= 1:
        return "0DTE_1DTE"
    if dte <= 7:
        return "WEEKLY"
    if dte <= 35:
        return "1_5_WEEKS"
    if dte <= 180:
        return "2_6_MONTHS"
    if dte <= 365:
        return "6_12_MONTHS"
    return "LEAPS"


def expiration_relevance_score(dte: Optional[float], trade_function: str = "MOMENTUM_BURST") -> float:
    bucket = expiration_bucket(dte)
    tf = _upper(trade_function)
    if tf in {"MOMENTUM_BURST", "QUICK_SCALP", "SCALP_15M"}:
        scores = {"0DTE_1DTE": 100, "WEEKLY": 82, "1_5_WEEKS": 55, "2_6_MONTHS": 28,
                  "6_12_MONTHS": 16, "LEAPS": 8, "UNKNOWN": 25}
    elif tf in {"SCALP_30M", "INTRADAY"}:
        scores = {"0DTE_1DTE": 92, "WEEKLY": 88, "1_5_WEEKS": 68, "2_6_MONTHS": 42,
                  "6_12_MONTHS": 24, "LEAPS": 12, "UNKNOWN": 30}
    else:
        scores = {"0DTE_1DTE": 35, "WEEKLY": 55, "1_5_WEEKS": 78, "2_6_MONTHS": 92,
                  "6_12_MONTHS": 88, "LEAPS": 84, "UNKNOWN": 35}
    return float(scores[bucket])


def persistence_score(order: Mapping[str, Any], context: Mapping[str, Any], *, now: Optional[datetime] = None) -> float:
    current = now or _now()
    age = _trade_age_minutes(order, current)
    dte = _days_to_expiration(order.get("expiration"), current)
    age_half_life = 45.0 if (dte is not None and dte <= 1.0) else 240.0 if (dte is not None and dte <= 7) else 1440.0
    age_component = 100.0 * math.exp(-math.log(2) * age / max(1.0, age_half_life))

    strike = _num(order.get("strike"))
    spot = _num(context.get("spot") or context.get("underlying_price"))
    if strike > 0 and spot > 0:
        distance_pct = abs(spot - strike) / spot * 100.0
        strike_component = _clamp(100.0 - distance_pct * 18.0)
    else:
        strike_component = 45.0

    oi_change = _num(order.get("open_interest_change") or context.get("open_interest_change"))
    oi_component = 75.0 if oi_change > 0 else 35.0 if oi_change < 0 else 50.0
    follow_through = _num(context.get("subsequent_flow_alignment"), 50.0)
    reaction = _num(context.get("market_reaction_alignment"), 50.0)
    catalyst_penalty = 18.0 if bool(context.get("major_catalyst_since_trade")) else 0.0

    return round(_clamp(age_component * 0.35 + strike_component * 0.20 + oi_component * 0.15 +
                        follow_through * 0.15 + reaction * 0.15 - catalyst_penalty), 2)


def infer_intent(order: Mapping[str, Any], context: Mapping[str, Any], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    current = now or _now()
    option_type = _upper(order.get("option_type") or order.get("type"))
    side = _upper(order.get("side") or order.get("execution_side") or order.get("at_bid_ask"))
    structure = _upper(order.get("structure") or order.get("trade_structure"), "SINGLE")
    trade_kind = _upper(order.get("trade_kind") or order.get("classification"), "BLOCK")
    dte = _days_to_expiration(order.get("expiration"), current)
    age = _trade_age_minutes(order, current)
    market_regime = _upper(context.get("market_regime") or context.get("trend_regime"))
    gamma = _upper(context.get("gamma_regime") or context.get("dealer_gamma_regime"))
    underlying_position = _upper(order.get("underlying_position") or context.get("underlying_position"), "UNKNOWN")
    opening = order.get("opening")
    opening_score = 1.0 if opening is True else -0.5 if opening is False else 0.0

    scores = {
        "DIRECTIONAL_BULLISH": 0.0,
        "DIRECTIONAL_BEARISH": 0.0,
        "PORTFOLIO_HEDGE": 0.0,
        "SHORT_HEDGE": 0.0,
        "VOLATILITY_TRADE": 0.0,
        "INCOME_OR_STRUCTURED": 0.0,
        "CLOSING_OR_ROLL": 0.0,
    }

    bought = side in {"ASK", "BOUGHT", "BUY", "ABOVE_ASK", "LIFTED_ASK"}
    sold = side in {"BID", "SOLD", "SELL", "BELOW_BID", "HIT_BID"}
    if option_type == "CALL":
        scores["DIRECTIONAL_BULLISH"] += 3.2 if bought else -0.4
        scores["DIRECTIONAL_BEARISH"] += 1.3 if sold else 0.0
        scores["SHORT_HEDGE"] += 2.8 if bought and underlying_position == "SHORT" else 0.0
    elif option_type == "PUT":
        scores["DIRECTIONAL_BEARISH"] += 3.2 if bought else -0.4
        scores["DIRECTIONAL_BULLISH"] += 1.3 if sold else 0.0
        scores["PORTFOLIO_HEDGE"] += 3.2 if bought and underlying_position in {"LONG", "LONG_PORTFOLIO", "UNKNOWN"} else 0.0

    if dte is not None and dte <= 1:
        scores["DIRECTIONAL_BULLISH"] += 1.0 if option_type == "CALL" and bought else 0.0
        scores["DIRECTIONAL_BEARISH"] += 1.0 if option_type == "PUT" and bought else 0.0
    if dte is not None and dte >= 60 and option_type == "PUT" and bought:
        scores["PORTFOLIO_HEDGE"] += 2.0
    if dte is not None and dte >= 180:
        scores["VOLATILITY_TRADE"] += 0.7
    if structure not in {"SINGLE", "BLOCK", "SWEEP", "UNKNOWN"}:
        scores["INCOME_OR_STRUCTURED"] += 3.0
        scores["VOLATILITY_TRADE"] += 1.0
    if trade_kind in {"SPREAD", "MULTI_LEG", "COMPLEX"}:
        scores["INCOME_OR_STRUCTURED"] += 2.5
    if opening is False:
        scores["CLOSING_OR_ROLL"] += 7.0
    if order.get("is_roll"):
        scores["CLOSING_OR_ROLL"] += 5.0
    if market_regime in {"BULL_TREND", "RISK_ON", "UPTREND"} and option_type == "PUT" and bought:
        scores["PORTFOLIO_HEDGE"] += 1.4
    if market_regime in {"BEAR_TREND", "RISK_OFF", "DOWNTREND"} and option_type == "CALL" and bought:
        scores["SHORT_HEDGE"] += 1.4
    if gamma in {"NEGATIVE", "NEGATIVE_GAMMA"} and dte is not None and dte <= 7 and bought:
        directional = "DIRECTIONAL_BULLISH" if option_type == "CALL" else "DIRECTIONAL_BEARISH"
        scores[directional] += 0.9
    for key in scores:
        scores[key] += opening_score

    floor_scores = {k: max(0.05, v + 0.5) for k, v in scores.items()}
    total = sum(floor_scores.values())
    probabilities = {k: round(v / total * 100.0, 1) for k, v in floor_scores.items()}
    likely_intent = max(probabilities, key=probabilities.get)
    confidence = probabilities[likely_intent]
    return {
        "likely_intent": likely_intent,
        "intent_confidence": confidence,
        "intent_probabilities": probabilities,
        "trade_age_minutes": round(age, 2),
        "days_to_expiration": round(dte, 2) if dte is not None else None,
        "expiration_bucket": expiration_bucket(dte),
        "inputs": {"option_type": option_type, "side": side, "structure": structure,
                   "market_regime": market_regime, "gamma_regime": gamma},
        "uncertainty_note": "Intent is probabilistic; public flow cannot prove beneficial ownership or full multi-leg context.",
    }


def evaluate_large_order(order: Mapping[str, Any], context: Optional[Mapping[str, Any]] = None,
                         *, trade_function: str = "MOMENTUM_BURST", now: Optional[datetime] = None,
                         persist: bool = True) -> Dict[str, Any]:
    ctx = dict(context or {})
    current = now or _now()
    intent = infer_intent(order, ctx, now=current)
    persistence = persistence_score(order, ctx, now=current)
    expiry_relevance = expiration_relevance_score(intent.get("days_to_expiration"), trade_function)
    influence_score = _clamp(persistence * 0.62 + expiry_relevance * 0.38)
    influence = "VERY_HIGH" if influence_score >= 85 else "HIGH" if influence_score >= 70 else "MODERATE" if influence_score >= 45 else "LOW"

    directional_map = {
        "DIRECTIONAL_BULLISH": 1.0, "DIRECTIONAL_BEARISH": -1.0,
        "PORTFOLIO_HEDGE": 0.15, "SHORT_HEDGE": -0.15,
        "VOLATILITY_TRADE": 0.0, "INCOME_OR_STRUCTURED": 0.0, "CLOSING_OR_ROLL": 0.0,
    }
    signed = directional_map.get(intent["likely_intent"], 0.0)
    directional_value = round(signed * influence_score * (intent["intent_confidence"] / 100.0), 2)
    if abs(directional_value) >= 55:
        momentum_impact = "STRONG_BULLISH" if directional_value > 0 else "STRONG_BEARISH"
    elif abs(directional_value) >= 25:
        momentum_impact = "SUPPORTIVE_BULLISH" if directional_value > 0 else "SUPPORTIVE_BEARISH"
    elif intent["likely_intent"] in {"PORTFOLIO_HEDGE", "SHORT_HEDGE"}:
        momentum_impact = "HEDGE_CONTEXT_ONLY"
    else:
        momentum_impact = "NEUTRAL_OR_UNCERTAIN"

    result = {
        "version": "PHASE_38",
        "symbol": _upper(order.get("symbol"), "SPX"),
        "option_type": _upper(order.get("option_type") or order.get("type")),
        "expiration": order.get("expiration"),
        "trade_function": _upper(trade_function),
        **intent,
        "persistence_score": persistence,
        "expiration_relevance_score": expiry_relevance,
        "current_influence_score": round(influence_score, 2),
        "current_influence": influence,
        "directional_value": directional_value,
        "momentum_burst_impact": momentum_impact,
        "advisory_only": True,
    }
    fingerprint_payload = {"order": dict(order), "context": ctx, "trade_function": trade_function}
    fp = hashlib.sha256(json.dumps(fingerprint_payload, sort_keys=True, default=str).encode()).hexdigest()
    result["order_fingerprint"] = fp
    if persist:
        with _connect() as con:
            con.execute(
                "INSERT OR IGNORE INTO institutional_intent_events(created_at,order_fingerprint,symbol,option_type,expiration,trade_age_minutes,likely_intent,intent_confidence,persistence_score,expiration_relevance,current_influence,momentum_impact,directional_value,payload_json,result_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (current.isoformat(), fp, result["symbol"], result["option_type"], str(result.get("expiration") or ""),
                 result["trade_age_minutes"], result["likely_intent"], result["intent_confidence"], persistence,
                 expiry_relevance, influence, momentum_impact, directional_value,
                 json.dumps(fingerprint_payload, sort_keys=True, default=str), json.dumps(result, sort_keys=True, default=str)),
            )
    return result


def evaluate_order_batch(orders: Iterable[Mapping[str, Any]], context: Optional[Mapping[str, Any]] = None,
                         *, trade_function: str = "MOMENTUM_BURST", persist: bool = True) -> Dict[str, Any]:
    results = [evaluate_large_order(o, context, trade_function=trade_function, persist=persist) for o in orders]
    weighted = sum(r["directional_value"] for r in results)
    high_influence = [r for r in results if r["current_influence"] in {"HIGH", "VERY_HIGH"}]
    return {
        "version": "PHASE_38",
        "order_count": len(results),
        "high_influence_count": len(high_influence),
        "net_directional_value": round(weighted, 2),
        "net_bias": "BULLISH" if weighted >= 25 else "BEARISH" if weighted <= -25 else "MIXED_OR_NEUTRAL",
        "orders": results,
        "advisory_only": True,
    }


def institutional_intent_status(limit: int = 25) -> Dict[str, Any]:
    with _connect() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT id,created_at,symbol,option_type,expiration,trade_age_minutes,likely_intent,intent_confidence,persistence_score,expiration_relevance,current_influence,momentum_impact,directional_value FROM institutional_intent_events ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 200)),),
        ).fetchall()]
    return {
        "version": "PHASE_38",
        "advisory_only": True,
        "history": rows,
        "last_assessment": rows[0] if rows else None,
        "assessment_count": len(rows),
        "execution_note": "Large call/put orders are interpreted probabilistically; no order is treated as directional by type alone.",
    }
