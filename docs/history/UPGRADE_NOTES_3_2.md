# APEX 3.2 Upgrade Notes

Replace the live repo files in `apex-engine` with this package. The current production entry point remains `app.py`.

Recommended order:

1. Confirm `RUN_SCANNER_ON_IMPORT=true` is set in Render.
2. Upload/replace `app.py`, `requirements.txt`, `runtime.txt`, and README files.
3. Keep `render.yaml` only if it matches the existing service setup.
4. Deploy.
5. Verify `/`, `/dashboard.json`, `/api/status`, `/api/run`, and `/health`.
6. After confirming stability, archive or delete old `apex_engine_v1.py`.

Do not create a new Render service unless you intentionally want a separate staging instance.
