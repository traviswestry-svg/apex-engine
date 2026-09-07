# APEX 50.6.2.2 — Durable Canonical Context Resolver

## Objective
Close the production gap where LTPE returned `NO_SPOT` after deploy/restart even though a valid Morning Brief had previously produced SPX spot and next-session institutional levels.

## Changes
- Added `engine/canonical_session_context.py`.
- Successful Morning Brief generations persist a compact canonical SPX session context.
- Default durable path is `/data/apex_canonical_context.db` on Render when `/data` is writable; `APEX_CANONICAL_CONTEXT_DB` can override it.
- Persisted fields include source session, target session, reference spot, prior close, and structured institutional levels.
- LTPE now reads this durable context when the process-local Morning Brief archive is unavailable.
- Durable context is read-only for LTPE; it never creates transition observations or statistics.
- LTPE still excludes future-session OR/IB rows marked `[FEED REQUIRED]`.
- Morning Brief archive loader now falls back from revisions to immutable snapshots.

## Expected weekend path
For the validated 2026-08-03 prep context:
`7489.52 -> 7512.04 PDH -> 7529.00 Expected Move High`
with evidence status `INSUFFICIENT_HISTORY` until real transition samples accumulate.

## Validation
- 17/17 focused LTPE canonical-context/fail-safe/durable-context tests passed.
- Repository Python compilation passed.
- Trading, risk, execution, and evidence-only probability policy unchanged.
