# APEX 69.7.0 + 69.7.1 combined changed files

This combined overlay contains only files added or changed by the Failed
Breakdown Lifecycle foundation and Universal Trade Trigger Observatory builds.

- `app.py`
- `engine/application_composition.py`
- `engine/failed_breakdown_lifecycle.py`
- `engine/failed_breakdown_lifecycle_routes.py`
- `engine/trigger_observatory.py`
- `engine/trigger_observatory_routes.py`
- `config/apex_release_manifest.json`
- `config/apex_capability_registry.yaml`
- `tests/test_apex_69_7_0_failed_breakdown_lifecycle.py`
- `tests/test_apex_69_7_1_universal_trigger_observatory.py`
- `tests/test_apex_69_6_1_tick_momentum_diagnostic_freshness_closure.py`
- `tests/test_apex_69_6_2_tick_momentum_diagnostic_probe_import_fix.py`
- `APEX_69_7_0_FAILED_BREAKDOWN_LIFECYCLE_INTELLIGENCE_FOUNDATION.md`
- `APEX_69_7_1_UNIVERSAL_TRADE_TRIGGER_OBSERVATION_MANUAL_ETRADE_HANDOFF.md`
- `APEX_69_7_0_69_7_1_COMBINED_CHANGED_FILES.md`

`engine.application_composition` now explicitly imports the trigger observatory
module pair. The live `app.py` composition remains the single route-registration
owner, avoiding duplicate Flask endpoints while satisfying runtime reachability.
