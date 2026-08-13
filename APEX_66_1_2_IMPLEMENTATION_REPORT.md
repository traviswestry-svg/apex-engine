# APEX 66.1.2 — Dynamic Level Identity Stabilization

## Objective
Preserve canonical UUID identity when a mutable institutional level moves by a bounded amount, rather than treating every new price print as a new level.

## Changes
- Added kind-specific identity migration tolerances for developing POC, VAH/VAL, HVN/LVN, swing/liquidity and gap families.
- Added deterministic nearest-neighbor, one-to-one matching for multi-node families.
- Price migrations update the existing canonical row and increment its revision without changing `canonical_level_id` or `valid_from`.
- Added durable `canonical_level_migrations` audit history with old/new price, distance, timestamp, version and metadata.
- Added `level_migration_history()` read helper.
- Reconciliation diagnostics now expose `migrated`, `migration_distance`, and active identity tolerances.
- Updated component/version labels to `66.1.2_DYNAMIC_LEVEL_IDENTITY`.
- Preserved 66.1.1 behavior for exact matches, reactivation, authoritative retirement, static-level protection, and full-registry context refresh.

## Validation
Focused registry/live publication suite: 16 passed.
