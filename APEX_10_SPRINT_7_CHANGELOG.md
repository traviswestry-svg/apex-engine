# APEX 10 Sprint 7 — Phase 9 Institutional Intelligence Layer

## Added

- `engine/institutional_state.py`
  - Canonical institutional market-state composition
  - Evidence graph with explicit nodes and relationships
  - Structured deterministic market story
  - Five-stage decision trace
  - Stable SHA-256 state hash for identical decision-time inputs
  - Guardrails preventing direction recomputation, fabricated intent, similarity promotion, and automatic policy activation

- `engine/institutional_state_routes.py`
  - `GET /api/institutional_state`
  - `GET /api/evidence_graph`
  - `GET /api/decision_trace`
  - `GET /api/market_story`
  - Optional `sample_id` replay sourcing from immutable provenance snapshots

- Mission Control Institutional View
  - Unified market-state badges
  - Deterministic market narrative
  - Evidence-domain display
  - Decision-trace display
  - State-hash visibility

- Tests
  - Canonical state behavior
  - Stable state hashing
  - Structured story and trace
  - Honest empty state
  - All four API contracts
  - Dashboard rendering contract

## Architecture stabilization

Removed stale orphaned forks:

- `engine/contracts.py`
- `engine/persistence.py`

Canonical implementations remain under `engine/director/`. These files had no valid importers and violated the repository's architecture guard tests.

## Guardrails

The Sprint 7 layer:

- Does not fetch market data
- Does not independently score trade direction
- Does not convert similarity into a trade signal
- Does not activate learning policies
- Does not infer or fabricate institutional intent
- Uses existing engine outputs as the source of truth

## Validation

- Full test suite: **593 passed, 0 failed**
