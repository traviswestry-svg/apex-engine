# APEX 69.10.0 — Flow Surprise Intelligence & Gamma Transition Dynamics

## Audit / release selection
The canonical pre-build release was **69.9.10** (`config/apex_release_manifest.json`). This is a new additive intelligence capability rather than a patch-level closure, so the next semantic release is **69.10.0**.

## Architecture reused
- **Flow identity:** `engine.flow_clusters` remains the sole clustering engine and sole source of `cluster_id` identity.
- **Flow authenticity / independence:** existing `flow_authenticity`, `flow_excitation`, and Evidence Eligibility remain authoritative. Surprise is a separate descriptive dimension and never applies a second independence discount.
- **Historical evidence:** immutable `flow_features` is reused for contextual baselines and decision-time freezing; no new flow outcome database was created.
- **Gamma:** `engine.gamma` remains the sole gamma engine. Existing gamma path, term structure, maturity concentration/durability, active flip, and capacity context are extended with temporal observations.
- **Outcome/calibration:** existing decision evidence, feature/label separation, outcome grading, calibration, and governance remain unchanged and authoritative.

## Flow Surprise methodology
For each existing canonical cluster, APEX compares total contracts, total premium, and contracts-per-second against prior immutable flow-feature samples conditioned first on **30-minute session-time bucket** and **expiration class (0DTE vs later)**. Empirical percentiles and current-to-historical-mean ratios are emitted only when at least 20 comparable rows exist. Otherwise the state is `INSUFFICIENT_HISTORY` and numerical surprise values remain null.

States: `NORMAL`, `ELEVATED`, `HIGH`, `EXTREME`, with no directional or behavioral meaning. Current cluster identity is preserved as the existing `cluster_id`.

## Gamma Transition methodology
Each genuine gamma provider observation contributes the minimum temporal state required for derivatives: observation/source timestamp when available, provider, path version, net GEX, active flip, 0DTE / 0–1DTE / <=7DTE exposure shares, durability, and optional capacity ratio. The history is an additive table inside the **existing canonical DB path**, not a new database.

Derivatives are computed at 5m/15m/30m only from appropriately aged observations. Stale observations are rejected. Classification is deterministic and scale-aware using change relative to current absolute net GEX: `STABLE`, `STRENGTHENING`, `WEAKENING`, `RAPID_TRANSITION`. Missing genuine source values remain `UNAVAILABLE`/null.

## Persistence and decision-time evidence
Flow Surprise is frozen into the existing immutable feature vector at the sealed-cluster decision boundary; first-write-wins prevents later history from rewriting the context. Gamma Transition is exposed through Dynamic State so canonical decision snapshots can freeze the observed transition alongside existing gamma context. Existing outcome/calibration infrastructure can therefore grade future effectiveness without a duplicate ledger.

## Evidence Eligibility / behavior
Identity, authenticity, independence, surprise, and eligibility remain distinct. This build does not modify positive evidence weights, conviction, consensus, entry thresholds, sizing, or execution. It does not double-discount clustered/correlated flow.

- `execution_authority = false`
- `behavioral_authority = false`
- `automatic_calibration_activation = false`
- `production_effect = NONE`

## API / observability
- `/api/flow_clusters`: each cluster can include `flow_surprise`, including baseline context/sample/confidence and explicit `AVAILABLE` / `INSUFFICIENT_HISTORY` / `UNAVAILABLE` states.
- `/api/dynamic-state`: includes `gamma_transition` with temporal deltas/classification while existing gamma path/term/capacity blocks remain unchanged.

No placeholder values are fabricated for unavailable inputs.

## Known limitations / evidence collection
1. Flow Surprise begins with only time bucket + expiration class to avoid over-segmentation. Additional conditioning requires sufficient sample density.
2. Gamma provider payload does not expose a distinct exchange/source event timestamp in every response; APEX preserves it when present and otherwise relies on the actual observation time while making no claim of a provider timestamp.
3. Capacity-change is null until a capacity ratio is present on the gamma observation itself; existing Dynamic State capacity remains authoritative.
4. Predictive effectiveness is not claimed. Production needs accumulated, graded samples before any governed promotion could even be considered.
