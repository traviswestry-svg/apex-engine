"""Phase 4E read-only integration review; no production authorization capability."""
from __future__ import annotations
import argparse
import datetime as dt
import json
from engine.forward_provenance_phase4e import assess_phase4e


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence-dir', help='Dedicated offline audit-copy directory; not /data')
    p.add_argument('--manifest', help='Phase 4E manifest JSON (contains SHA256 references only)')
    p.add_argument('--phase4d-report', help='Read-only Phase 4D JSON report')
    args = p.parse_args(argv)
    problems = []
    def load(name):
        if not name: return None
        try:
            with open(name,encoding='utf-8') as f: return json.load(f)
        except (OSError,ValueError,UnicodeError):
            problems.append('UNREADABLE_OR_INVALID_' + ('MANIFEST' if name == args.manifest else 'PHASE4D_REPORT'))
            return None
    manifest = load(args.manifest)
    report = load(args.phase4d_report)
    result = assess_phase4e(evidence_dir=args.evidence_dir,manifest=manifest,phase4d_report=report)
    result['validation_errors'] = sorted(set(result['validation_errors'] + problems))
    print(json.dumps(result,sort_keys=True,indent=2))
    return 2

if __name__ == '__main__':
    raise SystemExit(main())
