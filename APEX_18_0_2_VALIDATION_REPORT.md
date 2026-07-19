# APEX 18.0.2 Validation Report

## Automated tests

- Recommendation Ledger suite: **10 passed**
- Complete repository regression suite: **905 passed**
- Failures: **0**

## New coverage

1. Unexecutable settlement attempts are forced to `NOT_EXECUTABLE` with zero P/L.
2. Executable live-chain credit recommendations preserve submitted outcomes.
3. Uppercase `LIVE_CHAIN_EXECUTABLE` is recognized.
4. `NOT_EXECUTABLE` rows do not increase gradeable calibration history.
5. Immutable event payload and ledger row store the same governed outcome.
6. Attempted caller outcome and P/L remain present as audit metadata.
7. Missing pricing basis fails closed.
8. Missing, zero, or negative entry credit fails closed.

## Environment note
Flask was installed in the clean validation environment because the full suite imports Flask application and route modules during collection.
