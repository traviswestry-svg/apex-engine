# APEX 13.0 Sprint 5 — Institutional Research Intelligence

## Scope
Sprint 5 extends the Sprint 4 similarity foundation into a governed, research-only Strategy Intelligence layer. It consumes immutable graded outcomes and Sprint 2 quality eligibility. It does not query providers and cannot alter live recommendation logic.

## Implemented
- Versioned research schema `apex.institutional.research.v1`
- Immutable research-run registry with reproducible dataset hashes
- Quality-eligible outcome dataset construction
- Comparisons across recommendation family, regime, consensus grade, confidence band, conviction band, and execution band
- Minimum cohort and minimum comparison-cohort gates
- Descriptive directional accuracy, average realized P/L, and average realized R only when real values exist
- Date coverage, sample size, evidence strength, and statistical-insufficiency disclosure
- Material-separation findings with explicit observational/non-causal limitations
- Research-run deduplication for unchanged datasets
- Governance audit entry for each generated run
- Permanent `policy_effect: NONE`
- Institutional Strategy Intelligence dashboard

## New APIs
- `GET /api/research/findings`
- `GET /api/research/findings/<finding_id>`
- `POST /api/research/generate`
- `GET /api/research/comparisons?dimension=<dimension>`
- `GET /api/research/runs`
- `GET /apex_os/strategy_intelligence`

## Safety behavior
- Returns `COLLECTING` or `INSUFFICIENT_HISTORY` when readiness gates fail.
- Excludes outcomes lacking `GOOD` or `VERIFIED` data quality.
- Excludes recommendations not eligible under the Sprint 2 quality gate.
- Does not infer missing outcomes, P/L, R multiples, or execution scores.
- Does not make causal claims.
- Does not suppress, promote, or modify any live strategy.
- Does not create adaptive candidates automatically.
