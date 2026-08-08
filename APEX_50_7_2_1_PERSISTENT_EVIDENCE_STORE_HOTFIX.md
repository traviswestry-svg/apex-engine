# APEX 50.7.2.1 — Persistent Evidence Store & Session-Date Integrity Hotfix

## Scope
- Durable `/data` defaults for calibration and governance SQLite stores when Render persistent disk is mounted.
- Best-effort SQLite backup migration from the former repository-local defaults; never overwrites an existing durable DB.
- Governance archive schemas initialize asynchronously at app route registration.
- HLCE session dates now use centralized America/New_York session intelligence rather than UTC calendar dates.
- Legacy Saturday/Sunday HLCE rows are repaired back to the most recent weekday only when the target table/session is empty, avoiding destructive merges.
- Evidence Audit resolves the same durable governance store used by report writers.

## Safety
- Explicit `APEX_CALIBRATION_DB` and `APEX_GOVERNANCE_DB` environment values remain authoritative.
- Migration uses SQLite backup semantics and a temporary file + atomic replace.
- Existing `/data` databases are never overwritten by migration.
- No trading, execution, risk, scoring, or probability policy changes.
