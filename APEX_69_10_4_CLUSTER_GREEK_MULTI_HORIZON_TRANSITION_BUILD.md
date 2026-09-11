# APEX 69.10.4 — Cluster Greek Structure & Multi-Horizon Transition Context

## Baseline
Canonical attached repository audited first: **APEX 69.10.3 — Morning Forecast & Evening Validation Integrity Closure**.

The audit confirmed that APEX already had canonical flow clustering, Flow Surprise, Gamma Capacity/Structure Durability, Gamma Transition Dynamics, Evidence Eligibility, multi-horizon ES transaction momentum, predictive-effectiveness/calibration infrastructure, and production governance. This build therefore extends those components instead of creating duplicate engines.

## What changed

### 1. Provider-grounded Cluster Greek Structure
The live flow tape now preserves provider-supplied `gamma` and implied volatility in addition to existing provider-supplied `delta`. The classifier carries those observations into canonical flow events without modeling missing values.

`engine.flow_clusters` now adds, when source coverage permits:
- `weighted_delta`
- `weighted_gamma`
- `weighted_implied_volatility`
- `cluster_delta_exposure`
- `cluster_gamma_exposure`
- `strike_dispersion`
- `volume_concentration`
- `gamma_concentration`
- `greek_coverage_pct`
- `liquidity_quality` including quote coverage and median relative spread

Missing Greeks remain `None` and are explicitly described in `unavailable_metrics`. No Black-Scholes inference, IV backsolve, chain substitution, or synthetic Greek generation was added.

### 2. Normalized Gamma Transition Dynamics
The existing gamma-transition engine was extended rather than replaced.

New observational fields include:
- `net_gex_change_1m`
- `net_gex_transition_ratio_1m`
- `net_gex_transition_ratio_5m`
- `net_gex_transition_ratio_15m`
- `net_gex_transition_ratio_30m`
- `transition_magnitude_ratio`
- `gamma_capacity_change_15m`

Normalized transition ratios divide the observed change by the **prior observed absolute GEX**, so an identical nominal move is interpreted relative to the structure it displaced.

The 1-minute derivative has a tight freshness tolerance. A five-minute-old snapshot cannot masquerade as a 1-minute observation.

### 3. Multi-Horizon Transition Context
New `engine.multi_horizon_transition_context` composes already-produced observations into a read-only context surface.

It preserves separate 1m/5m/15m/30m gamma-transition ratios and reports:
- `transition_alignment`
- `transition_acceleration`
- `multi_horizon_disagreement`
- `context_confidence`

It can additionally expose current Flow Surprise context and optional ES tick-momentum state. ES transaction-count horizons remain explicitly separate and are **not relabeled as clock-time horizons**.

This is not a directional model and does not vote in consensus.

### 4. Dynamic State / Dashboard
`engine.dynamic_state` now exposes:
- current Flow Surprise when present
- `multi_horizon_transition_context`

The APEX OS Dynamic State panel includes a **Multi-Horizon Transition** card showing 1m/5m/15m/30m normalized gamma changes, alignment/disagreement, acceleration, and context completeness.

### 5. Release-cohort integrity fix
The audit found that historical-evidence and trigger-observatory readiness code used their static implementation version as the definition of the current deployment cohort. That would cause a legitimate version bump to classify new decisions as not belonging to the current release.

Those surfaces now read current release truth from `config/apex_release_manifest.json` while retaining their historical implementation-version identifiers.

Older release tests that permanently pinned the repository to 69.10.3 were converted to version-ratchet checks while preserving the guardrails each release introduced.

## Governance
- `behavioral_authority = false`
- `execution_authority = false`
- `automatic_calibration_activation = false`
- `production_effect = NONE` for the new Cluster Greek / Multi-Horizon intelligence
- Provider Greeks only; missing values stay unavailable
- No duplicate flow-cluster engine
- No duplicate gamma engine
- No duplicate persistence store or outcome ledger
- No synthetic Greek generation
- No automatic consensus/conviction boost
- No ES transaction-count horizon relabeling

## Version
- `apex_version`: **69.10.4**
- `semantic_version`: **69.10.4**
- `application_version`: **69.10.4**
- Build: **Cluster Greek Structure & Multi-Horizon Transition Context**

## Validation
Focused regression command covered the new release, existing Flow Surprise/Gamma Transition, flow clustering/classification, release closures from 69.9.8 through 69.10.3, dynamic-state behavior, mesh independence, and consolidation guardrails.

**Result: 157 passed.**

All modified/new Python modules compile successfully with `py_compile`.

A repository-wide `pytest -q` run was attempted but collection stopped because the sandbox does not have Flask installed (`ModuleNotFoundError: No module named 'flask'`). The repository requirements remain the authority for production dependencies; this environmental limitation is not represented as a passing full-suite run.

## Known limitations
1. Cluster gamma metrics remain unavailable when the live flow provider does not supply gamma for member prints.
2. Flow Surprise is still a current cluster context, not a complete 1m/5m/15m/30m historical series; this build does not fabricate such a series.
3. Multi-horizon clock-time context is currently strongest on persisted gamma snapshots. ES momentum retains its native transaction-count horizons.
4. The new observations have no behavioral authority until APEX accumulates sufficient outcome-linked evidence and governance explicitly promotes a future policy change.
