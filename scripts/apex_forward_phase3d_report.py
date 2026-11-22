"""Read-only Phase 3D staging provenance report. Never authorizes promotion."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from engine.forward_provenance_operational import report


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ledger', required=True, help='Existing transaction-consistent audit-copy SQLite path')
    p.add_argument('--decision-id', help='Exact receipt ID (optional for aggregate report)')
    p.add_argument('--bundle', help='Existing Phase 3C staging bundle JSON')
    p.add_argument('--pinned-public-key', help='Existing 32-byte raw Ed25519 public key')
    p.add_argument('--trust-policy', help='External trust-policy JSON')
    p.add_argument('--as-of', help='UTC/offset-aware ISO 8601 verification time')
    p.add_argument('--max-checkpoint-age-seconds', type=int, default=900)
    p.add_argument('--source-decision-ids', help='Optional JSON list; inventory claims only')
    args = p.parse_args()
    try:
        bundle = json.loads(Path(args.bundle).read_text()) if args.bundle else None
        trust = json.loads(Path(args.trust_policy).read_text()) if args.trust_policy else None
        key = Path(args.pinned_public_key).read_bytes() if args.pinned_public_key else None
        ids = json.loads(Path(args.source_decision_ids).read_text()) if args.source_decision_ids else None
        verdict = report(ledger_path=args.ledger, decision_id=args.decision_id,
                         bundle=bundle, trust_policy=trust, pinned_public_key=key,
                         source_decision_ids=ids, as_of=args.as_of,
                         max_checkpoint_age_seconds=args.max_checkpoint_age_seconds)
    except (OSError, ValueError, TypeError) as exc:
        verdict = {'ok': False, 'status': 'UNVERIFIED',
                   'reason': 'INPUT_ERROR_' + type(exc).__name__,
                   'mode': 'READ_ONLY', 'promotion_authority': 'NONE'}
    print(json.dumps(verdict, indent=2, sort_keys=True))
    return 0 if verdict.get('ok') else 2

if __name__ == '__main__':
    raise SystemExit(main())
