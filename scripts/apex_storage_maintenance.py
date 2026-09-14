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

from engine.historical_payload_compaction import audit_historical_payload_compaction
from engine.historical_payload_archive import (
    archive_batch, archive_plan, archive_status, shadow_validate,
    ARCHIVE_DB as HISTORICAL_ARCHIVE_DB, TRIGGER_DB as HISTORICAL_TRIGGER_DB,
)
from engine.evidence_pipeline import DEFAULT_DB as HISTORICAL_EVIDENCE_DB
from engine.storage_retention import (
    audit,
    checkpoint_wals,
    cleanup_quarantined_backups,
    prune_mature_price_samples,
    prune_mature_trigger_observations,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="APEX governed storage maintenance")
    parser.add_argument(
        "action",
        choices=("audit", "payload-compaction-readiness", "payload-archive-plan", "payload-archive-status", "archive-trigger-payloads", "archive-decision-payloads", "shadow-validate-trigger-payloads", "shadow-validate-decision-payloads", "checkpoint-wals", "cleanup-quarantine", "prune-price-samples", "prune-trigger-observations"),
        nargs="?",
        default="audit",
    )
    parser.add_argument("--apply", action="store_true", help="explicitly apply the selected bounded maintenance action")
    parser.add_argument("--limit", type=int, default=25, help="bounded row limit for archive/shadow actions (default: 25, max: 500)")
    args = parser.parse_args()

    if args.action == "audit":
        result = audit()
    elif args.action == "payload-compaction-readiness":
        if args.apply:
            parser.error("payload-compaction-readiness is read-only; --apply is not supported")
        result = audit_historical_payload_compaction(exhaustive=True)
    elif args.action == "payload-archive-plan":
        if args.apply:
            parser.error("payload-archive-plan is read-only; --apply is not supported")
        result = archive_plan()
    elif args.action == "payload-archive-status":
        if args.apply:
            parser.error("payload-archive-status is read-only; --apply is not supported")
        result = archive_status()
    elif args.action == "archive-trigger-payloads":
        result = archive_batch(payload_type="TRIGGER_EVIDENCE", source_path=HISTORICAL_TRIGGER_DB, limit=args.limit, apply=args.apply)
    elif args.action == "archive-decision-payloads":
        result = archive_batch(payload_type="DECISION_SNAPSHOT", source_path=HISTORICAL_EVIDENCE_DB, limit=args.limit, apply=args.apply)
    elif args.action == "shadow-validate-trigger-payloads":
        if args.apply:
            parser.error("shadow validation is read-only; --apply is not supported")
        result = shadow_validate(payload_type="TRIGGER_EVIDENCE", source_path=HISTORICAL_TRIGGER_DB, limit=args.limit)
    elif args.action == "shadow-validate-decision-payloads":
        if args.apply:
            parser.error("shadow validation is read-only; --apply is not supported")
        result = shadow_validate(payload_type="DECISION_SNAPSHOT", source_path=HISTORICAL_EVIDENCE_DB, limit=args.limit)
    elif args.action == "checkpoint-wals":
        result = checkpoint_wals(apply=args.apply)
    elif args.action == "cleanup-quarantine":
        result = cleanup_quarantined_backups(apply=args.apply)
    elif args.action == "prune-price-samples":
        result = prune_mature_price_samples(apply=args.apply)
    else:
        result = prune_mature_trigger_observations(apply=args.apply)

    result = dict(result)
    result["operator_invoked"] = True
    result["explicit_apply"] = bool(args.apply)
    result["automatic_maintenance"] = False
    result["vacuum_performed"] = bool(result.get("vacuum_performed", False))
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result.get("ok", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
