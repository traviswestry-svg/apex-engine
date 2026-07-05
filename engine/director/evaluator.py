"""engine/director/evaluator.py — Outcome Evaluator (Stage 2).

Grades the Active Trade Director's OWN decisions after the fact, using the
directive ledger self-referentially: because the Director logs the SPX mark on
every evaluation (~every 5s), the rows that come *after* any directive ARE its
forward price path — at exactly the cadence the Director makes decisions. No
external data source, no second-resolution bars, works for SPX cash.

Primary lens is DIRECTIVE-CORRECT, not trade-P&L:
  - An ENTER can be correct even if later mismanagement loses money.
  - A HOLD can be wrong even if the trade eventually turns profitable.
  - An EXIT can be premature even though it locked in a gain.

So each directive is scored against the thing it claimed — an EXIT that fired on
a weak trigger while POC kept rising and the hold level never failed is graded
PREMATURE even if it booked +20%. A trade-P&L proxy is recorded alongside, but
it is secondary.

This module only reads history and writes its own `director_outcomes` table plus
the previously-empty outcome columns on `director_directives`. It never touches a
live decision and degrades to a no-op if the DB is unavailable.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

from .store import _connect, init_store  # reuse the same DB path + WAL connection


# ── tunables (env-overridable; these are evaluation params, not live thresholds) ──
def _envf(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


HORIZON_S = _envf("DIRECTOR_EVAL_HORIZON_S", 300.0)      # forward window per directive
MIN_MATURITY_S = _envf("DIRECTOR_EVAL_MATURITY_S", 300.0)  # row must be this old to score
MIN_SAMPLES = int(_envf("DIRECTOR_EVAL_MIN_SAMPLES", 2))   # forward rows needed to score

# favorable move worth "a lot" for a 0DTE SPX scalp, in index points
BIG_MOVE_PTS = _envf("DIRECTOR_EVAL_BIG_MOVE_PTS", 3.0)
SMALL_ADVERSE_PTS = _envf("DIRECTOR_EVAL_SMALL_ADVERSE_PTS", 1.0)

_LOCK = threading.RLock()
_INIT = False


# ── schema ────────────────────────────────────────────────────────────────────

def init_evaluator() -> bool:
    global _INIT
    if not init_store():
        return False
    with _LOCK:
        if _INIT:
            return True
        try:
            conn = _connect()
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS director_outcomes (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    directive_id   INTEGER UNIQUE,
                    symbol         TEXT,
                    ts             TEXT,
                    directive      TEXT,
                    family         TEXT,
                    side           TEXT,
                    trade_type     TEXT,
                    confidence     INTEGER,
                    mark_price     REAL,
                    fwd_30s        REAL,
                    fwd_60s        REAL,
                    fwd_180s       REAL,
                    fwd_300s       REAL,
                    mfe            REAL,
                    mae            REAL,
                    horizon_s      REAL,
                    samples        INTEGER,
                    score          INTEGER,
                    correct        INTEGER,
                    actionable     INTEGER,
                    classification TEXT,
                    pnl_proxy_pts  REAL,
                    detail         TEXT,
                    scored_at      TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_do_symbol_ts ON director_outcomes(symbol, ts);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_do_family ON director_outcomes(symbol, family);")
            conn.commit()
            conn.close()
            _INIT = True
            return True
        except Exception as e:  # pragma: no cover
            print(f"Director evaluator DISABLED — outcomes table init failed: {e}", flush=True)
            return False


# ── helpers ─────────────────────────────────────────────────────────────────────

_FAMILY = {
    "ENTER": "ENTER", "ENTER_SCALP": "ENTER",
    "HOLD": "HOLD",
    "PROTECT_PROFIT": "PROTECT",
    "SCALE_OUT_25": "SCALE", "SCALE_OUT_50": "SCALE", "SCALE_OUT_75": "SCALE",
    "EXIT_CALL_NOW": "EXIT", "EXIT_PUT_NOW": "EXIT", "EXIT_IMMEDIATELY": "EXIT",
}
_MONITORING = {"WATCHING", "SCALP_READY", "OBSERVE", "COOLDOWN", "NO_TRADE", "STAND_DOWN"}


def _family(directive: str) -> str:
    d = (directive or "").upper()
    if d.startswith("ENTER_SCALP"):
        return "ENTER"
    if d.startswith("ENTER"):
        return "ENTER"
    if d.startswith("HOLD"):
        return "HOLD"
    if d.startswith("SCALE_OUT"):
        return "SCALE"
    if d.startswith("EXIT"):
        return "EXIT"
    if d == "PROTECT_PROFIT":
        return "PROTECT"
    for k in _MONITORING:
        if d.startswith(k) or d == k:
            return "MONITOR"
    return "MONITOR"


def _epoch(ts: str) -> Optional[float]:
    if not ts:
        return None
    try:
        s = ts.replace("Z", "+00:00")
        return dt.datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def _mark(row: Dict[str, Any]) -> Optional[float]:
    """SPX mark for a ledger row — payload.position.current_price, then price col."""
    payload = row.get("payload")
    if payload:
        try:
            p = json.loads(payload)
            cp = ((p.get("position") or {}).get("current_price"))
            if cp is not None:
                return float(cp)
            if p.get("price") is not None:
                return float(p["price"])
        except Exception:
            pass
    v = row.get("price")
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _favorable(delta: float, side: str) -> float:
    """Signed so that >0 means the move helped the traded/approved side."""
    return delta if (side or "").upper() == "CALL" else -delta if (side or "").upper() == "PUT" else delta


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> int:
    return int(max(lo, min(hi, round(x))))


def _nearest_delta(base_ts: float, base_mark: float, fwd: List[Tuple[float, float]],
                   horizon: float, side: str) -> Optional[float]:
    """Favorable-signed delta at ~horizon seconds forward (nearest sample within +/-25%)."""
    target = base_ts + horizon
    best, best_dist = None, None
    for t, m in fwd:
        dist = abs(t - target)
        if dist <= horizon * 0.25 and (best_dist is None or dist < best_dist):
            best, best_dist = m, dist
    if best is None:
        return None
    return round(_favorable(best - base_mark, side), 3)


# ── scoring (directive-correct lens) ────────────────────────────────────────────

def score_directive(row: Dict[str, Any], forward: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Grade one directive row against its forward price path.

    `forward` = later ledger rows for the same symbol, within HORIZON_S, ascending.
    Returns a scorecard dict, or None if unscorable.
    """
    directive = row.get("directive") or ""
    fam = _family(directive)
    side = (row.get("side") or "").upper()
    base_ts = _epoch(row.get("ts"))
    base_mark = _mark(row)
    quality = row.get("payload")

    # market-closed rows carry no forward meaning
    try:
        flags = json.loads(quality).get("quality_flags", []) if quality else []
    except Exception:
        flags = []
    if "MARKET_CLOSED" in flags:
        return None
    if base_ts is None or base_mark is None:
        return None

    # For monitoring directives with no side, use approved/prev side hint from payload
    if not side:
        try:
            pl = json.loads(quality) if quality else {}
            side = (pl.get("side") or (pl.get("conflict") or {}).get("approved_side") or "").upper()
        except Exception:
            side = ""

    fwd: List[Tuple[float, float]] = []
    for fr in forward:
        t = _epoch(fr.get("ts"))
        m = _mark(fr)
        if t is None or m is None:
            continue
        if t <= base_ts or t > base_ts + HORIZON_S:
            continue
        fwd.append((t, m))
    fwd.sort(key=lambda x: x[0])

    if len(fwd) < MIN_SAMPLES:
        return None

    # favorable-signed excursions across the window (need a side to be meaningful)
    favs = [_favorable(m - base_mark, side) for _, m in fwd] if side else [m - base_mark for _, m in fwd]
    mfe = round(max(favs + [0.0]), 3)          # best favorable excursion (>=0)
    mae = round(min(favs + [0.0]), 3)          # worst adverse excursion (<=0)
    net = round(favs[-1], 3)                    # favorable-signed net at window end
    horizon_covered = round(fwd[-1][0] - base_ts, 1)

    fwd30 = _nearest_delta(base_ts, base_mark, fwd, 30, side)
    fwd60 = _nearest_delta(base_ts, base_mark, fwd, 60, side)
    fwd180 = _nearest_delta(base_ts, base_mark, fwd, 180, side)
    fwd300 = _nearest_delta(base_ts, base_mark, fwd, min(300, HORIZON_S), side)

    poc = (row.get("poc_migration") or "").upper()
    poc_favorable = (side == "CALL" and poc == "RISING") or (side == "PUT" and poc == "FALLING")
    invalidation = row.get("invalidation")
    hold_level = row.get("hold_level")
    # did price breach the hold/invalidation against the side within the window?
    breached = False
    if hold_level not in (None, "") and side in ("CALL", "PUT"):
        try:
            hl = float(hold_level)
            worst_mark = base_mark + mae if side == "CALL" else base_mark - mae  # mae<=0
            breached = (worst_mark < hl) if side == "CALL" else (worst_mark > hl)
        except (TypeError, ValueError):
            breached = False

    detail: Dict[str, Any] = {"family": fam, "side": side, "mfe": mfe, "mae": mae, "net": net,
                              "poc_favorable": poc_favorable, "hold_breached": breached,
                              "samples": len(fwd), "evidence": []}
    ev = detail["evidence"]
    actionable = 1
    correct: Optional[int] = None

    # ── ENTER ────────────────────────────────────────────────────────────────
    if fam == "ENTER":
        score = 55 + 7.0 * mfe + 9.0 * mae   # mae is negative => penalizes adverse
        if mfe >= BIG_MOVE_PTS and mae > -SMALL_ADVERSE_PTS:
            cls = "GOOD_ENTRY"; ev.append(f"Expanded +{mfe} pts with only {mae} adverse.")
        elif mfe < 1.0 and mae <= -1.5:
            cls = "BAD_ENTRY"; ev.append(f"Went {mae} adverse before any expansion.")
        else:
            cls = "MARGINAL_ENTRY"; ev.append(f"Mixed follow-through (mfe {mfe}, mae {mae}).")
        score = _clamp(score)
        correct = 1 if score >= 60 else 0

    # ── HOLD ─────────────────────────────────────────────────────────────────
    elif fam == "HOLD":
        score = 55 + 7.0 * net + 5.0 * mae
        if breached:
            score -= 25; ev.append("Held while price breached the hold level.")
        if net > 0.5 and not breached:
            cls = "GOOD_HOLD"; ev.append(f"Position continued +{net} pts; hold intact.")
        elif net <= -1.5 or breached:
            cls = "BAD_HOLD"; ev.append(f"Held through reversal (net {net}).")
        else:
            cls = "ACCEPTABLE_HOLD"; ev.append(f"Flat-to-mild continuation (net {net}).")
        score = _clamp(score)
        correct = 1 if score >= 55 and not breached else 0

    # ── PROTECT ──────────────────────────────────────────────────────────────
    elif fam == "PROTECT":
        run_after = max(0.0, net)            # money left on the table if it kept running
        score = 65 - 8.0 * run_after + 6.0 * max(0.0, -mae)
        if run_after >= BIG_MOVE_PTS:
            cls = "PROTECT_TOO_EARLY"; ev.append(f"Trade ran +{run_after} more pts after protect.")
        elif mae <= -SMALL_ADVERSE_PTS:
            cls = "GOOD_PROTECT"; ev.append(f"Give-back of {mae} followed — protect was right.")
        else:
            cls = "ACCEPTABLE_PROTECT"; ev.append(f"Modest drift after protect (net {net}).")
        score = _clamp(score)
        correct = 1 if score >= 55 else 0

    # ── SCALE ────────────────────────────────────────────────────────────────
    elif fam == "SCALE":
        run_after = max(0.0, net)
        score = 60 - 6.0 * run_after + 6.0 * max(0.0, -mae)
        if run_after >= BIG_MOVE_PTS:
            cls = "SCALE_TOO_EARLY"; ev.append(f"Runner would have gained +{run_after} more pts.")
        else:
            cls = "GOOD_SCALE"; ev.append(f"Flow stalled/reverted after scale (net {net}).")
        score = _clamp(score)
        correct = 1 if score >= 55 else 0

    # ── EXIT (premature-exit detection is the point) ─────────────────────────
    elif fam == "EXIT":
        favorable_after = mfe               # how much more the side would have gained
        avoided = max(0.0, -mae)            # adverse move the exit avoided
        weak_trigger = poc_favorable and not breached
        score = 55 - 7.0 * favorable_after + 8.0 * avoided
        if weak_trigger and favorable_after >= BIG_MOVE_PTS:
            score -= 15
            cls = "PREMATURE_EXIT"
            ev.append(f"Price advanced +{favorable_after} pts after exit; POC still favorable, hold intact.")
        elif avoided >= SMALL_ADVERSE_PTS and favorable_after < 1.0:
            cls = "GOOD_EXIT"; ev.append(f"Exit avoided {mae} of drawdown.")
        elif favorable_after >= BIG_MOVE_PTS:
            cls = "EARLY_EXIT"; ev.append(f"Left +{favorable_after} pts on the table.")
        else:
            cls = "ACCEPTABLE_EXIT"; ev.append(f"Roughly neutral after exit (mfe {mfe}, mae {mae}).")
        score = _clamp(score)
        correct = 1 if score >= 55 else 0

    # ── MONITOR (non-actionable in Stage 2; data kept for Stage 3 counterfactual) ─
    else:
        actionable = 0
        cls = "NON_ACTIONABLE"
        score = 50
        ev.append("Monitoring directive — not scored for accuracy (reserved for counterfactual replay).")

    # trade-P&L proxy (secondary): favorable net over window, in points
    pnl_proxy = net

    return {
        "directive_id": row.get("id"),
        "symbol": row.get("symbol"),
        "ts": row.get("ts"),
        "directive": directive,
        "family": fam,
        "side": side,
        "trade_type": row.get("trade_type") or "",
        "confidence": int(row.get("confidence") or 0),
        "mark_price": base_mark,
        "fwd_30s": fwd30, "fwd_60s": fwd60, "fwd_180s": fwd180, "fwd_300s": fwd300,
        "mfe": mfe, "mae": mae, "horizon_s": horizon_covered, "samples": len(fwd),
        "score": score, "correct": correct, "actionable": actionable,
        "classification": cls, "pnl_proxy_pts": pnl_proxy, "detail": detail,
    }


# ── backfill ────────────────────────────────────────────────────────────────────

def backfill_outcomes(symbol: str = "SPX", limit: int = 5000) -> Dict[str, Any]:
    """Score every matured, not-yet-scored directive for `symbol`. Idempotent."""
    if not init_evaluator():
        return {"ok": False, "scored": 0, "reason": "evaluator disabled"}
    symbol = (symbol or "SPX").upper()
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    cutoff_iso = dt.datetime.fromtimestamp(now - MIN_MATURITY_S, dt.timezone.utc).isoformat()

    scored = skipped = 0
    try:
        with _LOCK:
            conn = _connect()
            conn.row_factory = __import__("sqlite3").Row
            rows = conn.execute(
                """
                SELECT d.* FROM director_directives d
                LEFT JOIN director_outcomes o ON o.directive_id = d.id
                WHERE d.symbol = ? AND o.id IS NULL AND d.ts <= ?
                ORDER BY d.id ASC LIMIT ?
                """,
                (symbol, cutoff_iso, int(limit)),
            ).fetchall()
            rows = [dict(r) for r in rows]

            for r in rows:
                base_ts = _epoch(r.get("ts"))
                if base_ts is None:
                    skipped += 1
                    continue
                fwd = conn.execute(
                    """
                    SELECT id, ts, price, payload FROM director_directives
                    WHERE symbol = ? AND ts > ? AND ts <= ?
                    ORDER BY ts ASC LIMIT 400
                    """,
                    (symbol, r["ts"],
                     dt.datetime.fromtimestamp(base_ts + HORIZON_S, dt.timezone.utc).isoformat()),
                ).fetchall()
                card = score_directive(r, [dict(x) for x in fwd])
                if not card:
                    skipped += 1
                    continue
                _persist(conn, card)
                scored += 1
            conn.commit()
            conn.close()
    except Exception as e:  # pragma: no cover
        return {"ok": False, "scored": scored, "skipped": skipped, "error": str(e)}
    return {"ok": True, "symbol": symbol, "scored": scored, "skipped": skipped,
            "horizon_s": HORIZON_S, "maturity_s": MIN_MATURITY_S}


def _persist(conn, card: Dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO director_outcomes (
            directive_id, symbol, ts, directive, family, side, trade_type, confidence,
            mark_price, fwd_30s, fwd_60s, fwd_180s, fwd_300s, mfe, mae, horizon_s,
            samples, score, correct, actionable, classification, pnl_proxy_pts, detail, scored_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            card["directive_id"], card["symbol"], card["ts"], card["directive"], card["family"],
            card["side"], card["trade_type"], card["confidence"], card["mark_price"],
            card["fwd_30s"], card["fwd_60s"], card["fwd_180s"], card["fwd_300s"],
            card["mfe"], card["mae"], card["horizon_s"], card["samples"], card["score"],
            card["correct"], card["actionable"], card["classification"], card["pnl_proxy_pts"],
            json.dumps(card["detail"])[:8000],
            dt.datetime.now(dt.timezone.utc).isoformat(),
        ),
    )
    # mirror a quick-glance summary onto the directive row's reserved columns
    conn.execute(
        "UPDATE director_directives SET outcome = ?, outcome_pnl = ? WHERE id = ?",
        (card["classification"], card["pnl_proxy_pts"], card["directive_id"]),
    )


# ── aggregate scorecard ─────────────────────────────────────────────────────────

def scorecard(symbol: str = "SPX") -> Dict[str, Any]:
    """Aggregate self-evaluation: per-family accuracy, premature-exit rate,
    confidence calibration, and the worst recent actionable decisions."""
    if not init_evaluator():
        return {"ok": False, "reason": "evaluator disabled"}
    symbol = (symbol or "SPX").upper()
    import sqlite3
    try:
        with _LOCK:
            conn = _connect()
            conn.row_factory = sqlite3.Row

            fam_rows = conn.execute(
                """
                SELECT family, COUNT(*) n, AVG(score) avg_score,
                       AVG(CASE WHEN correct IS NOT NULL THEN correct END) accuracy,
                       AVG(pnl_proxy_pts) avg_pnl_pts
                FROM director_outcomes
                WHERE symbol = ? AND actionable = 1
                GROUP BY family ORDER BY family
                """,
                (symbol,),
            ).fetchall()
            families = {r["family"]: {"n": r["n"],
                                      "avg_score": round(r["avg_score"] or 0, 1),
                                      "accuracy": round((r["accuracy"] or 0) * 100, 1),
                                      "avg_pnl_pts": round(r["avg_pnl_pts"] or 0, 2)}
                        for r in fam_rows}

            prem = conn.execute(
                """SELECT
                     SUM(CASE WHEN classification='PREMATURE_EXIT' THEN 1 ELSE 0 END) prem,
                     SUM(CASE WHEN family='EXIT' THEN 1 ELSE 0 END) exits
                   FROM director_outcomes WHERE symbol = ?""",
                (symbol,),
            ).fetchone()
            exits = prem["exits"] or 0
            premature_exit_rate = round(100.0 * (prem["prem"] or 0) / exits, 1) if exits else 0.0

            cal_rows = conn.execute(
                """
                SELECT
                  CASE
                    WHEN confidence >= 90 THEN '90-100'
                    WHEN confidence >= 80 THEN '80-89'
                    WHEN confidence >= 70 THEN '70-79'
                    WHEN confidence >= 60 THEN '60-69'
                    ELSE '<60' END AS bucket,
                  COUNT(*) n,
                  AVG(CASE WHEN correct IS NOT NULL THEN correct END) accuracy,
                  AVG(confidence) avg_conf
                FROM director_outcomes
                WHERE symbol = ? AND actionable = 1 AND correct IS NOT NULL
                GROUP BY bucket ORDER BY bucket DESC
                """,
                (symbol,),
            ).fetchall()
            calibration = [{"bucket": r["bucket"], "n": r["n"],
                            "stated_confidence": round(r["avg_conf"] or 0, 1),
                            "actual_accuracy": round((r["accuracy"] or 0) * 100, 1)}
                           for r in cal_rows]

            totals = conn.execute(
                """SELECT COUNT(*) n,
                          AVG(CASE WHEN correct IS NOT NULL THEN correct END) accuracy,
                          AVG(score) avg_score
                   FROM director_outcomes WHERE symbol = ? AND actionable = 1""",
                (symbol,),
            ).fetchone()

            worst = conn.execute(
                """SELECT directive_id, ts, directive, side, score, classification, mfe, mae, pnl_proxy_pts
                   FROM director_outcomes
                   WHERE symbol = ? AND actionable = 1
                   ORDER BY score ASC, ts DESC LIMIT 10""",
                (symbol,),
            ).fetchall()
            worst_list = [dict(r) for r in worst]

            conn.close()
    except Exception as e:  # pragma: no cover
        return {"ok": False, "error": str(e)}

    return {
        "ok": True, "symbol": symbol,
        "totals": {"scored_actionable": totals["n"] or 0,
                   "overall_accuracy": round((totals["accuracy"] or 0) * 100, 1),
                   "avg_score": round(totals["avg_score"] or 0, 1)},
        "by_family": families,
        "premature_exit_rate": premature_exit_rate,
        "confidence_calibration": calibration,
        "worst_decisions": worst_list,
        "lens": "directive_correct",
        "note": "Accuracy = share of directives that were correct on their own terms; "
                "avg_pnl_pts is a secondary trade-P&L proxy in SPX points.",
    }
