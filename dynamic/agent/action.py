"""Action Layer — agent actions and execution plans.

The agent executes actions based on reasoning: explain, compare, predict, fix.
Actions are organized into ActionPlans that can be executed or simulated.

Usage:
    action = Action(kind='explain', target_var='result', input_query='WHY result')
    plan = ActionPlan()
    plan.add_action(action)
    results = plan.execute_all(context)
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .reasoning import ReasoningChain


@dataclass
class Action:
    """A single agent action."""
    kind: str                          # 'explain' | 'compare' | 'predict' | 'suggest_fix' | 'query'
    target_var: str = ''               # target variable
    target_step: int = -1              # target step
    input_query: str = ''              # DSL query or question
    confidence: float = 0.5
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {'kind': self.kind, 'confidence': round(self.confidence, 3)}
        if self.target_var:
            d['target_var'] = self.target_var
        if self.target_step >= 0:
            d['target_step'] = self.target_step
        if self.input_query:
            d['input_query'] = self.input_query
        if self.metadata:
            d['metadata'] = self.metadata
        return d


@dataclass
class ActionResult:
    """Result of executing an action."""
    action: Action
    success: bool
    output: Any = None
    reasoning_chain: Optional[ReasoningChain] = None
    error: str = ''
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        d = {
            'action': self.action.to_dict(),
            'success': self.success,
            'duration_ms': round(self.duration_ms, 2),
        }
        if self.output:
            d['output'] = self.output
        if self.reasoning_chain:
            d['reasoning'] = self.reasoning_chain.serialize()
        if self.error:
            d['error'] = self.error
        return d


class ActionPlan:
    """Ordered sequence of actions to execute.

    Supports:
    - execute_all(): run all actions, collect results
    - simulate(): predict results without changing state
    """

    def __init__(self):
        self._actions: List[Action] = []

    def add_action(self, action: Action) -> None:
        self._actions.append(action)

    @property
    def actions(self) -> List[Action]:
        return self._actions

    def __len__(self) -> int:
        return len(self._actions)

    def execute_all(self, executor_fn) -> List[ActionResult]:
        """Execute all actions using the provided executor function.

        Args:
            executor_fn: callable(Action) -> ActionResult
        """
        results = []
        for action in self._actions:
            t0 = time.time()
            try:
                result = executor_fn(action)
                result.duration_ms = (time.time() - t0) * 1000
                results.append(result)
            except Exception as e:
                results.append(ActionResult(
                    action=action,
                    success=False,
                    error=str(e),
                    duration_ms=(time.time() - t0) * 1000,
                ))
        return results

    def simulate(self, state) -> List[Dict[str, Any]]:
        """Predict results without executing. Returns predicted outcomes."""
        predictions = []
        for action in self._actions:
            pred = {'action': action.to_dict(), 'predicted': True}
            if action.kind == 'explain':
                pred['prediction'] = f'Would explain {action.target_var or action.input_query}'
            elif action.kind == 'compare':
                pred['prediction'] = f'Would compare step {action.target_step}'
            elif action.kind == 'predict':
                pred['prediction'] = f'Would predict behavior of {action.target_var}'
            elif action.kind == 'suggest_fix':
                pred['prediction'] = f'Would suggest fix for {action.target_var}'
            predictions.append(pred)
        return predictions

    def to_dict(self) -> dict:
        return {
            'action_count': len(self._actions),
            'actions': [a.to_dict() for a in self._actions],
        }


# ── Action Generators ───────────────────────────────────────────

class ActionGenerator:
    """Generates actions from reasoning chain conclusions."""

    def generate_from_reasoning(self, chain: ReasoningChain,
                                 state) -> ActionPlan:
        """Create an action plan from a reasoning chain."""
        plan = ActionPlan()

        for step in chain.steps:
            h = step.hypothesis
            meta = h.metadata or {}

            if meta.get('pattern') == 'monotonic_increase':
                plan.add_action(Action(
                    kind='explain',
                    target_var=meta.get('var', ''),
                    input_query=f'TRACE {meta.get("var", "")}',
                    confidence=h.confidence,
                    metadata={'reason': 'accumulation_detected'},
                ))

            elif meta.get('pattern') == 'heavy_mutation':
                plan.add_action(Action(
                    kind='explain',
                    target_var=meta.get('var', ''),
                    input_query=f'WHY {meta.get("var", "")}',
                    confidence=h.confidence,
                    metadata={'reason': 'heavy_mutation'},
                ))

            elif meta.get('pattern') == 'complex_control_flow':
                plan.add_action(Action(
                    kind='explain',
                    input_query='STATS',
                    confidence=h.confidence,
                    metadata={'reason': 'complex_flow'},
                ))

        return plan
