"""APEX application version.

Single source of truth: config/apex_release_manifest.json, loaded via
engine.release_manager. APPLICATION_VERSION is *derived* here rather than
restated as a literal, so a release bump in the manifest can never silently
drift from the version string the application reports. Historically this file
carried its own hard-coded string and drifted out of sync with the manifest on
every bump; deriving it removes that failure mode at the source.
"""
from __future__ import annotations

from .release_manager import APPLICATION_VERSION

MORNING_BRIEF_VERSION = APPLICATION_VERSION
VALIDATION_VERSION = APPLICATION_VERSION

__all__ = ["APPLICATION_VERSION", "MORNING_BRIEF_VERSION", "VALIDATION_VERSION"]
