# APEX 9 — Step 1: Remove the orphaned director fork

**Status:** complete. Full suite **221 passed / 0 failed** (was 210 passed / 2 failed).

---

## The deletion was not safe as-issued — and that mattered

The approved instruction was *"delete the orphaned fork if confirmed safe."*
Verification proved it was **not** safe: the fork was not stale duplicate code.
It contained an **unmerged bug fix** for a live defect, and deleting it as-is
would have discarded that fix permanently and left a real bug in production.

`engine/persistence.py` carried this, absent from the canonical director:

> POSITION TRUTH OVERRIDES DEBOUNCE: if a position is live but the
> previously-emitted directive is a flat/entry directive, we must NOT debounce —
> anti-churn cannot be allowed to keep emitting ENTER while the trader is already
> holding.

That is precisely the failure of the other long-standing broken test,
`test_manual_position_confirmation_switches_to_management`, which asserted:

    d_in = get_director().build(_ctx(position=_call_pos()))
    assert d_in.position_state.startswith(("HOLD", "IN_", "SCALE", "PROTECT"))
    # AssertionError: 'ENTER_CALL'.startswith(...) is False

**The live bug:** `_MIN_DIRECTIVE_S` defaults to 8s. If a position goes live
within 8s of an `ENTER_*` being emitted, the anti-churn debounce holds the stale
`ENTER_CALL` instead of switching to management — the director tells you to enter
a position you are already holding. The window is short but lands exactly when a
trader is watching the screen: immediately after entry.

So Step 1 became **merge, verify, then delete** — which satisfies the goal
(fork gone, guard green) without destroying value.

---

## 1. Dependency verification (pre-deletion)

| Check | Result |
|---|---|
| Static imports (`from engine.contracts import`, `from engine import contracts`, `import engine.contracts`, + persistence variants) | **0 hits** |
| Relative imports binding the orphan (`from .contracts import` inside `engine/*.py`) | **1** — `engine/persistence.py` → `engine/contracts.py` (both deleted together; a closed island) |
| Relative imports inside `engine/director/*.py` | 11 files → resolve to the **canonical** `director/` versions, untouched |
| Other subpackages (`options/`, `execution/`, `brokers/`) | none |
| Dynamic imports (`importlib`, `__import__`, `exec`, `eval`) | only `__import__("sqlite3")` and `importlib.reload(engine.director.persistence)` — the **canonical** module |
| Module-name string literals | all `"contracts"` hits are option-chain **dict keys**, not module paths |
| Deployment / config (`Procfile`, `render.yaml`, `Dockerfile`, `requirements*.txt`, shell) | none |
| Non-`.py` references | only the Phase 0 audit doc (documentation) |
| **Serialized objects** (pickle/shelve/dill/joblib/marshal) | **none anywhere in the repo** → no serialized class path can reference these modules |
| Canonical replacements exist in `engine/director/` | confirmed — every live consumer imports them |

## 2. Content reconciliation

| File | Orphan | Canonical | Unique to orphan |
|---|---|---|---|
| `contracts.py` | 306 lines | 296 | `ENTRY_DIRECTIVES` (10 lines) |
| `persistence.py` | 249 lines | 234 | `ENTRY_DIRECTIVES` import + `stale_entry_while_holding` bypass + note line |

The orphan was **newer**, not older — a fork that received a fix the live code
never got. Post-merge symbol check: canonical is a proven **superset** (16/16 and
13/13 symbols; zero missing).

## 3. Merge (verbatim, no rewrites)

- `engine/director/contracts.py` — added `ENTRY_DIRECTIVES` frozenset.
- `engine/director/persistence.py` — imports `ENTRY_DIRECTIVES`, adds the
  `stale_entry_while_holding` debounce bypass and its note line.

No director classes were renamed or relocated, per instruction.

**Result:** `test_manual_position_confirmation_switches_to_management` → **passes**;
full director suite 30/30.

## 4. Deletion

Deleted `engine/contracts.py`, `engine/persistence.py`
(backups: `/tmp/orphan_contracts.py.bak`, `/tmp/orphan_persistence.py.bak`).

## 5. Architecture guard (strengthened)

The existing guard was **filename**-based — a re-fork under any other name would
slip past it. Added to `tests/test_architecture_canonical_imports.py`:

- `test_director_core_type_defined_once_in_canonical_location` — parametrized
  over the 7 core types (`Directive`, `DirectorContext`, `HoldLevel`,
  `PositionView`, `ConflictReport`, `FlowAcceleration`, `DirectivePersistence`).
  Scans every `.py` in the repo and fails if a type is defined more than once or
  outside its canonical owner. **Ownership is asserted on the types, not the filenames.**
- `test_orphaned_director_fork_stays_deleted` — the two paths must not return.
- `test_entry_directives_live_in_canonical_contracts` — the merged fix must stay
  wired (fails if `persistence.py` stops importing `ENTRY_DIRECTIVES`).

## 6. Post-deletion verification

| Check | Result |
|---|---|
| Stale imports (4 patterns) | **0 hits** |
| Import validation | **72/72** engine modules import OK |
| `app.py` boot | OK — **93 routes** register |
| Architecture guard | **26/26 pass** |
| **Full suite** | **221 passed / 0 failed** |

Suite math: 212 (210 pass + 2 fail) + 9 new guard tests = 221, with both failures
converted to passes.

---

## Files

**Deleted:** `engine/contracts.py`, `engine/persistence.py`
**Modified:** `engine/director/contracts.py`, `engine/director/persistence.py`,
`tests/test_architecture_canonical_imports.py`
**Added:** `APEX_9_STEP_1_CHANGELOG.md`

**Migrations:** none (no schema change).
**Feature flags:** none (dead-code removal + bug fix).

## Rollback

    cp /tmp/orphan_contracts.py.bak    engine/contracts.py
    cp /tmp/orphan_persistence.py.bak  engine/persistence.py

…and revert the two `engine/director/` files plus the guard test. Note that
rolling back restores the **failing** director test and the ENTER-over-live-position
bug; the merge is independently valuable and should be kept even if the deletion
is reverted.

## Known limitations

- The 8-second debounce window is unchanged; only the position-truth bypass was
  added. Whether `DIRECTOR_MIN_DIRECTIVE_S=8` is the right value is a separate
  question, untouched here.
- Two `tests/test_decision_intelligence.py` tests remain **date-dependent** (they
  call the live event calendar and fail on high-impact event days — see
  `APEX_7_6_1_CHANGELOG.md`). They pass today because the calendar reads CLEAR.
  The suite is green *today*; on the next CPI day those two will fail again. Fix
  is a one-line `events={}` fixture — not done here to keep Step 1 scoped.

## Next dependency

**Step 2 — Flow Classifier.** No blockers from Step 1. The classifier lands as a
read-only bus consumer following the `premium_strategy` pattern
(`engine/flow_classifier.py` + `engine/flow_routes.py`, non-fatal import guard,
`register_*_routes`). Nothing in Step 1 constrains it.
