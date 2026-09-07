# APEX 11.0B — Chain Quality as a First-Class Pricing Input

**Status:** complete. Full suite **650 passed / 0 failed** (was 638; +12).
**Phase goal (from the roadmap):** *"A trade priced using degraded data should
never outrank one priced with verified live quotes."*

---

## What this phase does

11.0B connects two things that were built but not wired together: the chain-quality
gate (which graded chains) and the premium pricer (which priced structures without
consulting quality). Now every chain-priced structure carries an execution-quality
assessment of the exact legs it was built from, and that assessment **caps the
recommendation's confidence** — so a degraded-chain trade ranks below a
verified-chain one automatically.

## Gate correctness — executable prices, not mids

The research brief's third paper: *"Require executable-price consistency rather than
relying solely on midpoint consistency."* The gate's shape check ran on mids, which
produces false positives on the wide, asymmetric quotes that are normal in 0DTE.

**Fixed — monotonicity now tests executable prices:**

```
6300C 0.05 x 1.00  |  6310C 0.50 x 1.20    (mids invert: .525 -> .850)
mid test        : VIOLATION (false positive)
executable test : ask(6300)=1.00 < bid(6310)=0.50 is FALSE -> no arb -> clean
```

A monotonicity violation is now flagged only when you could actually execute it for
a credit: calls `ask(low K) < bid(high K)`, puts `ask(high K) < bid(low K)`.

**Added — convexity (butterfly) detection.** A long fly can never be entered for a
credit on a convex curve. Violation iff `2*body_bid > wing_ask_low + wing_ask_high`
— the short fly collects more than the wings cost even at worst executable prices.
Surfaced as `convexity_violation_count`. Tested to fire on a rich-body/cheap-wing
chain and stay silent on a normal convex one.

## Freshness is now real (was vacuous)

The original bug: `quote_age_seconds` was always `None` because Polygon's quote
timestamp was never extracted, so freshness scored 100/HIGH for data it never
checked — "unknown treated as perfect."

Verified end-to-end in this ZIP: `polygon_chain.py` now emits `last_updated`, and
`normalize_chain` converts the nanosecond timestamp to `quote_age_seconds`. A quote
3 seconds old now reports `quote_age_seconds ≈ 3.0`. When no timestamp exists at
all, freshness reports `None` with a reason and renormalises out of the score — it
is never silently treated as fresh.

## Quality caps confidence — the 11.0B guarantee

`price_structure` now assesses quality on the **exact legs used to price the
structure**, not the whole chain — a pristine chain elsewhere can't rescue a stale
short leg. It delegates to the one `evaluate_chain_quality` (no second private copy
to drift), and returns an `execution_confidence` in [0,1] that blends *what* the
score is with *how much* was measurable.

The engine then caps confidence: `confidence * (0.5 + 0.5 * execution_confidence)`.

| Same structure, priced off… | Grade | exec_conf | Confidence |
|---|---|---|---|
| fresh, tight chain | HIGH | 1.00 | **72** |
| stale (120s) chain | ACCEPTABLE | 0.80 | **65** |

**Quality only ever caps — it never inflates.** A HIGH chain leaves confidence
untouched (the ceiling); a degraded chain pulls it down. Confidence cannot rise
because the chain was clean. This is the mechanism that makes a degraded-chain
structure rank below a verified one.

## Files

**Modified:**
- `engine/chain_quality.py` — executable-price monotonicity, convexity check,
  `convexity_violation_count`; `VERSION` → 1.2.0
- `engine/premium_chain_pricing.py` — `_assess_leg_quality`; `chain_quality` on the
  pricing result
- `engine/premium_strategy.py` — carries `chain_grade` / `execution_confidence` onto
  the legs; caps confidence by execution feasibility

**Added:** `tests/test_chain_quality_pricing.py` (12 tests)

Freshness extraction (`polygon_chain.py`, `options_data_bus.py`) was already present
in the uploaded ZIP and is verified here, not re-added.

## Tests

| Concern | Tests |
|---|---|
| asymmetric wings are not a false shape violation | 1 |
| real call / put monotonicity arbitrage detected | 2 |
| convexity violation detected; normal chain clean | 2 |
| freshness measured from a real timestamp | 1 |
| no timestamp → unmeasurable, not fresh | 1 |
| leg quality available / not-confident-when-empty | 2 |
| HIGH chain leaves confidence uncapped | 1 |
| **degraded chain ranks below verified chain** | 1 |
| confidence is never raised by chain quality | 1 |

## Known limitations

1. **`execution_confidence` caps but does not yet reorder a multi-strategy list.**
   There is no Trade Finder yet (that's gated on history). When Module 1 exists,
   ranking should sort on quality-capped confidence — the field is already there.
2. **Convexity assumes equal strike spacing**; unequal-spaced triples are skipped
   rather than mis-flagged. Correct but not exhaustive.
3. **The cap function `0.5 + 0.5*xc` is a floor of 50%**: even a near-zero execution
   confidence retains half the model confidence. That is deliberate for now (the
   structure was still priceable), but the coefficient is a candidate for
   calibration once 11.1 has realized outcomes to fit against.
