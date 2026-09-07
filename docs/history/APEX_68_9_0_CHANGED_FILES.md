# APEX 68.9.0 Changed Files

- `app.py` — registers the 68.9 microstructure calibration surface.
- `engine/market_microstructure_calibration.py` — new integrity, offline calibration, shadow confirmation, and promotion-readiness logic.
- `engine/market_microstructure_store.py` — v2 store schema with explicit outcome ledger and calibration query helpers.
- `engine/market_microstructure_routes.py` — new integrity/calibration/readiness/shadow/outcome endpoints.
- `tests/test_apex_68_9_microstructure_calibration_governance.py` — focused 68.9 regression/governance coverage.
- `APEX_68_9_0_MICROSTRUCTURE_CALIBRATION_PROMOTION_GOVERNANCE.md` — build specification and governance notes.
- `APEX_ENVIRONMENT_VARIABLE_REFERENCE.md` — adds 68.9 promotion-readiness thresholds and non-activating approval flag.
