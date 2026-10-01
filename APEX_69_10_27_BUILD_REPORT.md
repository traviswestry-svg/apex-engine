# APEX 69.10.27 — Durable Bound Origin Re-observation Closure

## Root cause
69.10.25 correctly resolved direct continuing event ancestry, but production telemetry showed 1,202 transport observations, 2,274 unbound events, and zero bound events observed at the later P/L handoff. Review found an ordering/source-window gap: the P/L pipeline attempts transport before the feature writer persists and binds the current cycle's sealed feature. On later cycles, the provider tape may no longer contain the originating print, so the exact bound event never re-enters the rebuilt cluster even though its binding is durable.

## Closure
69.10.27 adds a post-persistence durable origin re-observation path. After the writer has persisted the feature and atomically registered exact event→canonical-sample bindings, APEX queries those exact bindings joined to the already-recorded event facts in `flow_pl_tracking`, obtains a genuine current option-chain mark, recomputes P/L for the original bound events, aggregates only those exact members by canonical sample, verifies the exact registered owner tuple, and writes/updates the canonical sample excursion.

## Guardrails preserved
- Canonical owner comes only from `flow_feature_origin_bindings`.
- Exact registered owner verification is mandatory before evidence writes.
- No fuzzy matching, nearest-time matching, market-attribute owner search, owner substitution, sample-id reconstruction, or historical backfill.
- No synthetic quote or P/L: missing current chain quotes fail closed.
- Persisted event facts are observation inputs only; they do not create ownership.
- Settlement semantics are unchanged.
- Decision authority and execution authority are unchanged.

## Observability
Scanner runtime now counts durable origin re-observation candidates, samples marked, excursion inserts/updates, and errors.

## Validation
Focused regression set: 28 passed, covering 69.10.24, 69.10.25, 69.10.26 and new 69.10.27 behavior. Full-suite collection is blocked in the current sandbox because Flask 3.0.3 from requirements.txt is not installed; pytest reports collection-time `ModuleNotFoundError: flask` errors before executing those tests.

## Post-deployment acceptance
The key success signal is no longer only `origin_transport_coverage.bound_events`. Because provider tape windows may legitimately discard old prints, validate the new scanner runtime counters: `origin_reobservation_candidates > 0`, `origin_reobservation_samples_marked > 0`, and `origin_reobservation_updated > 0` during a live session. Canonical `sample_excursions`, settlement exact matches/labels, and `flow_features.graded` should continue advancing without increases in ownership-integrity or leakage failures.
