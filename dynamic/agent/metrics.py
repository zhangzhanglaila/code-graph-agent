"""Agent Metrics — hypothesis, evidence, and action performance tracking.

Tracks agent reasoning quality: hypothesis count/depth, evidence density,
action success/failure rates.

Usage:
    from dynamic.agent.metrics import agent_metrics
    agent_metrics.record_run(result)
    stats = agent_metrics.snapshot()
"""

from __future__ import annotations
import threading
from collections import defaultdict
from typing import Dict, List


class AgentMetrics:
    """Thread-safe agent performance metrics."""

    def __init__(self):
        self._lock = threading.Lock()
        self._runs: int = 0
        self._hypothesis_counts: List[int] = []
        self._reasoning_depths: List[int] = []
        self._evidence_per_hypothesis: List[float] = []
        self._action_success: int = 0
        self._action_failure: int = 0
        self._action_total: int = 0
        self._run_durations: List[float] = []

    def record_run(self, agent_result: dict) -> None:
        """Record metrics from an AgentEngine.run() result."""
        with self._lock:
            self._runs += 1

            # Reasoning metrics
            reasoning = agent_result.get('reasoning', {})
            steps = reasoning.get('steps', [])
            self._hypothesis_counts.append(len(steps))
            self._reasoning_depths.append(reasoning.get('depth', 0))

            # Evidence density
            for step in steps:
                h = step.get('hypothesis', {})
                support = h.get('support_count', 0)
                contradict = h.get('contradict_count', 0)
                total_evidence = support + contradict
                self._evidence_per_hypothesis.append(total_evidence)

            # Action metrics
            for ar in agent_result.get('action_results', []):
                self._action_total += 1
                if ar.get('success'):
                    self._action_success += 1
                else:
                    self._action_failure += 1

            # Duration
            self._run_durations.append(agent_result.get('duration_ms', 0))

    def snapshot(self) -> dict:
        with self._lock:
            return {
                'total_runs': self._runs,
                'reasoning': {
                    'avg_hypotheses': round(_avg(self._hypothesis_counts), 2),
                    'avg_depth': round(_avg(self._reasoning_depths), 2),
                    'avg_evidence_per_hypothesis': round(_avg(self._evidence_per_hypothesis), 2),
                    'max_depth': max(self._reasoning_depths) if self._reasoning_depths else 0,
                },
                'actions': {
                    'total': self._action_total,
                    'success': self._action_success,
                    'failure': self._action_failure,
                    'success_rate': round(
                        self._action_success / max(self._action_total, 1), 3
                    ),
                },
                'performance': {
                    'avg_duration_ms': round(_avg(self._run_durations), 2),
                    'p95_duration_ms': round(_p95(self._run_durations), 2),
                },
            }

    def reset(self) -> None:
        with self._lock:
            self._runs = 0
            self._hypothesis_counts.clear()
            self._reasoning_depths.clear()
            self._evidence_per_hypothesis.clear()
            self._action_success = 0
            self._action_failure = 0
            self._action_total = 0
            self._run_durations.clear()


def _avg(values: list) -> float:
    return sum(values) / len(values) if values else 0


def _p95(values: list) -> float:
    if not values:
        return 0
    s = sorted(values)
    return s[min(int(len(s) * 0.95), len(s)-1)]


# Singleton
agent_metrics = AgentMetrics()
