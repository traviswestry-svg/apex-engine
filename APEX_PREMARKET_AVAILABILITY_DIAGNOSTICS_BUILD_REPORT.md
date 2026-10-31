# APEX — Premarket Feature Availability & Session-Boundary Diagnostics

Candidate based on APEX 69.10.47 plus the supplied Premarket Feature Completeness candidate. Research-only; release metadata unchanged.

## Changed files (relative to completeness candidate)
- `engine/premarket_availability_diagnostics.py` — new bounded, no-network, decision-time diagnostics covering provider unavailable, missing/partial overnight bars, delayed bar availability, target-session mismatch, premarket decision cutoff, prior-RTH coverage, missing close proxy, nonconsecutive trend bars, invalid volume/OHLC, and unavailable gamma provenance.
- `app.py` — calls existing ES adapter and new diagnostic together, passes additive metadata to the existing Morning Brief freezer.
- `engine/premarket_directional_features.py` — freezes original diagnostic metadata with the canonical snapshot, and exposes it through the *existing* read-only research endpoint. Historical snapshots without this metadata remain unchanged.
- `tests/test_premarket_availability_diagnostics_candidate.py` — six tests for Monday ES unavailability, missing Sunday open, target-date mismatch, immutable snapshot capture, legacy rows, and availability precedence.

## Verification
- Premarket tests: 20 passed.
- Premarket + selected gamma integrity tests: 33 passed.
- Consolidation guard: 4 passed.
- Python compilation: passed.
- Full repository CI/release truth: NOT completed. Complete CI and installed application dependencies are required before production use.
- Live provider and next canonical Morning Brief validation: NOT performed.

## Important limitations
- The 2026-11-02 entry supplied by the user was future-dated relative to the current system date 2026-10-31, and is **not independently verified as a completed production session**.
- Diagnostic reasons are based on locally available upstream context; some are categorical rather than exhaustive provider-level root causes. In particular `UNVERIFIED_OR_INCOMPLETE_ES_INPUT` is not an independent confirmation of a provider defect.
- The completeness candidate's existing RTH extraction and timestamp assumptions remain; this patch does not change feature math or claim to fix futures-data availability.
- Only *new* frozen snapshots can have these reasons; old records are not modified or backfilled.
- To verify after release: `GET /api/research/premarket-directional-features?limit=15` and inspect `details[].availability_diagnostics.feature_reasons` for a new session.
- No new environment variables, schema changes, provider requests, official forecast changes, new API routes, or execution authority changes.
