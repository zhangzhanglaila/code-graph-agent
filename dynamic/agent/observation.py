"""Observation Layer — semantic observations from execution timeline.

Converts raw ExecutionStep events into semantic Observation objects
that the agent can reason about.

Usage:
    stream = ObservationStream.from_timeline(timeline)
    changed = stream.filter(lambda o: o.variables_changed)
    groups = stream.group_by_variable('x')
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set


@dataclass
class Observation:
    """A single semantic observation from execution.

    One step may produce multiple observations (e.g., variable change + branch taken).
    """
    step_id: int
    line_no: int
    function: str
    code: str
    variables_changed: Dict[str, Any] = field(default_factory=dict)
    variables_new: List[str] = field(default_factory=list)
    variables_removed: List[str] = field(default_factory=list)
    branch_taken: Optional[str] = None       # 'if_true' | 'if_false' | 'elif' | 'else' | None
    loop_iteration: Optional[int] = None     # iteration count if inside loop
    call_entered: Optional[str] = None       # function name if call entered
    call_returned: Optional[str] = None      # function name if call returned
    mutation: Optional[str] = None           # var name if in-place mutation
    alias_formed: Optional[List[str]] = None # vars now aliased
    depth: int = 0
    block_id: int = 0
    ssa_versions: Dict[str, int] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            'step_id': self.step_id,
            'line_no': self.line_no,
            'function': self.function,
            'code': self.code.strip(),
        }
        if self.variables_changed:
            d['variables_changed'] = {
                k: {'value': v.value_repr, 'type': v.value_type}
                if hasattr(v, 'value_repr') else {'value': str(v)}
                for k, v in self.variables_changed.items()
            }
        if self.variables_new:
            d['variables_new'] = self.variables_new
        if self.variables_removed:
            d['variables_removed'] = self.variables_removed
        if self.branch_taken:
            d['branch_taken'] = self.branch_taken
        if self.loop_iteration is not None:
            d['loop_iteration'] = self.loop_iteration
        if self.call_entered:
            d['call_entered'] = self.call_entered
        if self.call_returned:
            d['call_returned'] = self.call_returned
        if self.mutation:
            d['mutation'] = self.mutation
        if self.alias_formed:
            d['alias_formed'] = self.alias_formed
        if self.depth:
            d['depth'] = self.depth
        if self.ssa_versions:
            d['ssa_versions'] = self.ssa_versions
        return d

    @staticmethod
    def from_timeline_event(step) -> List['Observation']:
        """Create Observations from an ExecutionStep.

        A single ExecutionStep may produce multiple Observations:
        - One for variable changes
        - One for branch decisions
        - One for call events
        """
        observations = []

        # Variable change observation
        if step.changed_vars or step.new_vars or step.removed_vars:
            changed = {v: step.variables[v] for v in step.changed_vars if v in step.variables}
            obs = Observation(
                step_id=step.step_index,
                line_no=step.line_number,
                function=step.function_name,
                code=step.code_line,
                variables_changed=changed,
                variables_new=list(step.new_vars),
                variables_removed=list(step.removed_vars),
                depth=step.depth,
                block_id=step.block_id,
                ssa_versions=dict(step.ssa_versions),
            )
            # Detect mutations
            if step.mutated_vars:
                obs.mutation = step.mutated_vars[0]
            # Detect aliases
            if step.alias_groups:
                obs.alias_formed = step.alias_groups[0]
            observations.append(obs)

        # Branch observation
        branch = _detect_branch(step)
        if branch:
            observations.append(Observation(
                step_id=step.step_index,
                line_no=step.line_number,
                function=step.function_name,
                code=step.code_line,
                branch_taken=branch,
                depth=step.depth,
                block_id=step.block_id,
            ))

        # Call observation
        if step.code_line.strip().startswith(('def ', 'return ')):
            pass  # handled by call_events, not individual steps

        # If no observations created, make a generic one
        if not observations:
            observations.append(Observation(
                step_id=step.step_index,
                line_no=step.line_number,
                function=step.function_name,
                code=step.code_line,
                depth=step.depth,
                block_id=step.block_id,
                ssa_versions=dict(step.ssa_versions),
            ))

        return observations


def _detect_branch(step) -> Optional[str]:
    """Detect if a step is a branch decision."""
    code = step.code_line.strip()
    if code.startswith('if ') or code.startswith('if('):
        return 'if_true'  # entering if block
    if code.startswith('elif ') or code.startswith('elif('):
        return 'elif'
    if code.startswith('else') or code == 'else:':
        return 'else'
    if code.startswith('for ') or code.startswith('while '):
        return 'loop_enter'
    return None


class ObservationStream:
    """Ordered stream of Observations from an execution.

    Supports filtering, grouping, and slicing for agent reasoning.
    """

    def __init__(self, observations: List[Observation] = None):
        self._observations: List[Observation] = observations or []

    @classmethod
    def from_timeline(cls, timeline) -> 'ObservationStream':
        """Build ObservationStream from an ExecutionTimeline."""
        observations = []
        for step in timeline.steps:
            observations.extend(Observation.from_timeline_event(step))
        return cls(observations)

    def append(self, obs: Observation) -> None:
        self._observations.append(obs)

    def extend(self, obs_list: List[Observation]) -> None:
        self._observations.extend(obs_list)

    @property
    def observations(self) -> List[Observation]:
        return self._observations

    def __len__(self) -> int:
        return len(self._observations)

    def __iter__(self):
        return iter(self._observations)

    def __getitem__(self, idx):
        return self._observations[idx]

    def filter(self, predicate: Callable[[Observation], bool]) -> 'ObservationStream':
        """Return a new stream with only matching observations."""
        return ObservationStream([o for o in self._observations if predicate(o)])

    def group_by_variable(self, var_name: str) -> List[Observation]:
        """Get all observations where a specific variable changed."""
        return [o for o in self._observations
                if var_name in o.variables_changed or var_name in o.variables_new]

    def slice(self, start_step: int, end_step: int) -> 'ObservationStream':
        """Return observations within a step range."""
        return ObservationStream([
            o for o in self._observations
            if start_step <= o.step_id <= end_step
        ])

    def variables_touched(self) -> Set[str]:
        """Get all variable names that were touched in this stream."""
        vars = set()
        for o in self._observations:
            vars.update(o.variables_changed.keys())
            vars.update(o.variables_new)
        return vars

    def step_ids(self) -> List[int]:
        """Get unique step IDs in order."""
        seen = set()
        result = []
        for o in self._observations:
            if o.step_id not in seen:
                seen.add(o.step_id)
                result.append(o.step_id)
        return result

    def to_dicts(self) -> List[dict]:
        return [o.to_dict() for o in self._observations]
