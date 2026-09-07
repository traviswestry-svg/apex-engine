# APEX 66.3.2 — Stateful Thesis Persistence & Structured Invalidation Lifecycle

## Release identity
- APEX version: **66.3.2**
- Build: **Stateful Thesis Persistence & Structured Invalidation Lifecycle**
- Canonical decision contract: `apex.institutional_decision.v3`
- Canonical thesis contract: `apex.institutional_thesis.v2`
- Thesis lifecycle contract: `apex.thesis_lifecycle.v1`
- Database schema version: **5** (application schema identity unchanged)

## Objective
Make the canonical Institutional Thesis durable and machine-governed without creating a parallel decision engine. The lifecycle layer persists and transitions the thesis produced by `engine.institutional_narrative`; it does not synthesize direction, consensus, conviction, or trade actions.

## Implemented
1. Added `engine/thesis_lifecycle.py` as a persistence/governance layer over the canonical thesis candidate.
2. Added durable thesis state and immutable thesis transition events to the existing recommendation-ledger SQLite database.
3. Implemented thesis states: `FORMING`, `ACTIVE`, `WEAKENING`, `CONFLICTED`, `INVALIDATED`, `EXPIRED`, `CLOSED`, `UNKNOWN`.
4. Implemented deterministic transitions for creation, strengthening, weakening, conflict, soft invalidation, hard invalidation, replacement after invalidation, session expiry, and session close.
5. Added explicit machine-evaluable invalidation operators: `LT`, `LTE`, `BELOW`, `AT_OR_BELOW`, `GT`, `GTE`, `ABOVE`, `AT_OR_ABOVE`, `CROSSES_BELOW`, `CROSSES_ABOVE`.
6. Hard invalidations are created only from explicit existing stop/invalidation inputs. APEX does not infer hard invalidation from nearby reference levels or prose.
7. Existing VAH/VAL/POC acceptance references remain soft invalidation context and are explicitly marked non-machine-evaluable until normalized acceptance evidence can evaluate them safely.
8. Added restart persistence keyed by ticker + session date.
9. Added automatic expiration of older nonterminal theses when a newer live session begins.
10. Prevented closed-market/weekend API reads from creating empty thesis records when no prior session thesis exists.
11. Added thesis state to the canonical decision response and exposed `thesis_lifecycle` and `thesis_evolution_timeline`.
12. Added thesis persistence to immutable Decision Intelligence timelines through the canonical `evolution_timeline`.
13. Added `THESIS_SNAPSHOT` to recommendation replay snapshots.
14. Added thesis and thesis lifecycle snapshots to institutional evidence packages.
15. Added read-only thesis APIs.
16. Hardened final actionability: **only an `ACTIVE` thesis may be actionable**. `FORMING`, `WEAKENING`, `CONFLICTED`, `INVALIDATED`, `EXPIRED`, and `CLOSED` are fail-closed / `NO_TRADE`.
17. A hard invalidation now yields `THESIS_INVALIDATED` status even if current consensus/conviction would otherwise pass the actionability gate.

## Files added
- `engine/thesis_lifecycle.py`
- `tests/test_apex_66_3_2_thesis_lifecycle.py`
- `APEX_66_3_2_IMPLEMENTATION_REPORT.md`
- `APEX_66_3_2_DEPLOYMENT_ROLLBACK.md`

## Files modified
- `engine/institutional_narrative.py`
- `engine/institutional_decision_object.py`
- `engine/institutional_intelligence_routes.py`
- `engine/recommendation_ledger.py`
- `engine/decision_review.py`
- `engine/institutional_evidence.py`
- `engine/version.py`
- `config/apex_release_manifest.json`
- `config/apex_capability_registry.yaml`
- `tests/test_apex_48_2_version.py`

## Files deprecated
None.

## Files removed
None.

## Database notes
No destructive migration and no application database-version bump. On first use, `engine.thesis_lifecycle.init_db()` additively creates:

- `institutional_thesis_state`
- `institutional_thesis_events`

Both tables live in the existing recommendation-ledger database selected by `RECOMMENDATION_LEDGER_DB_PATH` / `DB_PATH`. Existing recommendation, execution, HLCE, governance, and learning rows are not modified or backfilled.

Rollback does **not** require dropping these tables. Older releases ignore them safely.

## API changes
Added read-only endpoints:

- `GET /api/institutional-thesis`
  - Returns the current canonical persisted thesis, lifecycle state, and thesis event timeline.
- `GET /api/institutional-thesis/history?ticker=SPX&session_date=YYYY-MM-DD`
  - Returns persisted historical thesis state and transition events for an explicit session.

Existing `GET /api/institutional-decision` remains authoritative and now includes:
- `institutional_thesis` / `thesis` using `apex.institutional_thesis.v2`
- `thesis_lifecycle`
- `thesis_evolution_timeline`

## Guardrails
- No new analytical engine.
- No broker calls.
- No execution-boundary changes.
- No bypass of confirmation, readiness, risk, quote freshness, duplicate prevention, or execution governance.
- No fabricated historical evidence or calibration probabilities.
- No inferred hard invalidation from prose/reference levels.
- Ambiguous invalidation operators fail closed as **not triggered**.
- Lifecycle persistence does not synthesize direction, consensus, conviction, or strategy.

## Validation
Focused 66.3.2 thesis lifecycle suite:
- **12 passed / 0 failed**

Combined APEX 65–66 + execution/risk regression suite:
- **106 passed / 0 failed / 1 skipped**
- Skip: `tests/test_apex_65_8_evidence_accumulation.py` Flask-dependent route test because Flask is unavailable in the isolated development runtime.

Python compilation:
- **586 Python files compiled / 0 errors**

End-to-end invalidation validation:
- Pre-invalidation: BULLISH, raw conviction 91.5, thesis ACTIVE, ACTIONABLE.
- Explicit hard invalidation breached: thesis INVALIDATED, actionability false, action NO_TRADE, status THESIS_INVALIDATED.

## Validation limitations
- Flask route execution was not run in the isolated build runtime because Flask is not installed there. Render installs Flask 3.0.3 from `requirements.txt`.
- Production persistence against `/data` will be validated after deployment.
- Live RTH production adapters still require Monday-session validation to confirm all eight primitive engines emit normalized opinions under live data.

## Recommended next step
After deployment, verify thesis persistence and the two new read-only endpoints. During the next RTH session, validate non-abstaining production EngineOpinion adapters and observe at least one thesis transition. Once validated, proceed to derived-evidence consolidation: Failed Break Quality and uncalibrated Trap Evidence using the canonical level registry + HLCE + normalized Acceptance, without creating independent trade signals.
