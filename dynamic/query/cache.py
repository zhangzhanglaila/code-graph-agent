"""Query Result Cache — deterministic, hash-keyed result memoization.

Because Query AST is frozen + hashable + deterministic:
    cache[q.query_hash()] = result

Cache is scoped per QueryExecutor instance (tied to a specific pdg/facts/engine).
New analysis → new executor → new cache. No stale-data risk.

Usage:
    cache = QueryResultCache(max_size=128, ttl_seconds=600)
    cached = cache.get(query)
    if cached is None:
        result = execute(query)
        cache.put(query, result)
"""

from __future__ import annotations
import copy
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class CacheEntry:
    """A single cached query result."""
    result: dict
    created_at: float
    hit_count: int = 0

    def is_expired(self, ttl: float) -> bool:
        return time.time() - self.created_at > ttl


class QueryResultCache:
    """LRU-like cache keyed by query.query_hash().

    Properties:
        - Deterministic: same semantic query → same hash → same cache key
        - Scoped: per-executor, dies when pdg/facts change
        - TTL: entries expire after configurable seconds
        - Bounded: evicts oldest entries when max_size reached
    """

    def __init__(self, max_size: int = 128, ttl_seconds: float = 600):
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._entries: Dict[str, CacheEntry] = {}
        self._hits = 0
        self._misses = 0

    def get(self, query) -> Optional[dict]:
        """Look up a cached result. Returns None on miss or expiry.
        Returns a deep copy to prevent mutation of cached data."""
        key = query.query_hash()
        entry = self._entries.get(key)
        if entry is None:
            self._misses += 1
            return None
        if entry.is_expired(self._ttl):
            del self._entries[key]
            self._misses += 1
            return None
        entry.hit_count += 1
        self._hits += 1
        return copy.deepcopy(entry.result)

    def put(self, query, result: dict) -> None:
        """Store a query result. Evicts oldest if at capacity."""
        key = query.query_hash()
        if len(self._entries) >= self._max_size and key not in self._entries:
            self._evict_oldest()
        self._entries[key] = CacheEntry(
            result=result,
            created_at=time.time(),
        )

    def invalidate(self, query) -> bool:
        """Remove a specific query from cache. Returns True if found."""
        key = query.query_hash()
        if key in self._entries:
            del self._entries[key]
            return True
        return False

    def clear(self) -> None:
        """Clear all cached entries."""
        self._entries.clear()
        self._hits = 0
        self._misses = 0

    @property
    def size(self) -> int:
        return len(self._entries)

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    def stats(self) -> dict:
        return {
            'size': self.size,
            'max_size': self._max_size,
            'hits': self._hits,
            'misses': self._misses,
            'hit_rate': round(self.hit_rate, 3),
            'ttl_seconds': self._ttl,
        }

    def _evict_oldest(self) -> None:
        """Remove the oldest entry (by creation time)."""
        if not self._entries:
            return
        oldest_key = min(self._entries, key=lambda k: self._entries[k].created_at)
        del self._entries[oldest_key]
