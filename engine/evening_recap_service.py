"""APEX 69.3.3 — import-safe Evening Recap service boundary.

Routes import this lightweight module instead of importing the archive/generation
module directly.  The implementation module is resolved only when a service
function is invoked, after application module initialization has completed.
"""
from __future__ import annotations

import importlib
from typing import Any

VERSION = "69.10.36.1"


def _impl():
    return importlib.import_module("engine.evening_recap")


def save_morning_snapshot(payload: dict, ticker: str = "SPX"):
    """Persist a Morning Brief through the import-safe recap boundary."""
    return _impl().save_morning_snapshot(payload, ticker=ticker)


def morning_history(limit: Any = 60):
    """Read Morning Brief archive history through the import-safe boundary."""
    return _impl().morning_history(limit)


def get_morning_snapshot(session_date: str):
    return _impl().get_morning_snapshot(session_date)


def morning_archive_status(session_date: str):
    return _impl().morning_archive_status(session_date)


def generate_evening_recap(**kwargs: Any):
    return _impl().generate_evening_recap(**kwargs)


def recap_history(limit: Any = 30):
    return _impl().recap_history(limit)
