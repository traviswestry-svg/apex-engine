# APEX 69.8.1 — Changed Files Only

Baseline: APEX 69.8.0
Build: Premium Discipline Trade Visualization & Learning Readiness Command Center

## Changed / Added Files

- `app.py` — release/fallback observatory version truth updated to 69.8.1.
- `config/apex_capability_registry.yaml` — 69.8.1 registry truth, trade-view/readiness routes, visualization guardrails.
- `config/apex_release_manifest.json` — 69.8.1 release identity and non-authoritative visualization guardrails.
- `engine/application_composition.py` — application composition release version 69.8.1.
- `engine/trigger_observatory.py` — read-only trade visualization contract, premium truth projection, learning-readiness surface.
- `engine/trigger_observatory_routes.py` — adds `/api/triggers/trade-view` and `/api/triggers/learning-readiness`.
- `templates/premium_discipline_command_center.html` — visual trade path, recent trigger selector, targets/stop/MFE/MAE, premium evidence, effectiveness and learning readiness.
- `tests/test_apex_69_8_0_evidence_integrity_outcome_linkage.py` — preserves 69.8.0 guardrail regression under newer release metadata.
- `tests/test_apex_69_8_1_trade_visualization_dashboard.py` — 69.8.1 behavioral/read-only regression coverage.
- `APEX_69_8_1_PREMIUM_DISCIPLINE_TRADE_VISUALIZATION_LEARNING_READINESS.md` — build notes.
- `APEX_69_8_1_CHANGED_FILES.md` — this changed-files manifest.

## Validation

- Python compilation: PASS for changed Python runtime files.
- Browser JavaScript syntax (`node --check`): PASS.
- Focused non-Flask regression set: 23 passed.
- Consolidation/dead-module guard: PASS.
- Flask-dependent route-registration tests: ENVIRONMENT-BLOCKED because Flask is not installed in the audit container; repository dependency declaration remains unchanged.

## Authority

No new decision authority, execution authority, broker mutation, automatic calibration promotion, Tick Momentum promotion, or Microstructure promotion is introduced by 69.8.1.
