# APEX — Exact Identity Settlement and Volume/Auction Input Investigations

**Source repository:** `apex-engine-main(20261106-121700).zip`  
**Scope:** Changed-files-only diagnostic candidate; no major release, no trading/scoring/label eligibility change.

## Reproducible production observations (November 9)

- Pending settlement requested **1,391 exact feature sample IDs**; **0** matched canonical excursion rows; **1,304** were identity-map-only awaiting real P&L and **87** feature-only unregistered. Across the checked cohort **10,875** existing excursion IDs were not requested. This is **cohort divergence**, not evidence that the database has no excursions, and **does not prove a writer defect**.
- `component_liveness` marked `auction` and `volume_profile` frozen after **18** unchanged compositions, while `auction_intelligence` was unavailable. The OS code has a bounded `_volume_profile_bundle` fetch; timeout/exception produces `{}` and a partial-result path. Liveness fingerprinting strips timestamps and cannot distinguish a failed fetch from a stable valid profile.

## Investigations added

1. `engine/settlement_gap_investigation.py` — read-only classifier for existing exact-ID cohort counts, lifecycle status, global partition integrity, and gaps. Attached to existing scanner-owned settlement scheduler's durable `last_result.settlement_gap_investigation`. It **does not** change `settle_labels`, join logic, sample IDs, P&L, or the selected settlement cohort.
2. `engine/volume_auction_input_investigation.py` — read-only classifier of whether the **existing** bounded fetch timed out/failed, returned empty or incomplete profile/auction data, or had present but unchanged liveness fingerprints. Reports preexisting source and quality flags, POC/VAH/VAL presence, elapsed fetch time, deadline and component liveness status. Attached as `last_result.volume_auction_input_investigation` in the institutional OS scanner result. It never calls providers or retries.

## What to inspect after integration

- `/api/learning/evidence-lifecycle` → `families.flow_features.settlement.last_result.settlement_gap_investigation`. Expected **if population persists**: `REQUESTED_COHORT_HAS_NO_EXACT_EXCURSIONS`; use `requested_identity_only`, `requested_feature_only`, `awaiting_real_pl`, `existing_excursions_outside_requested_cohort` to determine next targeted source audit.
- Existing institutional OS scanner/result endpoint → `last_result.volume_auction_input_investigation`. Distinguish `FETCH_TIMEOUT_OR_EXCEPTION` vs `EMPTY_VOLUME_BUNDLE`, `MISSING_VOLUME_PROFILE`, `MISSING_AUCTION`, `UNCHANGED_COMPONENTS_NEED_SOURCE_FRESHNESS_CHECK`, and `INPUTS_PRESENT_NO_FAILURE_PROVEN`.
- Existing component liveness endpoint remains unchanged, providing relative stability but not input acquisition cause.

## Test and release truth

- **50 selected tests passed**: new targeted investigations, scheduler closure, exact-ID reconciliation and alignment, excursion/settlement linkage, component liveness, auction nodes, consolidation guard, and gamma decision/settlement linkages.
- `python -m compileall` passed for changed modules and app.
- Full repository test suite **could not collect**: **68 import errors**, starting with `ModuleNotFoundError: No module named 'flask'` in this environment. Therefore **not production-certified**.
- No new environment variables; no version or release manifest modifications; no new provider requests or database tables; no new HTTP routes. Keep the release version **69.10.47** pending normal release governance.

## Limitations / gates

- Source is the November 6 uploaded repository; this patch does not reconcile subsequently deployed changes unless applied against the current branch with conflicts reviewed.
- `FETCH_TIMEOUT_OR_EXCEPTION` intentionally records the existing shared exception path; to differentiate timeout from provider exception further, retain exception class at the existing fetch boundary in a later **separately verified** change.
- A frozen fingerprint is an investigation trigger, not proof of source-feed outage. A complete profile can remain unchanged when underlying data is stable or upstream cache is re-used.
- Do not increase label authority, infer real P&L, generate synthetic excursions, or promote settlement/auction output to execution authorization.
