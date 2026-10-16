# APEX Runtime Memory Cache Attribution — Conditional Candidate

Source: apex-engine-main(20261016-140942).zip. Changed files only.

Adds `inactive_file_bytes`, `noninactive_bytes`, and `noninactive_pct` to existing cgroup telemetry. Preserves raw `usage_pct`, WARN/CRITICAL thresholds, OOM event detection, scan cadence, trading behavior, and release metadata (69.10.37).

The adjusted figure subtracts Linux cgroup v2 `inactive_file` from `memory.current` and is **diagnostic only**, not a guarantee of available memory. Missing memory.stat yields null adjusted fields. The console warning includes both raw and adjusted context.

Validated locally: 9 focused tests passed, Python compilation passed. Full CI and production behavior not validated; run GitHub Actions and monitor Render after applying.

No changes to settlement eligibility or missing P/L logic: `AWAITING_REAL_PL` is already used by the writer when genuine P/L is absent.
