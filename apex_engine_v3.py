"""APEX 3.1 CLI entrypoint.

Runs exactly one scan. Importing app.py no longer starts the background scanner
unless RUN_SCANNER_ON_IMPORT=true is set for the Render/Gunicorn web service.
"""
from app import STATE, run_scan_once

if __name__ == "__main__":
    run_scan_once(force=True)
    print(STATE.get("last_scan_status"))
