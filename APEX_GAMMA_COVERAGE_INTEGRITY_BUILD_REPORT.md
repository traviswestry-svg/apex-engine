# APEX — Gamma Calculation-Universe Comparability Guard (candidate)

Date: 2026-10-30. Base release remains **69.10.47**. Research/measurement integrity only; no changes to production authority.

## Purpose
The existing gamma_model_integrity/gamma_models_comparable implementation already checked source, model ID/version, calculation method and gamma units, but did not compare optional declarations describing the contract universe used by the provider. Therefore two otherwise identical provider/model records with different *declared* calculation coverage could appear comparable.

## Changed files
- `engine/gamma_transition.py`: optional declared coverage fields, canonical identity material (only when present), snapshot extraction, explicit comparison diagnostics for 15-minute historical reference, and suppression of incompatible gamma and maturity-share deltas. Reuses canonical gamma snapshot table and JSON. No new persistence table or new environment variable.
- `tests/test_gamma_coverage_integrity_candidate.py`: unchanged legacy identity behavior; changed/one-sided metadata rejection; identity changes; transition regression.

## Coverage fields
`calculation_universe_id`, `contract_coverage_id`, `expiration_coverage`, `strike_coverage`, `option_side_coverage`, `underlying_coverage`. These must be explicitly declared by the upstream provider/integration. The patch does **not** infer coverage from gamma values or invent any provider metadata.

A status of `UNKNOWN` means no coverage evidence was declared. Existing legacy model compatibility is preserved, but this does NOT mean the universe has been verified as unchanged. `INCOMPLETE` or `CHANGED` prevents economic delta comparisons. `MATCHED` verifies only the fields declared, not undisclosed provider changes. Historical stored payloads remain untouched.

## Test results
- Targeted gamma integrity / regressions: **39 passed**.
- Relevant Python module compilation: passed.
- Full suite attempted; **68 collection errors**, primarily `ModuleNotFoundError: No module named 'flask'` because the full project's runtime dependencies are not installed in this execution environment. Full CI cannot be certified.
- No live-provider replay or production deployment verified. Release governance not independently certified by full CI.

## Deployment requirements
1. Install all project requirements in CI and run standard blocking CI + full release/governance checks, including gamma regression coverage, before promotion.
2. Check whether QuantData or any other provider actually supplies immutable universe/coverage identifiers. If unavailable, keep coverage status UNKNOWN; do not describe coverage as verified.
3. Check downstream consumers of `transition_state` and diagnostic fields under actual provider data. Preserve all read-only and broker safety gates.
4. Separately verify **post-deployment** Morning Brief snapshot persistence. Historical October 15–29 missing snapshots do not establish an active failure.

## Limitations
Existing source/model comparison permits legacy observations when neither side declares coverage. Preventing *all* unreported universe changes requires reliable provider identifiers; this build cannot solve absent provider evidence. This is a targeted candidate patch, **not validated for production promotion**.
