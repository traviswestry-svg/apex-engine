"""Stable production WSGI entry point for APEX 22.5+."""
from engine.application_composition import create_app

app = create_app()
