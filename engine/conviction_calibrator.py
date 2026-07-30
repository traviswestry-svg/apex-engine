"""
APEX — Conviction calibrator.

Location: engine/conviction_calibrator.py

Turns raw conviction (the entry-time ICI) into a *calibrated* probability by
measuring realized outcomes, so "80" actually means "~80% of the time this
resolved a win." Feeds ConvictionResult.build(calibrator=...) in the decision
reasoning layer, and can also back a corrected calibration-readiness readout.

WHERE THE DATA COMES FROM — the important bit:
  It reads `pine_signals` (apex_tracking.db), NOT recommendation_ledger.
  pine_signals stores `apex_ici` (raw conviction at entry) alongside `outcome`
  (WIN/LOSS/SCRATCH), and signal_evaluator.mark_due_signals auto-grades it in the
  live loop. recommendation_ledger has no auto-grader, which is why the existing
  Calibration Readiness endpoint reads 0 — it's counting the wrong table.

METHOD (honest, small-sample-safe):
  * Only WIN/LOSS resolve the rate; SCRATCH is excluded from the denominator
    (reported separately) — it's chop, not a directional verdict.
  * Bin raw ICI, Beta-shrink each bin's win-rate toward the base rate so a thin
    bin can't swing the curve, then enforce monotonic non-decreasing with
    pool-adjacent-violators (isotonic). Calibrated value = interpolation along
    the monotonic bin curve.
  * Below `minimum` graded samples -> returns an IDENTITY calibrator flagged
    disabled (raw==calibrated). Never certifies a curve built on too little data.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

DEFAULT_MIN = 50


def _db_path() -> str:
    return os.getenv("SIGNAL_EVAL_DB_PATH", os.getenv("DB_PATH", "apex_tracking.db"))


@dataclass
class Outcome:
    raw: float                 # apex_ici (or score) at entry, 0..100
    win: Optional[bool]        # True=WIN, False=LOSS, None=SCRATCH (excluded from rate)


def load_pine_outcomes(db_path: Optional[str] = None, *, value_col: str = "apex_ici",
                       system: Optional[str] = None) -> List[Outcome]:
    """Read graded signals. Pure DB read; returns [] on any error (never raises)."""
    path = db_path or _db_path()
    out: List[Outcome] = []
    try:
        c = sqlite3.connect(path, timeout=5.0)
        c.row_factory = sqlite3.Row
        q = (f"SELECT {value_col} AS raw, outcome FROM pine_signals "
             f"WHERE outcome IS NOT NULL AND {value_col} IS NOT NULL")
        args: tuple = ()
        if system:
            q += " AND system=?"
            args = (system,)
        for r in c.execute(q, args):
            oc = str(r["outcome"]).upper()
            win = True if oc == "WIN" else False if oc == "LOSS" else None
            try:
                raw = float(r["raw"])
            except (TypeError, ValueError):
                continue
            out.append(Outcome(raw, win))
        c.close()
    except sqlite3.Error:
        pass
    return out


def _beta_shrink(wins: float, n: float, prior: float, strength: float = 4.0) -> float:
    """Shrink a bin win-rate toward the base rate; strength = pseudo-observations."""
    denom = n + strength
    return ((wins + strength * prior) / denom) if denom > 0 else prior


def _pava(ys: List[float], ws: List[float]) -> List[float]:
    """Weighted pool-adjacent-violators -> monotonic non-decreasing fit of ys."""
    n = len(ys)
    if n == 0:
        return []
    # blocks: (value, weight, count)
    vals = list(ys)
    wts = list(ws)
    blocks: List[List[float]] = [[vals[i], wts[i], 1] for i in range(n)]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] > blocks[i + 1][0] + 1e-12:  # violation -> pool
            w0, w1 = blocks[i][1], blocks[i + 1][1]
            merged_w = w0 + w1
            merged_v = (blocks[i][0] * w0 + blocks[i + 1][0] * w1) / merged_w if merged_w else blocks[i][0]
            blocks[i] = [merged_v, merged_w, blocks[i][2] + blocks[i + 1][2]]
            del blocks[i + 1]
            if i > 0:
                i -= 1
        else:
            i += 1
    # expand blocks back to per-bin values
    result: List[float] = []
    for v, _w, cnt in blocks:
        result.extend([v] * int(cnt))
    return result


@dataclass
class Calibrator:
    enabled: bool
    minimum: int
    n_graded: int
    n_scratch: int
    base_rate: float
    bin_centers: List[float] = field(default_factory=list)
    bin_calibrated: List[float] = field(default_factory=list)   # 0..1, monotonic
    reliability: List[dict] = field(default_factory=list)
    source: str = "pine_signals.apex_ici"

    def calibrate(self, raw: float) -> float:
        """raw ICI (0..100) -> calibrated confidence (0..100). Identity if disabled."""
        try:
            x = float(raw)
        except (TypeError, ValueError):
            return raw
        if not self.enabled or not self.bin_centers:
            return round(x, 2)
        cs, ys = self.bin_centers, self.bin_calibrated
        if x <= cs[0]:
            y = ys[0]
        elif x >= cs[-1]:
            y = ys[-1]
        else:
            y = ys[-1]
            for i in range(1, len(cs)):
                if x <= cs[i]:
                    span = cs[i] - cs[i - 1]
                    t = (x - cs[i - 1]) / span if span else 0.0
                    y = ys[i - 1] + t * (ys[i] - ys[i - 1])
                    break
        return round(100.0 * y, 2)

    def __call__(self, raw: float) -> float:
        return self.calibrate(raw)

    def status(self) -> dict:
        """Mirrors the Calibration Readiness payload — drop-in replacement that
        counts the table that actually has an auto-grader."""
        return {
            "status": "READY" if self.enabled else "INSUFFICIENT_HISTORY",
            "gradeable_rows": self.n_graded,
            "minimum_required": self.minimum,
            "remaining": max(0, self.minimum - self.n_graded),
            "calibration_enabled": self.enabled,
            "base_rate": round(self.base_rate, 4),
            "scratch_excluded": self.n_scratch,
            "source": self.source,
            "ok": True,
        }


def build_conviction_calibrator(
    db_path: Optional[str] = None, *,
    minimum: int = DEFAULT_MIN,
    value_col: str = "apex_ici",
    system: Optional[str] = None,
    n_bins: int = 5,
    shrink_strength: float = 4.0,
    _rows: Optional[Sequence[Outcome]] = None,   # injectable for testing
) -> Calibrator:
    rows = list(_rows) if _rows is not None else load_pine_outcomes(db_path, value_col=value_col, system=system)
    resolved = [o for o in rows if o.win is not None]
    n_scratch = sum(1 for o in rows if o.win is None)
    n = len(resolved)
    base = (sum(1 for o in resolved if o.win) / n) if n else 0.0

    if n < minimum:
        return Calibrator(False, minimum, n, n_scratch, base, source=f"pine_signals.{value_col}")

    lo = min(o.raw for o in resolved)
    hi = max(o.raw for o in resolved)
    if hi <= lo:
        # all raw identical -> can't build a curve; stay disabled
        return Calibrator(False, minimum, n, n_scratch, base, source=f"pine_signals.{value_col}")

    width = (hi - lo) / n_bins
    centers: List[float] = []
    rates: List[float] = []
    weights: List[float] = []
    reliability: List[dict] = []
    for b in range(n_bins):
        b_lo = lo + b * width
        b_hi = hi if b == n_bins - 1 else lo + (b + 1) * width
        members = [o for o in resolved if (b_lo <= o.raw <= b_hi if b == n_bins - 1 else b_lo <= o.raw < b_hi)]
        cnt = len(members)
        if cnt == 0:
            continue
        wins = sum(1 for o in members if o.win)
        shrunk = _beta_shrink(wins, cnt, base, shrink_strength)
        centers.append((b_lo + b_hi) / 2.0)
        rates.append(shrunk)
        weights.append(float(cnt))
        reliability.append({
            "bin": f"{b_lo:.0f}-{b_hi:.0f}", "n": cnt,
            "raw_win_rate": round(wins / cnt, 4),
            "calibrated": round(shrunk, 4),
        })

    if len(centers) < 2:
        return Calibrator(False, minimum, n, n_scratch, base, source=f"pine_signals.{value_col}")

    mono = _pava(rates, weights)
    for i, r in enumerate(reliability):
        r["calibrated"] = round(mono[i], 4)

    return Calibrator(True, minimum, n, n_scratch, base, centers, mono, reliability,
                      source=f"pine_signals.{value_col}")


# --------------------------------------------------------------------------- #
# Demo / self-test
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    import random
    random.seed(7)

    def synth(n):
        """Signals where P(win) rises with apex_ici (logistic), ~15% SCRATCH."""
        out = []
        for _ in range(n):
            ici = random.uniform(30, 95)
            p = 1 / (1 + pow(2.718281828, -(ici - 62) / 8))  # ~0 at low ICI, ~1 at high
            if random.random() < 0.15:
                out.append(Outcome(ici, None))               # scratch
            else:
                out.append(Outcome(ici, random.random() < p))
        return out

    print("== insufficient sample (n=20) ==")
    cal = build_conviction_calibrator(_rows=synth(20))
    print(cal.status())
    print("calibrate(80) ->", cal.calibrate(80), "(identity, disabled)")

    print("\n== sufficient sample (n=300) ==")
    cal = build_conviction_calibrator(_rows=synth(300))
    st = cal.status()
    print(st)
    print("reliability (raw win-rate vs monotonic calibrated):")
    for r in cal.reliability:
        print(f"   ICI {r['bin']:>7}  n={r['n']:>3}  raw={r['raw_win_rate']:.2f}  cal={r['calibrated']:.2f}")
    print("monotonic check:", [cal.calibrate(x) for x in (35, 50, 65, 80, 92)])
    print("-> ACT gate: raw ICI 80 now means calibrated", cal.calibrate(80), "%")
