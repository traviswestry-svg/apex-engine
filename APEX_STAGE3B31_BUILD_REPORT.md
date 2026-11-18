# APEX Stage 3B.3.1 — Canonical Gamma Linkage Completeness & Historical Eligibility Classification

## Purpose

Investigate the missing/unlinked canonical gamma identities reported by Stage 3B.3 without assuming a present-day requirement applies to old records. Research-only, on-demand audit of existing source tables. No archive decompression, database writes, record backfill, reader cutover, or execution authority.

## Evidence basis

The 2026-11-18 Stage 3B.3 production report reported 8 `GAMMA_ID_NULL_OR_UNLINKED` occurrences, two resolved trigger-to-decision references, two null trigger decision IDs, and two incomplete decision/trigger gamma links. These state counts can overlap. It found no confirmed gamma-ID or ticker mismatches in the sampled cohort.

## What this candidate verifies

- Oldest and newest bounded source-table cohorts for `decisions` and `observed_trade_triggers`, preserving only aggregate counts in the report.
- Gamma identity resolution by indexed `gamma_observational_snapshots.canonical_gamma_snapshot_id` lookup.
- Gamma symbol/ticker agreement and trigger-to-decision source existence, ticker agreement and gamma identity conflict.
- Presence or absence of decision `gamma_provenance_class`, **not** whether a non-null value proves historical eligibility.
- Differentiates linkage state (`GAMMA_ID_NULL_OR_UNLINKED`, `GAMMA_ID_NOT_FOUND`, `GAMMA_SYMBOL_CONFLICT`, etc.) from historical policy classification (`UNVERIFIABLE_HISTORICAL_POLICY`).

## Critical limitation

The source schema and supplied reports do not independently establish the version-specific rules governing when gamma linkage was mandatory. Thus the production audit intentionally **never declares `REQUIRED_LINK_MISSING_OR_INVALID` or `HISTORICALLY_NOT_REQUIRED`** absent independently verified versioned evidence. Its pure `classify` helper supports those outcomes for isolated unit tests, but the production sample path does **not** accept user-provided policy assertions or infer them from today’s rules. Provenance version and eligibility require a separate source-of-truth review, including historical contract, effective dates, and decision-time rule provenance. No historical eligibility is established by a resolved identity alone.

## Integration

Add the script and the focused tests. No edits to existing runtime code. Run `python scripts/apex_stage3b31_gamma_eligibility_audit.py --root /data --sample-rows 4 --query-budget-ms 400 --total-budget-ms 8000 --output /tmp/apex-stage3b31-gamma-eligibility.json` during off-market hours. Output MUST remain outside `/data`.

## Safety controls

SQLite `mode=ro` and `PRAGMA query_only=ON`, indexed identity lookup requirement, bounded oldest/newest queries, ≤16 rows per edge/type, ≤1,000ms per query cooperative deadline, ≤20,000ms total, no BLOB or JSON payload reads, no exported IDs, timestamps, names, payload or hashes; no updates, backfill, checkpoint, VACUUM, deletions, migration or trade authority.

## Tests

12 new focused tests passed on synthetic SQLite fixtures: normal/absent/mismatched identities, pure classification rules, missing DB, missing index, limits, read-only preservation. The prior Stage 3B.3 test suite and full APEX CI have not been run as part of this build. No production data was opened or audited.

## Release gates

`migration_authority=BLOCKED_RESEARCH_ONLY` regardless of findings. Historical rule provenance, population-wide identity coverage, UTF-8 archive reader correction, full replay, reader coverage, backup/restore and rollback remain independent blockers.
