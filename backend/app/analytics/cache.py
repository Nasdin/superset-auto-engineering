"""Bounded process-local read cache; PostgreSQL remains the source of truth.

Keys must include the durable repository revision and every cohort filter.
Only completed results enter the cache; failures never replace good data. The
caller bounds expensive misses separately, so cache hits remain available while
another analysis is running. Superset uses its shared Redis chart cache instead.
"""

import copy
import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable


class AnalyticsResultCache:
    def __init__(
        self,
        *,
        ttl: float = 60,
        max_entries: int = 32,
        max_bytes: int = 8 * 1024 * 1024,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.ttl = ttl
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.clock = clock
        self._entries: OrderedDict[Hashable, tuple[float, int, dict]] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()

    def get(self, key: Hashable) -> dict | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires, size, value = entry
            if expires <= self.clock():
                del self._entries[key]
                self._bytes -= size
                return None
            self._entries.move_to_end(key)
            return copy.deepcopy(value)

    def put(self, key: Hashable, value: dict) -> None:
        # Include a byte budget as well as entry count; large filter results must
        # not fill a small VM. Serialization also rejects non-JSON cache values.
        size = len(json.dumps(value, separators=(",", ":")).encode())
        if size > self.max_bytes or self.max_entries <= 0 or self.ttl <= 0:
            return
        with self._lock:
            existing = self._entries.pop(key, None)
            if existing:
                self._bytes -= existing[1]
            self._entries[key] = (self.clock() + self.ttl, size, copy.deepcopy(value))
            self._bytes += size
            while len(self._entries) > self.max_entries or self._bytes > self.max_bytes:
                _, (_, evicted_size, _) = self._entries.popitem(last=False)
                self._bytes -= evicted_size
