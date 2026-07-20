"""Dedicated scanner process for APEX 24.2.1.

Runs beside Gunicorn in the same Render service so both processes share the
mounted /data volume while the web process remains free of import-time jobs.
"""
from __future__ import annotations

import os
import signal
import time

os.environ["RUN_SCANNER_ON_IMPORT"] = "false"

import app as apex_app  # noqa: E402
from engine.operational_runtime import write_scanner_heartbeat  # noqa: E402

_RUNNING = True


def _stop(_signum, _frame):
    global _RUNNING
    _RUNNING = False


def main() -> int:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    apex_app.start_background_scanner()
    while _RUNNING:
        write_scanner_heartbeat({
            "scanner_started": bool(apex_app.SCANNER_STARTED),
            "thread_alive": bool(apex_app.STATE.get("scanner_thread_alive", False)),
            "last_scan_at": apex_app.SCANNER_STATE.get("updated_at"),
            "last_error": apex_app.STATE.get("last_error"),
        })
        time.sleep(max(5, int(os.getenv("APEX_SCANNER_PROCESS_HEARTBEAT_SECONDS", "15"))))
    write_scanner_heartbeat({"scanner_started": False, "stopped": True})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
