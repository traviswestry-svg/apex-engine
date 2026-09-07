# APEX 69.9.8 — Live Actionability Capture Probe & Lifecycle Attribution Closure

## Purpose

69.9.8 closes an observability ambiguity exposed after 69.9.7 deployment: the graded counterfactual-regret population can legitimately contain zero current-release rows even when the live scanner capture hook is working, because grading and Trigger Observatory linkage happen later.

This release does **not** add another speculative source-path fallback. Instead, it separates decision-time persistence truth from downstream grading/linkage truth.

## New pre-grade live capture audit

New read-only endpoint:

`GET /api/triggers/actionability-capture-readiness?limit=100`

The endpoint reads the canonical `decisions` ledger directly, before canonical grading and before Trigger Observatory linkage. It reports:

- latest persisted decision timestamp and release version;
- current-release decision count;
- current-release entry-window-ready count and percentage;
- capture-version counts;
- entry-window source counts;
- lifecycle-stage counts;
- bounded recent decision diagnostics;
- whether each decision already has a canonical grade.

Current-release states are:

- `WAITING_FOR_CURRENT_RELEASE_DECISION`
- `CURRENT_RELEASE_ENTRY_WINDOW_READY`
- `CURRENT_RELEASE_ENTRY_WINDOW_PARTIAL`
- `CURRENT_RELEASE_ENTRY_WINDOW_NOT_READY`

This makes it possible to distinguish:

1. no new current-release decision has been persisted yet;
2. a current-release decision was persisted but actionability capture is missing;
3. actionability capture is persisted and ready but grading/trigger linkage has not happened yet.

## Counterfactual readiness lifecycle attribution

`counterfactual_regret.actionability_capture_readiness` advances to `apex.actionability_capture_readiness.v2`.

It now includes a `live_capture_audit` block and pre-grade current-release counts. A new readiness state is available:

`CURRENT_RELEASE_CAPTURED_AWAITING_QUALIFICATION_LINKAGE`

This state means the canonical decision ledger already proves current-release entry-window capture, while the graded counterfactual population has not yet received the corresponding grade/trigger linkage.

Therefore, a zero graded current-release row count is no longer interpreted as a capture-wiring failure by itself.

## Runtime probe

The historical evidence lifecycle runtime now records:

- `actionability_capture_attempts`
- `actionability_capture_ready`
- `actionability_capture_missing`
- `last_actionability_capture_at`
- `last_actionability_capture_version`
- `last_entry_window_source`
- `last_entry_cutoff_et`
- `last_cutoff_passed`
- `last_actionability_capture_provenance`

These counters are observational and are included in the existing scanner-owned historical evidence lifecycle heartbeat.

## Schema/version changes

- historical evidence lifecycle: `apex.historical_evidence_lifecycle.v1.6`
- predictive validation: `apex.predictive_validation.v9`
- actionability capture readiness: `apex.actionability_capture_readiness.v2`
- counterfactual regret qualification: `apex.counterfactual_regret_qualification.v3`
- live capture audit: `apex.live_actionability_capture_audit.v1`

## Guardrails

69.9.8 does not:

- change `TRADE_NO_NEW_AFTER_ET`;
- change the 11:30 entry cutoff;
- modify `THESIS_INVALIDATED` or any blocker;
- change conviction/confidence;
- alter consensus weighting;
- activate calibration;
- infer missing historical policy;
- backfill legacy actionability evidence;
- grant execution authority;
- mutate broker state.

The existing 69.9.7 entry-window capture logic remains unchanged. 69.9.8 only proves where a current-release decision is in the capture → persistence → grade/link lifecycle.
