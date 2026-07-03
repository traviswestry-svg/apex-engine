"""engine/common/cache.py — APEX 8.0 per-engine memory cache.

Thread-safe TTL cache. Each engine gets its own instance.
Usage:
    _cache = EngineCache(ttl_seconds=8.0, name="dealer_positioning")
    hit = _cache.get("SPX")
    if hit is not None:
        return hit
    result = _run_engine(...)
    _cache.set("SPX", result)
    return result
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional


class EngineCache:
    """Thread-safe per-engine TTL cache keyed by ticker."""

    def __init__(self, ttl_seconds: float = 8.0, name: str = "engine"):
        self._lock   = threading.Lock()
        self._store: Dict[str, Dict[str, Any]] = {}
        self._ttl    = ttl_seconds
        self.name    = name
        self.hits    = 0
        self.misses  = 0

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
        if entry is None:
            self.misses += 1
            return None
        if time.monotonic() - entry["ts"] > self._ttl:
            self.misses += 1
            return None
        self.hits += 1
        return entry["data"]

    def set(self, key: str, data: Any) -> None:
        with self._lock:
            self._store[key] = {"data": data, "ts": time.monotonic()}

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    def stats(self) -> Dict[str, Any]:
        return {
            "name":     self.name,
            "hits":     self.hits,
            "misses":   self.misses,
            "hit_rate": round(self.hit_rate, 3),
            "ttl":      self._ttl,
            "entries":  len(self._store),
        }
