# APEX 69.9.10 — Recommendation-Layer No-Trade Blocker Attribution Closure

## Summary

APEX 69.9.10 tightens the observational blocker taxonomy inside the counterfactual-regret surface. Historically, abstentions with **no explicit trigger blocker codes** but a captured recommendation-layer **`NO_TRADE`** were grouped under **`NO_EXPLICIT_BLOCKER`**. That preserved correctness, but it made the blocker inventory less honest and inflated the diagnostic bucket meant for truly unexplained abstentions.

This release promotes recommendation-layer abstention into a **first-class observational blocker category** — **`RECOMMENDATION_LAYER_NO_TRADE`** — whenever the persisted blocker list is empty and the captured recommendation intent itself says to stand down.

The result is a cleaner blocker taxonomy, more truthful attribution in `by_blocker_session`, and a smaller/more meaningful `no_explicit_blocker_diagnostics` cohort. Execution authority remains **false**; the build is strictly observational.

---

## What changed

### 1) First-class recommendation-layer blocker attribution

`engine/trigger_observatory.py`

- Added `_recommendation_layer_blocks(...)` helper.
- When persisted trigger blocker codes are empty but the captured recommendation action/state is one of:
  - `NO_TRADE`
  - `STAND_DOWN`
  - `ABSTAIN`
  - `WATCH`
  - `WATCH_ONLY`
- the counterfactual loader now assigns the derived blocker:
  - `RECOMMENDATION_LAYER_NO_TRADE`

This is observational attribution only. No live decisions, broker flows, or grading outcomes are changed.

### 2) Counterfactual qualification now treats the recommendation gate like any other target blocker

`engine/trigger_observatory.py`

- The qualification routine now recognizes when the **target blocker under evaluation** is `RECOMMENDATION_LAYER_NO_TRADE`.
- In that case, a recommendation-driven abstention no longer disqualifies the row as an independent blocker; it becomes the blocker being tested for potential regret.

This means recommendation-driven abstentions can now surface honestly in `potential_blocker_regret` when all other captured gates pass and the canonical directional grade later proves correct.

### 3) Capability registry and release manifest advanced to 69.9.10

Updated:

- `config/apex_release_manifest.json`
- `config/apex_capability_registry.yaml`

New observational capability flag:

- `recommendation_layer_blocker_attribution`

### 4) Regression coverage added

`tests/test_apex_69_9_6_actionability_counterfactual_regret.py`

Added/updated tests to prove:

- recommendation-layer `NO_TRADE` with no explicit blocker is promoted to `RECOMMENDATION_LAYER_NO_TRADE`
- that row is eligible for blocker-specific regret analysis when all other gates pass
- `no_explicit_blocker_diagnostics` remains reserved for genuine no-explicit-blocker cases
- release truth artifacts advertise the new capability

---

## Why this build matters

Your live audit showed that a meaningful share of `NO_EXPLICIT_BLOCKER` rows were not actually unexplained. They were **recommendation-layer abstentions**. Leaving them inside the “no explicit blocker” bucket diluted the diagnostic value of that cohort.

69.9.10 closes that attribution gap by making the blocker ledger say what actually happened:

- if the recommendation layer abstained, the blocker is **recommendation-layer no-trade**
- if nothing explicit blocked and the recommendation layer also did not abstain, only then does the row remain **no explicit blocker**

That makes follow-on blocker analytics more actionable and easier to trust.

---

## Guardrails

- **Execution authority:** false
- **Broker mutation:** false
- **Observational only:** true
- **Historical rewrite/backfill:** false
- **Trade-decision influence:** none

This release changes **analytics attribution only**.

---

## Files changed

- `engine/trigger_observatory.py`
- `config/apex_release_manifest.json`
- `config/apex_capability_registry.yaml`
- `tests/test_apex_69_9_6_actionability_counterfactual_regret.py`
- `tests/test_apex_69_9_8_live_actionability_capture_probe.py`
- `tests/test_apex_69_9_9_live_flow_canonical_excursion_invocation_closure.py`
- `APEX_69_9_10_RECOMMENDATION_LAYER_NO_TRADE_BLOCKER_ATTRIBUTION_CLOSURE.md`

---

## Expected outcome

After deployment, `/api/triggers/counterfactual-regret` should show:

- fewer rows classified under `NO_EXPLICIT_BLOCKER` when the recommendation layer already abstained
- new blocker-level visibility for `RECOMMENDATION_LAYER_NO_TRADE`
- a cleaner `no_explicit_blocker_diagnostics` sample representing truly unexplained abstentions

