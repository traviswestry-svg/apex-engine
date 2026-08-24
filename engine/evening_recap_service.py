"""APEX 69.3.3 — import-safe Evening Recap service boundary.

Routes import this lightweight module instead of importing the archive/generation
module directly.  The implementation module is resolved only when a service
function is invoked, after application module initialization has completed.
"""
from __future__ import annotations

import importlib
from typing import Any

VERSION = "69.3.3"


def _impl():
    return importlib.import_module("engine.evening_recap")


def get_morning_snapshot(session_date: str):
    return _impl().get_morning_snapshot(session_date)


def morning_archive_status(session_date: str):
    return _impl().morning_archive_status(session_date)


def generate_evening_recap(**kwargs: Any):
    return _impl().generate_evening_recap(**kwargs)


def recap_history(limit: Any = 30):
    return _impl().recap_history(limit)
