#!/usr/bin/env python3
"""Operator-governed APEX storage maintenance.

Dry-run is the default.  Mutating actions require an explicit --apply flag.
No action VACUUMs an active database or deletes canonical decisions, grades,
flow features, excursions, calibration evidence, or trigger evidence.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.storage_retention import (
    audit,
    checkpoint_wals,
    cleanup_quarantined_backups,
    prune_mature_price_samples,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="APEX governed storage maintenance")
    parser.add_argument(
        "action",
        choices=("audit", "checkpoint-wals", "cleanup-quarantine", "prune-price-samples"),
        nargs="?",
        default="audit",
    )
    parser.add_argument("--apply", action="store_true", help="explicitly apply the selected bounded maintenance action")
    args = parser.parse_args()

    if args.action == "audit":
        result = audit()
    elif args.action == "checkpoint-wals":
        result = checkpoint_wals(apply=args.apply)
    elif args.action == "cleanup-quarantine":
        result = cleanup_quarantined_backups(apply=args.apply)
    else:
        result = prune_mature_price_samples(apply=args.apply)

    result = dict(result)
    result["operator_invoked"] = True
    result["explicit_apply"] = bool(args.apply)
    result["automatic_maintenance"] = False
    result["vacuum_performed"] = bool(result.get("vacuum_performed", False))
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result.get("ok", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
