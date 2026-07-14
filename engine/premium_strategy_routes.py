"""engine/premium_strategy_routes.py — APEX 7.6.0 Premium Strategy API.

register_premium_strategy_routes(app, last_result_provider=...) attaches:

    GET /api/premium_strategy            — the structure recommendation,
                                           assembled read-only from the Data Bus
                                           + confluence + events.
    GET /api/premium_strategy/scorecard  — recommendation log aggregated by
                                           regime (win-rate surfaces populate as
                                           graded outcomes accumulate).

Mirrors engine/decision_routes.py: isolated so app.py stays thin, consumes the
already-composed bus object, and never 500s the dashboard.

ALERTS
------
The master prompt asks for alerts only WHEN THE RECOMMENDATION CHANGES. This
module tracks the last emitted strategy in-process and stamps each response
with `changed` + `alert` when the structure flips. It deliberately does NOT
dispatch Telegram itself — a read-only GET polled every 20s must not fire
notifications. The scanner cycle is the correct dispatch point; `alert` is the
ready-made payload for it to send (see APEX_7_6_0_CHANGELOG.md).
"""
from __future__ import annotations

import datetime as _dt
import os
import sqlite3
import threading
from typing import Any, Callable, Dict, List, Optional

from flask import jsonify, request

from .premium_strategy import build_premium_strategy
from .confluence import build_confluence

try:
    from .event_calendar import build_event_intelligence
except Exception:  # pragma: no cover - event layer optional
    build_event_intelligence = None  # type: ignore[assignment]

_DB_PATH = os.getenv("DB_PATH", "apex_tracking.db")
_LOCK = threading.Lock()
_LAST_STRATEGY: Dict[str, str] = {}   # ticker -> last emitted strategy
_DB_READY = False


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _init_db() -> None:
    """Create the recommendation log table. Non-fatal: disables logging on error."""
    global _DB_READY
    try:
        db_dir = os.path.dirname(_DB_PATH)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        with _conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS premium_recommendations (
                       id            INTEGER PRIMARY KEY AUTOINCREMENT,
                       ts            TEXT,
                       ticker        TEXT,
                       strategy      TEXT,
                       premium_kind  TEXT,
                       confidence    REAL,
                       vix           REAL,
                       vix_regime    TEXT,
                       case_label    TEXT,
                       pop           REAL,
                       outcome       TEXT,   -- NULL until graded: WIN | LOSS | SCRATCH
                       outcome_ts    TEXT
                   )"""
            )
            c.commit()
        _DB_READY = True
    except Exception as e:  # pragma: no cover
        _DB_READY = False
        print(f"Premium strategy log DISABLED — DB init failed at '{_DB_PATH}': {e}", flush=True)


def _log_recommendation(ticker: str, panel: Dict[str, Any]) -> None:
    if not _DB_READY:
        return
    try:
        legs = panel.get("legs") or {}
        with _conn() as c:
            c.execute(
                """INSERT INTO premium_recommendations
                   (ts, ticker, strategy, premium_kind, confidence, vix, vix_regime,
                    case_label, pop, outcome, outcome_ts)
                   VALUES (?,?,?,?,?,?,?,?,?,NULL,NULL)""",
                (
                    _dt.datetime.now(_dt.timezone.utc).isoformat(),
                    ticker,
                    panel.get("strategy"),
                    panel.get("premium_kind"),
                    float(panel.get("confidence") or 0),
                    panel.get("vix"),
                    panel.get("vix_regime"),
                    panel.get("case"),
                    legs.get("pop"),
                ),
            )
            c.commit()
    except Exception as e:  # pragma: no cover
        print(f"Premium recommendation log error (non-fatal): {e}", flush=True)


def _detect_change(ticker: str, strategy: str, panel: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return an alert payload only when the strategy flips from the last one."""
    with _LOCK:
        prev = _LAST_STRATEGY.get(ticker)
        if strategy and strategy != prev:
            _LAST_STRATEGY[ticker] = strategy
            if prev is None:
                return None  # first observation is not a "change"
            legs = panel.get("legs") or {}
            return {
                "changed": True,
                "from": prev,
                "to": strategy,
                "text": _alert_text(ticker, panel, legs),
            }
    return None


def _alert_text(ticker: str, panel: Dict[str, Any], legs: Dict[str, Any]) -> str:
    lines: List[str] = [
        "APEX ALERT — Premium Strategy",
        f"{ticker}: {panel.get('strategy_label')}",
        f"Confidence {panel.get('confidence')}",
    ]
    if panel.get("strategy") in ("BULL_PUT_CREDIT_SPREAD", "BEAR_CALL_CREDIT_SPREAD"):
        lines.append(f"Spread {legs.get('sell_leg')}/{legs.get('buy_leg')}  "
                     f"credit {legs.get('entry_credit')}  POP {round((legs.get('pop') or 0)*100)}%")
    elif panel.get("strategy") in ("DEBIT_CALL_SPREAD", "DEBIT_PUT_SPREAD"):
        lines.append(f"Spread {legs.get('buy_leg')}/{legs.get('sell_leg')}  "
                     f"debit {legs.get('entry_debit')}")
    elif panel.get("strategy") == "IRON_CONDOR":
        lines.append(f"Condor {legs.get('put_long')}/{legs.get('put_short')} — "
                     f"{legs.get('call_short')}/{legs.get('call_long')}  "
                     f"credit {legs.get('entry_credit')}")
    return "\n".join(lines)


def register_premium_strategy_routes(
    app,
    *,
    last_result_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    default_ticker: str = "SPX",
    log_recommendations: bool = True,
) -> None:
    if log_recommendations:
        _init_db()

    @app.route("/api/premium_strategy")
    def _premium_strategy():
        try:
            ticker = (request.args.get("ticker") or default_ticker).upper()
            lr = (last_result_provider() if last_result_provider else {}) or {}
            conf = build_confluence(lr)
            ev = build_event_intelligence() if build_event_intelligence else {}
            panel = build_premium_strategy(lr, confluence=conf, events=ev)

            alert = None
            if panel.get("available"):
                alert = _detect_change(ticker, panel.get("strategy", ""), panel)
                if log_recommendations and alert and alert.get("changed"):
                    _log_recommendation(ticker, panel)
            panel["alert"] = alert
            return jsonify({"ok": True, "ticker": ticker, "premium_strategy": panel})
        except Exception as e:
            return jsonify({"ok": True, "premium_strategy": {
                "available": False, "note": f"premium strategy route recovered: {e}",
                "strategy": "NO_TRADE", "strategy_label": "No Trade",
                "premium_kind": "NONE", "confidence": 0,
                "headline": "NO TRADE — STAND ASIDE",
                "reason": [f"route recovered: {e}"], "legs": {}, "exit_plan": {},
                "story": [], "opening_range_model": {"active": False},
            }})

    @app.route("/api/premium_strategy/scorecard")
    def _premium_scorecard():
        try:
            if not _DB_READY:
                return jsonify({"ok": True, "scorecard": {
                    "available": False, "note": "recommendation logging not initialized.",
                    "by_regime": [], "by_strategy": [], "total": 0}})
            with _conn() as c:
                rows = c.execute(
                    "SELECT strategy, premium_kind, vix_regime, confidence, outcome "
                    "FROM premium_recommendations"
                ).fetchall()

            by_strategy: Dict[str, Dict[str, Any]] = {}
            by_regime: Dict[str, Dict[str, Any]] = {}
            graded = 0
            for r in rows:
                s = r["strategy"] or "UNKNOWN"
                reg = r["vix_regime"] or "MID"
                oc = r["outcome"]
                for bucket, key in ((by_strategy, s), (by_regime, reg)):
                    b = bucket.setdefault(key, {"count": 0, "wins": 0, "losses": 0,
                                                "graded": 0, "conf_sum": 0.0})
                    b["count"] += 1
                    b["conf_sum"] += float(r["confidence"] or 0)
                    if oc == "WIN":
                        b["wins"] += 1; b["graded"] += 1
                    elif oc == "LOSS":
                        b["losses"] += 1; b["graded"] += 1
                if oc in ("WIN", "LOSS"):
                    graded += 1

            def _fmt(bucket: Dict[str, Dict[str, Any]], label_key: str) -> List[Dict[str, Any]]:
                out = []
                for k, v in sorted(bucket.items()):
                    wr = round(100.0 * v["wins"] / v["graded"], 1) if v["graded"] else None
                    out.append({
                        label_key: k, "count": v["count"], "graded": v["graded"],
                        "wins": v["wins"], "losses": v["losses"], "win_rate_pct": wr,
                        "avg_confidence": round(v["conf_sum"] / v["count"], 1) if v["count"] else None,
                    })
                return out

            return jsonify({"ok": True, "scorecard": {
                "available": True,
                "total": len(rows),
                "graded": graded,
                "note": ("Win-rate surfaces populate as outcomes are graded; "
                         "counts and avg-confidence are live now."),
                "by_strategy": _fmt(by_strategy, "strategy"),
                "by_regime": _fmt(by_regime, "vix_regime"),
            }})
        except Exception as e:
            return jsonify({"ok": True, "scorecard": {
                "available": False, "note": f"scorecard recovered: {e}",
                "by_regime": [], "by_strategy": [], "total": 0}})
