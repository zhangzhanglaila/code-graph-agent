"""Reasoning Layer — hypotheses, evidence, and reasoning chains.

The agent forms hypotheses from observations, supports them with evidence,
and builds reasoning chains that explain code behavior.

Usage:
    chain = ReasoningChain()
    h = Hypothesis(description="x is accumulating in a loop")
    h.add_evidence(Evidence(source=obs, kind='support', var='x'))
    chain.add_step(h, evidence, "The loop builds x incrementally")
"""

from __future__ import annotations
import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .observation import Observation
from .state import AgentState


@dataclass
class Evidence:
    """A piece of evidence supporting or contradicting a hypothesis."""
    source: Any                  # Observation, fact, or query result
    kind: str                    # 'support' | 'contradict'
    var: str = ''                # related variable
    description: str = ''        # human-readable
    weight: float = 1.0          # strength of evidence (0-1)

    def matches(self, hypothesis: 'Hypothesis') -> bool:
        """Check if this evidence is relevant to a hypothesis."""
        if self.var and self.var in hypothesis.description:
            return True
        if self.description and any(word in hypothesis.description.lower()
                                     for word in self.description.lower().split()[:3]):
            return True
        return False

    def to_dict(self) -> dict:
        d = {
            'kind': self.kind,
            'weight': self.weight,
        }
        if self.var:
            d['var'] = self.var
        if self.description:
            d['description'] = self.description
        if isinstance(self.source, Observation):
            d['source_step'] = self.source.step_id
        return d


@dataclass
class Hypothesis:
    """A candidate explanation for observed behavior."""
    id: str = ''
    description: str = ''
    confidence: float = 0.5
    supporting_evidence: List[Evidence] = field(default_factory=list)
    contradicting_evidence: List[Evidence] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            h = hashlib.md5(self.description.encode()).hexdigest()[:8]
            self.id = f'h_{h}'

    def add_evidence(self, evidence: Evidence) -> None:
        if evidence.kind == 'support':
            self.supporting_evidence.append(evidence)
        else:
            self.contradicting_evidence.append(evidence)
        self.update_confidence()

    def update_confidence(self) -> None:
        """Recalculate confidence based on evidence balance."""
        support = sum(e.weight for e in self.supporting_evidence)
        contradict = sum(e.weight for e in self.contradicting_evidence)
        total = support + contradict
        if total > 0:
            self.confidence = support / total
        # Cap at 0.95 — never fully certain
        self.confidence = min(self.confidence, 0.95)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'description': self.description,
            'confidence': round(self.confidence, 3),
            'support_count': len(self.supporting_evidence),
            'contradict_count': len(self.contradicting_evidence),
            'supporting': [e.to_dict() for e in self.supporting_evidence[:5]],
            'contradicting': [e.to_dict() for e in self.contradicting_evidence[:5]],
        }


@dataclass
class ReasoningStep:
    """One step in a reasoning chain."""
    hypothesis: Hypothesis
    evidence: List[Evidence]
    conclusion: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            'hypothesis': self.hypothesis.to_dict(),
            'evidence': [e.to_dict() for e in self.evidence],
            'conclusion': self.conclusion,
        }


class ReasoningChain:
    """An ordered chain of reasoning steps: hypothesis → evidence → conclusion.

    Provides full explainability — every conclusion has supporting evidence.
    """

    def __init__(self):
        self._steps: List[ReasoningStep] = []
        self._start_time = time.time()

    def add_step(self, hypothesis: Hypothesis, evidence: List[Evidence],
                 conclusion: str) -> None:
        for e in evidence:
            hypothesis.add_evidence(e)
        self._steps.append(ReasoningStep(
            hypothesis=hypothesis,
            evidence=evidence,
            conclusion=conclusion,
        ))

    @property
    def steps(self) -> List[ReasoningStep]:
        return self._steps

    def depth(self) -> int:
        return len(self._steps)

    def overall_confidence(self) -> float:
        if not self._steps:
            return 0.0
        return sum(s.hypothesis.confidence for s in self._steps) / len(self._steps)

    def conclusions(self) -> List[str]:
        return [s.conclusion for s in self._steps]

    def serialize(self) -> dict:
        return {
            'depth': self.depth(),
            'overall_confidence': round(self.overall_confidence(), 3),
            'steps': [s.to_dict() for s in self._steps],
            'duration_ms': round((time.time() - self._start_time) * 1000, 2),
        }

    def to_text(self) -> str:
        """Human-readable reasoning chain."""
        lines = ['Reasoning Chain', '─' * 40]
        for i, step in enumerate(self._steps, 1):
            h = step.hypothesis
            lines.append(f'  Step {i}: {h.description}')
            lines.append(f'    Confidence: {h.confidence:.1%}')
            for e in step.evidence[:3]:
                lines.append(f'    Evidence ({e.kind}): {e.description or e.var}')
            lines.append(f'    Conclusion: {step.conclusion}')
        lines.append('─' * 40)
        lines.append(f'  Overall confidence: {self.overall_confidence():.1%}')
        return '\n'.join(lines)

    def to_dict(self) -> dict:
        return self.serialize()


@dataclass
class AgentQuery:
    """Internal query structure for agent reasoning.

    Not user-facing DSL — these are the questions the agent asks itself
    to understand code behavior.
    """
    question: str
    target_var: str = ''
    target_step: int = -1
    kind: str = 'why'  # 'why' | 'how' | 'what' | 'predict' | 'compare'

    def to_dict(self) -> dict:
        d = {'question': self.question, 'kind': self.kind}
        if self.target_var:
            d['target_var'] = self.target_var
        if self.target_step >= 0:
            d['target_step'] = self.target_step
        return d


# ── Hypothesis Generators ───────────────────────────────────────

class HypothesisGenerator:
    """Generates hypotheses from AgentState observations."""

    def generate(self, state: AgentState) -> List[Hypothesis]:
        """Generate candidate hypotheses from accumulated state."""
        hypotheses = []

        # Check for accumulation patterns
        for name, record in state.get_all_variables().items():
            if len(record.values) >= 3:
                # Check if value is growing
                try:
                    nums = [float(v['value']) for v in record.values if _is_numeric(v['value'])]
                    if len(nums) >= 3 and all(nums[i] <= nums[i+1] for i in range(len(nums)-1)):
                        hypotheses.append(Hypothesis(
                            description=f'{name} is monotonically increasing across {len(nums)} observations',
                            confidence=0.7,
                            metadata={'var': name, 'pattern': 'monotonic_increase'},
                        ))
                except (ValueError, TypeError):
                    pass

            if record.mutation_count > 2:
                hypotheses.append(Hypothesis(
                    description=f'{name} is heavily mutated ({record.mutation_count} times)',
                    confidence=0.6,
                    metadata={'var': name, 'pattern': 'heavy_mutation'},
                ))

        # Check for branch patterns
        branches = state.get_branches()
        if len(branches) > 3:
            loop_branches = [b for b in branches if b['type'] == 'loop_enter']
            if loop_branches:
                hypotheses.append(Hypothesis(
                    description=f'Code contains {len(loop_branches)} loop(s) with {len(branches)} branch decisions',
                    confidence=0.8,
                    metadata={'pattern': 'complex_control_flow'},
                ))

        return hypotheses


def _is_numeric(s: str) -> bool:
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False
