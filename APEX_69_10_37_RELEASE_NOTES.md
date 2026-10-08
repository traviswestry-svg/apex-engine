# APEX 69.10.37 — Forecast Regime & Expected-Move Provenance Diagnostics

Scope: additive decision-time Morning Brief diagnostics, observation-only. No change to regime voting, expected move selection, grading, lifecycle, settlement, or execution authority.

Files: engine/forecast_provenance_diagnostics.py, engine/morning_brief.py, tests/test_apex_69_10_37_forecast_provenance_diagnostics.py.

The new `structured.forecast_provenance_diagnostics` payload captures deterministic vote evidence, vote plurality, selected expected-move source, derived straddle estimate, IV implied one-sigma, ATR/ADR comparisons and missing raw quote metadata. It is captured with the Morning Brief result; downstream persistence must be checked to confirm the entire new structured field is retained by the frozen forecast snapshot.

Raw straddle quotes, IV, expiration, time-to-close and quote freshness are not currently available at this assembly point; those fields are explicitly null, not fabricated. This diagnostic does not retrospectively explain the Oct 7 session; only future snapshots carrying the field do.

Build prerequisite: 69.10.36.1 hotfix remains deployed separately. This changed-files archive is an additive diagnostic patch and does NOT bump the global release manifest/registry from 69.10.36; deployers must not claim the global application version is 69.10.37 until the full version-alignment process is completed.

Validation: 7 targeted tests passed; compileall passed. Production and end-to-end persistence not verified.
