APEX Dashboard Loading Fix

Replace these repository files:
1. app.py
2. static/js/apex_os.js

Why:
- The old ThreadPoolExecutor context manager waited for all provider calls even after the intended timeout.
- That blocked Render's limited gunicorn threads and caused the dashboard API requests to remain pending/canceled.
- The corrected code uses one shared provider timeout and shuts the pool down without waiting for stalled calls.
- The browser timeout is increased from 6 to 12 seconds to allow the bounded compose to finish without an unnecessary abort.

After pushing to GitHub:
- In Render choose Manual Deploy > Clear build cache & deploy.
- Hard refresh the dashboard after deployment.
