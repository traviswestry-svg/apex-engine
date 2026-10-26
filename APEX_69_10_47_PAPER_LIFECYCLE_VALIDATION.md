# APEX 69.10.47 — Paper Execution Lifecycle Validation

## Scope
Pure, deterministic **offline simulation** of an exact SPX options contract lifecycle. The simulation accepts a server-assembled canonical candidate and synthetic event sequence. It does **not** read broker state or submit trades. Caller assertions `canonical_persisted` and `server_approved` are checked for scenario completeness only and are **not trusted authorization**; no route exposes this function as execution permission.

## Model
`engine.execution.paper_lifecycle_validation.validate_scenario(candidate, events, *, daily_loss_limit='1000', prior_verified_daily_pnl=None)`

Candidate fields: `decision_id`, `contract` (`ticker: SPX`, `right: CALL|PUT`, `expiration`, `strike`), `quantity` (1–3), `entry_limit`, `multiplier` (100), optional `max_entry_risk` (<= 2000), `canonical_persisted`, `server_approved`. Events require unique `event_id`, matching `decision_id` and exact `contract`, offset-aware `at`, `type`, `quantity`, and positive `price` for fill events.

Supported event types: `ENTRY_FILL`, `ENTRY_PARTIAL_FILL`, `ENTRY_REJECTED`, `ENTRY_CANCELLED`, `EXIT_FILL`, `EXIT_PARTIAL_FILL`, `EXIT_REJECTED`, `EXIT_CANCELLED`.

Rejects duplicate IDs, mismatched identities, out-of-order times, overfills, orphan exits, and entry risk over $2,000. Unresolved entry remainders, open positions, missing verified daily P&L, and modeled loss-limit breaches remain blockers. Results explicitly set `may_send_order=false`, `broker_fill_verified=false`, `daily_loss_enforced=false`, `ready_for_unattended_orders=false`.

Modeled P&L uses fill prices * 100 and ignores commission/slippage; it is **not** broker-confirmed or externally verified. This is a test harness, not a live performance score or authorization source.

## Release discipline
Apply against the uploaded 69.10.46 snapshot; only four files have changed. Run full repository GitHub CI and release/governance checks before promotion. Focused tests validate simulation mechanics, not real fill reconciliation. No environment variables added, no historical tests edited.

## Production limitation
TradersPost broker reconciliation remains unavailable and dispatch remains blocked. A separate verified broker adapter and independently enforced risk/exits remain prerequisites before authorized paper execution.
