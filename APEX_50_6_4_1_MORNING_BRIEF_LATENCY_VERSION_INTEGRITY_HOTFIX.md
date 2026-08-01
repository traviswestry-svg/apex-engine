# APEX 50.6.4.1 — Morning Brief Latency & Version Integrity Hotfix

## Scope
Production stabilization only. No trading, scoring, broker, risk, or signal logic changed.

## Repairs
1. **Hard Anthropic wall-clock budget**
   - Adds `APEX_BRIEF_AI_TOTAL_BUDGET_SECONDS` (default 12s, hard-capped at 20s).
   - Budget covers all attempts plus retry backoff, not each attempt independently.
   - The remaining budget is divided across remaining attempts so the controlled retry can still occur.
   - Emits `BUDGET_EXHAUSTED` telemetry and immediately preserves deterministic fallback.

2. **Canonical release aliases**
   - Adds `/api/version` and `/api/release-manifest` to the canonical release router.
   - Both expose the same runtime release identity used by `/api/system/version` and `/api/system/release`.
   - Removes false version-consistency warnings caused by missing canonical alias endpoints.

3. **Morning Brief → LTPE canonical integration**
   - Resolves `next_level_path` server-side from the exact generated Morning Brief payload.
   - Dashboard consumes the embedded path first and only uses the legacy LTPE HTTP request as fallback.
   - Prevents session/snapshot mixing (for example a VAH from a different snapshot) and eliminates the fragile second request from the normal render path.
   - Probability policy remains `EVIDENCE_ONLY_NO_FABRICATION`.

## Validation
- Python compilation passed for all changed Python files.
- Anthropic resilience + session readiness tests: 21 passed.
- Earlier focused LTPE durable-context + Anthropic resilience suite: 6 passed.
- Flask is not installed in the local build container, so an isolated Flask route-client smoke test could not be executed here; route definitions were statically compiled and existing readiness tests passed.
