# APEX 69.10.26 Build Report

## Release

**Version:** 69.10.26  
**Build name:** Expected Range Reversal Timing Intelligence  
**Database schema:** 8  
**Starting point:** APEX 69.10.25 — Origin Provenance Transport Coverage Closure

## Problem Addressed

The existing Range Intelligence correctly exposed the canonical Expected Session Range, but the range boundary could still be operationally interpreted too literally when trading reversals. A session can exceed the expected boundary, rotate near the extreme for hours, and only later reverse. That timing mismatch is especially hostile to low-delta 0DTE options.

This build separates **where a reversal becomes interesting** from **whether a reversal has actually begun**.

## Implementation

### 1. Expected-range extension bands

Added deterministic 10%, 20%, and 30% full-range extensions above and below the canonical Expected Session Range.

The canonical range remains authoritative; extension bands are context only.

### 2. Reversal state machine

Added advisory states:

`RANGE_MONITOR -> EXHAUSTION_WATCH / EXTENSION_ACTIVE -> REVERSAL_DEVELOPING -> REVERSAL_CONFIRMED_ADVISORY`

The state machine cannot authorize execution.

### 3. Conservative rejection proxy

A return-through-envelope proxy is recognized only when the observed RTH session extreme reached/exceeded the canonical edge and current price subsequently returned through that edge.

The payload explicitly labels this as a proxy rather than asserting actual resting-liquidity execution.

### 4. Existing evidence reuse

The reversal layer consumes existing APEX observations only:

- flow bias
- institutional market-structure direction / acceptance-rejection direction
- microstructure absorption candidate when genuinely available
- session extreme displacement

Unavailable evidence remains unavailable.

### 5. Time-at-extreme evidence

Added read-only timing from canonical `price_samples`:

- first edge touch
- elapsed time since first touch
- observed continuous extreme dwell

A five-minute inter-sample cap prevents scanner gaps from inflating dwell time.

### 6. Contract horizon advisory

Added non-executable strategy alignment:

- timing uncertain / extension active: 2DTE, delta 0.50–0.65
- advisory reversal confirmed: 1DTE, delta 0.45–0.60

No 0DTE contract is promoted by the reversal timing layer while the reversal is merely anticipated.

### 7. Institutional OS presentation

The Range Intelligence panel now renders extension bands, reversal state, evidence score, time-at-extreme, and DTE/delta horizon advisory.

### 8. Release governance

The release manifest and capability registry declare the feature as advisory-only with no trade-decision or execution-authority expansion.

## Validation

Command:

`pytest -q tests/test_apex_69_10_*.py tests/test_range_intelligence.py tests/test_range_intelligence_canonical.py`

Result:

**200 passed**

Compile validation:

`python -m compileall -q engine`

Result: **passed**

## Dedicated 69.10.26 coverage

The dedicated suite verifies:

- release metadata and capability registration
- exact 10/20/30% extension calculations
- extension does not imply a reversal
- return-through-envelope rejection plus bearish evidence can produce advisory confirmation
- lower-edge symmetry
- early/unconfirmed reversals prefer more time rather than low-delta 0DTE exposure
- genuine price-sample timing and the five-minute gap cap
- embedded Range Intelligence output preserves advisory-only governance

## Production Acceptance Checks

After deployment, confirm the `/api/range_intelligence` payload exposes:

- `reversal_timing_intelligence.version = 69.10.26_EXPECTED_RANGE_REVERSAL_TIMING_INTELLIGENCE`
- `extension_bands.upper/lower`
- `location.extension_percent`
- `reversal_evidence.normalized_score`
- `timing.first_touch_at`
- `timing.minutes_since_first_touch`
- `timing.observed_extreme_minutes`
- `contract_horizon_advisory`
- governance showing no execution authority

On a session that exceeds the expected high and later returns below it, verify the system transitions from `EXTENSION_ACTIVE` toward `REVERSAL_DEVELOPING`/`REVERSAL_CONFIRMED_ADVISORY` only when confirming evidence is present.
