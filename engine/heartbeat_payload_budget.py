"""Read-only bounded projection of scanner heartbeat diagnostics.

The heartbeat is a liveness/status channel, not the authoritative diagnostic
archive. Avoid repeatedly transferring large historical result/sample lists to
web workers; never change scanner, settlement, or decision state.
"""
from __future__ import annotations

from typing import Any, Dict

VERSION = "apex.heartbeat_payload_budget.v1"


def _selected(source: Any, keys: tuple[str, ...]) -> Dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    return {key: source[key] for key in keys if key in source}


def compact_scanner_heartbeat(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Build a separate diagnostic projection without mutating source objects."""
    out = dict(payload)
    settlement = out.get("feature_label_settlement")
    if isinstance(settlement, dict):
        compact = dict(settlement)
        result = settlement.get("last_result")
        if isinstance(result, dict):
            brief = _selected(result, (
                "state", "labelled", "pending", "excursion_rows_found",
                "missing_excursion_row", "missing_feature_vector", "missing_mfe",
                "missing_cost_basis", "no_excursion", "write_failures",
                "leakage_rejected", "observability_version", "attempted_at",
            ))
            for source, keys in (
                ("canonical_pending_outcome_summary", (
                    "pending_sample_ids", "awaiting_real_pl", "feature_only_unregistered",
                    "registered_identity", "exact_excursion_present", "ownership_integrity_failures",
                    "fuzzy_matching", "reconstructs_identity", "writes_evidence",
                )),
                ("canonical_settlement_cohort_summary", (
                    "settlement_requested_ids", "requested_with_excursion",
                    "requested_without_excursion", "excursion_not_requested",
                    "fuzzy_matching", "writes_evidence",
                )),
                ("canonical_settlement_eligibility_38", (
                    "state", "classification", "coverage_scope", "identity_basis",
                    "execution_authority", "changes_trade_decisions",
                )),
            ):
                if isinstance(result.get(source), dict):
                    brief[source] = _selected(result[source], keys)
                    if source == "canonical_settlement_eligibility_38":
                        brief[source]["counts"] = dict(result[source].get("counts") or {})
            reports = result.get("session_reports")
            if isinstance(reports, list):
                brief["session_reports_omitted_from_heartbeat"] = len(reports)
            brief["diagnostic_detail_omitted"] = True
            brief["detail_source"] = "existing_settlement_reconciliation_sidecar"
            compact["last_result"] = brief
        out["feature_label_settlement"] = compact

    lifecycle = out.get("historical_evidence_lifecycle")
    if isinstance(lifecycle, dict):
        projected = dict(lifecycle)
        audit = projected.get("live_actionability_capture_audit")
        if isinstance(audit, dict):
            brief_audit = dict(audit)
            for key in ("recent_decisions", "current_release_recent_decisions"):
                entries = brief_audit.pop(key, None)
                if isinstance(entries, list):
                    brief_audit[key + "_omitted_from_heartbeat"] = len(entries)
            brief_audit["diagnostic_detail_omitted"] = True
            projected["live_actionability_capture_audit"] = brief_audit
        out["historical_evidence_lifecycle"] = projected
    out["heartbeat_payload_budget"] = {
        "schema": VERSION, "read_only": True, "changes_trade_decisions": False,
        "execution_authority": False,
        "note": "Historical sample lists omitted only from ephemeral heartbeat",
    }
    return out
