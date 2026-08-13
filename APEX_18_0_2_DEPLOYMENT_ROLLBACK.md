# APEX 18.0.2 Deployment and Rollback

## Deployment

1. Back up the current Render deployment and database.
2. Replace the repository with the APEX 18.0.2 package or merge the changed files.
3. Deploy through the normal GitHub-to-Render workflow.
4. Confirm application startup and Recommendation Ledger health.
5. Run a controlled settlement test for:
   - one executable live-chain credit recommendation
   - one unpriceable or modeled-only recommendation
6. Confirm the unexecutable event and ledger row both report `NOT_EXECUTABLE`, zero P/L, and preserved requested outcome metadata.
7. Confirm calibration readiness excludes the unexecutable row.

No database migration is required.

## Rollback

Restore the prior versions of:

- `engine/recommendation_ledger.py`
- `tests/test_recommendation_ledger.py`

No schema rollback is required. Events written by 18.0.2 remain valid JSON and are readable by prior builds, although older code will not actively enforce the settlement guard.
