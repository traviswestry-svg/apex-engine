# APEX 22.5 Deployment and Rollback

## Deploy

1. Deploy the complete repository package.
2. Prefer the WSGI entry point `wsgi:app`; legacy `app:app` remains compatible.
3. Configure `TV_WEBHOOK_SECRET` before using `/tv_signal`. The route intentionally returns 503 when no secret is configured.
4. For multi-worker deployments, leave `APEX_SCANNER_LEASE_PATH` at `/tmp/apex_scanner.lock` unless a different process-shared path is required.
5. Set `APEX_PERSISTENT_DISK_PATH` or rely on Render's `RENDER_DISK_PATH` when SQLite stores must survive redeployment.
6. Confirm `/api/pre23-hardening/status` and `/api/pre23-hardening/routes` report PASS or understood warnings.

## Rollback

Redeploy the prior APEX 22.0 complete repository. No schema migration or data rollback is required. Scanner lease files under `/tmp` are process-local and may be deleted safely after the old deployment is stopped.
