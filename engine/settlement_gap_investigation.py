"""Read-only classification of exact-identity settlement gaps.

Consumes existing exact-ID diagnostics. Does not reconstruct identity, query a
new owner, create evidence, change label eligibility, or authorize execution.
"""
from __future__ import annotations
from typing import Any, Mapping

SCHEMA = "APEX_SETTLEMENT_GAP_INVESTIGATION_V1"


def analyze(report: Mapping[str, Any]) -> dict[str, Any]:
    cohort = report.get("canonical_settlement_cohort_summary") or {}
    pending = report.get("canonical_pending_outcome_summary") or {}
    global_audit = report.get("canonical_settlement_eligibility_38") or {}
    counts = global_audit.get("counts") or {}
    requested = int(cohort.get("settlement_requested_ids") or 0)
    matched = int(cohort.get("requested_with_excursion") or 0)
    no_excursion = int(cohort.get("requested_without_excursion") or 0)
    identity_only = int(cohort.get("identity_map_only_requested") or 0)
    feature_only = int(cohort.get("feature_only_requested") or 0)
    awaiting = int(pending.get("awaiting_real_pl") or 0)
    outside = int(cohort.get("excursion_not_requested") or 0)
    integrity = global_audit.get("partition_integrity") or {}
    partitions_ok = bool(integrity) and all(v is True for v in integrity.values())
    if requested == 0:
        classification = "NO_SETTLEMENT_COHORT"
    elif matched == 0 and no_excursion == requested:
        classification = "REQUESTED_COHORT_HAS_NO_EXACT_EXCURSIONS"
    elif no_excursion > 0:
        classification = "MIXED_REQUESTED_COHORT_WITH_MISSING_EXCURSIONS"
    else:
        classification = "EXACT_REQUESTED_EXCURSIONS_PRESENT"
    return {
        "schema": SCHEMA, "state": classification, "read_only": True,
        "changes_trade_decisions": False, "writes_evidence": False,
        "execution_authority": False, "relaxes_label_eligibility": False,
        "requested_samples": requested, "requested_with_exact_excursion": matched,
        "requested_without_exact_excursion": no_excursion,
        "requested_identity_only": identity_only, "requested_feature_only": feature_only,
        "awaiting_real_pl": awaiting,
        "existing_excursions_outside_requested_cohort": outside,
        "global_unlabelled_features": counts.get("unlabelled"),
        "global_unlabelled_with_excursion": counts.get("excursion_unlabelled"),
        "global_partition_integrity_verified": partitions_ok,
        "investigation_next": (
            "Inspect historical feature capture/lifecycle ownership; do not infer missing P&L"
            if classification == "REQUESTED_COHORT_HAS_NO_EXACT_EXCURSIONS" else
            "Inspect requested sample-ID partitions and individual lifecycle evidence"
            if no_excursion else "No gap demonstrated in this selected cohort"
        ),
        "limitations": [
            "No synthetic excursion, P&L, fuzzy match, or cross-sample borrowing.",
            "Requested cohort is bounded and may differ from all persisted features.",
            "Missing excursion is not proof of a writer defect or a missing trade.",
        ],
    }
