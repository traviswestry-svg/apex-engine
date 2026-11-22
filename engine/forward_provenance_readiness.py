"""Phase 3E: fail-closed readiness assessment; never grants activation authority.

Statements supplied by an operator, or a signed staging fixture, do not constitute
independent evidence. Until a separately deployed, independently verified authority
and durable off-host checkpoint store are integrated, a production GO is impossible.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Mapping

GATE_NAMES = (
    ('code_integrity', 'Code integrity and deployed revision'),
    ('infrastructure', 'Independent authority and off-host storage'),
    ('runtime', 'Observed process identity and receipt linkage'),
    ('resilience', 'Fail-closed recovery and checkpoint continuity'),
    ('safety_isolation', 'Trading and historical-evidence isolation'),
)
REQUIRED = {
    'code_integrity': ('deployment_sha', 'source_sha', 'tests'),
    'infrastructure': ('collector', 'signer', 'checkpoint_store', 'key_custody', 'revocation'),
    'runtime': ('deployment_observation', 'boot_observation', 'ledger_checkpoint', 'receipt_correlation'),
    'resilience': ('restart_recovery', 'checkpoint_continuity', 'outage_policy', 'monitoring'),
    'safety_isolation': ('trading_unchanged', 'historical_read_only', 'fail_closed', 'rollback_plan'),
}


def _record(value: Any) -> bool:
    """Basic shape only. Even a conforming record is NOT a verified attestation."""
    return isinstance(value, dict) and isinstance(value.get('reference'), str) and bool(value['reference'].strip())


def assess(*, evidence: Mapping[str, Any] | None = None,
           operational_report: Mapping[str, Any] | None = None,
           as_of: str | None = None) -> dict[str, Any]:
    """Evaluate operator-supplied evidence without file writes or external side effects.

    True real-world verification is intentionally not implemented by this research
    patch. Reported evidence references are never sufficient for a production GO.
    """
    try:
        if as_of is not None:
            parsed = dt.datetime.fromisoformat(as_of.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                raise ValueError('naive timestamp')
            evaluated_at = parsed.astimezone(dt.timezone.utc).isoformat()
        else:
            evaluated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    except (ValueError, TypeError, AttributeError):
        evaluated_at = None
    ev = evidence if isinstance(evidence, Mapping) else {}
    operational = operational_report if isinstance(operational_report, Mapping) else {}
    gate_results: dict[str, Any] = {}
    for key, label in GATE_NAMES:
        supplied = ev.get(key, {})
        supplied = supplied if isinstance(supplied, Mapping) else {}
        missing = [name for name in REQUIRED[key] if not _record(supplied.get(name))]
        gate_results[key] = {
            'label': label,
            'verdict': 'INSUFFICIENT_EVIDENCE' if missing else 'NO_GO',
            'missing_evidence': missing,
            'provided_references': sorted(name for name in REQUIRED[key] if name not in missing),
            'independent_verification': 'NOT_IMPLEMENTED',
            'reason': ('EVIDENCE_MISSING' if missing else 'OPERATOR_REFERENCES_NOT_INDEPENDENTLY_AUTHENTICATED'),
        }
    # The existing 3D operational verifier explicitly cannot return real-world VERIFIED.
    op_status = operational.get('status', 'NOT_PROVIDED')
    op_real = operational.get('authentication')
    op_auth_claim = op_status == 'VERIFIED' or op_real == 'REAL_WORLD_AUTHENTICATED'
    if operational and (op_auth_claim or operational.get('promotion_authority') not in (None, 'NONE')):
        gate_results['runtime']['verdict'] = 'NO_GO'
        gate_results['runtime']['reason'] = 'UNSUPPORTED_REAL_WORLD_AUTHENTICATION_OR_PROMOTION_CLAIM'
    # Hard stops cannot be overridden by an operator's manifest.
    blockers = [
        'REAL_INDEPENDENT_COLLECTOR_NOT_INTEGRATED',
        'PROTECTED_OFF_HOST_SIGNER_NOT_INTEGRATED',
        'DURABLE_EXTERNAL_CHECKPOINT_AUTHORITY_NOT_INTEGRATED',
        'REAL_WORLD_VERIFICATION_AND_ACTIVATION_AUTHORITY_NOT_IMPLEMENTED',
    ]
    gate_results['infrastructure']['verdict'] = 'NO_GO'
    gate_results['infrastructure']['reason'] = 'MANDATORY_EXTERNAL_TRUST_BOUNDARY_NOT_OPERATIONAL'
    return {
        'phase': '3E', 'schema_version': '1', 'mode': 'READ_ONLY_READINESS',
        'as_of_utc': evaluated_at, 'ok': False, 'overall_verdict': 'NO_GO',
        'production_activation_authorized': False, 'promotion_authority': 'NONE',
        'authentication': 'NOT_REAL_WORLD_AUTHENTICATION',
        'historical_3569_population': 'EXCLUDED_FROM_RETROACTIVE_PROMOTION',
        'operational_report_status': op_status,
        'operational_report_authentication': op_real or 'NOT_PROVIDED',
        'gates': gate_results, 'hard_blockers': blockers,
        'required_action': 'DEPLOY_AND_INDEPENDENTLY_VERIFY_EXTERNAL_TRUST_INFRASTRUCTURE_BEFORE_RERUNNING',
    }
