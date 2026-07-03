"""engine/common/logging.py — APEX 8.0 structured engine logging.

Every engine uses engine_timer() context manager to capture:
  - execution_ms
  - success / failure
  - engine name and version

JSON-structured logging to stdout (Render captures it).

Usage:
    with engine_timer("dealer_positioning") as t:
        result = _run_engine(...)
        t.mark_success(len(result))
"""
from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from typing import Any, Dict, Generator, Optional


# Configure once at import — subsequent calls are no-ops
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    force=False,
)
apex_logger = logging.getLogger("apex.engine")


class EngineTimer:
    def __init__(self, name: str):
        self.name       = name
        self.start_ts   = time.monotonic()
        self.elapsed_ms = 0.0
        self.success    = False
        self.error:     Optional[str] = None
        self.output_size: int = 0

    def mark_success(self, output_size: int = 0) -> None:
        self.success     = True
        self.output_size = output_size
        self.elapsed_ms  = round((time.monotonic() - self.start_ts) * 1000, 1)

    def mark_failure(self, error: str) -> None:
        self.success    = False
        self.error      = error
        self.elapsed_ms = round((time.monotonic() - self.start_ts) * 1000, 1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "engine":       self.name,
            "execution_ms": self.elapsed_ms,
            "success":      self.success,
            "error":        self.error,
            "output_size":  self.output_size,
        }

    def log(self) -> None:
        level = logging.DEBUG if self.success else logging.WARNING
        apex_logger.log(level, json.dumps(self.to_dict()))


@contextmanager
def engine_timer(name: str) -> Generator[EngineTimer, None, None]:
    """Context manager that times an engine and logs the result."""
    t = EngineTimer(name)
    try:
        yield t
        if not t.success:  # caller forgot to call mark_success
            t.mark_success()
    except Exception as exc:
        t.mark_failure(str(exc))
        raise
    finally:
        t.log()
