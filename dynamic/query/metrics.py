"""Query Metrics — latency tracking, type breakdown, cache performance.

Thread-safe singleton. Records every query execution and provides
percentile latency, type distribution, and cache hit rates.

Usage:
    from dynamic.query.metrics import query_metrics
    query_metrics.record('why', duration_ms=12.3, cached=False)
    stats = query_metrics.snapshot()
"""

from __future__ import annotations
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional


class QueryMetrics:
    """Thread-safe query metrics collector."""

    def __init__(self):
        self._lock = threading.Lock()
        self._latencies: List[float] = []
        self._by_type: Dict[str, List[float]] = defaultdict(list)
        self._cache_hits: int = 0
        self._cache_misses: int = 0
        self._errors: int = 0
        self._total: int = 0
        self._start_time = time.time()

    def record(self, query_type: str, duration_ms: float,
               cached: bool = False, error: bool = False) -> None:
        """Record a query execution."""
        with self._lock:
            self._total += 1
            self._latencies.append(duration_ms)
            self._by_type[query_type].append(duration_ms)
            if cached:
                self._cache_hits += 1
            else:
                self._cache_misses += 1
            if error:
                self._errors += 1

    def snapshot(self) -> dict:
        """Get current metrics snapshot."""
        with self._lock:
            lats = sorted(self._latencies) if self._latencies else []
            return {
                'total_queries': self._total,
                'errors': self._errors,
                'uptime_seconds': round(time.time() - self._start_time, 1),
                'latency': self._percentiles(lats),
                'by_type': {
                    k: {'count': len(v), 'avg_ms': round(sum(v)/len(v), 2) if v else 0}
                    for k, v in sorted(self._by_type.items())
                },
                'cache': {
                    'hits': self._cache_hits,
                    'misses': self._cache_misses,
                    'hit_rate': round(self._cache_hits / max(self._cache_hits + self._cache_misses, 1), 3),
                },
            }

    def reset(self) -> None:
        with self._lock:
            self._latencies.clear()
            self._by_type.clear()
            self._cache_hits = 0
            self._cache_misses = 0
            self._errors = 0
            self._total = 0
            self._start_time = time.time()

    @staticmethod
    def _percentiles(sorted_lats: List[float]) -> dict:
        if not sorted_lats:
            return {'p50': 0, 'p95': 0, 'p99': 0, 'avg': 0, 'min': 0, 'max': 0}
        n = len(sorted_lats)
        return {
            'p50': round(sorted_lats[int(n * 0.5)], 2),
            'p95': round(sorted_lats[min(int(n * 0.95), n-1)], 2),
            'p99': round(sorted_lats[min(int(n * 0.99), n-1)], 2),
            'avg': round(sum(sorted_lats) / n, 2),
            'min': round(sorted_lats[0], 2),
            'max': round(sorted_lats[-1], 2),
            'count': n,
        }


# Singleton
query_metrics = QueryMetrics()
