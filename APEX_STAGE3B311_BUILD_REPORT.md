# APEX Stage 3B.3.11 — Isolated Historical Gamma Semantic Behavior & Decision-Time Replay Validation

## Build status
Candidate only. No production deployment, Git clone, database, migration, reader cutover or trade authority. Local selected tests: **8 passed**. In a local fixture using a November 12 APEX source snapshot that contains the 69.10.14 functions, selected eligibility tests **15/15 passed** and selected snapshot-freezing tests **6/6 passed**. These checks do **not** constitute execution or verification of the actual September 18 Git objects. The historical source collector must run against the user's verified mirror, and an offline validation must be conducted on a disposable machine.

## Historical target
- Parent: `6d8df89bda76765be4efeb5bbbdc5cb94f3518ab`
- Candidate: `6f15e854b21b6406a570c100d955ccbbb0debe59` (APEX 69.10.14)
- Five targeted source paths: `engine/evidence_eligibility.py`, `engine/historical_evidence_lifecycle.py`, `engine/gamma_transition.py`, `engine/evidence_pipeline.py`, `engine/trigger_observatory.py`.

## Two-phase safe workflow
1. **Collect only on Render**. After integrating `scripts/apex_stage3b311_semantic_replay.py` and deploying:

   ```bash
   python scripts/apex_stage3b311_semantic_replay.py \
     --mode collect \
     --git-repository /data/apex_audit_evidence/apex-git-mirror \
     --output /tmp/apex-stage3b311-historical-source-bundle.zip
   ```

   This executes only `git show`, `git rev-parse`, SHA-256 hashing, and ZIP serialization. It does not run any historical source. It refuses to overwrite an existing bundle. It requires accessible original Git objects.

2. **Transfer privately to a separate disposable machine / VM**, not the running Render production service. Use your approved transfer mechanism (e.g. authenticated SSH file transfer where available); do not publish the bundle or add it to the production Git repository.

   ```bash
   python scripts/apex_stage3b311_semantic_replay.py \
     --mode validate \
     --bundle ./apex-stage3b311-historical-source-bundle.zip \
     --output ./apex-stage3b311-validation.json
   ```

   The validation runner refuses execution when Render-specific environment or filesystem markers are present. It executes AST-extracted, individually selected functions from the collected snapshot in a limited builtins environment, **not** entire historical modules or entrypoints. This is not a hardened security boundary: operate only in a disposable VM/container with no production disks, credentials or network. The approved function `evaluate_evidence_eligibility` and pure helpers are extracted from each revision; `_freeze_gamma_evidence` and helpers are extracted from candidate with synthetic exact-ID lookup substituted for its internal relative import.

3. Read the validation JSON. It records parent and candidate outcomes, deterministic repeat outcomes, six snapshot-freezing fixtures, and explicitly unavailable gates. Never use fixture results to retrospectively reclassify production records.

## Behavioral checks
Eligibility: valid ID, missing ID, unknown/stale/aging gamma freshness, reconstructed/replayed/backfilled provenance, gapped/unknown continuity, low durability, weak capacity, event watch-only and stale opinion. Snapshot freeze: missing link stays `LEGACY_OR_UNKNOWN`, exact-ID lookup only, missing lookup stays an error (no latest fallback), mismatched dynamic ID cannot add capacity, same-ID capacity is preserved, repeat results deterministic.

## Limits / next gates
The test uses a fake gamma lookup; it does not execute original `decision_time_gamma_evidence`, confirm actual provider availability, test historical persistence, prove deployment origin, execute entire historical engine, or attest historical run-time activation. The original parent may not contain `_freeze_gamma_evidence`; its absence is recorded through source inspection, not simulated as executable behavior. Unit tests run against a current/November source fixture containing matching functions; actual Git source validation remains a pending operator step. Cross-database population coverage, Stage 3B.1 UTF-8 reader correction, historical replay equivalence and external backup/rollback remain separate gates.

**Migration authority: `BLOCKED_RESEARCH_ONLY`.**
