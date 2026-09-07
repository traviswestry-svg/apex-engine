# APEX 66.3.0 — Decision Reasoning Consolidation Foundation

## Release identity
- Application release: **66.3.0**
- Build: **Decision Reasoning Consolidation Foundation**
- Database schema: **5** (unchanged)
- Authoritative decision contract: `engine.institutional_decision_object` / `apex.institutional_decision.v3`

## Objective
Begin Decision Reasoning Consolidation without introducing a parallel decision engine. The existing production-facing `institutional_decision_object` remains authoritative. Existing primitive intelligence is normalized into shared contracts and legacy decision surfaces are adapted to the authoritative object.

## Implemented
1. Added canonical `EngineOpinion` normalization with explicit `BULLISH`, `BEARISH`, `NEUTRAL`, `UNKNOWN`, and `ABSTAIN` semantics.
2. Missing engine data now abstains; it is not converted into neutral or disagreement.
3. Added a normalized `AcceptanceResult` that reuses existing market-structure, auction, and institutional-intelligence acceptance outputs. No new acceptance detector was created.
4. Replaced authoritative simple agreement-count consensus with configured correlation-aware consensus using architecture clusters and transparent diminishing returns for redundant evidence.
5. Added independent-evidence coverage, redundant-evidence score, correlation penalty, disagreement, supporting/contradicting/abstaining/stale/unavailable engine lists, active/conflicted clusters, and an Evidence Conflict Matrix.
6. Split conviction into `raw_conviction` and `calibrated_conviction`. Calibrated conviction remains `null` until sufficient graded history and an approved calibration model exist.
7. Existing governance graded-history maturity is consulted; no win-rate or calibrated probability is fabricated.
8. Added a structured Institutional Thesis foundation with explicit state, supporting/contradicting/abstaining engines, known unknowns, next event, raw/calibrated conviction, and structured soft invalidation triggers.
9. Added an in-memory reasoning Evidence Graph preserving support, contradiction, neutral, unknown, abstention, stale and unavailable relationships without causal inference.
10. Upgraded `institutional_decision_object` to schema `apex.institutional_decision.v3` and explicitly marked it as the authoritative decision source.
11. Updated immutable Decision Intelligence persistence to retain normalized engine names/provenance.
12. Converted the older APEX 20.0 `institutional_decision_engine` into a compatibility adapter. Its legacy API shape remains, but it no longer independently synthesizes authoritative consensus, conviction, thesis, or actionability.
13. Reconciled capability-registry decision authority metadata.
14. Removed dead modules that the existing Consolidation Sprint 1 guard explicitly required to remain deleted and updated the stale APEX 65 static test that still expected the deleted v245 command-center route file.

## Correlation clusters
Initial configured clusters are transparent architectural priors, not learned statistics:
- STRUCTURE_AUCTION
- FLOW_LIQUIDITY
- DEALER_POSITIONING
- INTERNALS_BREADTH
- EXECUTION_READINESS
- NARRATIVE_EVENT

Secondary engines inside the same cluster currently receive a configured 0.35 diminishing-return factor. `historical_correlation_statistics_applied=false` is explicit in the contract.

## Files added
- `engine/decision_reasoning_contracts.py`
- `tests/test_apex_66_3_decision_reasoning_consolidation.py`
- `APEX_66_3_0_IMPLEMENTATION_REPORT.md`
- `APEX_66_3_0_DEPLOYMENT_ROLLBACK.md`
- `APEX_66_3_0_DELETE_FILES.txt`

## Files modified
- `engine/institutional_narrative.py`
- `engine/institutional_decision_object.py`
- `engine/institutional_decision_engine.py`
- `engine/decision_intelligence_core.py`
- `engine/version.py`
- `config/apex_release_manifest.json`
- `config/apex_capability_registry.yaml`
- `tests/test_apex_48_2_version.py`
- `tests/test_apex65_stabilization_static.py`

## Files removed
The following files were present in the supplied 66.2.2 baseline but contradicted the repository's own `tests/test_consolidation_guard.py`, which records them as Sprint-1 deletions. Static reachability also classified them as dead/unreachable. They were removed rather than carried forward:
- `engine/cache.py`
- `engine/confidence.py`
- `engine/format.py`
- `engine/institutional_command_center_v245.py`
- `engine/institutional_command_center_v245_routes.py`
- `engine/logging.py`
- `engine/market_regime.py`
- `engine/math.py`
- `engine/recommendation_ledger_routes.py`
- `engine/ribbon.py`
- `engine/risk.py`
- `engine/scheduler.py`
- `engine/structure.py`
- `engine/trend.py`
- `engine/types.py`

## Deprecated / compatibility surfaces
- APEX 20.0 `engine.institutional_decision_engine` is retained as a compatibility adapter and has **no authoritative decision authority**.
- `engine.canonical_decision` remains the legacy evidence snapshot contract; it is not promoted to authoritative institutional reasoning.

## API changes
Existing routes are preserved. Additive fields are exposed through the existing institutional endpoints, including:
- `engine_opinions`
- `acceptance`
- `effective_consensus`
- `raw_directional_evidence`
- `effective_directional_evidence`
- `independent_evidence_score`
- `redundant_evidence_score`
- `correlation_penalty`
- `disagreement`
- `active_clusters`
- `conflicted_clusters`
- `evidence_conflict_matrix`
- `evidence_graph`
- `raw_conviction`
- `calibrated_conviction`
- `calibration_state`
- `thesis`

The legacy `/api/institutional-decision/status|diagnostics|scenarios|evidence|strategy` family retains its response shape but now includes/derives from the authoritative canonical decision.

## Database migration
None. Database schema remains 5. No production history is deleted or rewritten.

## Validation
- APEX 65–66 integrity/execution/HLCE suite: **121 passed, 0 failed, 1 skipped**.
- Decision-consolidation/persistence/consolidation-guard suite: **43 passed, 0 failed**.
- Legacy APEX 20.0 non-route compatibility assertions: **6 passed**.
- Python compilation: passed for `engine/`, `app.py`, `scanner_worker.py`, and `wsgi.py`.
- Skip/limitation: isolated development runtime does not have Flask installed, so Flask-dependent route tests cannot be collected here. Render installs Flask from `requirements.txt`.

## Known limitations / deliberately deferred
- Stateful thesis lifecycle persistence across process restarts is not yet implemented in this foundation release.
- Hard invalidation remains empty unless a machine-defensible hard trigger exists; none is fabricated.
- Failed Break Quality and Trap Evidence have not yet been consolidated into canonical derived-evidence contracts.
- Executable Edge Margin has not yet been introduced.
- Historical correlation statistics are not fabricated; configured decorrelation is explicitly labeled.
- Calibrated conviction remains null until legitimate history plus an approved calibration model exist.
- Additional legacy decision/reasoning modules still require staged migration into adapters in subsequent 66.3.x builds.

## Recommended next step
APEX 66.3.1 should continue production integration by adding persisted thesis lifecycle/invalidation state and migrating the remaining legacy consensus/conviction synthesis consumers to the authoritative v3 decision object, followed by Failed Break Quality and Trap Evidence as derived evidence rather than trade signals.
