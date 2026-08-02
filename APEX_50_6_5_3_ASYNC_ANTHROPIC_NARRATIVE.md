# APEX 50.6.5.3 — Asynchronous Anthropic Narrative Pipeline

## Objective
Remove Anthropic latency from the synchronous Morning Brief critical path while preserving deterministic institutional analysis, LTPE pathing, forecast archival integrity, and narrative telemetry.

## Implementation
- Added `engine/async_narrative.py`, a durable SQLite-backed narrative job store.
- Job lifecycle: `PENDING -> RUNNING -> COMPLETE | FAILED`.
- `/api/morning-brief` now calls `generate_morning_brief(..., async_narrative=True)` and returns deterministic output immediately after scheduling the AI job.
- Added `GET /api/morning-brief/narrative-status` for persisted status, narrative, errors, and Anthropic telemetry.
- Morning Readiness polls the status endpoint and updates the narrative banner/content in-place without regenerating deterministic levels.
- Existing Anthropic adaptive web-search/no-web fallback, retry, exact failure classification, and circuit breaker are retained inside the background worker.
- Stale `PENDING/RUNNING` jobs are safely requeued after a configurable timeout to recover from Render process restarts.

## Persistence
Default database:
- `/data/apex_async_narrative.db` when writable on Render.
- local `apex_async_narrative.db` fallback.

Optional configuration:
- `APEX_ASYNC_NARRATIVE_DB`
- `APEX_ASYNC_NARRATIVE_STALE_SECONDS` (default 180)

## Safety / integrity
- Deterministic Morning Brief data does not wait for Anthropic.
- The immutable official forecast archive remains deterministic-first; background narrative completion does not rewrite the official snapshot.
- No trading, risk, signal, broker, or LTPE probability logic changed.

## Validation
- Async persistence/lifecycle regression: PASS.
- Synchronous LLM bypass regression: PASS.
- APEX 50.6 regression suite: 38/38 PASS.
- Python compilation: PASS.
