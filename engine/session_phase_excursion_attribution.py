"""APEX 69.10.32 — Canonical Excursion Semantics & Session-Phase Attribution Closure.

Read-only/advisory projection over immutable 68.6 attribution evidence.  Historical
rows are never rewritten.  The canonical excursion projection explicitly anchors
entry at zero excursion so MFE is non-negative and MAE is non-positive, while the
stored window-only values remain visible for provenance/audit.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict

from .abstention_causality import _rows, _dt
from .decision_outcome_attribution import DEFAULT_DB, _availability
from .counterfactual_cluster_discrimination import clusters as discrimination_clusters
from .canonical_market_calendar import classify as classify_market_session

VERSION = "69.10.32.1"
SCHEMA_VERSION = "apex.canonical_excursion_session_phase.v1.1"


def session_phase(value: str) -> str:
    return str(classify_market_session(value)["session_phase"])


def canonical_excursion(mfe: Any, mae: Any) -> Dict[str, Any]:
    """Project legacy window-only direction-adjusted extrema onto entry-anchored semantics.

    This is a deterministic read-time projection, not a historical evidence mutation.
    Because entry itself is zero directional excursion, canonical MFE=max(0,stored MFE)
    and canonical MAE=min(0,stored MAE).
    """
    fmfe = None if mfe is None else float(mfe)
    fmae = None if mae is None else float(mae)
    return {
        "stored_mfe": fmfe,
        "stored_mae": fmae,
        "canonical_mfe": None if fmfe is None else max(0.0, fmfe),
        "canonical_mae": None if fmae is None else min(0.0, fmae),
        "stored_semantics": "WINDOW_ONLY_DIRECTION_ADJUSTED",
        "canonical_semantics": "ENTRY_ANCHORED_DIRECTION_ADJUSTED",
        "projection_only": True,
    }


def _excursion_audit(rows: list[Dict[str, Any]]) -> Dict[str, Any]:
    with_values = [r for r in rows if r.get("mfe") is not None and r.get("mae") is not None]
    neg_mfe = sum(float(r["mfe"]) < 0 for r in with_values)
    pos_mae = sum(float(r["mae"]) > 0 for r in with_values)
    projected_bad = 0
    for r in with_values:
        x = canonical_excursion(r["mfe"], r["mae"])
        projected_bad += int(float(x["canonical_mfe"]) < 0 or float(x["canonical_mae"]) > 0)
    return {
        "rows_checked": len(rows), "rows_with_excursions": len(with_values),
        "stored_negative_mfe_rows": neg_mfe, "stored_positive_mae_rows": pos_mae,
        "stored_status": "WINDOW_ONLY_NOT_ENTRY_ANCHORED" if (neg_mfe or pos_mae) else "ENTRY_ANCHOR_COMPATIBLE",
        "canonical_projection_status": "CONSISTENT" if projected_bad == 0 else "INCONSISTENT",
        "canonical_projection_violations": projected_bad,
        "canonical_rule": {"mfe": "max(0, stored_direction_adjusted_mfe)", "mae": "min(0, stored_direction_adjusted_mae)"},
        "historical_rows_mutated": False,
        "eligible_as_decision_time_discriminator": False,
        "reason": "Excursions are post-decision outcomes; canonical projection is attribution/audit only.",
    }


def _phase_attribution(cs: list[Dict[str, Any]]) -> tuple[list[Dict[str, Any]], Dict[str, Any]]:
    bins = defaultdict(lambda: {"missed_clusters": 0, "protective_clusters": 0})
    excluded = defaultdict(int)
    eligible = []
    for c in cs:
        cal = classify_market_session(str(c["anchor_at"]))
        if not cal["rth_eligible"]:
            excluded[cal["session_phase"]] += 1
            continue
        eligible.append((c, cal))
        phase = cal["session_phase"]
        if c.get("classification") == "MISSED_OPPORTUNITY": bins[phase]["missed_clusters"] += 1
        elif c.get("classification") == "PROTECTIVE_ABSTENTION": bins[phase]["protective_clusters"] += 1
    total = sum(v["missed_clusters"] + v["protective_clusters"] for v in bins.values())
    total_m = sum(v["missed_clusters"] for v in bins.values())
    baseline = total_m / total if total else 0.0
    order = ["OPEN_DISCOVERY","MORNING_DEVELOPMENT","LATE_MORNING","MIDDAY","AFTERNOON"]
    out=[]
    for phase in order:
        b=bins[phase]; n=b["missed_clusters"]+b["protective_clusters"]; rate=b["missed_clusters"]/n if n else 0.0
        out.append({"session_phase":phase, **b, "clusters":n, "missed_rate_pct":round(rate*100,2) if n else None,
                    "baseline_missed_rate_pct":round(baseline*100,2) if total else None,
                    "relative_risk_vs_baseline":round(rate/baseline,3) if n and baseline else None,
                    "risk_difference_pct_points":round((rate-baseline)*100,2) if n and total else None})
    audit={"all_clusters":len(cs),"rth_eligible_clusters":total,"excluded_clusters":len(cs)-total,
           "excluded_by_session_state":dict(sorted(excluded.items())),
           "rth_denominator_excludes_closed_premarket_postmarket":True}
    return out,audit


def summary(path: str|Path=DEFAULT_DB) -> Dict[str, Any]:
    av=_availability(path)
    base={"ok":not av.get("degraded",False),"version":VERSION,"schema_version":SCHEMA_VERSION,**av,"execution_authority":False}
    if av.get("status") != "READY": return {**base,"excursion_semantics":{},"session_phase_attribution":[]}
    rows=_rows(path); cs=discrimination_clusters(path)
    phase_attr, calendar_audit = _phase_attribution(cs)
    return {**base,"status":"READY","excursion_semantics":_excursion_audit(rows),
            "session_phase_attribution":phase_attr,"session_calendar_integrity":calendar_audit,
            "session_phase_rule":{"timezone":"America/New_York","MARKET_CLOSED":"weekend/full-day holiday/unsupported calendar year","PREMARKET":"valid trading day before 09:30","OPEN_DISCOVERY":"09:30-10:00","MORNING_DEVELOPMENT":"10:00-11:00","LATE_MORNING":"11:00-11:30","MIDDAY":"11:30-13:00","AFTERNOON":"13:00-16:00","POSTMARKET":"valid trading day after 16:00"},
            "governance":{"observational_only":True,"historical_evidence_immutable":True,"projection_is_read_only":True,
                "session_phase_is_attribution_context_only":True,"canonical_session_calendar_required":True,"closed_session_clusters_excluded_from_rth_denominator":True,"excursions_are_post_outcome_only":True,
                "changes_trade_decisions":False,"changes_thresholds":False,"changes_learning_eligibility":False,
                "feeds_calibration_automatically":False,"automatic_promotion":False,"changes_execution_authority":False,
                "human_review_required_for_policy_change":True}}


def excursion_detail(path: str|Path=DEFAULT_DB, limit:int=500) -> Dict[str,Any]:
    av=_availability(path)
    if av.get("status") != "READY": return {"ok":not av.get("degraded",False),"version":VERSION,**av,"items":[]}
    items=[]
    for r in reversed(_rows(path)):
        x=canonical_excursion(r.get("mfe"),r.get("mae"))
        items.append({"decision_id":r.get("decision_id"),"captured_at":r.get("captured_at"),"ticker":r.get("ticker"),
                      "direction":r.get("direction"),**classify_market_session(str(r.get("captured_at"))),**x})
        if len(items)>=max(1,min(int(limit),2000)): break
    return {"ok":True,"version":VERSION,"schema_version":SCHEMA_VERSION,**av,"items":items,"execution_authority":False}
