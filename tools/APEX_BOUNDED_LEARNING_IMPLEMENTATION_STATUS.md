# APEX Bounded Flow-Learning Execution — checkpoint foundation only

Status: INCOMPLETE / NOT DEPLOYABLE AS A CONTINUITY CLOSURE.

The attached module supplies a durable compare-and-swap cursor for a stable session/source fingerprint. The caller must first commit canonical evidence, then advance the cursor. The module is not yet wired to the scanner or to the pipeline.

## Required remaining work
1. Introduce a stable, immutable input snapshot and deterministic cluster/event ordering. A mutable flow tape must not be resumed by offset alone.
2. Split source retrieval, classification, pricing and persistence into bounded resumable phases, including bounded chain-fetch timeouts.
3. Preserve the existing feature writer as the only canonical owner and use idempotent exact-sample writes.
4. Implement bounded replay of a checkpoint after a crash; if evidence commits but cursor advancement fails, replay must be harmless.
5. Wire scanner deadline admission to actual batch estimates and emit per-phase progress/age counters.
6. Run focused + full CI and a live-session soak test verifying both scan freshness and learning progress.

No release bump. No execution authority. Do not deploy this package as a finished fix.
