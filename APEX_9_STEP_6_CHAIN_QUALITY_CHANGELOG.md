# APEX 9 — Step 6: Option Chain Quality Gate

**Status:** complete. Full suite **544 passed / 0 failed** (was 537). Seven new tests.

## Why this was next

Flow classification, clustering, cluster P/L, scanner-side sampling, and the leakage-safe feature store are already present. The next highest-risk gap was upstream data integrity: downstream GEX/DEX, expected-move, contract-selection, and future similarity logic could display precise values even when the normalized chain was stale, wide, incomplete, crossed, or internally inconsistent.

## Added

- `engine/chain_quality.py`
  - 0–100 descriptive quality score.
  - HIGH / ACCEPTABLE / DEGRADED / LOW / UNAVAILABLE grades.
  - Hard `gate_passed` decision.
  - Quote coverage, freshness, acceptable-spread coverage, depth coverage, Greeks coverage.
  - Crossed, locked, stale, wide, and missing quote counts.
  - Basic call/put vertical price-shape validation.
  - Explicit warning that derived metrics should be suppressed or confidence-capped when the gate fails.

## Integrated

`OptionsDataBus.get_chain()` now returns `chain_quality` alongside `contracts`, `source`, `tried`, and `warnings`. Empty chains return an explicit UNAVAILABLE quality object rather than implying a valid zero.

No provider API calls were added. The gate evaluates the normalized chain already fetched by the bus.

## Architecture repair

The ZIP had reintroduced `engine/contracts.py` and `engine/persistence.py`, despite Step 1 documenting their deletion. They were removed again. The canonical implementations remain in `engine/director/`, including the merged position-truth-overrides-debounce fix.

## Tests

- High-quality chain passes.
- Crossed and missing quotes fail.
- Stale/wide chain degrades.
- Call vertical shape violation detected.
- Put vertical shape violation detected.
- Empty chain is UNAVAILABLE.
- Options Data Bus attaches quality lineage.
- Architecture guard confirms orphan files stay deleted.

Full result: `544 passed`.

## Recommended next step

Wire `chain_quality.gate_passed` and `score` into confidence decomposition:

- cap gamma/delta contribution when quality is degraded;
- suppress derived walls/flip when LOW or UNAVAILABLE;
- display the quality badge beside every chain-derived level;
- persist the quality score as a pre-decision feature for future similarity, never as an outcome label.
