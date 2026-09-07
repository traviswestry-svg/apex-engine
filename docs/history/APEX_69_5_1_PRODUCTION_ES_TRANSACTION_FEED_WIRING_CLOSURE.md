# APEX 69.5.1 — Production ES Transaction Feed Wiring Closure

## Purpose
Close the production boundary identified after 69.5.0 deployed healthy but reported `WAITING_FOR_TRANSACTION_FEED` with `transactions_seen=0`.

## Authoritative source audit
The repository already consumed Massive/Polygon futures **aggregate bars** through `/futures/v1/aggs/{ticker}`. Those bars remain ineligible for tick momentum. The provider also exposes genuine individual futures trades through `/futures/v1/trades/{ticker}` with exchange timestamp, price, size, and sequence metadata. 69.5.1 wires only that individual-trade evidence class.

## Production wiring
The dedicated scanner process owns polling. It resolves the active ES front month with the repository's existing resolver and uses the existing Massive/Polygon base URL and API key. The feed is bounded, cursor-based, and de-duplicates an intentional overlap at the provider timestamp boundary using `(timestamp_ns, sequence_number, report_sequence)`.

A bootstrap poll requests a bounded recent transaction window. Later polls use `timestamp.gte` from the last provider cursor. Provider pagination is bounded and pagination URLs are restricted to the configured provider host.

## Freshness guardrail
A delayed entitlement must not masquerade as live transaction momentum. If the newest provider trade is more than 120 seconds old, the provider cursor advances for observability/deduplication but the stale batch is **not** applied to current 233/512/1000/2000 state. Health reports `STALE_TRANSACTION_FEED`.

## Governance preserved
- observational only
- production effect `NONE`
- decision authority `NONE`
- execution authority `NONE`
- aggregate futures bars remain prohibited as tick evidence
- no synthetic depth
- no automatic promotion
- feed failure is fail-soft and observable
- existing market-microstructure L2/MBO evidence remains separate

## Expected production progression
`provider individual ES trades -> scanner poll -> cursor/dedup -> freshness validation -> canonical tick momentum store -> 233/512/1000/2000 buckets -> alignment state`

If the provider plan does not entitle the individual futures trades endpoint, health remains explicit (`PROVIDER_UNAVAILABLE_OR_NOT_ENTITLED`) rather than fabricating tick evidence from aggregates.
