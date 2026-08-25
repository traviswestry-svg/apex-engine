# APEX 69.4.2 — Microstructure Governance Truth Closure

## Scope

Governance-only release. No market-microstructure analytics, ingestion, persistence behavior, calibration math, trading decisions, confidence weighting, risk logic, or execution behavior is changed.

## Canonical truth closure

The deployed 68.7–68.9 market-microstructure subsystem is now represented in the canonical capability registry with its five deployed modules and twelve `/api/microstructure/*` routes. The registry records the subsystem as observational only with `production_effect = NONE`, no decision authority, and no execution authority.

The release manifest now preserves the following truths across future releases: real licensed ES L2/MBO evidence is required; aggregate futures bars are not substitutes for depth; synthetic depth is prohibited; calibration remains shadow-only; automatic promotion is prohibited; and an operator approval flag alone cannot activate production influence.

## Persistence classification

`engine/market_microstructure_store.py` intentionally retains its direct `sqlite3.connect(..., timeout=5.0)` connection and local WAL/NORMAL policy. It is formally classified as `SPECIALIZED_OBSERVATIONAL_BUFFER` because it stores bounded observational L2/MBO evidence and explicit offline outcomes, is not high-consequence state, and has no decision or execution authority.

This classification is an explicit exception registration, not a migration waiver for unrelated direct SQLite sites. The canonical high-consequence persistence requirement remains closed and unchanged.

## Deferred integration note

Decision Outcome Attribution and Microstructure Shadow Calibration measure related phenomena in separate evidence stores. Reconciliation is intentionally deferred. A future build must explicitly approve any cross-store mapping or merge and must preserve leakage protection, no-fabrication rules, and human promotion governance. APEX 69.4.2 does not merge these stores and does not allow observational microstructure outcomes to become adaptive production calibration inputs.

## Preserved behavior

The 68.7, 68.8, and 68.9 implementation/build documents remain canonical historical records and are not recreated. Existing microstructure route behavior, feed validation, persistence schema and retention, calibration thresholds, promotion-readiness semantics, and all 69.4.1 flow/decision evidence behavior remain unchanged.
