"""Stable production WSGI entry point for APEX 22.5+.

APEX 65.7.3 adds a deployment fail-safe: if Render/Gunicorn is started directly
instead of through ``start_render.sh``, WSGI supervises a *separate*
``scanner_worker.py`` process.  The web process never owns the scanner loop or
HLCE collector.
"""
from engine.application_composition import create_app
from engine.scanner_process_supervisor import ensure_scanner_process

app = create_app()
app.config["APEX_SCANNER_SUPERVISOR"] = ensure_scanner_process()
