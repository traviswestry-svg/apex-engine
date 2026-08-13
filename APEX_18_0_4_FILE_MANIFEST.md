# APEX 18.0.4 File Manifest

## Modified files

- `app.py` — configuration governance import, route registration, and startup validation.
- `engine/release_manager.py` — authoritative runtime and semantic version update plus feature identity.
- `templates/apex_os.html` — compact Mission Control Configuration Health panel and safe diagnostics polling.

## New code and tests

- `engine/configuration_governance.py` — centralized registry, validation, redaction, status, categories, deployment identity, and execution safety.
- `engine/configuration_governance_routes.py` — four read-only Flask endpoints.
- `tests/test_configuration_governance.py` — configuration, safety, redaction, compatibility, route, health, and Mission Control tests.

## Release documentation

- `APEX_18_0_4_IMPLEMENTATION_REPORT.md`
- `APEX_18_0_4_VALIDATION_REPORT.md`
- `APEX_18_0_4_DEPLOYMENT_ROLLBACK.md`
- `APEX_18_0_4_FILE_MANIFEST.md`
- `APEX_ENVIRONMENT_VARIABLE_REFERENCE.md`

## Database changes

None.
