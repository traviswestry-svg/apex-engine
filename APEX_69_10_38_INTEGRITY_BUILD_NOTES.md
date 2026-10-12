# APEX 69.10.38 — Gamma Model Integrity & Regime Stability: implementation candidate

Baseline: user-supplied 69.10.37 repository (2026-10-12 upload). This is a **non-promoted, observational-only candidate**, not a production-ready closure. The manifest and registry remain 69.10.37 intentionally.

## Delivered
- Existing `engine/gamma_transition.py` remains the single canonical gamma observation store; no duplicate table or provider call.
- Explicit provider-declared model ID/version/method/unit comparability; absent metadata fails closed. Comparisons of net GEX, flip, and capacity across non-comparable observations are suppressed.
- Optional model metadata participates in canonical gamma snapshot identity only when explicitly present; historical snapshots without metadata preserve legacy identity basis. A source-observation ID reused across different declared models cannot collide.
- Gamma flip validity requires explicit provider confirmation, not merely a numeric level. Structural levels are observational diagnostics only and are **not** promoted to validated levels in downstream consumers.
- Observational flip crossing and dwell statistics require explicitly synchronized spot, comparable model, continuous observed samples, and adequate lookback coverage. Unavailable inputs remain null/UNKNOWN. No extrapolated or synthetic price points.
- Gamma model integrity and regime stability appear in existing transition output; observation-time stability is stored in the existing canonical snapshot JSON for new observations.
- No directional signals, execution authority, settlement, forecast, or grading changes.

## Validation
31 focused tests passed: new 69.10.38 tests, 69.10.14 canonical gamma identity/provenance tests, consolidation guard. Python module compiled. Full repository test suite not run; no live Render validation.

## Production promotion blockers — must close before 69.10.38 manifest bump
1. The existing QuantData adapter does not establish all `model_id`, `model_version`, `calculation_method`, `gamma_unit`, `flip_calculation_valid`, and `spot_synchronized_with_gamma` from documented, trustworthy provider semantics. Do not invent these fields. Until verified, new diagnostics intentionally report UNKNOWN/UNAVAILABLE.
2. Provider-specific units, sign convention, expiry scope, and gamma methodology must be independently mapped and tested; flip/wall validity needs actual source-level evidence, not numeric range checks.
3. Existing downstream level consumers must be audited and either explicitly gated or left unchanged with clear diagnostic-only labeling.
4. Read-only dashboard/observability, canonical decision-time evidence attachment and calibration ingestion must be verified without substituting latest snapshots for historical decision evidence.
5. Full CI, production-like DB compatibility, and runtime telemetry need verification before promotion.

Do not deploy this candidate over 69.10.37 as a completed release. Do not apply the earlier partial ZIP on top of this one; this supersedes its three-file experiment.
