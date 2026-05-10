"""Pattern Detector — identifies algorithmic patterns in execution."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class DetectedPattern:
    """A detected algorithmic pattern."""
    name: str
    description: str
    confidence: float
    evidence: List[str] = field(default_factory=list)
    complexity: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "confidence": round(self.confidence, 3),
            "evidence": self.evidence,
            "complexity": self.complexity,
        }


def detect_patterns(facts: list, pdg: Any) -> List[DetectedPattern]:
    """Detect algorithmic patterns from semantic facts and PDG."""
    patterns = []

    # Check for loop accumulation
    loop_facts = [f for f in facts if 'loop' in getattr(f, 'kind', '')]
    if loop_facts:
        patterns.append(DetectedPattern(
            name="loop.accumulation",
            description="Loop accumulates values into a result variable",
            confidence=0.85,
            evidence=[f.description for f in loop_facts[:3]],
            complexity="O(n)",
        ))

    # Check for memoization
    memo_facts = [f for f in facts if 'memo' in getattr(f, 'subject', '').lower()
                  or 'cache' in getattr(f, 'subject', '').lower()
                  or 'memo' in getattr(f, 'description', '').lower()]
    if memo_facts:
        patterns.append(DetectedPattern(
            name="memoization",
            description="Caches computed values to avoid redundant computation",
            confidence=0.9,
            evidence=[f.description for f in memo_facts[:3]],
            complexity="O(n) with cache",
        ))

    # Check for recursion
    call_facts = [f for f in facts if 'call' in getattr(f, 'kind', '').lower()
                  or 'recursive' in getattr(f, 'description', '').lower()]
    if call_facts:
        patterns.append(DetectedPattern(
            name="recursion",
            description="Function calls itself to solve subproblems",
            confidence=0.8,
            evidence=[f.description for f in call_facts[:3]],
        ))

    # Check for mutation-heavy code
    mutation_facts = [f for f in facts if 'mutation' in getattr(f, 'kind', '').lower()
                      or 'mutate' in getattr(f, 'description', '').lower()]
    if mutation_facts:
        patterns.append(DetectedPattern(
            name="in_place_mutation",
            description="Data structures are modified in place",
            confidence=0.75,
            evidence=[f.description for f in mutation_facts[:3]],
        ))

    # If no patterns found, add a generic one
    if not patterns:
        patterns.append(DetectedPattern(
            name="sequential",
            description="Sequential computation with no dominant pattern",
            confidence=0.5,
            complexity="O(n)",
        ))

    return patterns
