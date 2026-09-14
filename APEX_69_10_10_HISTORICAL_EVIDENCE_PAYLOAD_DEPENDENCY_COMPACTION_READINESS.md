# APEX 69.10.10 — Historical Evidence Payload Dependency & Compaction Readiness

## Purpose

APEX 69.10.10 is a read-only storage-governance build. It does not rewrite, delete, VACUUM, compact, or otherwise mutate canonical historical evidence. Its purpose is to determine whether the historically amplified payload columns can be reduced safely in a future release.

The two audited payloads are:

- `apex_trigger_observatory.db -> observed_trade_triggers.evidence_json`
- `apex_evidence_pipeline.db -> decisions.snapshot_json`

## Source-audited dependency findings

Trigger Observatory evidence is not an isolated blob. `engine.trigger_observatory.history()` returns the persisted evidence payload, and `trade_visualization()` reads premium-related fields from the persisted trigger evidence. A destructive in-place rewrite therefore cannot be declared safe solely because the 69.10.9 projection is much smaller.

Decision snapshots also remain live historical inputs. Source consumers include Evidence Pipeline readiness, the outcome grader, Trigger Observatory predictive metadata joins, dynamic-state calibration recovery, decision-outcome attribution, and actionability-capture readiness. Historical snapshot removal must preserve those fallback contracts or move the original payload into an immutable archival representation.

## Implementation

`engine/historical_payload_compaction.py` adds:

- bounded, read-only largest-row sampling for the normal storage audit endpoint;
- explicit source-verified dependency contracts;
- simulation of the current bounded Trigger Observatory and Evidence Pipeline projections;
- logical reduction estimates without claiming filesystem reclaim;
- an exhaustive operator-only read-only scan;
- fail-closed compaction readiness state.

Normal `/api/admin/storage/audit` stays bounded. It does not materialize the complete historical payload corpus.

For an exact logical projection, an operator can run:

```bash
python scripts/apex_storage_maintenance.py payload-compaction-readiness
```

This action is read-only. `--apply` is rejected.

## Readiness policy

The build intentionally reports:

`BLOCKED_PENDING_DEPENDENCY_PRESERVATION`

while any of the following remain true:

- Trigger history exposes the original persisted evidence payload.
- Trigger visualization depends on premium fields in persisted evidence.
- Historical decision/calibration/attribution paths still recover data from `snapshot_json`.
- No immutable archival sidecar exists for fields that a compact projection would remove.

The recommended future architecture is:

`IMMUTABLE_ARCHIVAL_SIDECAR_PLUS_CANONICAL_COMPACT_PROJECTION`

That recommendation is architectural only. 69.10.10 does not create the sidecar or rewrite any row.

## Guardrails

- No automatic or manual historical rewrite is implemented.
- No canonical evidence deletion.
- No VACUUM.
- No filesystem reclaim promise.
- No payload values exposed by diagnostics.
- No trade-decision changes.
- No calibration-policy activation.
- No risk-rule changes.
- No execution-authority changes.
