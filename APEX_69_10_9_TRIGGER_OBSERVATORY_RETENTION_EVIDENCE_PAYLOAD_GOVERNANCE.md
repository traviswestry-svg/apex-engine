# APEX 69.10.9 — Trigger Observatory Retention & Evidence Payload Governance

## Source-verified production motivation
The 69.10.8 production storage audit showed `/data` CRITICAL at 11.14% free. `apex_trigger_observatory.db` was ~652 MB, with ~649 MB in `observed_trade_triggers`. `apex_evidence_pipeline.db` was ~705 MB, with ~661 MB in `decisions`; historical decision snapshots reached ~1.2 MB while recent rows were ~18 KB.

## Closure
69.10.9 adds forward-only payload governance and operator-controlled trigger retention. Future oversized trigger `evidence_json` is projected to a bounded canonical evidence surface (default 32 KiB) while preserving trigger identity, linkage, and execution/decision authority. Future decision snapshots gain a second 128 KiB hard size guardrail on top of the existing 69.4.4 canonical projection.

The storage audit now reports Trigger Observatory row age, status distribution, evidence payload sizes, protected open rows, protected old unlinked rows, and eligible mature terminal linked+graded rows.

A new `prune-trigger-observations` maintenance action is dry-run by default. `--apply` may delete only rows older than the configured retention window (default 30 days) that are terminal (`OBSERVED` or `OBSERVATION_WINDOW_INCOMPLETE`), have a canonical decision link, and have canonical grade status. Associated trigger price observations are deleted in the same transaction. Open and unlinked rows are protected. No VACUUM follows the delete; freed SQLite pages are reusable internally and filesystem reclaim is not promised.

## Guardrails
- No automatic trigger pruning.
- No historical trigger rewrite/compaction.
- No automatic VACUUM.
- No active database unlink.
- No change to trade decisions, risk limits, broker mutation, or execution authority.
- No change to 69.10.6 replay/canonical feature/excursion capture semantics.
- No change to 69.10.7 scanner completion truth.
- No relaxation of 69.10.8 capacity thresholds.
