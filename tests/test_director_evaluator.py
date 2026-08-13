"""tests/test_director_evaluator.py — Outcome Evaluator (Stage 2) tests.

Two layers:
  1. Unit — score_directive() graded against hand-built forward price paths, one
     per directive family, asserting the directive-correct classification.
  2. Integration — a coherent synthetic session written to a temp ledger DB, then
     backfilled and aggregated, asserting scored counts, idempotency, the
     maturity gate, and scorecard shape (premature-exit rate + calibration).

Run: python -m pytest tests/test_director_evaluator.py -q
(no pytest? the __main__ block runs the same assertions.)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# isolate the evaluator/store on a throwaway DB before importing them
_TMP_DB = os.path.join(tempfile.gettempdir(), "atd_eval_test.db")
if os.path.exists(_TMP_DB):
    os.remove(_TMP_DB)
os.environ["DIRECTOR_DB_PATH"] = _TMP_DB
os.environ.setdefault("DIRECTOR_MIN_DIRECTIVE_S", "0")  # match director suite; deterministic when run together

from engine.director import evaluator as EV  # noqa: E402
from engine.director.store import init_store, _connect  # noqa: E402


def _iso(sec_ago: float) -> str:
    return dt.datetime.fromtimestamp(
        dt.datetime.now(dt.timezone.utc).timestamp() - sec_ago, dt.timezone.utc
    ).isoformat()


def _payload(mark: float, flags=None) -> str:
    return json.dumps({"position": {"current_price": mark}, "quality_flags": flags or []})


def _row(directive, side, base_mark, *, poc="", hold_level=None, invalidation=None,
         confidence=80, trade_type="SCALP", rid=1, ts=None):
    return {
        "id": rid, "symbol": "SPX", "ts": ts or _iso(600),
        "directive": directive, "side": side, "trade_type": trade_type,
        "confidence": confidence, "poc_migration": poc,
        "hold_level": hold_level, "invalidation": invalidation,
        "price": None, "payload": _payload(base_mark),
    }


def _fwd(base_mark, path, side_ts_base=600, step=5):
    """Build forward rows from a list of absolute marks, spaced `step` seconds."""
    out = []
    for i, m in enumerate(path, start=1):
        out.append({"id": 1000 + i, "ts": _iso(side_ts_base - i * step),
                    "price": None, "payload": _payload(m)})
    return out


# ── UNIT: one scenario per family ────────────────────────────────────────────

def test_enter_expansion_is_good():
    row = _row("ENTER_CALL", "CALL", 7480.0, poc="RISING", hold_level=7478.0)
    fwd = _fwd(7480.0, [7481, 7482.5, 7484, 7484.5, 7484])  # +4.5 mfe, ~0 adverse
    card = EV.score_directive(row, fwd)
    assert card["family"] == "ENTER"
    assert card["classification"] == "GOOD_ENTRY"
    assert card["correct"] == 1


def test_enter_immediate_adverse_is_bad():
    row = _row("ENTER_CALL", "CALL", 7484.0, poc="RISING", hold_level=7482.0)
    fwd = _fwd(7484.0, [7483, 7482, 7481.5, 7482, 7482.5])  # went adverse, little expansion
    card = EV.score_directive(row, fwd)
    assert card["classification"] == "BAD_ENTRY"
    assert card["correct"] == 0


def test_hold_continuation_is_good():
    row = _row("HOLD_CALL", "CALL", 7484.0, poc="RISING", hold_level=7482.0)
    fwd = _fwd(7484.0, [7485, 7486, 7486.5, 7487])  # net +3
    card = EV.score_directive(row, fwd)
    assert card["family"] == "HOLD"
    assert card["classification"] == "GOOD_HOLD"
    assert card["correct"] == 1


def test_hold_through_breach_is_bad():
    row = _row("HOLD_CALL", "CALL", 7484.0, poc="FALLING", hold_level=7482.0)
    fwd = _fwd(7484.0, [7483, 7481.5, 7480.5, 7480])  # breaks 7482 hold, net -4
    card = EV.score_directive(row, fwd)
    assert card["classification"] == "BAD_HOLD"
    assert card["detail"]["hold_breached"] is True
    assert card["correct"] == 0


def test_protect_too_early():
    row = _row("PROTECT_PROFIT", "CALL", 7484.0, poc="RISING", hold_level=7482.0)
    fwd = _fwd(7484.0, [7485.5, 7487, 7488, 7489])  # kept running +5
    card = EV.score_directive(row, fwd)
    assert card["classification"] == "PROTECT_TOO_EARLY"
    assert card["correct"] == 0


def test_protect_giveback_is_good():
    row = _row("PROTECT_PROFIT", "CALL", 7484.0, poc="RISING", hold_level=7482.0)
    fwd = _fwd(7484.0, [7483.5, 7482.5, 7482.0, 7482.3])  # gave back ~2
    card = EV.score_directive(row, fwd)
    assert card["classification"] == "GOOD_PROTECT"
    assert card["correct"] == 1


def test_scale_too_early():
    row = _row("SCALE_OUT_50", "CALL", 7484.0, poc="RISING", hold_level=7482.0)
    fwd = _fwd(7484.0, [7485, 7486.5, 7487.5, 7488])  # runner +4
    card = EV.score_directive(row, fwd)
    assert card["family"] == "SCALE"
    assert card["classification"] == "SCALE_TOO_EARLY"


def test_exit_premature_weak_trigger():
    # CALL exit while POC still RISING and hold intact, then price runs +4 -> premature
    row = _row("EXIT_CALL_NOW", "CALL", 7484.0, poc="RISING", hold_level=7481.0)
    fwd = _fwd(7484.0, [7485, 7486.5, 7487.5, 7488])
    card = EV.score_directive(row, fwd)
    assert card["family"] == "EXIT"
    assert card["classification"] == "PREMATURE_EXIT"
    assert card["correct"] == 0


def test_exit_good_avoided_drawdown():
    # CALL exit, then price falls -2.5 -> exit protected, favorable_after small
    row = _row("EXIT_CALL_NOW", "CALL", 7484.0, poc="FALLING", hold_level=7482.0)
    fwd = _fwd(7484.0, [7483, 7482, 7481.5, 7481.5])
    card = EV.score_directive(row, fwd)
    assert card["classification"] == "GOOD_EXIT"
    assert card["correct"] == 1


def test_put_side_favorable_is_downward():
    # PUT hold: favorable = price falling
    row = _row("HOLD_PUT", "PUT", 7480.0, poc="FALLING", hold_level=7482.0)
    fwd = _fwd(7480.0, [7479, 7478, 7477.5, 7477])  # net favorable for PUT
    card = EV.score_directive(row, fwd)
    assert card["side"] == "PUT"
    assert card["classification"] == "GOOD_HOLD"
    assert card["correct"] == 1


def test_market_closed_row_skipped():
    row = _row("STAND_DOWN", "", 7483.0)
    row["payload"] = json.dumps({"position": {"current_price": 7483.0},
                                 "quality_flags": ["MARKET_CLOSED"]})
    fwd = _fwd(7483.0, [7483, 7483, 7483])
    assert EV.score_directive(row, fwd) is None


def test_monitoring_is_non_actionable():
    row = _row("WATCHING_CALLS", "", 7484.0, poc="RISING")
    fwd = _fwd(7484.0, [7485, 7486, 7486.5])
    card = EV.score_directive(row, fwd)
    assert card["actionable"] == 0
    assert card["classification"] == "NON_ACTIONABLE"
    assert card["correct"] is None


def test_insufficient_forward_samples():
    row = _row("HOLD_CALL", "CALL", 7484.0, hold_level=7482.0)
    assert EV.score_directive(row, _fwd(7484.0, [7485])) is None  # only 1 sample


# ── INTEGRATION: backfill + scorecard on a synthetic session ─────────────────

def _insert(conn, rid, ts, directive, side, mark, *, poc="", hold=None, inval=None,
            conf=80, tt="SCALP", flags=None):
    conn.execute(
        """INSERT INTO director_directives
           (id, ts, ts_et, symbol, directive, position_state, side, trade_type, confidence,
            urgency, thesis_status, flow_state, flow_change_pct, auction_state, gamma_regime,
            poc_migration, hold_level, hold_source, invalidation, price, target_1, target_2,
            target_3, reason, next_action, next_trigger, prev_directive, state_transition,
            position_source, trade_id, position_id, outcome, outcome_pnl, payload)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (rid, ts, "", "SPX", directive, "", side, tt, conf, "", "", "", 0.0, "", "",
         poc, hold, "", inval, None, None, None, None, "", "", "", "", "", "MANUAL", "", "",
         None, None, _payload(mark, flags)),
    )


def _build_session():
    init_store()
    EV.init_evaluator()
    conn = _connect()
    conn.execute("DELETE FROM director_directives")
    conn.execute("DELETE FROM director_outcomes")
    # A coherent CALL trade, all matured (>=300s old), price path rising then fading.
    # marks are logged on every row; a directive's forward path = later rows.
    base = 3600  # seconds ago for the first row
    seq = [
        ("ENTER_CALL", "CALL", 7480.0, "RISING", 7478.0),
        ("HOLD_CALL", "CALL", 7481.5, "RISING", 7479.0),
        ("HOLD_CALL", "CALL", 7483.0, "RISING", 7480.0),
        ("HOLD_CALL", "CALL", 7484.5, "RISING", 7481.0),
        ("PROTECT_PROFIT", "CALL", 7485.5, "RISING", 7482.0),
        ("EXIT_CALL_NOW", "CALL", 7486.0, "RISING", 7483.0),  # exit while POC rising...
    ]
    # ...then a long tail of rising marks so the EXIT looks premature
    tail = [7487.0, 7488.0, 7489.0, 7489.5, 7490.0, 7490.5, 7491.0, 7491.0]
    rid = 1
    t = base
    for (d, s, mark, poc, hold) in seq:
        _insert(conn, rid, _iso(t), d, s, mark, poc=poc, hold=hold, inval=hold, conf=85)
        rid += 1
        t -= 30
    for mark in tail:
        _insert(conn, rid, _iso(t), "HOLD_CALL", "CALL", mark, poc="RISING", hold=7483.0, inval=7483.0)
        rid += 1
        t -= 30
    conn.commit()
    conn.close()


def test_backfill_scores_and_is_idempotent():
    _build_session()
    r1 = EV.backfill_outcomes("SPX")
    assert r1["ok"] and r1["scored"] > 0
    first = r1["scored"]
    r2 = EV.backfill_outcomes("SPX")  # nothing new to score
    assert r2["scored"] == 0
    # outcomes table has exactly `first` rows
    conn = _connect()
    n = conn.execute("SELECT COUNT(*) FROM director_outcomes WHERE symbol='SPX'").fetchone()[0]
    conn.close()
    assert n == first


def test_exit_flagged_premature_in_session():
    _build_session()
    EV.backfill_outcomes("SPX")
    conn = _connect()
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM director_outcomes WHERE symbol='SPX' AND family='EXIT'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["classification"] == "PREMATURE_EXIT"


def test_maturity_gate_skips_recent_rows():
    _build_session()
    conn = _connect()
    # add a fresh (too-recent) directive that must NOT be scored yet
    _insert(conn, 999, _iso(5), "HOLD_CALL", "CALL", 7492.0, poc="RISING", hold=7483.0)
    conn.commit(); conn.close()
    EV.backfill_outcomes("SPX")
    conn = _connect()
    got = conn.execute("SELECT COUNT(*) FROM director_outcomes WHERE directive_id=999").fetchone()[0]
    conn.close()
    assert got == 0


def test_scorecard_shape():
    _build_session()
    EV.backfill_outcomes("SPX")
    sc = EV.scorecard("SPX")
    assert sc["ok"] is True
    assert sc["lens"] == "directive_correct"
    assert "by_family" in sc and "EXIT" in sc["by_family"]
    assert sc["premature_exit_rate"] >= 0.0
    assert isinstance(sc["confidence_calibration"], list)
    assert sc["totals"]["scored_actionable"] > 0


def test_outcome_mirrored_onto_directive_row():
    _build_session()
    EV.backfill_outcomes("SPX")
    conn = _connect()
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT outcome, outcome_pnl FROM director_directives WHERE directive='EXIT_CALL_NOW'"
    ).fetchone()
    conn.close()
    assert row["outcome"] == "PREMATURE_EXIT"
    assert row["outcome_pnl"] is not None


# ── runner ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn(); passed += 1; print(f"  PASS {fn.__name__}")
        except AssertionError as e:
            print(f"  FAIL {fn.__name__}: {e}")
        except Exception as e:
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
