APEX DEPLOYMENT HOTFIX

Changed file:
- app.py

What it fixes:
- Prevents missing optional APEX 25.5 and 26.1-26.5 route modules from aborting Gunicorn startup.
- Existing included modules continue to register normally.

Render database repair (required separately):
The persistent file /data/apex_tracking.db is not a valid SQLite database.
Before redeploying, use Render Shell and run:

  mv /data/apex_tracking.db /data/apex_tracking.db.corrupt-20260720

Then redeploy. APEX will create a new SQLite database at the configured DB_PATH.
Do not run this command if preserving the corrupted file under a different backup name is required.
