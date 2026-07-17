"""engine/feature_store_writer.py — APEX 9 Step 5a.1: populating the store.

This is what starts the clock. Until it runs, `flow_features` stays at zero rows
forever — the store is inert, not accumulating.

THE DECISION POINT: WHEN IS A CLUSTER'S SAMPLE WRITTEN?
-------------------------------------------------------
A cluster mutates as prints arrive, so "now" is not a decision point. Two rules
resolve it:

  * `decision_time` = the cluster's **end_time** (its last print). That is the
    instant the campaign was observable in full.
  * The sample is only written once the cluster is **SEALED** — i.e.
    `now >= end_time + FLOW_CLUSTER_GAP_S`. Past that, no later print can chain
    to it (Step 3's gap rule), so membership can no longer grow.

Writing at seal but stamping `decision_time = end_time` is the crux: features are
resolved at-or-before end_time, so the ~2 minutes we waited for the seal buys
completeness **without** leaking hindsight into the vector.

WHY FIRST-WRITE-WINS IS CORRECT HERE
------------------------------------
The tape is a sliding window (last ~100 prints). A cluster is visible only while
its prints remain in it; as the window slides, members age out and the cluster
**shrinks**. So the first sealed observation is the most complete one that will
ever exist. `write_features` refusing overwrites is therefore not just an
immutability rule — it captures the best available snapshot.

THE LABEL HORIZON, AND WHOSE TARGET IT IS
-----------------------------------------
Outcomes are measured to **session close** (16:00 ET). For 0DTE that is expiry;
for later expirations it is a defined intraday horizon.

`target_hit` / `stop_hit` use **APEX-defined thresholds on the cluster's own cost
basis** — we do not know the participant's actual target, and pretending to would
be fabrication. Defaults: target = +100% of cost basis, stop = −50%. Both are
flags, and the label record says plainly that these are our thresholds, not
theirs.

**Ordering matters more than either flag.** A cluster that hit −50% before it hit
+100% was a loser, not a winner. So `final_outcome` compares `time_to_mae` with
`time_to_mfe` and reports TARGET_FIRST / STOP_FIRST / BOTH_SAME_SAMPLE /
TARGET_ONLY / STOP_ONLY / NEITHER. When both excursions land in the same sampling
interval their true order is unknowable — that is reported as
BOTH_SAME_SAMPLE rather than guessed.
"""
from __future__ import annotations

import datetime as dt
import os
from typing import Any, Callable, Dict, List, Optional

from .feature_store import (
    Feature,
    LeakageError,
    build_label_record,
    build_pre_decision_vector,
    features_from_frame,
    frames_from_replay,
    make_sample_id,
    resolve_frame_at_or_before,
)
from . import feature_store_db, flow_pl_store

WRITER_VERSION = "9.5.1_FEATURE_STORE_WRITER"

_GAP_S = float(os.getenv("FLOW_CLUSTER_GAP_S", "120"))
# A decision informed by a 20-minute-old frame is barely informed. Recorded per
# sample regardless, but beyond this the sample is skipped rather than written
# with features nobody would call current.
_MAX_FRAME_STALENESS_S = float(os.getenv("FEATURE_MAX_FRAME_STALENESS_S", "600"))
_TARGET_PCT = float(os.getenv("FLOW_LABEL_TARGET_PCT", "100"))
_STOP_PCT = float(os.getenv("FLOW_LABEL_STOP_PCT", "-50"))

# Cluster-derived features. Whitelisted, so a new Step 3 field cannot silently
# become a model input without someone deciding it should be.
_CLUSTER_FEATURE_KEYS = (
    "number_of_prints", "total_premium", "total_contracts",
    "weighted_average_execution_price", "aggression_score",
    "repeat_intensity_score", "distinct_contracts", "premium_concentration",
    "confidence", "duration_seconds", "option_type",
    "directional_interpretation", "expiration",
)


def _secs(hhmmss: Any) -> Optional[int]:
    parts = str(hhmmss or "").split(":")
    if len(parts) < 2:
        return None
    try:
        h, m = int(parts[0]), int(parts[1])
        s = int(parts[2]) if len(parts) > 2 else 0
    except (TypeError, ValueError):
        return None
    return h * 3600 + m * 60 + s


def _cluster_features(cl: Dict[str, Any], at: str) -> List[Feature]:
    """Cluster attributes, available at the cluster's own end_time."""
    out: List[Feature] = []
    for k in _CLUSTER_FEATURE_KEYS:
        if k not in cl:
            continue
        out.append(Feature(name=f"cluster_{k}", value=cl.get(k),
                           available_at=at, source="flow_cluster"))
    iu = cl.get("intent_uncertainty") or {}
    if "score" in iu:
        out.append(Feature(name="cluster_intent_uncertainty", value=iu.get("score"),
                           available_at=at, source="flow_cluster"))
    auth = cl.get("flow_authenticity") or {}
    for k in ("state", "scheduled_candidate", "near_hour_or_half_hour",
              "boundary_distance_seconds", "complex_print_ratio",
              "directional_confidence_multiplier"):
        if k in auth:
            out.append(Feature(name=f"cluster_flow_authenticity_{k}", value=auth.get(k),
                               available_at=at, source="flow_authenticity"))
    if "directional_confidence_adjusted" in cl:
        out.append(Feature(name="cluster_directional_confidence_adjusted",
                           value=cl.get("directional_confidence_adjusted"),
                           available_at=at, source="flow_authenticity"))
    sr = cl.get("strike_range")
    if isinstance(sr, (list, tuple)) and len(sr) == 2:
        out.append(Feature(name="cluster_strike_low", value=sr[0],
                           available_at=at, source="flow_cluster"))
        out.append(Feature(name="cluster_strike_high", value=sr[1],
                           available_at=at, source="flow_cluster"))
    return out


def write_samples(*, priced_clusters: List[Dict[str, Any]],
                  replay_rows: List[Dict[str, Any]],
                  session_date: str,
                  now_et_seconds: int,
                  ticker: str = "SPX") -> Dict[str, Any]:
    """Write pre-decision vectors for every SEALED cluster. Never raises.

    Returns a report — counts plus why samples were skipped, so a store that
    stays empty explains itself instead of looking healthy.
    """
    report = {"written": 0, "already_present": 0, "not_sealed": 0,
              "no_frame": 0, "refused": 0, "reasons": [],
              "writer_version": WRITER_VERSION}
    if not feature_store_db.is_ready():
        report["reasons"].append("feature store not ready")
        return report
    try:
        frames = frames_from_replay(replay_rows)
        for cl in priced_clusters or []:
            end_t = _secs(cl.get("end_time"))
            if end_t is None:
                report["refused"] += 1
                continue
            # SEAL: no later print can chain to this cluster any more.
            if now_et_seconds - end_t < _GAP_S:
                report["not_sealed"] += 1
                continue

            decision_time = f"{session_date}T{cl.get('end_time')}"
            ckey = cl.get("cluster_key_string") or _key_string(cl)
            sid = make_sample_id(ticker=cl.get("ticker") or ticker,
                                 decision_time=decision_time, cluster_key=ckey)
            if feature_store_db.get_features(sid):
                report["already_present"] += 1
                continue

            frame = resolve_frame_at_or_before(
                frames, decision_time, max_staleness_seconds=_MAX_FRAME_STALENESS_S)
            if frame is None:
                report["no_frame"] += 1
                report["reasons"].append(
                    f"{sid}: no replay frame at-or-before {decision_time} within "
                    f"{_MAX_FRAME_STALENESS_S:.0f}s — sample skipped rather than "
                    f"built from stale or future state")
                continue

            feats = features_from_frame(frame) + _cluster_features(cl, decision_time)
            try:
                vec = build_pre_decision_vector(
                    sample_id=sid, decision_time=decision_time,
                    ticker=cl.get("ticker") or ticker, features=feats,
                    session_date=session_date)
            except LeakageError as e:
                # The guards did their job. Never downgrade this to a warning.
                report["refused"] += 1
                report["reasons"].append(f"{sid}: REFUSED — {e}")
                continue
            if feature_store_db.write_features(vec):
                report["written"] += 1
            else:
                report["already_present"] += 1
        return report
    except Exception as e:  # pragma: no cover
        report["reasons"].append(f"writer recovered: {e}")
        return report


def _key_string(cl: Dict[str, Any]) -> str:
    k = cl.get("cluster_key") or {}
    return f"{k.get('ticker')}|{k.get('option_type')}|{k.get('expiration')}|" \
           f"{k.get('directional_interpretation')}"


def _classify_outcome(mfe: Optional[float], mae: Optional[float],
                      cost: Optional[float], t_mfe: Optional[int],
                      t_mae: Optional[int]) -> Dict[str, Any]:
    """Decide target/stop and — crucially — which came first."""
    if not cost or cost <= 0 or mfe is None or mae is None:
        return {"target_hit": None, "stop_hit": None, "final_outcome": None}
    mfe_pct = mfe / cost * 100.0
    mae_pct = mae / cost * 100.0
    hit_t = mfe_pct >= _TARGET_PCT
    hit_s = mae_pct <= _STOP_PCT
    if hit_t and hit_s:
        if t_mfe is None or t_mae is None:
            outcome = "BOTH_ORDER_UNKNOWN"
        elif t_mae < t_mfe:
            outcome = "STOP_FIRST"
        elif t_mfe < t_mae:
            outcome = "TARGET_FIRST"
        else:
            # Same sampling interval — the true order is not observable at a
            # 300s grid, and guessing would invent a win rate.
            outcome = "BOTH_SAME_SAMPLE"
    elif hit_t:
        outcome = "TARGET_ONLY"
    elif hit_s:
        outcome = "STOP_ONLY"
    else:
        outcome = "NEITHER"
    return {"target_hit": bool(hit_t), "stop_hit": bool(hit_s), "final_outcome": outcome}


def settle_labels(*, session_date: str, ticker: str = "SPX") -> Dict[str, Any]:
    """Write label records for unlabelled samples, measured to session close.

    Called after the cash close. Never raises.
    """
    report = {"labelled": 0, "no_excursion": 0, "skipped": 0,
              "writer_version": WRITER_VERSION}
    if not feature_store_db.is_ready() or not flow_pl_store.is_ready():
        return report
    try:
        pending = feature_store_db.unlabelled_samples(session_date)
        if not pending:
            return report
        vectors = [feature_store_db.get_features(sid) for sid in pending]
        vectors = [v for v in vectors if v]
        keys = []
        for v in vectors:
            f = v.get("features") or {}
            keys.append(f"{v.get('ticker')}|{f.get('cluster_option_type')}|"
                        f"{f.get('cluster_expiration')}|"
                        f"{f.get('cluster_directional_interpretation')}")
        exc = flow_pl_store.get_cluster_excursions(list(set(keys)), session_date)

        settled_at = f"{session_date}T16:00:00"
        for v, key in zip(vectors, keys):
            e = exc.get(key)
            if not e or e.get("mfe_dollars") is None:
                report["no_excursion"] += 1
                continue
            cost = e.get("cost_basis")
            oc = _classify_outcome(e.get("mfe_dollars"), e.get("mae_dollars"), cost,
                                   e.get("time_to_mfe_seconds"), e.get("time_to_mae_seconds"))
            labels = {
                "mfe_dollars": e.get("mfe_dollars"),
                "mae_dollars": e.get("mae_dollars"),
                "time_to_mfe_seconds": e.get("time_to_mfe_seconds"),
                "time_to_mae_seconds": e.get("time_to_mae_seconds"),
                "final_pl_dollars": e.get("last_pl"),
                "duration_seconds": e.get("time_to_mfe_seconds"),
            }
            labels.update({k: val for k, val in oc.items() if val is not None})
            if cost:
                labels["final_return_pct"] = round(
                    (e.get("last_pl") or 0.0) / cost * 100.0, 2)
            try:
                rec = build_label_record(
                    sample_id=v["sample_id"], decision_time=v["decision_time"],
                    settled_at=settled_at, labels=labels, session_date=session_date,
                    label_basis=(
                        f"Outcome measured to session close. target_hit/stop_hit use "
                        f"APEX-defined thresholds (+{_TARGET_PCT:g}% / {_STOP_PCT:g}% of the "
                        f"cluster's cost basis) — the participant's real targets are unknown. "
                        f"Excursions are sampled on the scanner interval, so MFE/MAE are lower "
                        f"bounds and ordering within one interval is not observable."))
            except LeakageError:
                report["skipped"] += 1
                continue
            if feature_store_db.write_label(rec):
                report["labelled"] += 1
        return report
    except Exception as e:  # pragma: no cover
        report["error"] = str(e)
        return report


def health() -> Dict[str, Any]:
    return {
        "writer_version": WRITER_VERSION,
        "seal_gap_seconds": _GAP_S,
        "max_frame_staleness_seconds": _MAX_FRAME_STALENESS_S,
        "target_pct_of_cost_basis": _TARGET_PCT,
        "stop_pct_of_cost_basis": _STOP_PCT,
        "label_horizon": "session_close",
        "decision_point": ("cluster end_time; written once sealed (end_time + gap), so "
                           "waiting for completeness never leaks hindsight into features"),
        "threshold_caveat": ("target/stop are APEX-defined thresholds on cost basis, not the "
                             "participant's actual targets, which are unobservable"),
    }
