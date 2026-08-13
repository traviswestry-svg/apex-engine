# APEX 66.1 — Live Active Level Publication

## Objective
Complete the APEX 66.0 Canonical Active Level Registry by keeping mutable intraday institutional levels current throughout RTH without creating a second level engine, changing decision authority, or modifying HLCE interaction/outcome logic.

## Conflict / duplication check
66.1 reuses the existing Daily Key Levels deterministic adapters and the 66.0 canonical registry. It does **not** create a new level taxonomy, database, probability engine, learning contract, interaction detector, or execution surface.

## Changes

### 1. Selective live registry publication
`engine/canonical_session_context.py`
- Added `publish_live_levels(...)`.
- Static levels remain untouched during live refreshes.
- Mutable kinds are refreshed by authoritative provider domain.
- Multi-node kinds such as HVN/LVN are replaced as complete current sets.
- Superseded rows remain historical with `active=0` and `valid_to` populated.
- Empty authoritative domains can retire stale levels (for example, an FVG that no longer exists).
- Provider-unavailable domains preserve last-known-good levels instead of falsely deleting them.
- The durable canonical context is rebuilt from the full active registry after each successful live publication, updating `generated_at` and `reference_spot`.

### 2. Scanner-owned live publisher
`engine/live_active_level_publisher.py`
- New lightweight publisher; no Morning Brief or AI generation.
- Reuses existing QuantData flow, Polygon intraday/daily bars, volume-profile bundle, Daily Key Levels adapters, and existing market-state assembly.
- Publishes only mutable intraday kinds.
- Runs in its own scanner-owned daemon thread so provider latency cannot stall scanner heartbeat/HLCE health.
- Default cadence: 60 seconds (`APEX_LIVE_LEVEL_PUBLISH_SECONDS`, minimum 30 seconds).
- Bounded to RTH (09:30–16:05 ET).
- Daily bars cached for 15 minutes to reduce provider load.

### 3. Scanner integration
`scanner_worker.py`
- Starts/stops the live level publisher alongside the scanner-owned HLCE collector.
- Publishes diagnostics into `/data/scanner_heartbeat.json` under `live_active_level_publisher`.
- Does not change scanner ownership, process lease, or HLCE collector ownership.

### 4. Active-level diagnostics
`engine/historical_level_calibration_routes.py`
- Existing `/api/level-calibration/active-levels/diagnostics` now reports 66.1.
- Adds canonical context source and live publisher heartbeat diagnostics.
- Existing registry↔HLCE sync comparison remains unchanged.

## Mutable domains
- Volume profile: developing POC, VAH, VAL, HVN, LVN
- Liquidity/structure: swing high/low, FVG, buy/sell-side liquidity, unfilled gaps
- Opening/IB: OR5, OR15, initial balance and extension levels
- Gamma: gamma flip, zero gamma, call/put walls, high/low gamma strikes, volatility trigger, related dealer levels when a current value is actually supplied

Static prior-session / overnight / expected-move references remain owned by their canonical session publication unless explicitly wired to a live authoritative producer later.

## Evidence-safety behavior
- No synthetic levels.
- No probability changes.
- No learning thresholds changed.
- No execution/decision influence added.
- Missing provider data does not imply a level disappeared.
- A stale level is retired only when its provider domain is currently authoritative.

## Validation
- 45/45 passed across APEX 66.1, 66.0, 65.9, HLCE and LTPE targeted regression suites.
- 20/21 passed in the older APEX 65.7 integrity suite; the single failure is packaging-only because the attached source zip omits `.gitignore`, which that test directly reads.
- Python compile checks passed for all changed runtime modules.

## Post-deployment acceptance
Use:
`https://apex-engine-dashboard.onrender.com/api/level-calibration/active-levels/diagnostics`

Expected:
- `version = 66.1.0_LIVE_ACTIVE_LEVEL_PUBLICATION`
- `in_sync = true`
- `registry_only = []`
- `hlce_only = []`
- `canonical_context_source = scanner_live_active_level_publisher`
- `canonical_context_generated_at` advances during RTH
- `live_publisher.thread_alive = true`
- `live_publisher.successes > 0`
- `live_publisher.last_result.state = LIVE_LEVELS_PUBLISHED`

Mutable level `observed_at` values should advance during RTH when refreshed, while static levels should retain their original session timestamps unless their own authoritative source republishes them.
