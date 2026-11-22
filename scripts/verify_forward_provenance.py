#!/usr/bin/env python3
"""Offline, read-only verification of independently signed APEX provenance receipts.

Run from an independent audit environment with a copied sidecar SQLite database,
three trusted externally signed JSON attestations, and a separately pinned key.
Never signs, checkpoints, migrates, or updates records.
"""
import argparse
import base64
import json
from pathlib import Path

from engine.forward_provenance_verifier import verify_external_receipts


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ledger', required=True)
    p.add_argument('--decision-id', required=True)
    p.add_argument('--statements', required=True, help='JSON file containing exactly 3 signed statements')
    p.add_argument('--pinned-public-key', required=True,
                   help='Raw 32-byte Ed25519 public key or base64-encoded public key file')
    args = p.parse_args()
    try:
        raw = Path(args.pinned_public_key).read_bytes()
        public_key = raw if len(raw) == 32 else base64.b64decode(raw.strip(), validate=True)
        docs = json.loads(Path(args.statements).read_text())
        result = verify_external_receipts(ledger_path=args.ledger, statements=docs,
                                         pinned_public_key=public_key, decision_id=args.decision_id)
    except (OSError, ValueError, TypeError) as err:
        result = {'ok': False, 'status': 'UNVERIFIED', 'reason': 'INVALID_INPUT_' + type(err).__name__}
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
