"""APEX Trade Director Phase 24 — Institutional Policy Governance Laboratory.

Turns Phase 22 learning and Phase 23 replay findings into bounded, reviewable policy
proposals. It never edits live strategy, risk, authorization, execution, or lifecycle
configuration. Every recommendation is evidence-gated and intended for shadow review.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Mapping, Optional

from engine.trade_director_institutional_learning import build_learning_intelligence, learning_history
from engine.trade_director_replay_lab import build_replay_lab
from engine.trade_director_lifecycle_contracts import as_mapping, utc_now_iso


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _proposal_id(target: str, change: str) -> str:
    raw = f"{target}|{change}".encode("utf-8")
    return "P24-" + hashlib.sha256(raw).hexdigest()[:14].upper()


def _proposal(target_phase: str, policy_area: str, current_policy: str,
              proposed_policy: str, rationale: str, samples: int,
              expected_effect: str, risk: str = "MEDIUM") -> Dict[str, Any]:
    return {
        "proposal_id": _proposal_id(target_phase + policy_area, proposed_policy),
        "target_phase": target_phase,
        "policy_area": policy_area,
        "current_policy": current_policy,
        "proposed_policy": proposed_policy,
        "rationale": rationale,
        "evidence_samples": int(samples),
        "expected_effect": expected_effect,
        "implementation_risk": risk,
        "status": "DRAFT",
        "shadow_mode_required": True,
        "human_approval_required": True,
        "auto_apply": False,
    }


def _derive_proposals(learning: Mapping[str, Any], replay: Mapping[str, Any]) -> List[Dict[str, Any]]:
    summary = as_mapping(learning.get("summary"))
    calibration = as_mapping(learning.get("confidence_calibration"))
    samples = int(summary.get("trades_learned") or 0)
    proposals: List[Dict[str, Any]] = []

    error = _f(calibration.get("mean_absolute_calibration_error"), 0.0)
    if error >= 10:
        proposals.append(_proposal(
            "PHASE_20", "CONFIDENCE_CALIBRATION", "Raw committee confidence",
            "Apply an advisory calibration overlay before authorization review",
            f"Observed mean absolute calibration error is {error:.1f} points.", samples,
            "Reduce overconfident authorizations without changing hard risk controls.", "LOW"))

    for row in learning.get("strategy_scorecards") or []:
        row = as_mapping(row); n = int(row.get("samples") or 0); exp = _f(row.get("expectancy_r"), 0.0)
        strategy = str(row.get("strategy") or "UNCLASSIFIED")
        if n >= 10 and exp <= -0.15:
            proposals.append(_proposal(
                "PHASE_14", "STRATEGY_ELIGIBILITY", f"{strategy} eligible under current rules",
                f"Require stronger evidence or shadow-only status for {strategy}",
                f"The {strategy} cohort has {n} samples and {exp:.2f}R expectancy.", n,
                "Reduce exposure to a persistently negative-expectancy strategy cohort.", "MEDIUM"))
        elif n >= 15 and exp >= 0.50:
            proposals.append(_proposal(
                "PHASE_14", "STRATEGY_PRIORITY", f"{strategy} uses baseline ranking",
                f"Test a bounded ranking bonus for {strategy} in matching regimes",
                f"The {strategy} cohort has {n} samples and {exp:.2f}R expectancy.", n,
                "Improve strategy selection while preserving Phase 20 authorization.", "MEDIUM"))

    case = as_mapping(replay.get("replay_case")); score = as_mapping(case.get("decision_scorecard"))
    if case.get("ok") and _f(score.get("entry_timing"), 100) < 65:
        proposals.append(_proposal(
            "PHASE_19", "ENTRY_CONFIRMATION", "Existing confirmation cadence",
            "Shadow-test one additional confirmation checkpoint for matching setups",
            "The selected replay case received a weak entry-timing score.", 1,
            "Measure whether delayed confirmation improves adverse excursion and expectancy.", "LOW"))
    if case.get("ok") and _f(score.get("exit_quality"), 100) < 65:
        proposals.append(_proposal(
            "PHASE_21", "EXIT_MANAGEMENT", "Current lifecycle exit policy",
            "Shadow-test partial-plus-runner management for comparable positive-MFE cases",
            "Replay identified weak exit efficiency relative to bounded favorable excursion.", 1,
            "Improve captured R without weakening stop or daily-loss governance.", "MEDIUM"))

    return proposals[:12]


def evaluate_policy_proposal(proposal: Mapping[str, Any], *, minimum_samples: int = 20) -> Dict[str, Any]:
    p = dict(proposal or {})
    samples = int(p.get("evidence_samples") or 0)
    risk = str(p.get("implementation_risk") or "MEDIUM").upper()
    gates = {
        "sufficient_samples": samples >= minimum_samples,
        "bounded_scope": bool(p.get("target_phase") and p.get("policy_area")),
        "shadow_mode_required": bool(p.get("shadow_mode_required", True)),
        "human_approval_required": bool(p.get("human_approval_required", True)),
        "auto_apply_disabled": not bool(p.get("auto_apply", False)),
        "risk_acceptable_for_shadow": risk in {"LOW", "MEDIUM"},
    }
    passed = all(gates.values())
    p["governance_evaluation"] = {
        "minimum_samples": minimum_samples,
        "gates": gates,
        "passed": passed,
        "decision": "SHADOW_READY" if passed else "INSUFFICIENT_EVIDENCE",
        "failed_gates": [k for k, v in gates.items() if not v],
    }
    p["status"] = "SHADOW_READY" if passed else "DRAFT"
    return p


def build_policy_governance(context: Optional[Mapping[str, Any]] = None, *, minimum_samples: int = 20) -> Dict[str, Any]:
    ctx = dict(context or {})
    learning = as_mapping(ctx.get("institutional_learning")) or build_learning_intelligence(ctx)
    replay = as_mapping(ctx.get("replay_laboratory")) or build_replay_lab(limit=25)
    proposals = [evaluate_policy_proposal(p, minimum_samples=minimum_samples) for p in _derive_proposals(learning, replay)]
    shadow_ready = sum(1 for p in proposals if p.get("status") == "SHADOW_READY")
    history_count = len(learning_history(500))
    state = "NO_PROPOSALS" if not proposals else "REVIEW_REQUIRED" if shadow_ready else "COLLECTING_EVIDENCE"
    return {
        "version": "PHASE_24",
        "as_of": utc_now_iso(),
        "mode": "INSTITUTIONAL_POLICY_GOVERNANCE",
        "governance_state": state,
        "ledger_samples": history_count,
        "minimum_samples": minimum_samples,
        "proposal_count": len(proposals),
        "shadow_ready_count": shadow_ready,
        "proposals": proposals,
        "change_control": {
            "direct_configuration_mutation": False,
            "automatic_policy_promotion": False,
            "shadow_validation_required": True,
            "human_approval_required": True,
            "rollback_plan_required_before_deployment": True,
            "phase20_authorization_preserved": True,
            "phase21_management_preserved": True,
        },
        "safety_note": "Phase 24 creates evidence-gated policy proposals only. It cannot alter live rules, risk limits, authorization thresholds, lifecycle behavior, or broker execution.",
    }
