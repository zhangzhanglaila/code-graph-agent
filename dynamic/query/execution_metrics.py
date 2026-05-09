"""Execution Metrics — pipeline stage timing and endpoint latency.

Tracks PDG build, fact extraction, narrative generation, and
per-endpoint request latency.

Usage:
    from dynamic.query.execution_metrics import execution_metrics
    with execution_metrics.stage('pdg_build'):
        pdg = RuntimePDG.from_timeline(timeline)
    stats = execution_metrics.snapshot()
"""

from __future__ import annotations
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from typing import Dict, List


class ExecutionMetrics:
    """Thread-safe execution pipeline metrics."""

    def __init__(self):
        self._lock = threading.Lock()
        self._stages: Dict[str, List[float]] = defaultdict(list)
        self._endpoints: Dict[str, List[float]] = defaultdict(list)
        self._endpoint_errors: Dict[str, int] = defaultdict(int)

    @contextmanager
    def stage(self, name: str):
        """Context manager to time a pipeline stage."""
        t0 = time.time()
        try:
            yield
        finally:
            elapsed = (time.time() - t0) * 1000
            with self._lock:
                self._stages[name].append(elapsed)

    def record_endpoint(self, path: str, duration_ms: float,
                        error: bool = False) -> None:
        """Record an endpoint request."""
        with self._lock:
            self._endpoints[path].append(duration_ms)
            if error:
                self._endpoint_errors[path] += 1

    def snapshot(self) -> dict:
        with self._lock:
            return {
                'stages': {
                    name: self._summarize(times)
                    for name, times in sorted(self._stages.items())
                },
                'endpoints': {
                    path: {
                        **self._summarize(times),
                        'errors': self._endpoint_errors.get(path, 0),
                    }
                    for path, times in sorted(self._endpoints.items())
                },
            }

    def reset(self) -> None:
        with self._lock:
            self._stages.clear()
            self._endpoints.clear()
            self._endpoint_errors.clear()

    @staticmethod
    def _summarize(times: List[float]) -> dict:
        if not times:
            return {'count': 0, 'avg_ms': 0, 'p50': 0, 'p95': 0, 'total_ms': 0}
        n = len(times)
        s = sorted(times)
        return {
            'count': n,
            'avg_ms': round(sum(s) / n, 2),
            'p50': round(s[int(n * 0.5)], 2),
            'p95': round(s[min(int(n * 0.95), n-1)], 2),
            'total_ms': round(sum(s), 2),
        }


# Singleton
execution_metrics = ExecutionMetrics()
