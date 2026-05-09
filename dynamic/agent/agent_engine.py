"""Agent Engine — high-level API for observe → reason → act pipeline.

The AgentEngine orchestrates the full agent loop:
    1. Observe: timeline → ObservationStream
    2. Build state: ObservationStream → AgentState
    3. Reason: AgentState → Hypotheses → ReasoningChain
    4. Act: ReasoningChain → ActionPlan → ActionResult

Usage:
    engine = AgentEngine()
    result = engine.run(timeline, question="Why does result change?")
    result = engine.observe_and_reason(timeline)  # no actions, just analysis
"""

from __future__ import annotations
import json
import os
import tempfile
import time
from typing import Any, Dict, List, Optional

from .observation import Observation, ObservationStream
from .state import AgentState, KnowledgeBase
from .reasoning import (
    Hypothesis, Evidence, ReasoningChain, AgentQuery,
    HypothesisGenerator,
)
from .action import Action, ActionPlan, ActionResult, ActionGenerator


class AgentEngine:
    """High-level API for the agent observe → reason → act pipeline.

    Integrates with SemanticQueryEngine and NarrativeEngine for
    executing actions against the PDG.
    """

    def __init__(self, knowledge_base: Optional[KnowledgeBase] = None,
                 timeout_seconds: float = 30.0):
        self._kb = knowledge_base or KnowledgeBase()
        self._hypothesis_gen = HypothesisGenerator()
        self._action_gen = ActionGenerator()
        self._timeout = timeout_seconds

    @property
    def knowledge_base(self) -> KnowledgeBase:
        return self._kb

    def observe(self, timeline) -> ObservationStream:
        """Step 1: Build observations from timeline."""
        return ObservationStream.from_timeline(timeline)

    def build_state(self, stream: ObservationStream) -> AgentState:
        """Step 2: Build agent state from observations."""
        state = AgentState()
        state.update_from_stream(stream)
        return state

    def reason(self, state: AgentState, question: str = '') -> ReasoningChain:
        """Step 3: Generate hypotheses and build reasoning chain."""
        chain = ReasoningChain()

        # Generate hypotheses from state
        hypotheses = self._hypothesis_gen.generate(state)

        # If we have a specific question, add it as context
        if question:
            state.add_question(question)

        # Build reasoning chain from hypotheses
        for h in hypotheses:
            evidence = self._gather_evidence(h, state)
            conclusion = self._derive_conclusion(h, evidence)
            chain.add_step(h, evidence, conclusion)

        # If no hypotheses generated, create a basic observation summary
        if not hypotheses:
            h = Hypothesis(
                description=f'Observed {state.observation_count} steps across {len(state.functions_seen)} function(s)',
                confidence=0.9,
            )
            chain.add_step(h, [], 'Execution completed with no notable patterns detected')

        return chain

    def plan_actions(self, chain: ReasoningChain, state: AgentState) -> ActionPlan:
        """Step 4a: Generate action plan from reasoning."""
        return self._action_gen.generate_from_reasoning(chain, state)

    def execute_actions(self, plan: ActionPlan,
                         executor_fn=None) -> List[ActionResult]:
        """Step 4b: Execute action plan."""
        if executor_fn is None:
            executor_fn = self._default_executor
        return plan.execute_all(executor_fn)

    def run(self, timeline, question: str = '',
            executor_fn=None) -> Dict[str, Any]:
        """Full pipeline: observe → reason → act → result.

        Args:
            timeline: ExecutionTimeline from StateRecorder
            question: optional question to guide reasoning
            executor_fn: optional custom action executor

        Returns:
            Dict with observations, state, reasoning, actions, results
        """
        t0 = time.time()

        def _check_timeout(stage: str):
            elapsed = time.time() - t0
            if elapsed > self._timeout:
                raise TimeoutError(
                    f'Agent run timed out after {elapsed:.1f}s at stage: {stage}'
                )

        try:
            # Step 1: Observe
            stream = self.observe(timeline)
            _check_timeout('observe')

            # Step 2: Build state
            state = self.build_state(stream)
            _check_timeout('build_state')

            # Step 3: Reason
            chain = self.reason(state, question)
            _check_timeout('reason')

            # Step 4: Plan + execute actions
            plan = self.plan_actions(chain, state)
            results = self.execute_actions(plan, executor_fn)
            _check_timeout('execute_actions')

            # Learn from this execution
            self._kb.record_execution(state)

            duration_ms = (time.time() - t0) * 1000

            result = {
                'success': True,
                'observation_count': len(stream),
                'state': state.to_dict(),
                'reasoning': chain.serialize(),
                'action_plan': plan.to_dict(),
                'action_results': [r.to_dict() for r in results],
                'duration_ms': round(duration_ms, 2),
            }

            # Record metrics
            from .metrics import agent_metrics
            agent_metrics.record_run(result)

            return result

        except TimeoutError as e:
            duration_ms = (time.time() - t0) * 1000
            return {
                'success': False,
                'error': str(e),
                'duration_ms': round(duration_ms, 2),
            }
        except Exception as e:
            duration_ms = (time.time() - t0) * 1000
            return {
                'success': False,
                'error': f'Agent error: {e}',
                'duration_ms': round(duration_ms, 2),
            }

    def observe_and_reason(self, timeline, question: str = '') -> Dict[str, Any]:
        """Observe and reason without executing actions.

        Useful when you just want the analysis, not the actions.
        """
        t0 = time.time()

        stream = self.observe(timeline)
        state = self.build_state(stream)
        chain = self.reason(state, question)

        return {
            'success': True,
            'observation_count': len(stream),
            'state': state.to_dict(),
            'reasoning': chain.serialize(),
            'duration_ms': round((time.time() - t0) * 1000, 2),
        }

    def _gather_evidence(self, hypothesis: Hypothesis,
                          state: AgentState) -> List[Evidence]:
        """Gather evidence for a hypothesis from state."""
        evidence = []
        meta = hypothesis.metadata or {}

        var_name = meta.get('var', '')
        if var_name:
            record = state.get_variable_history(var_name)
            if record and record.values:
                evidence.append(Evidence(
                    source=record,
                    kind='support',
                    var=var_name,
                    description=f'{var_name} has {len(record.values)} recorded values',
                ))
                if record.mutation_count > 0:
                    evidence.append(Evidence(
                        source=record,
                        kind='support',
                        var=var_name,
                        description=f'{var_name} was mutated {record.mutation_count} times',
                    ))

        if meta.get('pattern') == 'complex_control_flow':
            branches = state.get_branches()
            if branches:
                evidence.append(Evidence(
                    source=branches,
                    kind='support',
                    description=f'{len(branches)} branch decisions observed',
                ))

        return evidence

    def _derive_conclusion(self, hypothesis: Hypothesis,
                            evidence: List[Evidence]) -> str:
        """Derive a conclusion from hypothesis and evidence."""
        if not evidence:
            return f'Insufficient evidence for: {hypothesis.description}'

        meta = hypothesis.metadata or {}
        pattern = meta.get('pattern', '')

        if pattern == 'monotonic_increase':
            var = meta.get('var', 'variable')
            return f'{var} shows a monotonically increasing pattern — likely an accumulator in a loop'

        if pattern == 'heavy_mutation':
            var = meta.get('var', 'variable')
            return f'{var} is heavily mutated — consider if this is intentional or a side effect'

        if pattern == 'complex_control_flow':
            return 'Complex control flow detected — multiple branches and loops'

        return f'Evidence supports: {hypothesis.description}'

    def _default_executor(self, action: Action) -> ActionResult:
        """Default executor — just returns the action info without real execution."""
        return ActionResult(
            action=action,
            success=True,
            output={'action': action.to_dict(), 'executed': False,
                    'note': 'No executor configured — action recorded but not executed'},
        )

    @staticmethod
    def save_state_atomic(state: AgentState, filepath: str) -> None:
        """Save agent state to file atomically (write-to-temp, then rename).

        Prevents corruption from interrupted writes.
        """
        data = json.dumps(state.to_dict(), ensure_ascii=False, indent=2)
        dir_name = os.path.dirname(filepath) or '.'
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(data)
            os.replace(tmp_path, filepath)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
