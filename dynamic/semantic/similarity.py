"""Semantic Similarity — Multi-vector similarity engine.

Computes deep semantic distance between two executions by comparing
multiple orthogonal vectors derived from fingerprints and ontology:

    1. Algorithm Vector   — what computation is being performed
    2. Structure Vector   — what data structures are used
    3. Control Vector     — what control flow patterns appear
    4. Semantic Role Vec. — what roles do variables play
    5. Invariant Vector   — what properties are maintained
    6. Behavior Vector    — what actions are performed

Unlike simple hash comparison, this engine uses the ontology to understand
that memo_table and visited_set are similar (both are state_cache),
even though their canonical IDs differ.

Usage:
    sim = SemanticSimilarity()
    result = sim.compare(fp_a, fp_b)
    print(result.score)           # 0.0 - 1.0
    print(result.breakdown)       # per-vector scores
    print(result.shared)          # what they share
    print(result.different)       # what differs

    # Ontology-aware: uses concept distance
    result = sim.compare_with_ontology(fp_a, fp_b, ontology)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Any
import math

from .fingerprint import SemanticFingerprint
from .ontology import SemanticOntology


# ─── Similarity Result ─────────────────────────────────────────

@dataclass
class VectorScore:
    """Score for a single similarity vector."""
    name: str               # e.g., 'algorithm', 'structure'
    score: float            # 0.0 - 1.0
    weight: float           # weight in final score
    shared: List[str]       # elements in common
    different: List[Tuple[str, str]]  # (only_in_a, only_in_b)

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'score': round(self.score, 3),
            'weight': self.weight,
            'shared': self.shared,
            'different': [{'a': a, 'b': b} for a, b in self.different],
        }


@dataclass
class SimilarityResult:
    """Complete similarity comparison result."""
    score: float                    # 0.0 - 1.0 weighted aggregate
    vectors: List[VectorScore]      # per-vector breakdown
    shared_identities: List[str]    # canonical IDs in common
    different_identities: List[Tuple[str, str]]  # (only_a, only_b)
    ontology_insights: List[str]    # human-readable insights from ontology
    summary: str                    # one-line description

    @property
    def breakdown(self) -> Dict[str, float]:
        return {v.name: v.score for v in self.vectors}

    @property
    def shared(self) -> List[str]:
        return self.shared_identities

    @property
    def different(self) -> List[Tuple[str, str]]:
        return self.different_identities

    def to_dict(self) -> dict:
        return {
            'score': round(self.score, 3),
            'breakdown': self.breakdown,
            'vectors': [v.to_dict() for v in self.vectors],
            'shared_identities': self.shared_identities,
            'different_identities': [
                {'a': a, 'b': b} for a, b in self.different_identities
            ],
            'ontology_insights': self.ontology_insights,
            'summary': self.summary,
        }

    def describe(self) -> str:
        lines = [self.summary, f'Score: {self.score:.1%}', '']
        for v in self.vectors:
            bar = '█' * int(v.score * 10) + '░' * (10 - int(v.score * 10))
            lines.append(f'  {v.name:20s} {bar} {v.score:.1%}')
        if self.ontology_insights:
            lines.append('')
            lines.append('Ontology insights:')
            for insight in self.ontology_insights:
                lines.append(f'  • {insight}')
        return '\n'.join(lines)


# ─── Similarity Engine ─────────────────────────────────────────

class SemanticSimilarity:
    """Multi-vector semantic similarity engine."""

    # Default weights for each vector
    DEFAULT_WEIGHTS = {
        'algorithm': 4.0,
        'structure': 2.5,
        'control': 2.0,
        'semantic_role': 2.0,
        'invariant': 1.0,
        'behavior': 1.5,
    }

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = weights or self.DEFAULT_WEIGHTS.copy()
        self._total_weight = sum(self.weights.values())

    def compare(
        self,
        fp_a: SemanticFingerprint,
        fp_b: SemanticFingerprint,
        ontology: Optional[SemanticOntology] = None,
    ) -> SimilarityResult:
        """Compare two fingerprints with multi-vector analysis.

        If ontology is provided, uses concept hierarchy for semantic distance.
        Otherwise, uses set overlap (still good, but no cross-concept bridging).
        """
        vectors = []

        # 1. Algorithm vector
        vectors.append(self._compare_algorithm(fp_a, fp_b))

        # 2. Structure vector
        vectors.append(self._compare_set_vector(
            'structure', fp_a.structures, fp_b.structures, ontology
        ))

        # 3. Control vector
        vectors.append(self._compare_set_vector(
            'control', fp_a.control, fp_b.control, ontology
        ))

        # 4. Semantic role vector (variable archetypes)
        vectors.append(self._compare_semantic_roles(fp_a, fp_b, ontology))

        # 5. Invariant vector
        vectors.append(self._compare_set_vector(
            'invariant', fp_a.invariant_set, fp_b.invariant_set, ontology
        ))

        # 6. Behavior vector
        vectors.append(self._compare_set_vector(
            'behavior', fp_a.behaviors, fp_b.behaviors, ontology
        ))

        # Weighted aggregate
        total_score = 0.0
        for v in vectors:
            w = self.weights.get(v.name, 1.0)
            total_score += v.score * w
        final_score = total_score / self._total_weight if self._total_weight > 0 else 0.0

        # Collect shared/different
        shared = []
        different = []
        for v in vectors:
            shared.extend(v.shared)
            different.extend(v.different)

        # Ontology insights
        insights = []
        if ontology:
            insights = self._generate_insights(fp_a, fp_b, ontology, vectors)

        # Summary
        summary = self._generate_summary(final_score, fp_a, fp_b, shared)

        return SimilarityResult(
            score=round(final_score, 3),
            vectors=vectors,
            shared_identities=sorted(set(shared)),
            different_identities=different,
            ontology_insights=insights,
            summary=summary,
        )

    # ── Vector Comparators ──

    def _compare_algorithm(
        self, fp_a: SemanticFingerprint, fp_b: SemanticFingerprint
    ) -> VectorScore:
        """Compare algorithm identities."""
        algo_a = fp_a.algorithm
        algo_b = fp_b.algorithm

        if algo_a == algo_b:
            score = 1.0
            shared = [algo_a] if algo_a != 'unknown' else []
            different = []
        else:
            # Both unknown = partial match
            if algo_a == 'unknown' and algo_b == 'unknown':
                score = 0.3
                shared = []
                different = []
            elif algo_a == 'unknown' or algo_b == 'unknown':
                score = 0.1
                shared = []
                different = [(algo_a, algo_b)]
            else:
                score = 0.0
                shared = []
                different = [(algo_a, algo_b)]

        # Confidence modulation
        avg_conf = (fp_a.algorithm_confidence + fp_b.algorithm_confidence) / 2
        score *= (0.5 + 0.5 * avg_conf)

        return VectorScore(
            name='algorithm',
            score=round(score, 3),
            weight=self.weights['algorithm'],
            shared=shared,
            different=different,
        )

    def _compare_set_vector(
        self,
        name: str,
        set_a: List[str],
        set_b: List[str],
        ontology: Optional[SemanticOntology] = None,
    ) -> VectorScore:
        """Compare two sets of canonical identities, optionally using ontology."""
        s_a = set(set_a)
        s_b = set(set_b)

        if not s_a and not s_b:
            return VectorScore(
                name=name, score=0.5, weight=self.weights.get(name, 1.0),
                shared=[], different=[],
            )

        # Direct overlap
        direct_shared = s_a & s_b
        only_a = s_a - s_b
        only_b = s_b - s_a

        # Ontology-bridged similarity for non-overlapping elements
        bridged_score = 0.0
        bridged_pairs = []
        if ontology and only_a and only_b:
            bridged_score, bridged_pairs = self._ontology_bridge_score(
                only_a, only_b, ontology
            )

        # Compute score
        intersection = len(direct_shared)
        # Add bridged matches as partial intersection
        intersection += bridged_score * min(len(only_a), len(only_b))
        union = len(s_a | s_b)

        score = intersection / union if union > 0 else 0.0

        shared = sorted(direct_shared)
        different = []
        # Unmatched elements
        matched_a = set(direct_shared)
        matched_b = set(direct_shared)
        for a, b in bridged_pairs:
            matched_a.add(a)
            matched_b.add(b)
        for a in sorted(only_a - matched_a):
            different.append((a, ''))
        for b in sorted(only_b - matched_b):
            different.append(('', b))

        return VectorScore(
            name=name,
            score=round(min(score, 1.0), 3),
            weight=self.weights.get(name, 1.0),
            shared=shared,
            different=different,
        )

    def _compare_semantic_roles(
        self,
        fp_a: SemanticFingerprint,
        fp_b: SemanticFingerprint,
        ontology: Optional[SemanticOntology] = None,
    ) -> VectorScore:
        """Compare variable archetype distributions."""
        arch_a = set(fp_a.variable_archetypes.values())
        arch_b = set(fp_b.variable_archetypes.values())

        if not arch_a and not arch_b:
            return VectorScore(
                name='semantic_role', score=0.5,
                weight=self.weights['semantic_role'],
                shared=[], different=[],
            )

        # Direct overlap
        shared_arch = arch_a & arch_b
        only_a = arch_a - shared_arch
        only_b = arch_b - shared_arch

        # Ontology bridge
        bridged_score = 0.0
        bridged_pairs = []
        if ontology and only_a and only_b:
            bridged_score, bridged_pairs = self._ontology_bridge_score(
                only_a, only_b, ontology
            )

        intersection = len(shared_arch) + bridged_score * min(len(only_a), len(only_b))
        union = len(arch_a | arch_b)
        score = intersection / union if union > 0 else 0.0

        # Variable name overlap (bonus)
        vars_a = set(fp_a.variable_archetypes.keys())
        vars_b = set(fp_b.variable_archetypes.keys())
        if vars_a and vars_b:
            var_overlap = len(vars_a & vars_b) / len(vars_a | vars_b)
            score = 0.7 * score + 0.3 * var_overlap

        shared = sorted(shared_arch)
        different = []
        matched_a = set(shared_arch) | {a for a, _ in bridged_pairs}
        matched_b = set(shared_arch) | {b for _, b in bridged_pairs}
        for a in sorted(only_a - matched_a):
            different.append((a, ''))
        for b in sorted(only_b - matched_b):
            different.append(('', b))

        return VectorScore(
            name='semantic_role',
            score=round(min(score, 1.0), 3),
            weight=self.weights['semantic_role'],
            shared=shared,
            different=different,
        )

    # ── Ontology Bridge ──

    def _ontology_bridge_score(
        self,
        set_a: Set[str],
        set_b: Set[str],
        ontology: SemanticOntology,
    ) -> Tuple[float, List[Tuple[str, str]]]:
        """Find ontology-mediated similarity between non-overlapping sets.

        Returns (score, matched_pairs) where matched_pairs are (a, b) that
        are semantically close via the ontology hierarchy.
        """
        matched_pairs = []
        total_similarity = 0.0

        for a in set_a:
            best_sim = 0.0
            best_b = None
            for b in set_b:
                sim = self._concept_distance(a, b, ontology)
                if sim > best_sim:
                    best_sim = sim
                    best_b = b
            if best_b and best_sim > 0.3:
                matched_pairs.append((a, best_b))
                total_similarity += best_sim

        if not matched_pairs:
            return 0.0, []

        avg_sim = total_similarity / len(matched_pairs)
        return avg_sim, matched_pairs

    def _concept_distance(
        self,
        id_a: str,
        id_b: str,
        ontology: SemanticOntology,
    ) -> float:
        """Compute semantic distance between two concept IDs.

        Uses ontology hierarchy:
        - Same concept = 1.0
        - Siblings (share parent) = 0.7
        - Parent-child = 0.5
        - Same family = 0.4
        - Same category = 0.2
        - Connected by relation = 0.3
        - No connection = 0.0
        """
        if id_a == id_b:
            return 1.0

        concept_a = ontology.get(id_a)
        concept_b = ontology.get(id_b)

        if not concept_a or not concept_b:
            return 0.0

        # Same family
        if concept_a.family == concept_b.family:
            # Siblings check
            a_ancestors = set(concept_a.parents)
            b_ancestors = set(concept_b.parents)
            if a_ancestors & b_ancestors:
                return 0.7
            # Parent-child
            if id_a in concept_b.parents or id_b in concept_a.parents:
                return 0.5
            return 0.4

        # Same category
        if concept_a.category == concept_b.category:
            return 0.2

        # Related by relation
        for rel, target in concept_a.related:
            if target == id_b:
                return 0.3
        for rel, target in concept_b.related:
            if target == id_a:
                return 0.3

        # Check if they share any ancestor
        ancestors_a = set(ontology.ancestors(id_a))
        ancestors_b = set(ontology.ancestors(id_b))
        shared_ancestors = ancestors_a & ancestors_b
        if shared_ancestors:
            # Closer ancestors = higher score
            depth = min(
                len(ontology.path_between(id_a, a) or [])
                for a in shared_ancestors
            )
            return max(0.1, 0.5 - depth * 0.1)

        return 0.0

    # ── Insights ──

    def _generate_insights(
        self,
        fp_a: SemanticFingerprint,
        fp_b: SemanticFingerprint,
        ontology: SemanticOntology,
        vectors: List[VectorScore],
    ) -> List[str]:
        """Generate human-readable insights from ontology analysis."""
        insights = []

        # Algorithm insight
        if fp_a.algorithm == fp_b.algorithm and fp_a.algorithm != 'unknown':
            concept = ontology.get(fp_a.algorithm)
            if concept:
                insights.append(
                    f'Both use {concept.label} — '
                    f'{concept.complexity_implication or "same algorithmic approach"}'
                )
                if concept.common_mistakes:
                    insights.append(
                        f'Watch for: {", ".join(concept.common_mistakes[:2])}'
                    )
        elif fp_a.algorithm != 'unknown' and fp_b.algorithm != 'unknown':
            path = ontology.path_between(fp_a.algorithm, fp_b.algorithm)
            if path:
                insights.append(
                    f'Algorithm path: {" → ".join(path)}'
                )

        # Structure insight
        shared_structs = set(fp_a.structures) & set(fp_b.structures)
        for s in shared_structs:
            concept = ontology.get(s)
            if concept:
                insights.append(
                    f'Shared structure: {concept.label} — {concept.complexity_implication}'
                )

        # Complexity insight
        if fp_a.complexity != fp_b.complexity:
            insights.append(
                f'Complexity differs: {fp_a.complexity} vs {fp_b.complexity}'
            )

        return insights[:5]

    def _generate_summary(
        self,
        score: float,
        fp_a: SemanticFingerprint,
        fp_b: SemanticFingerprint,
        shared: List[str],
    ) -> str:
        """Generate a one-line summary."""
        if score >= 0.95:
            return 'Semantically equivalent — same algorithm, same structure'
        elif score >= 0.75:
            return f'Highly similar — {fp_a.algorithm} with shared patterns'
        elif score >= 0.5:
            return f'Moderately similar — {len(shared)} shared identities'
        elif score >= 0.25:
            return f'Weakly similar — different approaches to related problems'
        else:
            return 'Semantically different — distinct algorithmic strategies'


# ─── Convenience ────────────────────────────────────────────────

def similarity(
    fp_a: SemanticFingerprint,
    fp_b: SemanticFingerprint,
    ontology: Optional[SemanticOntology] = None,
) -> SimilarityResult:
    """Quick similarity comparison."""
    engine = SemanticSimilarity()
    return engine.compare(fp_a, fp_b, ontology)


def batch_similarity(
    fingerprints: List[SemanticFingerprint],
    ontology: Optional[SemanticOntology] = None,
) -> List[List[float]]:
    """Compute pairwise similarity matrix for a batch of fingerprints."""
    n = len(fingerprints)
    engine = SemanticSimilarity()
    matrix = [[0.0] * n for _ in range(n)]

    for i in range(n):
        matrix[i][i] = 1.0
        for j in range(i + 1, n):
            result = engine.compare(fingerprints[i], fingerprints[j], ontology)
            matrix[i][j] = result.score
            matrix[j][i] = result.score

    return matrix
