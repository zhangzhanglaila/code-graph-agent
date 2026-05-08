"""Semantic Fingerprint — Execution DNA.

Generates a stable, comparable fingerprint from semantic identities.
Used for:
    - Semantic search (find similar executions)
    - Duplicate detection (same algorithm, different code)
    - Regression matching (did semantics change?)
    - Execution clustering (group by algorithm)

Fingerprint structure:
{
    "hash": "a3f8c1e2b4d56789",
    "algorithm": "dp_optimization",
    "structures": ["dict_state_write", "parallel_state_transition"],
    "control": ["bounded_iterator"],
    "complexity": "linear_iterative_dp",
    "variable_archetypes": {
        "memo": "dict_state_write",
        "a": "parallel_state_transition",
        "b": "parallel_state_transition"
    },
    "invariant_set": ["atomic_swap", "monotonic_growth", "key_value_mapping"]
}

Two executions with the same fingerprint are semantically equivalent.
Two executions with similar fingerprints share algorithmic structure.

Usage:
    fp = SemanticFingerprint.generate(pdg, facts)
    print(fp.hash)
    print(fp.match(other_fp))  # 0.0 - 1.0 similarity
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Any
import hashlib
import json

from .identity import IdentityGraph, SemanticIdentifier
from .identity_normalizer import IdentityNormalizer, NormalForm


@dataclass
class SemanticFingerprint:
    """A stable, comparable execution fingerprint."""
    hash: str                   # 16-char hex hash
    algorithm: str              # primary algorithm identity
    structures: List[str]       # data structure identities
    control: List[str]          # control flow identities
    complexity: str             # complexity shape
    variable_archetypes: Dict[str, str]  # var_name → canonical identity
    invariant_set: List[str]    # all invariants across identities
    behaviors: List[str]        # all behaviors across identities
    # Derived metrics
    identity_count: int = 0
    algorithm_confidence: float = 0.0
    structural_complexity: float = 0.0

    def to_dict(self) -> dict:
        return {
            'hash': self.hash,
            'algorithm': self.algorithm,
            'structures': self.structures,
            'control': self.control,
            'complexity': self.complexity,
            'variable_archetypes': self.variable_archetypes,
            'invariant_set': self.invariant_set,
            'behaviors': self.behaviors,
            'identity_count': self.identity_count,
            'algorithm_confidence': round(self.algorithm_confidence, 3),
            'structural_complexity': round(self.structural_complexity, 3),
        }

    def match(self, other: 'SemanticFingerprint') -> float:
        """Compute similarity with another fingerprint. Returns 0.0 - 1.0."""
        score = 0.0
        weights = 0.0

        # Algorithm match (highest weight)
        w = 4.0
        weights += w
        if self.algorithm == other.algorithm:
            score += w

        # Structure overlap
        w = 2.0
        weights += w
        if self.structures or other.structures:
            overlap = len(set(self.structures) & set(other.structures))
            total = len(set(self.structures) | set(other.structures))
            if total > 0:
                score += w * (overlap / total)

        # Control overlap
        w = 1.5
        weights += w
        if self.control or other.control:
            overlap = len(set(self.control) & set(other.control))
            total = len(set(self.control) | set(other.control))
            if total > 0:
                score += w * (overlap / total)

        # Complexity match
        w = 1.0
        weights += w
        if self.complexity == other.complexity:
            score += w

        # Variable archetype overlap
        w = 1.5
        weights += w
        self_vars = set(self.variable_archetypes.values())
        other_vars = set(other.variable_archetypes.values())
        if self_vars or other_vars:
            overlap = len(self_vars & other_vars)
            total = len(self_vars | other_vars)
            if total > 0:
                score += w * (overlap / total)

        # Invariant overlap
        w = 1.0
        weights += w
        if self.invariant_set or other.invariant_set:
            overlap = len(set(self.invariant_set) & set(other.invariant_set))
            total = len(set(self.invariant_set) | set(other.invariant_set))
            if total > 0:
                score += w * (overlap / total)

        return round(score / weights, 3) if weights > 0 else 0.0

    @classmethod
    def generate(cls, pdg, facts) -> 'SemanticFingerprint':
        """Generate a fingerprint from a PDG + facts."""
        # Identify and normalize
        identity_graph = SemanticIdentifier.identify(pdg, facts)
        normal_form = IdentityNormalizer.normalize(identity_graph, pdg)

        return cls._from_normal_form(normal_form)

    @classmethod
    def _from_normal_form(cls, nf: NormalForm) -> 'SemanticFingerprint':
        """Build fingerprint from normalized identities."""
        # Extract components
        algorithms = [c for c in nf.canonical_identities if c.category == 'algorithm']
        structures = [c for c in nf.canonical_identities if c.category == 'structure']
        controls = [c for c in nf.canonical_identities if c.category == 'control']
        variables = [c for c in nf.canonical_identities if c.category == 'variable']

        # Primary algorithm
        algorithm = algorithms[0].canonical_id if algorithms else 'unknown'
        algo_conf = algorithms[0].confidence if algorithms else 0.0

        # Variable archetypes
        var_archetypes = {}
        for v in variables:
            for subj in v.subjects:
                var_archetypes[subj] = v.canonical_id

        # All invariants and behaviors
        all_invariants = []
        all_behaviors = []
        for c in nf.canonical_identities:
            all_invariants.extend(c.invariants)
            all_behaviors.extend(c.behaviors)

        # Structural complexity: number of distinct canonical identities
        structural_complexity = len(set(c.canonical_id for c in nf.canonical_identities)) / 10.0

        return cls(
            hash=nf.fingerprint(),
            algorithm=algorithm,
            structures=sorted(set(c.canonical_id for c in structures)),
            control=sorted(set(c.canonical_id for c in controls)),
            complexity=nf.complexity_shape,
            variable_archetypes=var_archetypes,
            invariant_set=sorted(set(all_invariants)),
            behaviors=sorted(set(all_behaviors)),
            identity_count=len(nf.canonical_identities),
            algorithm_confidence=algo_conf,
            structural_complexity=min(structural_complexity, 1.0),
        )

    def describe(self) -> str:
        parts = [f'algo={self.algorithm}({self.algorithm_confidence:.0%})']
        if self.structures:
            parts.append(f'structs={"+".join(self.structures)}')
        if self.control:
            parts.append(f'ctrl={"+".join(self.control)}')
        parts.append(f'complexity={self.complexity}')
        return f'[{self.hash}] {" | ".join(parts)}'


class FingerprintIndex:
    """Index of fingerprints for semantic search and matching."""

    def __init__(self):
        self.index: Dict[str, SemanticFingerprint] = {}  # hash → fingerprint
        self.metadata: Dict[str, dict] = {}  # hash → extra info

    def add(self, fingerprint: SemanticFingerprint, metadata: dict = None):
        """Add a fingerprint to the index."""
        self.index[fingerprint.hash] = fingerprint
        if metadata:
            self.metadata[fingerprint.hash] = metadata

    def search(self, query_fp: SemanticFingerprint, top_k: int = 5) -> List[Tuple[str, float, SemanticFingerprint]]:
        """Find the most similar fingerprints."""
        scored = []
        for hash, fp in self.index.items():
            similarity = query_fp.match(fp)
            scored.append((hash, similarity, fp))
        scored.sort(key=lambda x: -x[1])
        return scored[:top_k]

    def find_by_algorithm(self, algorithm: str) -> List[SemanticFingerprint]:
        """Find all fingerprints with a specific algorithm."""
        return [fp for fp in self.index.values() if fp.algorithm == algorithm]

    def find_by_structure(self, structure: str) -> List[SemanticFingerprint]:
        """Find all fingerprints using a specific structure."""
        return [fp for fp in self.index.values() if structure in fp.structures]

    def clusters(self) -> Dict[str, List[str]]:
        """Cluster fingerprints by algorithm."""
        groups: Dict[str, List[str]] = {}
        for hash, fp in self.index.items():
            groups.setdefault(fp.algorithm, []).append(hash)
        return groups

    def stats(self) -> dict:
        algos = {}
        for fp in self.index.values():
            algos[fp.algorithm] = algos.get(fp.algorithm, 0) + 1
        return {
            'total': len(self.index),
            'algorithms': algos,
            'clusters': len(self.clusters()),
        }
