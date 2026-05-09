"""Agent State — accumulated knowledge from observations.

Tracks what the agent has learned: variable histories, branch patterns,
hypotheses, and open questions.

Usage:
    state = AgentState()
    for obs in stream:
        state.update(obs)
    history = state.get_variable_history('x')
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from collections import defaultdict

from .observation import Observation, ObservationStream


@dataclass
class VariableRecord:
    """Tracks a variable's evolution through observations."""
    name: str
    values: List[Dict[str, Any]] = field(default_factory=list)  # [{step, value, version}]
    first_seen_step: int = -1
    last_seen_step: int = -1
    mutation_count: int = 0
    rebind_count: int = 0

    def add(self, step_id: int, value: Any, version: int = 0) -> None:
        self.values.append({
            'step': step_id,
            'value': str(value) if not isinstance(value, str) else value,
            'version': version,
        })
        if self.first_seen_step < 0:
            self.first_seen_step = step_id
        self.last_seen_step = step_id

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'values': self.values,
            'first_seen': self.first_seen_step,
            'last_seen': self.last_seen_step,
            'mutations': self.mutation_count,
            'rebinds': self.rebind_count,
        }


class AgentState:
    """Accumulated knowledge from observations.

    Maintains:
    - Variable evolution histories
    - Branch pattern tracking
    - Observation count and step coverage
    - Open questions for reasoning
    """

    def __init__(self):
        self._variables: Dict[str, VariableRecord] = {}
        self._branches: List[Dict[str, Any]] = []
        self._mutations: List[Dict[str, Any]] = []
        self._calls: List[Dict[str, Any]] = []
        self._observation_count: int = 0
        self._step_range: tuple = (-1, -1)
        self._open_questions: List[str] = []
        self._functions_seen: Set[str] = set()

    def update(self, obs: Observation) -> None:
        """Incorporate a single observation into state."""
        self._observation_count += 1

        # Update step range
        if self._step_range[0] < 0:
            self._step_range = (obs.step_id, obs.step_id)
        else:
            self._step_range = (min(self._step_range[0], obs.step_id),
                                max(self._step_range[1], obs.step_id))

        self._functions_seen.add(obs.function)

        # Track variable changes
        for var_name, snapshot in obs.variables_changed.items():
            if var_name not in self._variables:
                self._variables[var_name] = VariableRecord(name=var_name)
            record = self._variables[var_name]
            value = snapshot.value_repr if hasattr(snapshot, 'value_repr') else str(snapshot)
            version = obs.ssa_versions.get(var_name, 0)
            record.add(obs.step_id, value, version)

        for var_name in obs.variables_new:
            if var_name not in self._variables:
                self._variables[var_name] = VariableRecord(name=var_name)
            record = self._variables[var_name]
            if not record.values:
                snapshot = obs.variables_changed.get(var_name)
                value = snapshot.value_repr if snapshot and hasattr(snapshot, 'value_repr') else '?'
                record.add(obs.step_id, value, 0)

        # Track mutations
        if obs.mutation:
            if obs.mutation in self._variables:
                self._variables[obs.mutation].mutation_count += 1
            self._mutations.append({
                'step': obs.step_id,
                'var': obs.mutation,
                'line': obs.line_no,
            })

        # Track branches
        if obs.branch_taken:
            self._branches.append({
                'step': obs.step_id,
                'type': obs.branch_taken,
                'code': obs.code.strip(),
                'line': obs.line_no,
            })

        # Track calls
        if obs.call_entered:
            self._calls.append({
                'step': obs.step_id,
                'function': obs.call_entered,
                'type': 'enter',
            })
        if obs.call_returned:
            self._calls.append({
                'step': obs.step_id,
                'function': obs.call_returned,
                'type': 'return',
            })

    def update_from_stream(self, stream: ObservationStream) -> None:
        """Incorporate all observations from a stream."""
        for obs in stream:
            self.update(obs)

    def merge(self, other: 'AgentState') -> 'AgentState':
        """Merge another state into this one. Returns self for chaining."""
        for name, record in other._variables.items():
            if name not in self._variables:
                self._variables[name] = record
            else:
                existing = self._variables[name]
                for v in record.values:
                    if v['step'] > existing.last_seen_step:
                        existing.add(v['step'], v['value'], v['version'])
                existing.mutation_count += record.mutation_count
                existing.rebind_count += record.rebind_count

        self._branches.extend(other._branches)
        self._mutations.extend(other._mutations)
        self._calls.extend(other._calls)
        self._observation_count += other._observation_count
        self._open_questions.extend(other._open_questions)
        self._functions_seen.update(other._functions_seen)

        if other._step_range[0] >= 0:
            if self._step_range[0] < 0:
                self._step_range = other._step_range
            else:
                self._step_range = (
                    min(self._step_range[0], other._step_range[0]),
                    max(self._step_range[1], other._step_range[1]),
                )
        return self

    # ── Queries ──────────────────────────────────────────────────

    def get_variable_history(self, var_name: str) -> Optional[VariableRecord]:
        return self._variables.get(var_name)

    def get_all_variables(self) -> Dict[str, VariableRecord]:
        return dict(self._variables)

    def get_branches(self) -> List[Dict[str, Any]]:
        return list(self._branches)

    def get_mutations(self) -> List[Dict[str, Any]]:
        return list(self._mutations)

    def get_calls(self) -> List[Dict[str, Any]]:
        return list(self._calls)

    @property
    def observation_count(self) -> int:
        return self._observation_count

    @property
    def step_range(self) -> tuple:
        return self._step_range

    @property
    def functions_seen(self) -> Set[str]:
        return self._functions_seen

    def add_question(self, question: str) -> None:
        self._open_questions.append(question)

    def get_questions(self) -> List[str]:
        return list(self._open_questions)

    def to_dict(self) -> dict:
        return {
            'observation_count': self._observation_count,
            'step_range': list(self._step_range),
            'variables': {k: v.to_dict() for k, v in self._variables.items()},
            'branch_count': len(self._branches),
            'mutation_count': len(self._mutations),
            'call_count': len(self._calls),
            'functions': sorted(self._functions_seen),
            'open_questions': self._open_questions,
        }


class KnowledgeBase:
    """Persistent knowledge store across multiple agent runs.

    Unlike AgentState which is per-execution, KnowledgeBase accumulates
    knowledge across executions (patterns, common bugs, etc.).
    """

    def __init__(self):
        self._patterns: List[Dict[str, Any]] = []
        self._known_bugs: List[Dict[str, Any]] = []
        self._execution_count: int = 0

    def record_execution(self, state: AgentState) -> None:
        """Learn from a completed execution."""
        self._execution_count += 1

        # Extract patterns from variable histories
        for name, record in state.get_all_variables().items():
            if record.mutation_count > 3:
                self._patterns.append({
                    'type': 'heavy_mutation',
                    'variable': name,
                    'count': record.mutation_count,
                    'executions': self._execution_count,
                })

    def get_patterns(self) -> List[Dict[str, Any]]:
        return list(self._patterns)

    def to_dict(self) -> dict:
        return {
            'execution_count': self._execution_count,
            'patterns': self._patterns,
            'known_bugs': self._known_bugs,
        }
