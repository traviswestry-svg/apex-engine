"""engine/feature_store.py — APEX 9 Step 5a: point-in-time feature store.

The single job of this module is to make look-ahead bias **structurally
impossible**, not merely tested for. Every function here refuses leaking input
rather than trusting the caller to behave. The tests then verify the refusal.

WHY THIS IS THE HIGH-RISK MODULE
--------------------------------
A leaky feature store does not crash. It produces a confident, well-tested,
entirely fictional edge — a backtest that says 71% win rate on a signal that
knew the answer. That failure is expensive precisely because everything
downstream looks healthy. So the defaults here are paranoid by design:
unknown feature → rejected; missing availability timestamp → rejected;
ambiguous revision status → rejected.

THE TWO-RECORD RULE (spec §17)
------------------------------
A sample is stored as two records that are never merged into one unrestricted
object:

    PreDecisionVector   — only what was knowable at `decision_time`
    LabelRecord         — MFE, MAE, target/stop, duration, outcome (the future)

They share a `sample_id` and nothing else. Reading them back together requires
`load_training_pairs()`, which enforces the session split. There is deliberately
no convenience function that hands you a flat row containing both.

THE TIMING RULE
---------------
Every feature carries `available_at`. A feature is admissible only if

    available_at <= decision_time

Strictly. A replay frame stamped 10:31:05 cannot inform a decision at 10:31:02,
even by three seconds — that is the whole ballgame.

REVISED DATA
------------
Some values are published once and revised later. End-of-day open interest is
the canonical trap: the number you can fetch tomorrow for yesterday's session was
NOT available during that session. A feature marked `revised=True` must carry the
timestamp of the revision that produced it, not the timestamp of the bar it
describes. `revised=True` with an intraday `available_at` is rejected outright.

IMMUTABILITY
------------
Samples are written, never recomputed. A flow cluster mutates as late prints
arrive (Step 3 by design), so recomputing features later would silently rewrite
history with knowledge the decision never had. Once a `PreDecisionVector` is
persisted it is frozen.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

FEATURE_SCHEMA_VERSION = "9.5.0_FEATURE_STORE"
LABEL_SCHEMA_VERSION = "9.5.0_LABELS"


class LeakageError(ValueError):
    """Raised when an operation would let the future inform the past.

    Deliberately an exception, not a warning: a leaking feature vector must never
    reach a model, and a caller that ignores warnings is the normal case.
    """


# ── The forbidden set — names that can never be pre-decision features ──────
# These are outcomes, or derived from outcomes. Any of them in a feature vector
# means the model can see the answer.
FORBIDDEN_FEATURE_NAMES: Set[str] = {
    # excursions (Step 4 labels)
    "mfe", "mfe_dollars", "mae", "mae_dollars",
    "time_to_mfe_seconds", "time_to_mae_seconds", "mfe_at", "mae_at",
    # realised P/L
    "estimated_pl_dollars", "estimated_return_pct", "current_mark", "last_mark",
    "last_pl", "cost_basis_dollars", "weighted_current_mark",
    # outcomes
    "outcome", "final_outcome", "target_hit", "stop_hit", "result", "win",
    "duration_to_outcome_seconds", "settled_at", "resolution",
    # session-closing values
    "session_close", "closing_price", "settlement", "settlement_price",
    "close", "eod_open_interest", "closing_open_interest",
    # sampling artefacts (Step 4.1 limitation 4 — reflects observation, not market)
    "samples", "sample_count", "observation_count",
}

# Substring guards catch renamed leaks ("cluster_mfe_dollars", "future_gex").
FORBIDDEN_FEATURE_SUBSTRINGS: Tuple[str, ...] = (
    "mfe", "mae", "outcome", "target_hit", "stop_hit", "settle",
    "future_", "next_", "eod_", "closing_", "_close",
    "realized", "realised", "final_",
)

# Names that are allowed despite tripping a substring guard, with the reason.
# Kept tiny and explicit — every entry is a hole in the net.
SUBSTRING_ALLOWLIST: Dict[str, str] = {
    "close_to_poc": "distance from POC at decision time; 'close' here means proximity",
}


@dataclass(frozen=True)
class Feature:
    """One point-in-time feature value.

    `available_at` is when this value became knowable — not when the thing it
    describes happened. For revised series they differ, and that difference is
    exactly the leak this store exists to prevent.
    """
    name: str
    value: Any
    available_at: str            # ISO-8601
    source: str                  # replay_frame | flow_cluster | chain | bars | ...
    revised: bool = False        # is this value subject to later revision?
    revision_of: Optional[str] = None   # ISO time of the observation it revises


def _parse(ts: Any) -> Optional[dt.datetime]:
    if not ts:
        return None
    if isinstance(ts, dt.datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=dt.timezone.utc)
    try:
        d = dt.datetime.fromisoformat(str(ts))
        return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def _forbidden_reason(name: str) -> Optional[str]:
    n = (name or "").strip().lower()
    if not n:
        return "feature name is empty"
    if n in SUBSTRING_ALLOWLIST:
        return None
    if n in FORBIDDEN_FEATURE_NAMES:
        return (f"{name!r} is an outcome or outcome-derived value; it belongs in the "
                f"label record, never in a pre-decision feature vector")
    for frag in FORBIDDEN_FEATURE_SUBSTRINGS:
        if frag in n:
            return (f"{name!r} contains {frag!r}, which marks future or outcome data. "
                    f"If this is genuinely a pre-decision feature, add it to "
                    f"SUBSTRING_ALLOWLIST with a written justification.")
    return None


def assert_feature_admissible(f: Feature, decision_time: Any) -> None:
    """Raise LeakageError unless this feature could have been known at decision_time."""
    if not isinstance(f, Feature):
        raise LeakageError(f"expected Feature, got {type(f).__name__} — features must "
                           f"carry an availability timestamp")
    reason = _forbidden_reason(f.name)
    if reason:
        raise LeakageError(reason)

    avail = _parse(f.available_at)
    dec = _parse(decision_time)
    if dec is None:
        raise LeakageError("decision_time is missing or unparseable — admissibility "
                           "cannot be established, so the feature is refused")
    if avail is None:
        raise LeakageError(f"{f.name!r} has no parseable available_at; a feature without "
                           f"an availability timestamp cannot be proven non-leaking")
    if avail > dec:
        raise LeakageError(
            f"{f.name!r} became available at {f.available_at}, which is AFTER the decision "
            f"at {decision_time}. It cannot inform that decision.")
    if f.revised:
        rev_of = _parse(f.revision_of)
        if rev_of is None:
            raise LeakageError(
                f"{f.name!r} is marked revised but carries no revision_of timestamp. A "
                f"revised value must state which observation it revises, or it will be "
                f"mistaken for contemporaneous data.")
        if avail <= rev_of:
            raise LeakageError(
                f"{f.name!r} claims to revise an observation at {f.revision_of} but reports "
                f"becoming available at {f.available_at} — a revision cannot predate what "
                f"it revises. This is how end-of-day data gets smuggled into intraday "
                f"features.")


def build_pre_decision_vector(*, sample_id: str, decision_time: str, ticker: str,
                              features: Sequence[Feature],
                              session_date: Optional[str] = None) -> Dict[str, Any]:
    """Assemble a pre-decision feature vector. Raises LeakageError on any leak.

    There is no `force=` or `strict=False`. A vector that cannot be proven
    non-leaking is not produced.
    """
    if not sample_id:
        raise LeakageError("sample_id is required — an unidentified sample cannot be "
                           "joined to its label without guesswork")
    dec = _parse(decision_time)
    if dec is None:
        raise LeakageError(f"decision_time {decision_time!r} is unparseable")
    if not features:
        raise LeakageError("a feature vector with no features is not a sample")

    seen: Set[str] = set()
    values: Dict[str, Any] = {}
    availability: Dict[str, Dict[str, Any]] = {}
    max_lag = 0.0
    for f in features:
        assert_feature_admissible(f, decision_time)
        if f.name in seen:
            raise LeakageError(f"duplicate feature {f.name!r} — ambiguous which value the "
                               f"decision saw")
        seen.add(f.name)
        values[f.name] = f.value
        avail = _parse(f.available_at)
        lag = (dec - avail).total_seconds()
        max_lag = max(max_lag, lag)
        availability[f.name] = {
            "available_at": f.available_at,
            "source": f.source,
            "lag_seconds": round(lag, 3),
            "revised": f.revised,
            "revision_of": f.revision_of,
        }

    return {
        "sample_id": sample_id,
        "session_date": session_date or str(decision_time)[:10],
        "ticker": ticker,
        "decision_time": decision_time,
        "features": values,
        "feature_availability": availability,
        "max_feature_lag_seconds": round(max_lag, 3),
        "feature_count": len(values),
        "schema_version": FEATURE_SCHEMA_VERSION,
    }


# ── Labels (the future — stored apart, deliberately) ──────────────────────
ALLOWED_LABEL_NAMES: Set[str] = {
    "mfe_dollars", "mae_dollars", "time_to_mfe_seconds", "time_to_mae_seconds",
    "target_hit", "stop_hit", "duration_seconds", "final_outcome",
    "final_pl_dollars", "final_return_pct", "samples",
}


def build_label_record(*, sample_id: str, decision_time: str, settled_at: str,
                       labels: Dict[str, Any],
                       session_date: Optional[str] = None,
                       label_basis: Optional[str] = None) -> Dict[str, Any]:
    """Assemble a post-outcome label record.

    `settled_at` must be after `decision_time`: a label that resolved before the
    decision is not an outcome of it.
    """
    if not sample_id:
        raise LeakageError("sample_id is required")
    dec = _parse(decision_time)
    settled = _parse(settled_at)
    if dec is None or settled is None:
        raise LeakageError("decision_time and settled_at must both be parseable")
    if settled < dec:
        raise LeakageError(
            f"settled_at {settled_at} precedes decision_time {decision_time} — a label "
            f"cannot resolve before the decision it labels")
    unknown = set(labels or {}) - ALLOWED_LABEL_NAMES
    if unknown:
        raise LeakageError(f"unknown label field(s) {sorted(unknown)} — add them to "
                           f"ALLOWED_LABEL_NAMES deliberately, so the label surface stays "
                           f"a closed set")
    return {
        "sample_id": sample_id,
        "session_date": session_date or str(decision_time)[:10],
        "decision_time": decision_time,
        "settled_at": settled_at,
        "labels": dict(labels or {}),
        "label_basis": label_basis or (
            "Excursions are sampled on the scanner's interval (default 300s), so MFE/MAE "
            "are lower bounds on true intraday extremes, measured from first observation "
            "rather than from the print."),
        "schema_version": LABEL_SCHEMA_VERSION,
    }


# ── Point-in-time frame resolution (the join, and the leakage boundary) ───
def resolve_frame_at_or_before(frames: Iterable[Dict[str, Any]], decision_time: str, *,
                               max_staleness_seconds: Optional[float] = None
                               ) -> Optional[Dict[str, Any]]:
    """Newest frame at or before decision_time. Never the nearest — only the prior.

    'Nearest' is the classic leak: a frame 3 seconds *after* the decision is
    nearer than one 5 minutes before, and using it hands the model the future.
    """
    dec = _parse(decision_time)
    if dec is None:
        return None
    best = None
    best_t = None
    for fr in frames or []:
        t = _parse(fr.get("captured_at") or fr.get("frame_iso"))
        if t is None:
            continue
        if t > dec:
            continue                       # strictly at-or-before
        if best_t is None or t > best_t:
            best, best_t = fr, t
    if best is None:
        return None
    if max_staleness_seconds is not None:
        lag = (dec - best_t).total_seconds()
        if lag > max_staleness_seconds:
            return None
    return best


def frames_from_replay(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize replay_snapshots rows to frames carrying a real ISO timestamp.

    replay_snapshots stores `session_date` + `frame_time` (ET wall clock) as
    separate columns; comparisons need one absolute instant.
    """
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        d = r.get("session_date")
        t = r.get("frame_time")
        if not d or not t:
            continue
        snap = r.get("snapshot")
        if snap is None and r.get("snapshot_json"):
            try:
                snap = json.loads(r["snapshot_json"])
            except (TypeError, ValueError):
                snap = None
        out.append({
            "session_date": d,
            "frame_time": t,
            "ticker": r.get("ticker"),
            "captured_at": f"{d}T{t}",
            "snapshot": snap or {},
        })
    out.sort(key=lambda f: f["captured_at"])
    return out


# Free-text / high-cardinality frame fields. These are NOT leaks — the story
# engine describes state as of the frame, so they were genuinely available — but
# they are prose, not features: unusable in a distance metric and effectively a
# unique value per sample. Excluded on modelling grounds, and named separately
# from FORBIDDEN_FEATURE_NAMES so the two reasons never get confused.
NON_FEATURE_FIELDS: Set[str] = {
    "executive_summary", "story", "narrative", "summary", "commentary",
    "coach_entry", "coach_stop", "coach_t1", "coach_t2",
}


def features_from_frame(frame: Dict[str, Any], *, names: Optional[Sequence[str]] = None
                        ) -> List[Feature]:
    """Turn a replay frame into Features stamped with the frame's own capture time.

    Every value inherits `available_at = frame.captured_at`, which is precisely
    what makes the timing rule enforceable downstream.

    Two kinds of field are skipped, for two different reasons:
      * FORBIDDEN_FEATURE_NAMES — outcome data. A leak.
      * NON_FEATURE_FIELDS — prose and per-trade price levels. Not a leak; simply
        not usable as features.

    APEX's own state at frame time (`ici`, `grade`, `decision_state`,
    `recommendation`, `coach_action`) IS kept. Those were genuinely knowable at
    the decision, and conditioning on them is the point: it is how you learn
    whether APEX's own calls fare better in some regimes than others.
    """
    snap = frame.get("snapshot") or {}
    at = frame.get("captured_at")
    out: List[Feature] = []
    for k, v in snap.items():
        if names is not None and k not in names:
            continue
        if k in NON_FEATURE_FIELDS:
            continue
        if _forbidden_reason(k):
            continue
        out.append(Feature(name=k, value=v, available_at=at, source="replay_frame"))
    return out


# ── Session splitting (spec: train and evaluation must not overlap) ───────
def assert_disjoint_sessions(train_sessions: Iterable[str],
                             eval_sessions: Iterable[str]) -> None:
    tr, ev = set(train_sessions or []), set(eval_sessions or [])
    overlap = tr & ev
    if overlap:
        raise LeakageError(
            f"train and evaluation share session(s) {sorted(overlap)}. Intraday samples "
            f"within one session are heavily correlated, so any overlap inflates measured "
            f"performance.")
    if not tr or not ev:
        raise LeakageError("both train and evaluation session sets must be non-empty")


def assert_chronological_split(train_sessions: Iterable[str],
                               eval_sessions: Iterable[str]) -> None:
    """Evaluation must come strictly after training.

    A random split across sessions leaks regime knowledge backwards: the model
    learns from Thursday to predict Tuesday, which no live system can do.
    """
    tr, ev = sorted(train_sessions or []), sorted(eval_sessions or [])
    assert_disjoint_sessions(tr, ev)
    if tr[-1] >= ev[0]:
        raise LeakageError(
            f"evaluation session {ev[0]} is not strictly after the last training session "
            f"{tr[-1]}. Evaluating on a session that precedes training data is "
            f"backwards-looking and will overstate the edge.")


def make_sample_id(*, ticker: str, decision_time: str, cluster_key: str) -> str:
    raw = f"{ticker}|{decision_time}|{cluster_key}"
    return "s_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


# ── Sample-size honesty (thresholds are PER NEIGHBOURHOOD, not global) ────
INSUFFICIENT = "insufficient"
EXPLORATORY = "exploratory"
MODERATE = "moderate"
STRONGER = "stronger"


def sample_quality(n: int) -> Dict[str, Any]:
    """Grade a MATCHED-NEIGHBOURHOOD sample count.

    The spec's thresholds don't say whether they apply globally or per
    neighbourhood. Globally they would bless "stronger evidence" at 200 total
    rows while the matched cell holds three — so this function is documented and
    named to be called with the neighbourhood count, and says so in its own output.
    """
    n = int(n or 0)
    if n < 20:
        tier, note = INSUFFICIENT, ("Fewer than 20 matched samples — no edge claim is "
                                    "supportable at any confidence.")
    elif n < 50:
        tier, note = EXPLORATORY, ("20–49 matched samples — exploratory only; treat any "
                                   "rate as a hypothesis, not a finding.")
    elif n < 200:
        tier, note = MODERATE, ("50–199 matched samples — moderate; report intervals, not "
                                "point estimates.")
    else:
        tier, note = STRONGER, ("200+ matched samples — stronger, but still subject to "
                                "regime relevance: correlated days are not independent "
                                "observations.")
    return {
        "matched_sample_count": n,
        "tier": tier,
        "note": note,
        "edge_claim_permitted": tier in (MODERATE, STRONGER),
        "basis": "Count is of samples in the MATCHED NEIGHBOURHOOD, not the store total.",
    }


def wilson_interval(successes: int, n: int, z: float = 1.96) -> Optional[Dict[str, float]]:
    """Wilson score interval — reported instead of a bare win rate.

    Chosen over the normal approximation because it stays sane at small n and
    near 0/1, which is exactly where a thin neighbourhood lives.
    """
    n = int(n or 0)
    if n <= 0:
        return None
    k = max(0, min(int(successes or 0), n))
    p = k / n
    d = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = (z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)) / d
    return {"point": round(p, 4), "low": round(max(0.0, centre - half), 4),
            "high": round(min(1.0, centre + half), 4), "n": n}
