"""Phase 4E: read-only external-infrastructure integration and authorization review.

This release has NO production approval mechanism. It inventories independently
sourced artifacts and checks local SHA-256 integrity; this is NOT provider/KMS/
WORM/process-origin authentication. No input can grant production GO.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

HEX = re.compile(r"^[a-f0-9]{64}$")
SHA40 = re.compile(r"^[a-f0-9]{40}$")
GATES = {
    'code_integrity': ('deployment_sha', 'source_sha', 'test_report'),
    'collector_independence': ('deployment_api_record', 'collector_identity', 'collector_isolation'),
    'protected_signing': ('key_custody_attestation', 'signing_policy', 'revocation_evidence'),
    'external_checkpoint': ('off_host_anchor', 'immutable_retention_evidence', 'continuity_report'),
    'process_origin': ('boot_supervision_evidence', 'process_to_gamma_linkage', 'decision_receipt_correlation'),
    'resilience': ('restart_test_report', 'outage_policy', 'external_monitoring'),
    'safety_isolation': ('execution_boundary_test', 'historical_immutability', 'rollback_procedure'),
}

BLOCKERS = (
    'INDEPENDENT_COLLECTOR_DEPLOYMENT_NOT_ATTESTED',
    'EXTERNAL_SIGNING_KEY_CUSTODY_NOT_ATTESTED',
    'IMMUTABLE_OFF_HOST_CHECKPOINT_AUTHORITY_NOT_ATTESTED',
    'INDEPENDENT_SCANNER_PROCESS_ORIGIN_NOT_ATTESTED',
    'PRODUCTION_AUTHORIZATION_AUTHORITY_NOT_IMPLEMENTED',
)


def _utc(value: Any) -> dt.datetime:
    if not isinstance(value, str):
        raise ValueError('INVALID_TIME')
    try:
        t = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as e:
        raise ValueError('INVALID_TIME') from e
    if t.tzinfo is None:
        raise ValueError('NAIVE_TIME')
    return t.astimezone(dt.timezone.utc)


def _digest_file(root: Path, ref: Mapping[str, Any]) -> tuple[bool,str]:
    """Confine evidence references to a dedicated, existing audit-copy directory.

    Uses no mutation or file creation. Symlinks and special files are rejected;
    hashes prove only that caller-provided bytes match caller-provided digests.
    """
    if not isinstance(ref, Mapping) or set(ref) != {'path', 'sha256'}:
        return False, 'INVALID_REFERENCE_SCHEMA'
    name, expected = ref['path'], ref['sha256']
    if not isinstance(name,str) or not name or '/' in name or '\\' in name or name in ('.','..'):
        return False, 'UNSAFE_REFERENCE_PATH'
    if not isinstance(expected,str) or not HEX.fullmatch(expected):
        return False, 'INVALID_REFERENCE_DIGEST'
    path = root / name
    if path.is_symlink() or not path.is_file():
        return False, 'MISSING_OR_UNSAFE_EVIDENCE_COPY'
    # Open with O_NOFOLLOW to avoid following a symlink swapped during the check.
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        try:
            import stat
            s = os.fstat(fd)
            if not stat.S_ISREG(s.st_mode) or s.st_size > 32 * 1024 * 1024 or s.st_size < 1:
                return False, 'INVALID_REFERENCE_FILE'
            h = hashlib.sha256()
            with os.fdopen(fd, 'rb', closefd=False) as file:
                for chunk in iter(lambda: file.read(65536), b''):
                    h.update(chunk)
            if h.hexdigest() != expected:
                return False, 'EVIDENCE_HASH_MISMATCH'
            return True, 'LOCAL_HASH_MATCH_NOT_INDEPENDENT_AUTHENTICATION'
        finally:
            os.close(fd)
    except OSError:
        return False, 'EVIDENCE_UNREADABLE'


def _result(gate: str, items: Mapping[str, Any], root: Path) -> dict:
    required = GATES[gate]
    matched, missing, invalid = [], [], []
    for key in required:
        if key not in items:
            missing.append(key)
        else:
            valid, reason = _digest_file(root, items[key])
            (matched if valid else invalid).append(key if valid else {'name':key,'reason':reason})
    return {
        'verdict': 'NO_GO' if invalid else 'INSUFFICIENT_EVIDENCE',
        'independent_verification': 'NOT_ESTABLISHED',
        'local_hash_matches': matched,
        'missing_evidence': missing,
        'invalid_evidence': invalid,
        'reason': 'INVALID_EVIDENCE_COPY' if invalid else 'EXTERNAL_AUTHORITY_NOT_INDEPENDENTLY_ATTESTED',
    }


def assess_phase4e(*, evidence_dir: str|Path|None = None,
                    manifest: Mapping[str, Any]|None = None,
                    phase4d_report: Mapping[str, Any]|None = None,
                    as_of_utc: str|None = None) -> dict:
    """Read-only fail-closed report. Evidence references are never authorization.

    A 4D staging report or operator-supplied VERIFIED status is not accepted
    as independent authentication. The only supported mode is research review.
    """
    now = dt.datetime.now(dt.timezone.utc)
    errors: list[str] = []
    try:
        when = _utc(as_of_utc) if as_of_utc is not None else now
    except ValueError as exc:
        errors.append(str(exc))
        when = now
    if not isinstance(manifest, Mapping) or set(manifest) != {'schema_version','mode','gates'} or manifest.get('schema_version') != '4E.1' or manifest.get('mode') != 'READ_ONLY':
        errors.append('INVALID_OR_MISSING_MANIFEST')
        supplied_gates: Mapping[str, Any] = {}
    else:
        supplied_gates = manifest['gates'] if isinstance(manifest['gates'],Mapping) else {}
        if set(supplied_gates) - set(GATES):
            errors.append('UNKNOWN_GATE')
    if evidence_dir is None:
        root = Path('/missing-evidence-directory')
        errors.append('EVIDENCE_DIR_NOT_PROVIDED')
    else:
        root = Path(evidence_dir).absolute()
        if root.is_symlink() or not root.is_dir() or str(root).startswith(('/data/','/audit-copy/')):
            errors.append('UNSAFE_OR_MISSING_EVIDENCE_DIRECTORY')
    gate_results = {}
    for gate in GATES:
        item = supplied_gates.get(gate, {})
        if not isinstance(item,Mapping) or set(item) - set(GATES[gate]):
            errors.append('INVALID_GATE_SCHEMA_' + gate)
            item = {}
        gate_results[gate] = _result(gate,item,root)
    report = phase4d_report
    if report is not None:
        if not isinstance(report,Mapping) or report.get('phase') != '4D':
            errors.append('INVALID_PHASE4D_REPORT')
        elif (report.get('production_activation_authorized') is True or
              report.get('promotion_authority') not in (None,'NONE') or
              report.get('status') == 'VERIFIED' or report.get('verdict') == 'GO'):
            errors.append('UNSUPPORTED_PHASE4D_AUTHENTICATION_CLAIM')
        elif report.get('authentication') not in ('STAGING_SIGNATURE_AND_CHECKPOINT_CONSISTENCY_ONLY','NOT_REAL_WORLD_AUTHENTICATION'):
            errors.append('UNKNOWN_PHASE4D_AUTHENTICATION_STATE')
    # Deliberately no mechanism for upgrading to GO in the research version.
    return {
        'phase':'4E', 'schema_version':'4E.1', 'mode':'READ_ONLY_INTEGRATION_REVIEW',
        'as_of_utc':when.isoformat(), 'ok':False, 'overall_verdict':'NO_GO',
        'production_activation_authorized':False, 'promotion_authority':'NONE',
        'authentication':'NOT_REAL_WORLD_AUTHENTICATION',
        'historical_3569_population':'EXCLUDED_FROM_RETROACTIVE_PROMOTION',
        'gates':gate_results, 'validation_errors':sorted(set(errors)),
        'hard_blockers':list(BLOCKERS),
        'required_action':'PROVISION_INDEPENDENT_INFRASTRUCTURE_AND_PROVE_REAL_PROCESS_ORIGIN',
    }
