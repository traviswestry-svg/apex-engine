"""Stable production WSGI entry point for APEX 22.5+.

APEX 65.7.4 hardens scanner bootstrap for real Gunicorn lifecycles.  Import-time
startup is retained as a fast path, but every HTTP request also executes an
idempotent scanner-ensure hook.  This guarantees bootstrap even when Gunicorn
preload/fork semantics prevent an import-time watchdog thread from surviving.

The web process never runs the scanner loop or HLCE collector itself; it only
supervises a separate ``scanner_worker.py`` process.
"""
from engine.application_composition import create_app
from engine.scanner_process_supervisor import ensure_scanner_process

app = create_app()


def _ensure_scanner_after_worker_init() -> None:
    """Idempotently ensure the scanner exists in the *serving* worker process."""
    try:
        app.config["APEX_SCANNER_SUPERVISOR"] = ensure_scanner_process()
    except Exception as exc:  # fail web-open, but surface diagnostics
        app.config["APEX_SCANNER_SUPERVISOR_ERROR"] = f"{type(exc).__name__}: {exc}"


# Fast path for normal non-preloaded Gunicorn workers.
_ensure_scanner_after_worker_init()

# Guaranteed serving-worker path.  If Gunicorn imported WSGI in a master/preload
# phase, this hook runs after fork on the first request and starts the watchdog
# in the actual worker.  Calls are cheap/idempotent after the scanner exists.
@app.before_request
def _apex_6574_scanner_lifecycle_guard():
    _ensure_scanner_after_worker_init()
