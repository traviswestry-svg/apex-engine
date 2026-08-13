# APEX Chain Quality 1.1

## Corrections

- Preserves Polygon `last_quote.last_updated` / `sip_timestamp` values and converts nanosecond, microsecond, millisecond, second, or ISO timestamps into `quote_age_seconds` relative to one chain fetch time.
- Reports freshness as `null` with an explicit reason when no timestamp is measurable.
- Renormalizes the quality score over measurable components instead of treating missing freshness as perfect freshness.
- Adds `score_confidence_pct`, `assessment_confidence`, timestamp coverage, and measurable/unmeasurable component lineage.
- Requires adequate assessment confidence for `gate_passed`; a chain with no timestamps cannot pass.
- Makes locked quotes affect the score through an unlocked-market component; a fully locked chain cannot pass.
- Clarifies that chain quality is intended to multiply or cap chain-dependent confidence components, never add an independent bullish/bearish confidence term.

## Validation

- 547 tests passed.
