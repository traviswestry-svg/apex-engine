# APEX 18.0.6 Validation Report

## Static validation

- Python compilation completed successfully for the new and modified runtime modules.

## Regression validation

Command:

`PYTHONPATH=. pytest -q`

Result:

**935 tests passed**

## Focused validation

The focused Premium Discipline and Trade Refusal Replay suite passed all 14 tests, including:

- profitable refused structure classified as `MISSED_WIN`;
- short-strike touch classified as `AVOIDED_STOP` even when price later recovers;
- missing executable credit classified as `NOT_EXECUTABLE`;
- replay persistence and idempotency;
- replay scorecard aggregation;
- API route registration and run behavior.
