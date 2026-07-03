"""engine/cache.py — tiny in-memory TTL cache for engine outputs."""
from __future__ import annotations

import time
import threading
from typing import Any, Dict, Optional, Tuple


class EngineCache:
    def __init__(self, default_ttl: float = 10.0):
        self.default_ttl = default_ttl
        self._data: Dict[str, Tuple[float, float, Any]] = {}
        self._lock = threading.RLock()

    def get(self, key: str, default: Any = None) -> Any:
        now = time.monotonic()
        with self._lock:
            item = self._data.get(key)
            if not item:
                return default
            created, ttl, value = item
            if ttl >= 0 and now - created > ttl:
                self._data.pop(key, None)
                return default
            return value

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> Any:
        with self._lock:
            self._data[key] = (time.monotonic(), self.default_ttl if ttl is None else ttl, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
