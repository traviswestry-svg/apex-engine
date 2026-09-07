# APEX 24.3 — Strategy Research Laboratory

Release identity: `17.3.0_STRATEGY_RESEARCH_LABORATORY`

## Summary

An institutional research environment that extends the existing APEX 15.5
`institutional_research_lab` (governed, immutable candidate / run / attribution
registry) with performance analytics, experiment tracking, and research
dashboards. Offline research only — nothing here alters production settings,
places orders, or promotes anything automatically.

## Reuse, not duplication

Candidate registration, runs, comparison, alpha attribution, and readiness gates
all delegate to `institutional_research_lab`. The 24.3 module adds the analytics
and experiment layers on top; `/api/research/strategies` reuses `lab.compare`.

## Implemented

- Performance analytics (`performance_analytics`): win rate, expectancy, profit
  factor, average R, max drawdown, plus breakdowns by regime, strategy family,
  and position sizing. Deterministic, pure over a supplied trade list.
- Equity curve and regime comparison helpers.
- Experiment tracking: `create_experiment`, `add_revision` (immutable version
  history), before/after comparison, notes. Experiments never alter production
  settings (`production_settings_modified: false`).
- Strategy ranking + performance summaries aggregated from the immutable lab
  candidates/runs.
- Research dashboard combining candidates, runs, attributions, and experiments.
- Mission Control: `STRATEGY_RESEARCH` panel + `/api/research/status` drill-down.

## API surface (one canonical namespace)

Owned by APEX 24.3: `GET /api/research/status`, `GET /api/research/strategies`,
`GET /api/research/experiments`, `GET /api/research/performance`, plus supporting
`POST /api/research/experiments`, `POST /api/research/experiments/revision`,
`POST /api/research/analytics`, `GET /api/research/dashboard`.

Backward compatible: `GET /api/research/status` is now owned by 24.3 and merges
the pre-existing research-findings + similarity + governed-research status via an
injected legacy provider, so existing consumers keep their fields. The existing
`/clusters`, `/findings`, `/generate`, `/comparisons`, `/runs`, `/similarity`,
`/vector` routes are untouched.

## Registrar hardening

Registration runs outside the broad non-fatal block, verifies all four canonical
routes, and fails loudly on missing or duplicate routes.

## Safety

Offline research only. Immutable candidate/run/experiment history (hash-audited
via governance). No production-settings mutation, no automatic promotion, no
broker effect.
