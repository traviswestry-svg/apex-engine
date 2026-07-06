"""
signal_evaluator.py — Auto-scoring of Pine signals by SPX forward movement.

WHY THIS EXISTS
---------------
Pine signals land at /tv_signal and are stored in an in-memory signal_log whose
outcome fields (outcome / outcome_pnl / outcome_notes) were only ever filled by a
manual POST to /api/signal_outcome that nothing called. Result: every signal's
outcome stayed null, so the ICI gate could never be calibrated against realized
results, and the log died on every restart.

This module fixes both:
  1. Persists every signal to SQLite (survives restarts, accumulates over time).
  2. Auto-scores each signal, once it is old enough, by the SPX price move over a
     short window after entry — recording BOTH max favorable excursion (MFE) and
     max adverse excursion (MAE) in points, plus a WIN/LOSS/SCRATCH label.

DESIGN NOTES
------------
- Outcome measure is SPX index movement, NOT option P&L (deliberate: option P&L
  would fold in strike/IV/theta and measure the expression, not the signal).
- We store raw MFE and MAE in points. The WIN/LOSS label is just a *view* over
  those numbers at the current thresholds, so you can re-classify later with
  different thresholds WITHOUT re-marking anything. The raw excursions are the
  durable data.
- Classification (MFE-based, path-aware):
    WIN     : favorable move reached +WIN_PTS before adverse move reached -LOSS_PTS
    LOSS    : adverse move reached -LOSS_PTS before favorable reached +WIN_PTS
    SCRATCH : neither threshold hit within the window (chop)
- Runs off the existing background scanner cycle (no new scheduler). Every cycle
  it marks any signal that is (a) unscored and (b) at least WINDOW_MIN old.

This module NEVER raises into the caller: every public entry point is guarded.
It is intentionally decoupled from the Director's evaluator (which scores
director_directives, a different data source).
"""

from __future__ import annotations

import os
import sqlite3
import datetime as dt
from typing import Any, Dict, List, Optional, Callable, Tuple


# ── Config (env-overridable) ────────────────────────────────────────────────
def _envf(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _envi(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# 0DTE: a real entry signal should prove itself fast. Default 10-minute window.
SIGNAL_EVAL_WINDOW_MIN = _envi("SIGNAL_EVAL_WINDOW_MIN", 10)
# Meaningful SPX move thresholds, in points.
SIGNAL_EVAL_WIN_PTS = _envf("SIGNAL_EVAL_WIN_PTS", 3.0)
SIGNAL_EVAL_LOSS_PTS = _envf("SIGNAL_EVAL_LOSS_PTS", 3.0)
# Small grace so we mark only once enough forward bars almost certainly exist.
SIGNAL_EVAL_GRACE_MIN = _envi("SIGNAL_EVAL_GRACE_MIN", 1)

_EASTERN = None  # injected from app to avoid re-importing tz


# ── Persistence ─────────────────────────────────────────────────────────────
def _db_path() -> str:
    # Mirror the app's DB path convention; own table lives alongside the others.
    return os.getenv("SIGNAL_EVAL_DB_PATH", os.getenv("DB_PATH", "apex_tracking.db"))


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_db_path(), timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init_signal_eval_db() -> bool:
    """Create the signals table if absent. Returns True on success."""
    try:
        with _conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS pine_signals (
                    received_at    TEXT PRIMARY KEY,   -- ISO UTC, the join key to the in-memory log
                    received_at_et TEXT,
                    ticker         TEXT,
                    signal         TEXT,               -- CALL / PUT
                    direction      TEXT,               -- BULLISH / BEARISH
                    system         TEXT,               -- PINE_APEX_OS_v1 etc.
                    score          REAL,
                    entry_price    REAL,               -- signal 'price'/'close' at entry
                    apex_ici       REAL,
                    apex_decision  TEXT,
                    apex_auction   TEXT,
                    poc            REAL,
                    vah            REAL,
                    val            REAL,
                    -- outcome (filled by auto-marker) --
                    outcome        TEXT,               -- WIN / LOSS / SCRATCH / null=unscored
                    mfe_pts        REAL,               -- max favorable excursion (pts, signed +)
                    mae_pts        REAL,               -- max adverse excursion (pts, signed -)
                    outcome_pnl    REAL,               -- convenience = mfe if win else mae
                    outcome_notes  TEXT,
                    marked_at      TEXT
                );
                """
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_ps_unscored ON pine_signals(outcome);")
            c.execute("CREATE INDEX IF NOT EXISTS idx_ps_system ON pine_signals(system, received_at);")
        return True
    except Exception as e:  # pragma: no cover - defensive
        print(f"signal_evaluator: init failed: {e}", flush=True)
        return False


def record_signal(sig: Dict[str, Any]) -> None:
    """Persist a freshly-received signal. Safe to call from /tv_signal.

    Idempotent on received_at (INSERT OR IGNORE) so a replay never double-inserts.
    """
    try:
        entry = sig.get("price")
        if entry is None:
            entry = sig.get("close")
        with _conn() as c:
            c.execute(
                """
                INSERT OR IGNORE INTO pine_signals
                  (received_at, received_at_et, ticker, signal, direction, system,
                   score, entry_price, apex_ici, apex_decision, apex_auction, poc, vah, val)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    sig.get("received_at"),
                    sig.get("received_at_et"),
                    sig.get("ticker"),
                    sig.get("signal"),
                    sig.get("direction"),
                    sig.get("system"),
                    _num(sig.get("score")),
                    _num(entry),
                    _num(sig.get("apex_ici")),
                    sig.get("apex_decision"),
                    sig.get("apex_auction"),
                    _num(sig.get("poc")),
                    _num(sig.get("vah")),
                    _num(sig.get("val")),
                ),
            )
    except Exception as e:  # pragma: no cover
        print(f"signal_evaluator: record_signal failed: {e}", flush=True)


def _num(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ── Marking ─────────────────────────────────────────────────────────────────
def _parse_iso_utc(s: str) -> Optional[dt.datetime]:
    if not s:
        return None
    try:
        d = dt.datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def _excursions(entry_price: float, side: str,
                fwd_bars: List[Dict[str, Any]]) -> Tuple[float, float]:
    """Return (mfe_pts, mae_pts) over forward bars, signed relative to the trade.

    For a CALL: favorable = up. MFE = max(high)-entry (>=0), MAE = min(low)-entry (<=0).
    For a PUT: favorable = down. We flip signs so MFE is still the favorable (>=0)
    magnitude and MAE the adverse (<=0) magnitude, both expressed in the trade's frame.
    """
    is_call = str(side).upper() == "CALL"
    highs = [b for b in (_num(x.get("h")) for x in fwd_bars) if b is not None]
    lows = [b for b in (_num(x.get("l")) for x in fwd_bars) if b is not None]
    if not highs or not lows:
        return (0.0, 0.0)
    hi = max(highs)
    lo = min(lows)
    if is_call:
        mfe = hi - entry_price          # best up-move (favorable)
        mae = lo - entry_price          # worst down-move (adverse, <=0)
    else:  # PUT
        mfe = entry_price - lo          # best down-move (favorable, positive magnitude)
        mae = entry_price - hi          # worst up-move (adverse, <=0)
    # Clamp to sensible signs.
    mfe = max(mfe, 0.0)
    mae = min(mae, 0.0)
    return (round(mfe, 2), round(mae, 2))


def _classify_pathaware(entry_price: float, side: str,
                        fwd_bars: List[Dict[str, Any]]) -> Tuple[str, float, float]:
    """Path-aware WIN/LOSS/SCRATCH: which threshold was hit FIRST, bar by bar.

    Returns (label, mfe_pts, mae_pts). mfe/mae are the full-window excursions
    (durable data); the label reflects which threshold was crossed first.
    """
    is_call = str(side).upper() == "CALL"
    win_t = SIGNAL_EVAL_WIN_PTS
    loss_t = SIGNAL_EVAL_LOSS_PTS
    label = "SCRATCH"
    for b in fwd_bars:
        h = _num(b.get("h"))
        l = _num(b.get("l"))
        if h is None or l is None:
            continue
        if is_call:
            fav = h - entry_price      # intrabar best favorable
            adv = l - entry_price      # intrabar worst adverse (<=0)
        else:
            fav = entry_price - l
            adv = entry_price - h
        # Path-aware but intrabar-ambiguous: if a single bar spans both thresholds
        # we cannot know order within the bar, so we treat adverse-first as the
        # conservative assumption (counts as LOSS) — never over-credit a win.
        hit_adv = adv <= -loss_t
        hit_fav = fav >= win_t
        if hit_adv:
            label = "LOSS"
            break
        if hit_fav:
            label = "WIN"
            break
    mfe, mae = _excursions(entry_price, side, fwd_bars)
    return (label, mfe, mae)


def mark_due_signals(
    get_intraday_bars: Callable[..., List[Dict[str, Any]]],
    now_utc: Optional[dt.datetime] = None,
    on_marked: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> int:
    """Score every unscored signal that is now old enough. Returns count marked.

    `get_intraday_bars(ticker, multiplier, limit_days)` is injected from the app so
    this module has no Polygon dependency of its own. `on_marked(received_at, patch)`
    is an optional callback to sync the in-memory log.
    """
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    window = dt.timedelta(minutes=SIGNAL_EVAL_WINDOW_MIN)
    grace = dt.timedelta(minutes=SIGNAL_EVAL_GRACE_MIN)
    due_before = now_utc - window - grace

    try:
        with _conn() as c:
            rows = c.execute(
                "SELECT * FROM pine_signals WHERE outcome IS NULL ORDER BY received_at ASC LIMIT 200"
            ).fetchall()
    except Exception as e:  # pragma: no cover
        print(f"signal_evaluator: select failed: {e}", flush=True)
        return 0

    if not rows:
        return 0

    # Cache bars per ticker for this pass (usually just SPX).
    bars_cache: Dict[str, List[Dict[str, Any]]] = {}
    marked = 0

    for r in rows:
        recv = _parse_iso_utc(r["received_at"])
        if not recv or recv > due_before:
            continue  # not old enough yet
        entry = _num(r["entry_price"])
        if entry is None or entry <= 0:
            _persist_outcome(r["received_at"], "SCRATCH", 0.0, 0.0,
                             "No entry price on signal — cannot score.", on_marked)
            marked += 1
            continue

        ticker = (r["ticker"] or "SPX")
        if ticker not in bars_cache:
            try:
                bars_cache[ticker] = get_intraday_bars(ticker, 1, 3)  # 1-min bars, ~3d
            except Exception as e:
                print(f"signal_evaluator: bar fetch failed for {ticker}: {e}", flush=True)
                bars_cache[ticker] = []
        allbars = bars_cache[ticker]

        start_ms = int(recv.timestamp() * 1000)
        end_ms = int((recv + window).timestamp() * 1000)
        fwd = []
        for b in allbars:
            t = _num(b.get("t"))
            if t is not None and start_ms <= t <= end_ms:
                fwd.append(b)

        if not fwd:
            # Bars for that window not available (data gap). Leave unscored so a
            # later pass can retry once Polygon backfills — UNLESS the window is
            # very stale (>1 day), in which case mark NO_DATA to stop retrying.
            if recv < now_utc - dt.timedelta(days=1):
                _persist_outcome(r["received_at"], "SCRATCH", 0.0, 0.0,
                                 "No forward bars available for window (stale).", on_marked)
                marked += 1
            continue

        label, mfe, mae = _classify_pathaware(entry, r["signal"], fwd)
        pnl = mfe if label == "WIN" else (mae if label == "LOSS" else 0.0)
        notes = (f"MFE {mfe:+.2f} / MAE {mae:+.2f} pts over {SIGNAL_EVAL_WINDOW_MIN}m "
                 f"(win≥{SIGNAL_EVAL_WIN_PTS}, loss≥{SIGNAL_EVAL_LOSS_PTS}); {len(fwd)} bars.")
        _persist_outcome(r["received_at"], label, mfe, mae, notes, on_marked, pnl=pnl)
        marked += 1

    return marked


def _persist_outcome(received_at: str, label: str, mfe: float, mae: float,
                     notes: str, on_marked: Optional[Callable[[str, Dict[str, Any]], None]],
                     pnl: Optional[float] = None) -> None:
    if pnl is None:
        pnl = mfe if label == "WIN" else (mae if label == "LOSS" else 0.0)
    marked_at = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        with _conn() as c:
            c.execute(
                """UPDATE pine_signals
                   SET outcome=?, mfe_pts=?, mae_pts=?, outcome_pnl=?, outcome_notes=?, marked_at=?
                   WHERE received_at=?""",
                (label, mfe, mae, pnl, notes, marked_at, received_at),
            )
    except Exception as e:  # pragma: no cover
        print(f"signal_evaluator: persist failed: {e}", flush=True)
        return
    if on_marked:
        try:
            on_marked(received_at, {
                "outcome": label, "outcome_pnl": pnl, "outcome_notes": notes,
                "mfe_pts": mfe, "mae_pts": mae,
            })
        except Exception:
            pass


# ── Reporting ───────────────────────────────────────────────────────────────
def scorecard(system: Optional[str] = None) -> Dict[str, Any]:
    """Aggregate win/loss stats. Optionally filter to one system (e.g. PINE_APEX_OS_v1)."""
    q = "SELECT outcome, mfe_pts, mae_pts, apex_ici FROM pine_signals WHERE outcome IS NOT NULL"
    params: List[Any] = []
    if system:
        q += " AND system=?"
        params.append(system)
    try:
        with _conn() as c:
            rows = c.execute(q, params).fetchall()
    except Exception as e:  # pragma: no cover
        return {"ok": False, "error": str(e)}

    n = len(rows)
    if n == 0:
        return {"ok": True, "n": 0, "note": "No scored signals yet."}
    wins = sum(1 for r in rows if r["outcome"] == "WIN")
    losses = sum(1 for r in rows if r["outcome"] == "LOSS")
    scratches = n - wins - losses
    decisive = wins + losses
    avg_mfe = round(sum((r["mfe_pts"] or 0) for r in rows) / n, 2)
    avg_mae = round(sum((r["mae_pts"] or 0) for r in rows) / n, 2)
    # ICI diagnostic: mean ICI of winners vs losers — the core calibration signal.
    win_ici = [r["apex_ici"] for r in rows if r["outcome"] == "WIN" and r["apex_ici"] is not None]
    loss_ici = [r["apex_ici"] for r in rows if r["outcome"] == "LOSS" and r["apex_ici"] is not None]
    return {
        "ok": True,
        "n": n,
        "wins": wins,
        "losses": losses,
        "scratches": scratches,
        "win_rate_decisive": round(100 * wins / decisive, 1) if decisive else None,
        "win_rate_all": round(100 * wins / n, 1),
        "avg_mfe_pts": avg_mfe,
        "avg_mae_pts": avg_mae,
        "mean_ici_winners": round(sum(win_ici) / len(win_ici), 1) if win_ici else None,
        "mean_ici_losers": round(sum(loss_ici) / len(loss_ici), 1) if loss_ici else None,
        "system": system or "ALL",
    }
