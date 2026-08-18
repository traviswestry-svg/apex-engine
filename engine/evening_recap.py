"""APEX 49 — Institutional Evening Recap & Forecast Validation.

Closes the Morning Brief feedback loop with deterministic, auditable comparisons
between projected structure and the completed SPX regular session. The model may
explain the evidence, but it never grades or invents prices.
"""
from __future__ import annotations

from .canonical_persistence import connect as canonical_connect

import datetime as dt
import json
import os
import re
import sqlite3
from typing import Any, Iterable, Optional
from .persistent_store import persistent_sqlite_path
from .evening_archive_schema import init_evening_archive_db

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    ET = dt.timezone(dt.timedelta(hours=-5))

VERSION = "49.1.0_FORECAST_ARCHIVE_INTEGRITY"
DB_PATH = persistent_sqlite_path("APEX_GOVERNANCE_DB", "apex_governance.db")
FEED_REQUIRED = "[FEED REQUIRED]"
REGIMES = ("EVENT DRIVEN", "MEAN REVERSION", "HIGH VOLATILITY", "LOW VOLATILITY", "BALANCED AUCTION", "COMPRESSION", "EXPANSION", "TREND")


def _now_et() -> dt.datetime:
    return dt.datetime.now(ET)


def _json(v: Any) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), default=str)


def _load(v: Any, default: Any = None) -> Any:
    if v in (None, ""):
        return {} if default is None else default
    try:
        return json.loads(v)
    except Exception:
        return {} if default is None else default


def _num(v: Any) -> Optional[float]:
    try:
        if v in (None, "", FEED_REQUIRED):
            return None
        x = float(v)
        return x if x == x else None
    except Exception:
        return None


def init_db() -> None:
    """Ensure the recap archive schema exists without any reverse service import."""
    init_evening_archive_db(DB_PATH)


def save_morning_snapshot(payload: dict, ticker: str = "SPX") -> dict:
    """Archive every generated brief while preserving the first as official.

    The official snapshot is immutable. Later generations are retained as
    revisions so forecast validation can never be rewritten after the fact.
    """
    init_db()
    sdate = str(payload.get("session_date") or _now_et().date().isoformat())
    generated_at = str(payload.get("generated_at") or _now_et().isoformat())
    body = _json(payload)
    with canonical_connect(DB_PATH, timeout=10) as c:
        existing = c.execute(
            "SELECT generated_at FROM apex49_morning_snapshots WHERE session_date=?",
            (sdate,),
        ).fetchone()
        is_official = existing is None
        if is_official:
            c.execute(
                "INSERT INTO apex49_morning_snapshots VALUES(?,?,?,?,?)",
                (sdate, generated_at, ticker, body, VERSION),
            )
        c.execute(
            """INSERT INTO apex49_morning_revisions
               (session_date,generated_at,ticker,payload_json,version,is_official)
               VALUES(?,?,?,?,?,?)""",
            (sdate, generated_at, ticker, body, VERSION, 1 if is_official else 0),
        )
        revision_count = c.execute(
            "SELECT COUNT(*) FROM apex49_morning_revisions WHERE session_date=?",
            (sdate,),
        ).fetchone()[0]
        official_generated_at = generated_at if is_official else existing[0]
    return {
        "session_date": sdate,
        "archived": True,
        "is_official": is_official,
        "official_generated_at": official_generated_at,
        "revision_count": int(revision_count),
        "version": VERSION,
    }


def morning_archive_status(session_date: str) -> dict:
    init_db()
    with canonical_connect(DB_PATH, timeout=10) as c:
        official = c.execute(
            "SELECT generated_at,ticker,version FROM apex49_morning_snapshots WHERE session_date=?",
            (session_date,),
        ).fetchone()
        count = c.execute(
            "SELECT COUNT(*) FROM apex49_morning_revisions WHERE session_date=?",
            (session_date,),
        ).fetchone()[0]
    return {
        "ok": True,
        "session_date": session_date,
        "archived": bool(official),
        "official_generated_at": official[0] if official else None,
        "ticker": official[1] if official else None,
        "archive_version": official[2] if official else None,
        "revision_count": int(count),
        "version": VERSION,
    }

def morning_history(limit: int = 60) -> dict:
    init_db()
    limit = max(1, min(int(limit), 365))
    with canonical_connect(DB_PATH, timeout=10) as c:
        rows = c.execute("""SELECT s.session_date,s.generated_at,s.ticker,s.version,
                            (SELECT COUNT(*) FROM apex49_morning_revisions r WHERE r.session_date=s.session_date)
                            FROM apex49_morning_snapshots s ORDER BY s.session_date DESC LIMIT ?""", (limit,)).fetchall()
    return {"ok": True, "count": len(rows), "items": [
        {"session_date": r[0], "official_generated_at": r[1], "ticker": r[2], "archive_version": r[3], "revision_count": int(r[4])}
        for r in rows], "version": VERSION}

def get_morning_snapshot(session_date: str) -> Optional[dict]:
    init_db()
    with canonical_connect(DB_PATH, timeout=10) as c:
        row = c.execute("SELECT payload_json FROM apex49_morning_snapshots WHERE session_date=?", (session_date,)).fetchone()
    return _load(row[0]) if row else None


def get_cached_recap(session_date: str) -> Optional[dict]:
    init_db()
    with canonical_connect(DB_PATH, timeout=10) as c:
        row = c.execute("SELECT payload_json FROM apex49_evening_recaps WHERE session_date=?", (session_date,)).fetchone()
    return _load(row[0]) if row else None


def _bar_time(bar: dict) -> Optional[dt.datetime]:
    raw = bar.get("t") or bar.get("timestamp") or bar.get("time")
    try:
        x = float(raw)
        if x > 10_000_000_000:
            x /= 1000.0
        return dt.datetime.fromtimestamp(x, tz=dt.timezone.utc).astimezone(ET)
    except Exception:
        return None


def session_bars(bars: Iterable[dict], session_date: str) -> list[dict]:
    target = dt.date.fromisoformat(session_date)
    out = []
    for b in bars or []:
        ts = _bar_time(b)
        if ts and ts.date() == target and dt.time(9, 30) <= ts.time() <= dt.time(16, 0):
            out.append(b)
    return sorted(out, key=lambda b: _bar_time(b) or dt.datetime.min.replace(tzinfo=ET))


def actual_session(bars: Iterable[dict], session_date: str) -> dict:
    rows = session_bars(bars, session_date)
    if not rows:
        return {"available": False, "session_date": session_date, "bar_count": 0}
    opens = [_num(b.get("o") or b.get("open")) for b in rows]
    highs = [_num(b.get("h") or b.get("high")) for b in rows]
    lows = [_num(b.get("l") or b.get("low")) for b in rows]
    closes = [_num(b.get("c") or b.get("close")) for b in rows]
    opens, highs, lows, closes = ([x for x in xs if x is not None] for xs in (opens, highs, lows, closes))
    if not opens or not highs or not lows or not closes:
        return {"available": False, "session_date": session_date, "bar_count": len(rows)}
    o, h, l, c = opens[0], max(highs), min(lows), closes[-1]
    rng = h - l
    close_location = ((c - l) / rng) if rng > 0 else 0.5
    direction = "BULLISH" if c > o else "BEARISH" if c < o else "FLAT"
    return {
        "available": True, "session_date": session_date, "bar_count": len(rows),
        "open": round(o, 2), "high": round(h, 2), "low": round(l, 2), "close": round(c, 2),
        "range": round(rng, 2), "net_change": round(c - o, 2),
        "net_change_pct": round(((c / o) - 1.0) * 100.0, 3) if o else None,
        "direction": direction, "close_location": round(close_location, 3),
    }


def extract_projected_regime(markdown: str) -> Optional[str]:
    text = (markdown or "").upper()
    for regime in REGIMES:
        if re.search(r"\b" + re.escape(regime) + r"\b", text):
            return regime.title()
    return None


def classify_actual_regime(actual: dict, expected_move: Optional[float]) -> str:
    if not actual.get("available"):
        return "Unavailable"
    rng = _num(actual.get("range")) or 0.0
    loc = _num(actual.get("close_location")) or 0.5
    net = abs(_num(actual.get("net_change")) or 0.0)
    if expected_move and expected_move > 0:
        ratio = rng / (2.0 * expected_move)
        if ratio >= 1.15:
            return "Expansion"
        if ratio <= 0.55:
            return "Compression"
    if loc >= 0.8 or loc <= 0.2:
        return "Trend"
    if rng > 0 and net / rng <= 0.25:
        return "Balanced Auction"
    return "Mean Reversion"


def evaluate_levels(levels: Iterable[dict], bars: Iterable[dict], session_date: str, tolerance: float = 1.0) -> list[dict]:
    rows = session_bars(bars, session_date)
    results = []
    for lvl in levels or []:
        price = _num(lvl.get("price"))
        if price is None:
            continue
        touches = 0
        first_touch = None
        closes_above = closes_below = 0
        for b in rows:
            lo, hi, close = _num(b.get("l") or b.get("low")), _num(b.get("h") or b.get("high")), _num(b.get("c") or b.get("close"))
            if lo is None or hi is None:
                continue
            if lo - tolerance <= price <= hi + tolerance:
                touches += 1
                if first_touch is None:
                    ts = _bar_time(b)
                    first_touch = ts.isoformat() if ts else None
            if close is not None:
                closes_above += int(close > price + tolerance)
                closes_below += int(close < price - tolerance)
        status = "NOT_TESTED"
        if touches:
            status = "ACCEPTED_ABOVE" if closes_above >= 3 and closes_above > closes_below else "ACCEPTED_BELOW" if closes_below >= 3 and closes_below > closes_above else "REJECTED_OR_CONTESTED"
        results.append({
            "kind": lvl.get("kind"), "label": lvl.get("label") or lvl.get("kind"), "price": round(price, 2),
            "touched": touches > 0, "touch_count": touches, "first_touch": first_touch, "outcome": status,
            "importance": lvl.get("importance"),
        })
    return results


def _grade(score: Optional[float]) -> str:
    if score is None: return "N/A"
    return "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "F"


def build_comparison(morning: dict, bars: Iterable[dict], session_date: str) -> dict:
    structured = morning.get("structured") or {}
    actual = actual_session(bars, session_date)
    em = structured.get("expected_move") or {}
    em1, upper, lower = _num(em.get("one_sigma")), _num(em.get("upper")), _num(em.get("lower"))
    projected_regime = extract_projected_regime(morning.get("markdown", ""))
    actual_regime = classify_actual_regime(actual, em1)
    checks = []
    if actual.get("available") and upper is not None and lower is not None:
        contained = actual["high"] <= upper and actual["low"] >= lower
        checks.append({"key": "expected_move_containment", "label": "Expected-move containment", "projected": f"{lower:.2f} to {upper:.2f}", "actual": f"{actual['low']:.2f} to {actual['high']:.2f}", "correct": contained})
    if projected_regime:
        compatible = projected_regime.upper() == actual_regime.upper()
        # Trend and Expansion are directionally compatible; Balanced and Mean Reversion likewise.
        families = ({"TREND", "EXPANSION"}, {"BALANCED AUCTION", "MEAN REVERSION", "COMPRESSION"})
        compatible = compatible or any(projected_regime.upper() in f and actual_regime.upper() in f for f in families)
        checks.append({"key": "regime", "label": "Regime projection", "projected": projected_regime, "actual": actual_regime, "correct": compatible})
    if actual.get("available") and em1 is not None:
        realized_half_range = actual["range"] / 2.0
        error = abs(realized_half_range - em1)
        accuracy = max(0.0, 1.0 - error / em1) if em1 > 0 else 0.0
        checks.append({"key": "expected_move_size", "label": "Expected-move size", "projected": round(em1, 2), "actual": round(realized_half_range, 2), "accuracy": round(accuracy, 3), "correct": accuracy >= 0.70})
    score = round(100.0 * sum(1 for c in checks if c.get("correct")) / len(checks), 1) if checks else None
    levels = evaluate_levels(structured.get("levels") or [], bars, session_date)
    return {
        "actual": actual, "projected_regime": projected_regime or "Not explicitly classified",
        "actual_regime": actual_regime, "checks": checks, "score": score, "grade": _grade(score),
        "levels": levels, "level_summary": {
            "evaluated": len(levels), "touched": sum(1 for x in levels if x["touched"]),
            "not_tested": sum(1 for x in levels if not x["touched"]),
        },
    }


def render_deterministic_markdown(session_date: str, comparison: dict) -> str:
    a = comparison["actual"]
    lines = [f"# APEX EVENING RECAP — {session_date}", "", "## Forecast Scorecard", ""]
    lines.append(f"**Validated accuracy:** {comparison['score'] if comparison['score'] is not None else 'N/A'}% · **Grade {comparison['grade']}**")
    lines += ["", "| Projection | Morning | Actual | Result |", "|---|---:|---:|---|"]
    for c in comparison["checks"]:
        result = "PASS" if c.get("correct") else "MISS"
        lines.append(f"| {c['label']} | {c.get('projected')} | {c.get('actual')} | {result} |")
    lines += ["", "## What Actually Happened", ""]
    if a.get("available"):
        lines.append(f"SPX opened **{a['open']:.2f}**, traded **{a['low']:.2f}–{a['high']:.2f}**, and closed **{a['close']:.2f}** ({a['direction']}, {a['net_change']:+.2f} points).")
        lines.append(f"Actual regime: **{comparison['actual_regime']}**. Morning projected: **{comparison['projected_regime']}**.")
    else:
        lines.append("Completed-session bars are unavailable; no outcome was fabricated.")
    lines += ["", "## Key-Level Reactions", "", "| Level | Price | Bar Touches | Outcome |", "|---|---:|---:|---|"]
    for x in [v for v in comparison["levels"] if v["touched"]][:15]:
        lines.append(f"| {x['label']} | {x['price']:.2f} | {x['touch_count']} | {x['outcome'].replace('_',' ')} |")
    if not any(v["touched"] for v in comparison["levels"]):
        lines.append("| No tracked level was touched | — | — | — |")
    return "\n".join(lines) + "\n"


def _call_narrative(evidence: dict, api_key: str, model: str) -> tuple[str, Optional[str]]:
    try:
        import requests
        prompt = """You are the APEX institutional review director. Explain the completed SPX session using ONLY the supplied evidence. Do not alter scores, prices, outcomes, or claim causation not present in the evidence. Write concise Markdown sections: Executive Review, Where the Morning Brief Was Right, Where It Missed, Lessons for Tomorrow, Carry-Forward Levels. Never issue a trade call.\n\nEVIDENCE:\n""" + json.dumps(evidence, indent=2, default=str)
        r = requests.post("https://api.anthropic.com/v1/messages", headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}, json={"model": model, "max_tokens": 2200, "messages": [{"role": "user", "content": prompt}]}, timeout=90)
        if r.status_code != 200:
            return "", f"anthropic {r.status_code}: {r.text[:160]}"
        blocks = r.json().get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        return (text, None) if text else ("", "empty narrative")
    except Exception as exc:
        return "", f"{type(exc).__name__}: {exc}"


def generate_evening_recap(*, morning: dict, intraday_bars: Iterable[dict], session_date: str, ticker: str = "SPX", force: bool = False, api_key: Optional[str] = None, model: Optional[str] = None) -> dict:
    if not force:
        cached = get_cached_recap(session_date)
        if cached:
            return {**cached, "cached": True}
    comparison = build_comparison(morning, intraday_bars, session_date)
    deterministic = render_deterministic_markdown(session_date, comparison)
    api_key = (api_key or os.getenv("ANTHROPIC_API_KEY", "")).strip()
    narrative, error = ("", "no ANTHROPIC_API_KEY set")
    if api_key and comparison["actual"].get("available"):
        narrative, error = _call_narrative(comparison, api_key, model or os.getenv("APEX_RECAP_MODEL", os.getenv("APEX_BRIEF_MODEL", "claude-sonnet-5")))
    markdown = deterministic + ("\n---\n\n" + narrative + "\n" if narrative else f"\n_Narrative unavailable ({error}). Deterministic validation remains complete._\n")
    result = {
        "ok": True, "ticker": ticker, "session_date": session_date, "generated_at": _now_et().isoformat(),
        "cached": False, "has_narrative": bool(narrative), "narrative_error": error,
        "score": comparison["score"], "grade": comparison["grade"], "markdown": markdown,
        "comparison": comparison, "version": VERSION,
    }
    init_db()
    with canonical_connect(DB_PATH, timeout=10) as c:
        c.execute("""INSERT INTO apex49_evening_recaps VALUES(?,?,?,?,?,?,?)
                     ON CONFLICT(session_date) DO UPDATE SET generated_at=excluded.generated_at,ticker=excluded.ticker,
                     payload_json=excluded.payload_json,score=excluded.score,grade=excluded.grade,version=excluded.version""",
                  (session_date, result["generated_at"], ticker, _json(result), comparison["score"], comparison["grade"], VERSION))
    return result


def recap_history(limit: int = 30) -> dict:
    init_db()
    with canonical_connect(DB_PATH, timeout=10) as c:
        rows = c.execute("SELECT session_date,generated_at,score,grade,payload_json FROM apex49_evening_recaps ORDER BY session_date DESC LIMIT ?", (max(1, min(int(limit), 250)),)).fetchall()
    items = []
    for sdate, generated, score, grade, payload in rows:
        p = _load(payload)
        cmp = p.get("comparison") or {}
        items.append({"session_date": sdate, "generated_at": generated, "score": score, "grade": grade, "actual_regime": cmp.get("actual_regime"), "projected_regime": cmp.get("projected_regime")})
    scored = [x["score"] for x in items if x["score"] is not None]
    return {"ok": True, "count": len(items), "average_accuracy": round(sum(scored)/len(scored), 1) if scored else None, "items": items, "version": VERSION}
