# APEX 10.0.2 — Release Manager

## Added

- `GET /api/system/version`
- `GET /api/system/build`
- `GET /api/system/features`
- `GET /api/system/migrations`
- `GET /api/system/release`
- Environment-aware build and Git commit reporting.
- Explicit feature manifest and database-schema readiness.
- Read-only release metadata guardrails.
- Regression tests for release metadata and route registration.

## Deployment variables

Optional variables improve traceability:

```text
APEX_BUILD_ID=<deployment identifier>
APEX_GIT_COMMIT=<full commit SHA>
APEX_DEPLOYED_AT=<ISO-8601 timestamp>
APEX_ENVIRONMENT=production
APEX_DATABASE_SCHEMA_VERSION=5
```

Render may provide `RENDER_GIT_COMMIT`; APEX uses it automatically when present.

## Validation

After deployment, call `/api/system/release`. Confirm:

- `application_version` is `10.0.2_RELEASE_MANAGER`.
- `commit` matches the deployed Git commit.
- `pending_migrations` is empty.
- `Release Manager` appears in `features`.
