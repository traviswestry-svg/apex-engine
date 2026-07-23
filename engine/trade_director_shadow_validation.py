"""APEX Trade Director Phase 25 — Institutional Shadow Validation & Promotion Pipeline.

Evaluates Phase 24 SHADOW_READY proposals against archived Phase 22 outcomes and
Phase 23 replay cases. Results are advisory; this module never mutates live policy,
risk, authorization, lifecycle, execution, or broker configuration.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Mapping, Optional

from engine.trade_director_lifecycle_contracts import as_mapping, utc_now_iso
from engine.trade_director_institutional_learning import learning_history
from engine.trade_director_policy_governance import build_policy_governance, evaluate_policy_proposal


def _f(v: Any, default: float = 0.0) -> float:
    try: return float(v)
    except (TypeError, ValueError): return default


def _id(proposal: Mapping[str, Any]) -> str:
    raw = str(proposal.get("proposal_id") or proposal).encode("utf-8")
    return "P25-" + hashlib.sha256(raw).hexdigest()[:14].upper()


def _eligible(record: Mapping[str, Any], proposal: Mapping[str, Any]) -> bool:
    area = str(proposal.get("policy_area") or "").upper()
    text = (str(proposal.get("proposed_policy") or "") + " " + str(proposal.get("rationale") or "")).upper()
    strategy = str(record.get("strategy") or "").upper()
    if "STRATEGY" in area:
        named = [s for s in ("OPENING_DRIVE","TREND_CONTINUATION","MEAN_REVERSION","MOMENTUM","BREAKOUT","FADE","IRON_CONDOR","DEBIT_SPREAD","CREDIT_SPREAD") if s in text]
        return not named or strategy in named
    return True


def _shadow_delta(record: Mapping[str, Any], proposal: Mapping[str, Any]) -> float:
    """Bounded deterministic estimate in R, clearly simulation-only."""
    r = _f(record.get("r_multiple"), 0.0)
    mae = abs(_f(record.get("mae"), 0.0))
    mfe = max(0.0, _f(record.get("mfe"), 0.0))
    area = str(proposal.get("policy_area") or "").upper()
    if area == "CONFIDENCE_CALIBRATION":
        conf = _f(record.get("decision_confidence"), 50.0)
        return -min(0.35, abs(r) * 0.35) if conf >= 80 and r < 0 else (0.05 if conf < 65 and r > 0 else 0.0)
    if area == "ENTRY_CONFIRMATION":
        return min(0.30, mae * 0.25) if r > -0.5 else -0.10
    if area == "EXIT_MANAGEMENT":
        return min(0.50, max(0.0, mfe - max(r, 0.0)) * 0.35)
    if area == "STRATEGY_PRIORITY":
        return 0.10 if r > 0 else -0.03
    if area == "STRATEGY_ELIGIBILITY":
        return min(0.40, abs(r) * 0.50) if r < 0 else -0.05
    return 0.0


def evaluate_shadow_trial(proposal: Mapping[str, Any], records: Optional[List[Mapping[str, Any]]] = None,
                          *, minimum_cases: int = 20, promotion_margin_r: float = 0.10) -> Dict[str, Any]:
    governed = evaluate_policy_proposal(proposal, minimum_samples=minimum_cases)
    trial_id = _id(governed)
    rows = [dict(r) for r in (records if records is not None else learning_history(1000)) if _eligible(r, governed)]
    baseline = [_f(r.get("r_multiple"), 0.0) for r in rows]
    shadow = [b + _shadow_delta(r, governed) for b, r in zip(baseline, rows)]
    n = len(rows)
    base_exp = sum(baseline)/n if n else 0.0
    shadow_exp = sum(shadow)/n if n else 0.0
    delta = shadow_exp - base_exp
    base_wr = sum(1 for x in baseline if x > 0)/n*100 if n else 0.0
    shadow_wr = sum(1 for x in shadow if x > 0)/n*100 if n else 0.0
    worst = min(shadow) if shadow else 0.0
    gates = {
        "phase24_shadow_ready": governed.get("status") == "SHADOW_READY",
        "minimum_cases": n >= minimum_cases,
        "positive_expectancy_delta": delta >= promotion_margin_r,
        "win_rate_not_degraded": shadow_wr + 2.0 >= base_wr,
        "bounded_tail_risk": worst >= -3.0,
        "human_approval_required": bool(governed.get("human_approval_required", True)),
        "auto_apply_disabled": not bool(governed.get("auto_apply", False)),
        "rollback_plan_present": bool(governed.get("rollback_plan") or governed.get("rollback_plan_required", True)),
    }
    statistical = n >= minimum_cases
    passed = all(gates.values())
    status = "PROMOTION_CANDIDATE" if passed else "SHADOW_RUNNING" if governed.get("status") == "SHADOW_READY" else "BLOCKED"
    return {
        "trial_id": trial_id, "proposal_id": governed.get("proposal_id"), "target_phase": governed.get("target_phase"),
        "policy_area": governed.get("policy_area"), "status": status, "cases_evaluated": n,
        "baseline": {"expectancy_r": round(base_exp,3), "win_rate_pct": round(base_wr,1)},
        "shadow": {"expectancy_r": round(shadow_exp,3), "win_rate_pct": round(shadow_wr,1), "worst_case_r": round(worst,3)},
        "impact": {"expectancy_delta_r": round(delta,3), "win_rate_delta_pct": round(shadow_wr-base_wr,1)},
        "validation": {"minimum_cases": minimum_cases, "promotion_margin_r": promotion_margin_r, "statistically_reviewable": statistical, "gates": gates, "passed": passed, "failed_gates": [k for k,v in gates.items() if not v]},
        "promotion_control": {"eligible_for_human_review": passed, "production_applied": False, "human_approval_required": True, "rollback_required": True, "automatic_promotion": False},
        "methodology": "Deterministic bounded shadow simulation using archived outcomes only; not a claim of executable historical fills.",
    }


def build_shadow_validation(context: Optional[Mapping[str, Any]] = None, *, minimum_cases: int = 20) -> Dict[str, Any]:
    ctx = dict(context or {})
    governance = as_mapping(ctx.get("policy_governance")) or build_policy_governance(ctx, minimum_samples=minimum_cases)
    records = learning_history(1000)
    trials = [evaluate_shadow_trial(p, records, minimum_cases=minimum_cases) for p in governance.get("proposals") or []]
    candidates = sum(1 for t in trials if t.get("status") == "PROMOTION_CANDIDATE")
    running = sum(1 for t in trials if t.get("status") == "SHADOW_RUNNING")
    state = "NO_TRIALS" if not trials else "HUMAN_REVIEW_REQUIRED" if candidates else "SHADOW_VALIDATION" if running else "EVIDENCE_BLOCKED"
    return {
        "version": "PHASE_25", "as_of": utc_now_iso(), "mode": "INSTITUTIONAL_SHADOW_VALIDATION",
        "validation_state": state, "ledger_cases": len(records), "trial_count": len(trials),
        "promotion_candidate_count": candidates, "shadow_running_count": running, "trials": trials,
        "controls": {"live_policy_mutation": False, "automatic_promotion": False, "human_approval_required": True,
                     "rollback_required": True, "phase20_authorization_preserved": True, "phase21_management_preserved": True,
                     "broker_access": False},
        "safety_note": "Phase 25 validates proposed changes in shadow only. Promotion candidates remain inactive until explicit human review and a separate deployment change.",
    }
