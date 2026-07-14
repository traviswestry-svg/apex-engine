"""engine/premium_strategy_routes.py — APEX 7.6.0 Premium Strategy API + spine hooks.

register_premium_strategy_routes(app, last_result_provider=...) attaches:

    GET /api/premium_strategy            — the structure recommendation,
                                           assembled read-only from the Data Bus
                                           + confluence + events.
    GET /api/premium_strategy/scorecard  — recommendation log aggregated by
                                           regime/strategy, with realized win-rate
                                           once outcomes are graded.

Mirrors engine/decision_routes.py: isolated so app.py stays thin, consumes the
already-composed bus object, and never 500s the dashboard.

SCANNER-SIDE SPINE HOOKS (7.6.0, wired into app.py)
---------------------------------------------------
A read-only GET polled every 20s must not fire notifications, so dispatch and
grading are driven from the same server-side spine the directional signals use:

  * dispatch_and_log(last_result, ticker, dispatcher, ...) is called from the
    /api/institutional_os composition cycle (right where the ENTER-NOW alert is
    dispatched). It logs a recommendation and fires `dispatcher(text)` ONLY when
    the structure changes vs. the last dispatched structure for that session —
    de-duped per (session_date, ticker), re-armed each session. Logging happens
    on change regardless of whether Telegram is enabled, so the scorecard fills
    even with alerts off.

  * grade_due_recommendations(get_intraday_bars, now_et_provider, ...) is called
    from scanner_loop alongside signal_evaluator.mark_due_signals. It settles
    each logged 0DTE structure at cash close from SPX bars and writes
    WIN/LOSS/SCRATCH + realized P&L back to the row — the same price-sampling
    spine, applied to structures instead of directional points.
"""
from __future__ import annotations

import datetime as _dt
import json as _json
import math as _math
import os
import sqlite3
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from flask import jsonify, request

from .premium_strategy import build_premium_strategy
from .confluence import build_confluence

try:
    from .event_calendar import build_event_intelligence
except Exception:  # pragma: no cover - event layer optional
    build_event_intelligence = None  # type: ignore[assignment]

_DB_PATH = os.getenv("DB_PATH", "apex_tracking.db")
_LOCK = threading.Lock()
_LAST_STRATEGY: Dict[str, str] = {}        # ticker -> last strategy seen by the GET (UI hint)
_LAST_DISPATCH: Dict[str, str] = {}        # (session_date|ticker) -> last DISPATCHED strategy
_DB_READY = False

# Structure constants (kept local so this module doesn't depend on engine internals).
_CREDIT = {"BULL_PUT_CREDIT_SPREAD", "BEAR_CALL_CREDIT_SPREAD"}
_DEBIT = {"DEBIT_CALL_SPREAD", "DEBIT_PUT_SPREAD"}
_CONDOR = "IRON_CONDOR"
_NO_TRADE = "NO_TRADE"

# Grading deadband: |P&L| below this (in points) is a SCRATCH, not a win/loss.
_GRADE_DEADBAND_PTS = float(os.getenv("PREMIUM_GRADE_DEADBAND_PTS", "0.05"))
_SETTLE_HOUR_ET = int(os.getenv("PREMIUM_SETTLE_HOUR_ET", "16"))  # cash close


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _init_db() -> None:
    """Create/upgrade the recommendation log table. Non-fatal: disables logging on error."""
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
                       session_date  TEXT,
                       ticker        TEXT,
                       strategy      TEXT,
                       premium_kind  TEXT,
                       confidence    REAL,
                       vix           REAL,
                       vix_regime    TEXT,
                       case_label    TEXT,
                       pop           REAL,
                       spot          REAL,
                       legs_json     TEXT,
                       outcome       TEXT,   -- NULL until graded: WIN | LOSS | SCRATCH
                       outcome_pnl   REAL,   -- realized $ per 1 contract (modeled at expiry)
                       outcome_notes TEXT,
                       outcome_ts    TEXT
                   )"""
            )
            # Migrate older tables that predate the grading columns.
            existing = {r["name"] for r in c.execute("PRAGMA table_info(premium_recommendations)")}
            for col, decl in (
                ("session_date", "TEXT"), ("spot", "REAL"), ("legs_json", "TEXT"),
                ("outcome_pnl", "REAL"), ("outcome_notes", "TEXT"),
            ):
                if col not in existing:
                    c.execute(f"ALTER TABLE premium_recommendations ADD COLUMN {col} {decl}")
            c.execute("CREATE INDEX IF NOT EXISTS idx_pr_ungraded "
                      "ON premium_recommendations(outcome)")
            c.commit()
        _DB_READY = True
    except Exception as e:  # pragma: no cover
        _DB_READY = False
        print(f"Premium strategy log DISABLED — DB init failed at '{_DB_PATH}': {e}", flush=True)


def _log_recommendation(ticker: str, panel: Dict[str, Any], session_date: str,
                        spot: Optional[float]) -> None:
    if not _DB_READY:
        return
    try:
        legs = panel.get("legs") or {}
        with _conn() as c:
            c.execute(
                """INSERT INTO premium_recommendations
                   (ts, session_date, ticker, strategy, premium_kind, confidence, vix,
                    vix_regime, case_label, pop, spot, legs_json, outcome, outcome_pnl,
                    outcome_notes, outcome_ts)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL)""",
                (
                    _dt.datetime.now(_dt.timezone.utc).isoformat(),
                    session_date, ticker,
                    panel.get("strategy"), panel.get("premium_kind"),
                    float(panel.get("confidence") or 0),
                    panel.get("vix"), panel.get("vix_regime"), panel.get("case"),
                    legs.get("pop"),
                    spot if spot is not None else panel.get("spot"),
                    _json.dumps(legs),
                ),
            )
            c.commit()
    except Exception as e:  # pragma: no cover
        print(f"Premium recommendation log error (non-fatal): {e}", flush=True)


def _alert_text(ticker: str, panel: Dict[str, Any], legs: Dict[str, Any]) -> str:
    lines: List[str] = [
        "APEX ALERT — Premium Strategy",
        f"{ticker}: {panel.get('strategy_label')}",
        f"Confidence {panel.get('confidence')}",
    ]
    if panel.get("strategy") in _CREDIT:
        lines.append(f"Spread {legs.get('sell_leg')}/{legs.get('buy_leg')}  "
                     f"credit {legs.get('entry_credit')}  POP {round((legs.get('pop') or 0)*100)}%")
    elif panel.get("strategy") in _DEBIT:
        lines.append(f"Spread {legs.get('buy_leg')}/{legs.get('sell_leg')}  "
                     f"debit {legs.get('entry_debit')}")
    elif panel.get("strategy") == _CONDOR:
        lines.append(f"Condor {legs.get('put_long')}/{legs.get('put_short')} — "
                     f"{legs.get('call_short')}/{legs.get('call_long')}  "
                     f"credit {legs.get('entry_credit')}")
    xp = panel.get("exit_plan") or {}
    if xp.get("target"):
        lines.append(f"Exit: {xp['target']}")
    if xp.get("stop"):
        lines.append(f"Stop: {xp['stop']}")
    return "\n".join(lines)


def _detect_change(ticker: str, strategy: str, panel: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """UI hint only: return an alert payload when the strategy flips (in-process)."""
    with _LOCK:
        prev = _LAST_STRATEGY.get(ticker)
        if strategy and strategy != prev:
            _LAST_STRATEGY[ticker] = strategy
            if prev is None:
                return None
            legs = panel.get("legs") or {}
            return {"changed": True, "from": prev, "to": strategy,
                    "text": _alert_text(ticker, panel, legs)}
    return None


# ── Scanner-side dispatch (authoritative log + alert-on-change) ──────────────
def dispatch_and_log(
    last_result: Dict[str, Any],
    ticker: str,
    dispatcher: Optional[Callable[[str], Any]] = None,
    *,
    confluence: Optional[Dict[str, Any]] = None,
    events: Optional[Dict[str, Any]] = None,
    spot: Optional[float] = None,
    now_et_provider: Optional[Callable[[], _dt.datetime]] = None,
) -> Dict[str, Any]:
    """Build the structure from the freshly composed bus; on a genuine change,
    log it and fire the dispatcher. Called from the /api/institutional_os cycle.

    De-dupe is scoped to (session_date, ticker) so it fires once per structure
    change per session and re-arms the next day — independent of dashboard polls.
    Returns {"changed": bool, "strategy": str, "dispatched": bool, "logged": bool}.
    Never raises.
    """
    out = {"changed": False, "strategy": None, "dispatched": False, "logged": False}
    try:
        lr = last_result or {}
        conf = confluence if confluence is not None else build_confluence(lr)
        ev = events if events is not None else (
            build_event_intelligence() if build_event_intelligence else {})
        panel = build_premium_strategy(lr, confluence=conf, events=ev)
        if not panel.get("available"):
            return out
        strategy = panel.get("strategy") or _NO_TRADE
        out["strategy"] = strategy

        now_et = (now_et_provider() if now_et_provider else
                  _dt.datetime.now(_dt.timezone.utc))
        session_date = now_et.date().isoformat()
        key = f"{session_date}|{ticker}"

        with _LOCK:
            prev = _LAST_DISPATCH.get(key)
            changed = strategy != prev
            if changed:
                _LAST_DISPATCH[key] = strategy
        if not changed:
            return out
        out["changed"] = True

        # Resolve spot for grading (SPX price on the bus at rec time).
        if spot is None:
            spot = (((lr.get("market_state") or {}).get("price"))
                    or panel.get("spot"))
        # Log every genuine change (even NO_TRADE, for a complete session record;
        # NO_TRADE rows are skipped by the grader). Logging is independent of alerts.
        _log_recommendation(ticker, panel, session_date, _safe_float(spot))
        out["logged"] = _DB_READY

        # Alert only for actionable structures (a flip TO stand-aside is silent).
        if dispatcher and strategy != _NO_TRADE:
            try:
                dispatcher(_alert_text(ticker, panel, panel.get("legs") or {}))
                out["dispatched"] = True
            except Exception as e:  # pragma: no cover
                print(f"Premium alert dispatch failed (non-fatal): {e}", flush=True)
        return out
    except Exception as e:  # pragma: no cover
        print(f"dispatch_and_log recovered (non-fatal): {e}", flush=True)
        return out


# ── Outcome grading (0DTE settlement over SPX bars) ─────────────────────────
def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _parse_iso_utc(s: str) -> Optional[_dt.datetime]:
    if not s:
        return None
    try:
        d = _dt.datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=_dt.timezone.utc)
        return d.astimezone(_dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _settle_structure(strategy: str, legs: Dict[str, Any],
                      close_px: float) -> Tuple[Optional[float], str]:
    """Return (pnl_points_per_contract, detail) for a 0DTE structure at cash close.

    Modeled expiry settlement: intrinsic value of each leg at the settlement print,
    netted against the entry credit/debit. Positive credit structures keep credit
    when short strikes finish OTM; debit structures realize intrinsic minus debit.
    Returns (None, reason) when the structure can't be settled (missing strikes).
    """
    width = _safe_float(legs.get("width")) or 10.0
    if strategy == "BULL_PUT_CREDIT_SPREAD":
        short_put = _safe_float(legs.get("sell_leg"))
        credit = _safe_float(legs.get("entry_credit"))
        if short_put is None or credit is None:
            return None, "missing bull-put legs"
        loss = _clamp(short_put - close_px, 0.0, width)   # ITM depth, capped at width
        pnl = credit - loss
        return pnl, f"close {close_px:.2f} vs short put {short_put:.2f}; credit {credit:.2f} − ITM {loss:.2f}"
    if strategy == "BEAR_CALL_CREDIT_SPREAD":
        short_call = _safe_float(legs.get("sell_leg"))
        credit = _safe_float(legs.get("entry_credit"))
        if short_call is None or credit is None:
            return None, "missing bear-call legs"
        loss = _clamp(close_px - short_call, 0.0, width)
        pnl = credit - loss
        return pnl, f"close {close_px:.2f} vs short call {short_call:.2f}; credit {credit:.2f} − ITM {loss:.2f}"
    if strategy == "DEBIT_CALL_SPREAD":
        long_call = _safe_float(legs.get("buy_leg"))
        debit = _safe_float(legs.get("entry_debit"))
        if long_call is None or debit is None:
            return None, "missing debit-call legs"
        value = _clamp(close_px - long_call, 0.0, width)
        pnl = value - debit
        return pnl, f"close {close_px:.2f} vs long call {long_call:.2f}; value {value:.2f} − debit {debit:.2f}"
    if strategy == "DEBIT_PUT_SPREAD":
        long_put = _safe_float(legs.get("buy_leg"))
        debit = _safe_float(legs.get("entry_debit"))
        if long_put is None or debit is None:
            return None, "missing debit-put legs"
        value = _clamp(long_put - close_px, 0.0, width)
        pnl = value - debit
        return pnl, f"close {close_px:.2f} vs long put {long_put:.2f}; value {value:.2f} − debit {debit:.2f}"
    if strategy == _CONDOR:
        put_short = _safe_float(legs.get("put_short"))
        call_short = _safe_float(legs.get("call_short"))
        credit = _safe_float(legs.get("entry_credit"))
        if put_short is None or call_short is None or credit is None:
            return None, "missing condor legs"
        put_loss = _clamp(put_short - close_px, 0.0, width)
        call_loss = _clamp(close_px - call_short, 0.0, width)
        pnl = credit - put_loss - call_loss
        return pnl, (f"close {close_px:.2f} inside {put_short:.2f}/{call_short:.2f}? "
                     f"credit {credit:.2f} − put ITM {put_loss:.2f} − call ITM {call_loss:.2f}")
    return None, f"unsupported structure {strategy}"


def _persist_outcome(row_id: int, label: str, pnl: Optional[float], notes: str,
                     on_marked: Optional[Callable[[int, Dict[str, Any]], None]] = None) -> None:
    try:
        ts = _dt.datetime.now(_dt.timezone.utc).isoformat()
        with _conn() as c:
            c.execute(
                "UPDATE premium_recommendations SET outcome=?, outcome_pnl=?, "
                "outcome_notes=?, outcome_ts=? WHERE id=?",
                (label, pnl, notes, ts, row_id),
            )
            c.commit()
        if on_marked:
            on_marked(row_id, {"outcome": label, "outcome_pnl": pnl,
                               "outcome_notes": notes, "outcome_ts": ts})
    except Exception as e:  # pragma: no cover
        print(f"Premium outcome persist failed (non-fatal): {e}", flush=True)


def grade_due_recommendations(
    get_intraday_bars: Callable[..., List[Dict[str, Any]]],
    now_et_provider: Callable[[], _dt.datetime],
    on_marked: Optional[Callable[[int, Dict[str, Any]], None]] = None,
) -> int:
    """Settle every ungraded structure whose session has closed. Returns count graded.

    Mirrors signal_evaluator.mark_due_signals: bars are injected (no Polygon
    dependency here), NO_TRADE rows are closed as SCRATCH (no position), and a
    session with no available bars is left for a later pass unless it is stale.
    """
    if not _DB_READY:
        return 0
    try:
        now_et = now_et_provider()
    except Exception:
        now_et = _dt.datetime.now(_dt.timezone.utc)
    today = now_et.date()
    # ET→UTC offset from the tz-aware provider (falls back to 0 if naive).
    offset = now_et.utcoffset() or _dt.timedelta(0)

    try:
        with _conn() as c:
            rows = c.execute(
                "SELECT * FROM premium_recommendations WHERE outcome IS NULL "
                "ORDER BY id ASC LIMIT 300"
            ).fetchall()
    except Exception as e:  # pragma: no cover
        print(f"Premium grade select failed (non-fatal): {e}", flush=True)
        return 0
    if not rows:
        return 0

    bars_cache: Dict[str, List[Dict[str, Any]]] = {}
    graded = 0

    for r in rows:
        rec_utc = _parse_iso_utc(r["ts"])
        sess = r["session_date"] or (rec_utc.astimezone(_dt.timezone.utc).date().isoformat()
                                     if rec_utc else None)
        if not rec_utc or not sess:
            _persist_outcome(r["id"], "SCRATCH", None,
                             "No timestamp/session — cannot settle.", on_marked)
            graded += 1
            continue
        try:
            sess_date = _dt.date.fromisoformat(sess)
        except ValueError:
            _persist_outcome(r["id"], "SCRATCH", None, "Bad session_date.", on_marked)
            graded += 1
            continue

        # Ready only once the session has settled (past cash close).
        ready = (today > sess_date) or (
            today == sess_date and now_et.hour >= _SETTLE_HOUR_ET)
        if not ready:
            continue

        strategy = r["strategy"] or _NO_TRADE
        if strategy == _NO_TRADE:
            _persist_outcome(r["id"], "SCRATCH", 0.0,
                             "Stand-aside (no position to settle).", on_marked)
            graded += 1
            continue

        ticker = r["ticker"] or "SPX"
        if ticker not in bars_cache:
            try:
                bars_cache[ticker] = get_intraday_bars(ticker, 5, 5)  # 5-min, ~5d back
            except Exception as e:
                print(f"Premium grade bar fetch failed for {ticker}: {e}", flush=True)
                bars_cache[ticker] = []
        allbars = bars_cache[ticker]

        # Window: from rec time to session cash close (naive-UTC ms).
        close_et_naive = _dt.datetime.combine(sess_date, _dt.time(_SETTLE_HOUR_ET, 0))
        close_utc = (close_et_naive - offset).replace(tzinfo=_dt.timezone.utc)
        start_ms = int(rec_utc.timestamp() * 1000)
        end_ms = int(close_utc.timestamp() * 1000)
        fwd = [b for b in allbars
               if (_safe_float(b.get("t")) is not None
                   and start_ms <= _safe_float(b.get("t")) <= end_ms)]

        if not fwd:
            # No bars yet — retry later, unless the session is > 2 days stale.
            if rec_utc < _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=2):
                _persist_outcome(r["id"], "SCRATCH", None,
                                 "No settlement bars available (stale).", on_marked)
                graded += 1
            continue

        close_px = _safe_float(fwd[-1].get("c"))
        if close_px is None:
            continue

        legs: Dict[str, Any] = {}
        try:
            legs = _json.loads(r["legs_json"]) if r["legs_json"] else {}
        except Exception:
            legs = {}

        pnl_pts, detail = _settle_structure(strategy, legs, close_px)
        if pnl_pts is None:
            _persist_outcome(r["id"], "SCRATCH", None,
                             f"Cannot settle: {detail}.", on_marked)
            graded += 1
            continue

        if pnl_pts > _GRADE_DEADBAND_PTS:
            label = "WIN"
        elif pnl_pts < -_GRADE_DEADBAND_PTS:
            label = "LOSS"
        else:
            label = "SCRATCH"
        pnl_dollars = round(pnl_pts * 100.0, 2)  # 1 contract, $100 multiplier
        notes = f"{label} @ expiry — {detail}. P&L {pnl_dollars:+.0f}/contract ({len(fwd)} bars)."
        _persist_outcome(r["id"], label, pnl_dollars, notes, on_marked)
        graded += 1

    return graded


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
                # UI hint only; the authoritative log+dispatch runs on the
                # institutional_os cycle via dispatch_and_log().
                alert = _detect_change(ticker, panel.get("strategy", ""), panel)
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
                    "SELECT strategy, premium_kind, vix_regime, confidence, outcome, "
                    "outcome_pnl FROM premium_recommendations"
                ).fetchall()

            by_strategy: Dict[str, Dict[str, Any]] = {}
            by_regime: Dict[str, Dict[str, Any]] = {}
            graded = 0
            net_pnl = 0.0
            for r in rows:
                s = r["strategy"] or "UNKNOWN"
                reg = r["vix_regime"] or "MID"
                oc = r["outcome"]
                pnl = r["outcome_pnl"] if r["outcome_pnl"] is not None else 0.0
                for bucket, key in ((by_strategy, s), (by_regime, reg)):
                    b = bucket.setdefault(key, {"count": 0, "wins": 0, "losses": 0,
                                                "graded": 0, "conf_sum": 0.0, "pnl": 0.0})
                    b["count"] += 1
                    b["conf_sum"] += float(r["confidence"] or 0)
                    if oc == "WIN":
                        b["wins"] += 1; b["graded"] += 1; b["pnl"] += pnl
                    elif oc == "LOSS":
                        b["losses"] += 1; b["graded"] += 1; b["pnl"] += pnl
                if oc in ("WIN", "LOSS"):
                    graded += 1
                    net_pnl += pnl

            def _fmt(bucket: Dict[str, Dict[str, Any]], label_key: str) -> List[Dict[str, Any]]:
                out = []
                for k, v in sorted(bucket.items()):
                    wr = round(100.0 * v["wins"] / v["graded"], 1) if v["graded"] else None
                    out.append({
                        label_key: k, "count": v["count"], "graded": v["graded"],
                        "wins": v["wins"], "losses": v["losses"], "win_rate_pct": wr,
                        "net_pnl": round(v["pnl"], 2) if v["graded"] else None,
                        "avg_confidence": round(v["conf_sum"] / v["count"], 1) if v["count"] else None,
                    })
                return out

            return jsonify({"ok": True, "scorecard": {
                "available": True,
                "total": len(rows),
                "graded": graded,
                "net_pnl": round(net_pnl, 2),
                "note": ("Outcomes are settled at cash close from SPX bars; "
                         "win-rate and net P&L are live once graded."),
                "by_strategy": _fmt(by_strategy, "strategy"),
                "by_regime": _fmt(by_regime, "vix_regime"),
            }})
        except Exception as e:
            return jsonify({"ok": True, "scorecard": {
                "available": False, "note": f"scorecard recovered: {e}",
                "by_regime": [], "by_strategy": [], "total": 0}})
