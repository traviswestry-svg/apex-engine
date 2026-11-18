# APEX Stage 3B.3 — Canonical Evidence Reader Compatibility & Cross-Database Identity Verification

## Candidate status

**Built and locally tested. Research-only; not deployed.** This is a standalone bounded production **read-only** audit, not a reader cutover, migration, rollback, full replay, or live-trading change.

## Source basis

- APEX source snapshot: `apex-engine-main(20261112-221036).zip`.
- Audits: Stage 3B.1, 3B.2.1, 3B.2.2, 3B.2.3 candidate packages.
- User-reported production Stage 3B.2.3 results: 8/8 sampled byte-exact matches, not exhaustive.
- Stage 3B.1: invalid UTF-8 payload raises unhandled exception in unpatched `retrieve_archived_payload()`; the existing optional reader fix remains **unapplied** in this candidate.

## Added implementation

`scripts/apex_stage3b3_reader_identity_audit.py`:

- Samples oldest/newest archived decision snapshots and trigger evidence (default 2 of each per edge, at most 4 per edge).
- Uses source primary-key indexes and requires an indexed canonical gamma lookup; does not scan source table populations.
- Checks archive identity mapping and timestamps; verifies bounded decompression, declared uncompressed size, stored SHA-256, valid UTF-8 and byte-exact correspondence to the inline canonical source.
- Separately checks sampled source canonical gamma ID existence **and symbol/ticker agreement**, trigger-to-decision identity existence, and trigger/decision canonical gamma ID agreement.
- Reports missing/null identities separately from proved mismatch; does not promote ambiguous identities.
- Static **text-hint** inventory of inline JSON and archive reader references; does not claim a verified call graph or automatic reader-compatibility certification.
- No IDs, hashes, raw JSON, source payloads or code excerpts in the JSON report.
- Queries use SQLite read-only URI and `PRAGMA query_only=ON` with cooperative progress-handler limits; I/O waits cannot be hard-limited by SQLite progress callbacks.

## Selected validation

- **15/15** new Stage 3B.3 tests passed.
- **51/51** Stage 3B.2.1–3B.2.3 regression tests passed.
- **66/66** combined tests passed.
- Full repository CI: **not run**.
- Live production probe: **not run**.
- Static baseline (Nov 12 snapshot): 421 engine Python files inspected, bounded to 450, no truncation. Static inventory indicates widespread direct source JSON use. These are not execution-path proofs.

## Production execution (after source review, integration, CI and deployment)

```bash
python scripts/apex_stage3b3_reader_identity_audit.py \
  --root /data \
  --repo-root . \
  --sample-rows 2 \
  --query-budget-ms 400 \
  --total-budget-ms 10000 \
  --max-payload-bytes 1572864 \
  --raw-byte-budget 16777216 \
  --output /tmp/apex-stage3b3-reader-identity.json
cat /tmp/apex-stage3b3-reader-identity.json
```

This is an operator-initiated diagnostic. Run off-market; the script reads live SQLite archives and may impose I/O cost. Output must be outside `/data`.

## Unverified migration gates

1. All application reader/writer runtime paths and cutover fallback behavior.
2. Real historical engine decision-time replay equivalence.
3. Population-wide archive/source and cross-database identity coverage.
4. Production Stage 3B.1 UTF-8 reader exception fix deployment and verification.
5. External backup and demonstrated restore on an isolated copy.
6. Isolated rollback and production-representative latency/memory performance.

Migration authority remains **`BLOCKED_RESEARCH_ONLY`** irrespective of matching samples.
