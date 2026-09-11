# APEX 69.10.6 — Decision-Time Replay Frame Availability & Canonical Feature Persistence Closure

## Purpose

APEX 69.10.5 correctly moved canonical flow excursion capture behind exact immutable feature persistence, but production evidence then isolated the next boundary: live flow learning produced source clusters and sealed feature candidates while every candidate was rejected before persistence because no eligible SPX replay frame existed at or before the candidate decision time.

Observed 69.10.5 production state before this build included 32 live-session cycles, 2,173 source clusters, 1,705 sealed feature candidates, 0 feature rows written, and 1,705 `skipped_before_persist_no_frame` refusals. Canonical identity counters remained clean because the writer never crossed the feature-persistence boundary.

## Root cause

The generic replay-frame hook is called from the equity scanner's per-ticker analysis path. The normal scanner universe is equity-focused and does not include the canonical `ASSISTANT_TICKER=SPX`. Consequently, the SPX feature writer filtered the in-memory replay store for SPX and could legitimately receive no eligible frame even while the independent SPX live active-level publisher was refreshing live flow, intraday bars, volume profile, spot and gamma-derived levels every minute.

This was an availability/wiring gap, not evidence that the point-in-time 600-second guard was too strict.

## Closure

69.10.6 reuses the existing scanner-owned `LiveActiveLevelPublisher` SPX refresh as the forward-only learning replay producer. It does not add a second provider request path. After the publisher has already fetched its normal live SPX flow/profile context, it records a bounded replay snapshot through the existing canonical `_record_replay_frame` boundary.

The learning replay snapshot contains only values actually present in the already-observed state. Missing values are omitted rather than inferred. If no observed context exists, no replay frame is written.

The feature writer remains unchanged. It still resolves only the newest frame at or before the cluster decision time and still rejects a frame beyond `FEATURE_MAX_FRAME_STALENESS_S` (default 600 seconds). Future frames remain forbidden.

## Observability

`live_active_level_publisher` diagnostics now expose:

- `learning_replay_version`
- `learning_replay_frames_published`
- `last_learning_replay_frame_at`
- `last_learning_replay_frame_state`
- per-publication `learning_replay_frame` result

`flow_learning_runtime` now exposes:

- `replay_frames_available`
- `last_replay_frame_at`

These fields are observational only.

## Guardrails preserved

- No decision authority added.
- No execution authority added.
- No broker mutation.
- No second SPX provider path.
- No synthetic replay context.
- No historical replay backfill.
- No future-frame joins.
- No relaxation of the 600-second default staleness rule.
- No historical excursion synthesis.
- No feature-store or sample-id identity changes.
- 69.10.5 post-persistence canonical excursion ownership remains intact.

## Expected production verification

After deployment during RTH, verify the following sequence over several cycles:

1. `live_active_level_publisher.learning_replay_frames_published` increases.
2. `flow_learning_runtime.replay_frames_available` becomes greater than zero.
3. `sealed_feature_candidates` continues increasing.
4. `feature_rows_written` begins increasing for candidates with an eligible prior frame.
5. `capture_attempts` / `canonical_capture_attempts` begin increasing only after exact feature persistence.
6. `canonical_missing_feature_sample`, `canonical_lookup_missing`, and `identity_registration_failures` remain zero.

It is valid for some candidates to remain `skipped_before_persist_no_frame` immediately after deployment or when their decision time predates the first available frame. The build does not rewrite or backfill those candidates.
