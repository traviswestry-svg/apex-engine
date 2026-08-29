"""APEX 69.5.0 — Multi-Horizon ES Tick Momentum Intelligence.

Observational transaction-momentum model using genuine individual ES/MES trades.
It never treats aggregate OHLCV bars as ticks or L2/MBO depth and has no
trade-decision or execution authority.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

VERSION = "69.6.2"
SCHEMA_VERSION = "apex.tick_momentum.v1"
HORIZONS = (233, 512, 1000, 2000)
WEIGHTS = {233: 1, 512: 2, 1000: 2, 2000: 3}
ET = ZoneInfo("America/New_York")


def initial_state(instrument: str = "ES") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "version": VERSION,
        "instrument": instrument.upper(),
        "session_date": None,
        "last_trade_price": None,
        "last_trade_at": None,
        "transactions_seen": 0,
        "outside_rth_skipped": 0,
        "horizons": {str(h): {"count": 0, "open": None, "high": None, "low": None,
                                     "close": None, "up_size": 0.0, "down_size": 0.0,
                                     "ema": None, "state": "NEUTRAL", "raw": 0.0,
                                     "buckets_closed": 0} for h in HORIZONS},
        "alignment": {"score": 0, "state": "MIXED", "bullish_points": 0, "bearish_points": 0,
                      "disagreement": True},
    }


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            raise ValueError("transaction observed_at/timestamp is required")
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError("transaction timestamp must include timezone/UTC offset")
    return dt.astimezone(timezone.utc)


def _rth(dt: datetime) -> tuple[bool, str]:
    et = dt.astimezone(ET)
    minute = et.hour * 60 + et.minute
    return 570 <= minute < 960, et.date().isoformat()


def validate_transactions(records: Any, *, instrument: str = "ES") -> list[dict[str, Any]]:
    if instrument.upper() not in {"ES", "MES"}:
        raise ValueError("tick momentum accepts ES or MES only")
    if not isinstance(records, list) or not records:
        raise ValueError("non-empty transactions array required")
    out: list[dict[str, Any]] = []
    for row in records:
        if not isinstance(row, Mapping):
            raise ValueError("each transaction must be an object")
        # Explicitly reject aggregate-bar substitution.
        if any(k in row for k in ("open", "high", "low", "close", "bar_interval", "timeframe")):
            raise ValueError("aggregate OHLC/timeframe bars are not accepted as tick transactions")
        price = row.get("price")
        try:
            p = float(price)
        except (TypeError, ValueError):
            raise ValueError("each transaction requires numeric price")
        if p <= 0:
            raise ValueError("transaction price must be positive")
        try:
            size = float(row.get("size", row.get("qty", row.get("quantity", 1.0))) or 1.0)
        except (TypeError, ValueError):
            raise ValueError("transaction size must be numeric")
        if size <= 0:
            raise ValueError("transaction size must be positive")
        ts = _parse_ts(row.get("observed_at", row.get("timestamp")))
        out.append({"price": p, "size": size, "observed_at": ts.isoformat()})
    out.sort(key=lambda x: x["observed_at"])
    return out


def _reset_buckets(state: dict[str, Any], session_date: str) -> None:
    state["session_date"] = session_date
    state["last_trade_price"] = None
    for h in HORIZONS:
        old = state["horizons"].get(str(h), {})
        state["horizons"][str(h)] = {
            "count": 0, "open": None, "high": None, "low": None, "close": None,
            "up_size": 0.0, "down_size": 0.0, "ema": old.get("ema"),
            "state": old.get("state", "NEUTRAL"), "raw": old.get("raw", 0.0),
            "buckets_closed": old.get("buckets_closed", 0),
        }


def _close_bucket(bucket: dict[str, Any], horizon: int, ema_len: int, neutral: float) -> dict[str, Any]:
    rng = max(float(bucket["high"]) - float(bucket["low"]), 0.25)
    body = max(-1.0, min(1.0, (float(bucket["close"]) - float(bucket["open"])) / rng))
    total = float(bucket["up_size"]) + float(bucket["down_size"])
    pressure = ((float(bucket["up_size"]) - float(bucket["down_size"])) / total) if total else 0.0
    alpha = 2.0 / (ema_len + 1.0)
    ema = float(bucket["close"]) if bucket.get("ema") is None else float(bucket["ema"]) + alpha * (float(bucket["close"]) - float(bucket["ema"]))
    trend = max(-1.0, min(1.0, (float(bucket["close"]) - ema) / rng))
    raw = 0.30 * body + 0.35 * pressure + 0.35 * trend
    label = "BULL" if raw > neutral else "BEAR" if raw < -neutral else "NEUTRAL"
    return {"horizon": horizon, "state": label, "raw": round(raw, 6), "body": round(body, 6),
            "pressure": round(pressure, 6), "trend": round(trend, 6), "ema": ema,
            "open": bucket["open"], "high": bucket["high"], "low": bucket["low"], "close": bucket["close"]}


def _alignment(state: dict[str, Any]) -> dict[str, Any]:
    bull = sum(WEIGHTS[h] for h in HORIZONS if state["horizons"][str(h)]["state"] == "BULL")
    bear = sum(WEIGHTS[h] for h in HORIZONS if state["horizons"][str(h)]["state"] == "BEAR")
    score = bull - bear
    label = "STRONG_BULL" if score >= 7 else "BULL" if score >= 5 else "STRONG_BEAR" if score <= -7 else "BEAR" if score <= -5 else "MIXED"
    active = [state["horizons"][str(h)]["state"] for h in HORIZONS if state["horizons"][str(h)]["buckets_closed"] > 0]
    return {"score": score, "state": label, "bullish_points": bull, "bearish_points": bear,
            "disagreement": len(set(active)) > 1 if active else True}


def process_transactions(state: Mapping[str, Any] | None, records: Iterable[Mapping[str, Any]], *,
                         instrument: str = "ES", ema_len: int = 5, neutral: float = 0.12) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    s = deepcopy(dict(state or initial_state(instrument)))
    closed: list[dict[str, Any]] = []
    for tx in records:
        dt = _parse_ts(tx["observed_at"])
        in_rth, session_date = _rth(dt)
        if not in_rth:
            s["outside_rth_skipped"] = int(s.get("outside_rth_skipped", 0)) + 1
            continue
        if s.get("session_date") != session_date:
            _reset_buckets(s, session_date)
        price, size = float(tx["price"]), float(tx["size"])
        previous = s.get("last_trade_price")
        direction = 0 if previous is None else (1 if price > float(previous) else -1 if price < float(previous) else 0)
        for h in HORIZONS:
            b = s["horizons"][str(h)]
            if int(b["count"]) == 0:
                b["open"] = b["high"] = b["low"] = price
                b["up_size"] = b["down_size"] = 0.0
            b["high"] = max(float(b["high"]), price)
            b["low"] = min(float(b["low"]), price)
            b["close"] = price
            if direction > 0: b["up_size"] += size
            elif direction < 0: b["down_size"] += size
            b["count"] += 1
            if b["count"] >= h:
                result = _close_bucket(b, h, ema_len, neutral)
                b.update({"ema": result["ema"], "state": result["state"], "raw": result["raw"],
                          "buckets_closed": int(b.get("buckets_closed", 0)) + 1,
                          "count": 0, "open": None, "high": None, "low": None, "close": None,
                          "up_size": 0.0, "down_size": 0.0})
                result["observed_at"] = dt.isoformat()
                result["session_date"] = session_date
                closed.append(result)
        s["last_trade_price"] = price
        s["last_trade_at"] = dt.isoformat()
        s["transactions_seen"] = int(s.get("transactions_seen", 0)) + 1
        s["alignment"] = _alignment(s)
    s["instrument"] = instrument.upper()
    s["version"] = VERSION
    s["schema_version"] = SCHEMA_VERSION
    s["alignment"] = _alignment(s)
    return s, closed


def capability() -> dict[str, Any]:
    return {
        "ok": True, "version": VERSION, "schema_version": SCHEMA_VERSION,
        "instrument": "ES", "spx_role": "OBSERVATIONAL_CONFIRMATION",
        "horizons": list(HORIZONS), "weights": WEIGHTS,
        "states": ["BULL", "BEAR", "NEUTRAL"],
        "alignment_states": ["STRONG_BULL", "BULL", "MIXED", "BEAR", "STRONG_BEAR"],
        "required_evidence": "INDIVIDUAL_ES_OR_MES_TRANSACTIONS",
        "aggregate_bars_allowed_as_ticks": False,
        "l2_mbo_depth_equivalent": False,
        "pine_vocabulary_compatible": True,
        "governance": {"observational_only": True, "production_effect": "NONE",
                       "changes_trade_decisions": False, "decision_authority": "NONE",
                       "execution_authority": "NONE", "automatic_promotion": False,
                       "human_promotion_required_for_future_influence": True,
                       "synthetic_depth_allowed": False},
    }
