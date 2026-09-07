# APEX 18.0.2 — Executability-Protected Settlement

## Objective
Prevent recommendations that were not executable at entry from being graded as directional wins or losses, while preserving the caller's attempted settlement for immutable audit review.

## Modified behavior

### Strict entry-time executability
A recommendation is executable only when all conditions are true:

- `tradeable` is true
- `pricing_basis`, after trim and lowercase normalization, equals `live_chain_executable`
- `entry_credit` exists and is greater than zero

Missing values fail closed.

### Settlement normalization before persistence
For `CLOSED`, `SETTLED`, and `GRADED` events that carry outcome economics, the payload is normalized before the immutable event is inserted and before the ledger row is updated.

An unexecutable recommendation is stored as:

- `outcome_label = NOT_EXECUTABLE`
- `realized_pnl = 0.0`
- `realized_r = 0.0`
- `executability_override = true`
- `override_reason = ENTRY_NOT_EXECUTABLE`

The attempted values are retained as:

- `requested_outcome_label`
- `requested_realized_pnl`
- `requested_realized_r`

This prevents event/ledger disagreement while preserving a complete audit trail.

### Calibration integrity
`NOT_EXECUTABLE` rows remain excluded from `gradeable` history. Calibration readiness therefore reflects executable settled recommendations only.

## Compatibility

- No database schema change
- No API removal
- Existing executable recommendations settle as before
- Existing event and recommendation retrieval remains compatible
