"""engine/logging.py — structured-light logger and timer helpers."""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator

apex_logger = logging.getLogger("apex.engine")
if not apex_logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    apex_logger.addHandler(handler)
apex_logger.setLevel(logging.INFO)


class EngineTimer:
    def __init__(self, name: str):
        self.name = name
        self.elapsed_ms = 0.0
        self._start = 0.0

    def __enter__(self) -> "EngineTimer":
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.elapsed_ms = round((time.monotonic() - self._start) * 1000.0, 1)
        if exc:
            apex_logger.warning("%s failed in %.1fms: %s", self.name, self.elapsed_ms, exc)
        else:
            apex_logger.debug("%s completed in %.1fms", self.name, self.elapsed_ms)


@contextmanager
def engine_timer(name: str) -> Iterator[EngineTimer]:
    timer = EngineTimer(name)
    with timer:
        yield timer
