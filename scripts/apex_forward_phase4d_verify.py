"""Read-only Phase 4D evidence-bundle verifier: staging only; never GO.

Consumes locally provided evidence files. No network, provider authentication,
KMS or real independent process supervision is implemented.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
from engine.forward_provenance_realworld_verifier import verify_phase4d, _fail


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle',required=True,help='JSON with observer_envelope, signer_attestation, signed_anchor')
    p.add_argument('--trust-policy',required=True,help='Pinned staging verification keys; never private keys')
    p.add_argument('--checkpoint-copy',required=True,help='Isolated, off-line checkpoint SQLite copy (read-only)')
    p.add_argument('--as-of-utc',help='ISO-8601 offset-aware UTC time, default current time')
    args=p.parse_args()
    try:
        with open(args.bundle,encoding='utf-8') as f: bundle=json.load(f)
        with open(args.trust_policy,encoding='utf-8') as f: policy=json.load(f)
        if not isinstance(bundle,dict) or set(bundle) != {'observer_envelope','signer_attestation','signed_anchor'}:
            report=_fail('INVALID_BUNDLE_SCHEMA')
        else:
            report=verify_phase4d(observer_envelope=bundle['observer_envelope'],
                signer_attestation=bundle['signer_attestation'], signed_anchor=bundle['signed_anchor'],
                trust_policy=policy, checkpoint_copy=args.checkpoint_copy,
                as_of_utc=args.as_of_utc or dt.datetime.now(dt.timezone.utc).isoformat())
    except (OSError,ValueError,TypeError) as e:
        report=_fail('INVALID_INPUT_OR_UNREADABLE_FILE')
    print(json.dumps(report,sort_keys=True,indent=2))
    # This research script NEVER returns an authorization success exit status.
    return 2

if __name__=='__main__': raise SystemExit(main())
