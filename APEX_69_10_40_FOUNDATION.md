# APEX 69.10.40 — Paper Execution Authority & Reconciliation Foundation

## Safety boundary
The 69.10.39 operator-supplied governance flags are NOT trusted authorization. 69.10.40 blocks all normal TradersPost dispatches unconditionally while preserving the separate fixed `test: true` connectivity probe. NO automatic live or paper orders are enabled.

## Foundation
`engine/execution/paper_execution_foundation.py` creates a persistent SQLite decision/evidence lifecycle with exact identifiers, duplicate rejection, strict transition checks, UTC timestamps, and evidence SHA-256 digests. It deliberately cannot independently assert verified fills, reconciled positions, or realized P&L. An authenticated adapter is required in a follow-on build. Loss-enforcement readiness fails closed for missing/unverified/uncertain execution evidence.

## Read-only route
`GET /api/paper/traderspost/foundation` uses existing APEX website session/global API auth. No operator-token prompt. Panel summary includes `foundation` status, but never a webhook secret or unconfirmed fill claim.

## Acceptance criteria still BLOCKED
- Connect trusted server-owned canonical decision approvals, never caller flags.
- Connect a separately authenticated, account-specific broker or permitted execution-evidence feed for entry/exit fills and complete position reconciliation.
- Enforce the $1,000 daily realized-loss limit using verified fills, including open-risk exposure and cross-process atomic limits.
- Verify trading-session exit controls, account isolation, actual lifecycle writes and provenance in production.
- Run full CI/release-governance and gamma regressions in the deployment environment; do not enable dispatch until cleared.

## Deployment/rollback
Migrate by deploying changed files through CI. The SQLite tables are created only when server-owned observe_decision() is invoked. They do not migrate existing legacy events automatically. The new dispatch remains fail-closed. Roll back to the prior commit only after verifying any previous dispatch access remains disabled.
