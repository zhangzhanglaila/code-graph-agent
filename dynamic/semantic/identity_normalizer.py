"""Identity Normalizer — Canonicalize runtime identities into normal form.

Different code producing the same behavior should map to the same canonical identity:

    memo[i] = x        }  all → canonical: dict_state_write(key, value)
    cache[k] = y       }
    dp[pos] = val      }

    a, b = b, a + b    →  canonical: parallel_state_transition([a, b])
    x, y = y, x * 2    →  canonical: parallel_state_transition([x, y])

    total += item       →  canonical: monotonic_accumulator(total, +)
    count += 1          →  canonical: monotonic_accumulator(count, +)

This enables:
    - Semantic search by canonical pattern
    - Cross-execution identity matching
    - Duplicate detection
    - Regression matching by structural identity

Usage:
    normal_form = IdentityNormalizer.normalize(identities, pdg)
    print(normal_form.canonical_identities)
    print(normal_form.fingerprint())
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Any
import hashlib
import json

from .identity import SemanticIdentity, IdentityGraph


# ─── Canonical Identity ─────────────────────────────────────────

@dataclass
class CanonicalIdentity:
    """A normalized, implementation-independent semantic identity."""
    canonical_id: str       # e.g., 'dict_state_write', 'parallel_state_transition'
    category: str           # 'variable' | 'control' | 'structure' | 'algorithm'
    parameters: dict        # normalized parameters (e.g., key_type, operator)
    source_identities: List[str]  # original archetype names that mapped here
    subjects: List[str]     # variable names / step ids
    confidence: float       # max confidence from source identities
    invariants: List[str]
    behaviors: List[str]

    def to_dict(self) -> dict:
        return {
            'canonical_id': self.canonical_id,
            'category': self.category,
            'parameters': self.parameters,
            'source_identities': self.source_identities,
            'subjects': self.subjects,
            'confidence': round(self.confidence, 3),
            'invariants': self.invariants,
            'behaviors': self.behaviors,
        }


@dataclass
class NormalForm:
    """The complete normalized identity set for an execution."""
    canonical_identities: List[CanonicalIdentity] = field(default_factory=list)
    # Structural summary
    algorithm_signature: str = ''
    structure_signature: str = ''
    control_signature: str = ''
    complexity_shape: str = ''

    def fingerprint(self) -> str:
        """Generate a deterministic hash of the normalized identity set."""
        data = {
            'algorithms': sorted(set(c.canonical_id for c in self.canonical_identities if c.category == 'algorithm')),
            'structures': sorted(set(c.canonical_id for c in self.canonical_identities if c.category == 'structure')),
            'variables': sorted(set(c.canonical_id for c in self.canonical_identities if c.category == 'variable')),
            'control': sorted(set(c.canonical_id for c in self.canonical_identities if c.category == 'control')),
            'complexity': self.complexity_shape,
        }
        raw = json.dumps(data, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def summary(self) -> str:
        cats = {}
        for c in self.canonical_identities:
            cats[c.category] = cats.get(c.category, 0) + 1
        parts = [f'{cat}:{n}' for cat, n in sorted(cats.items())]
        fp = self.fingerprint()
        return f'NormalForm({fp}): {len(self.canonical_identities)} canonical identities ({", ".join(parts)})'

    def to_dict(self) -> dict:
        return {
            'canonical_identities': [c.to_dict() for c in self.canonical_identities],
            'fingerprint': self.fingerprint(),
            'algorithm_signature': self.algorithm_signature,
            'structure_signature': self.structure_signature,
            'control_signature': self.control_signature,
            'complexity_shape': self.complexity_shape,
            'summary': self.summary(),
        }


# ─── Canonicalization Rules ─────────────────────────────────────

# Maps (archetype, pattern) → canonical_id
_CANONICALIZATION_TABLE: Dict[str, Tuple[str, dict]] = {
    # Variable archetypes
    'memo_table':       ('dict_state_write', {'structure': 'dict', 'access': 'indexed'}),
    'accumulator':      ('monotonic_accumulator', {'direction': 'increasing'}),
    'loop_counter':     ('bounded_iterator', {'step': 1}),
    'state_transition': ('parallel_state_transition', {'swap': True}),
    'visited_set':      ('membership_guard', {'structure': 'set'}),
    'boundary_condition': ('boolean_guard', {}),

    # Structure archetypes
    'stack_dfs':        ('lifo_traversal', {'structure': 'stack'}),
    'queue_bfs':        ('fifo_traversal', {'structure': 'queue'}),
    'heap_priority':    ('priority_selection', {'structure': 'heap'}),
    'hash_lookup':      ('constant_time_lookup', {'structure': 'hash'}),

    # Control archetypes
    'dedup_guard':      ('deduplication_filter', {}),
    'early_termination': ('short_circuit', {}),
    'convergence_check': ('fixed_point_detection', {}),

    # Algorithm archetypes
    'dynamic_programming': ('dp_optimization', {'technique': 'memoization'}),
    'greedy_selection':    ('greedy_optimization', {'technique': 'local_choice'}),
    'sliding_window':      ('window_optimization', {'technique': 'two_pointer'}),
}


class IdentityNormalizer:
    """Canonicalizes runtime identities into normal form."""

    @classmethod
    def normalize(cls, identity_graph: IdentityGraph, pdg=None) -> NormalForm:
        """Normalize all identities into canonical form."""
        nf = NormalForm()

        # Group identities by subject to merge related ones
        by_subject: Dict[str, List[SemanticIdentity]] = {}
        for ident in identity_graph.identities:
            by_subject.setdefault(ident.subject, []).append(ident)

        seen_canonical = set()

        for ident in identity_graph.identities:
            canonical = cls._canonicalize(ident, pdg)
            if canonical and canonical.canonical_id not in seen_canonical:
                nf.canonical_identities.append(canonical)
                seen_canonical.add(canonical.canonical_id)

        # Merge parallel state transitions
        nf.canonical_identities = cls._merge_parallel_transitions(nf.canonical_identities)

        # Compute signatures
        nf.algorithm_signature = cls._compute_algorithm_signature(nf)
        nf.structure_signature = cls._compute_structure_signature(nf)
        nf.control_signature = cls._compute_control_signature(nf)
        nf.complexity_shape = cls._compute_complexity_shape(nf, pdg)

        return nf

    @classmethod
    def _canonicalize(cls, ident: SemanticIdentity, pdg) -> Optional[CanonicalIdentity]:
        """Map a single identity to its canonical form."""
        entry = _CANONICALIZATION_TABLE.get(ident.archetype)
        if not entry:
            return None

        canonical_id, params = entry

        # Refine parameters based on evidence
        params = dict(params)
        if ident.archetype == 'memo_table' and pdg:
            params = cls._refine_memo_params(ident, pdg, params)
        elif ident.archetype == 'accumulator' and pdg:
            params = cls._refine_accumulator_params(ident, pdg, params)
        elif ident.archetype == 'state_transition' and pdg:
            params = cls._refine_transition_params(ident, pdg, params)

        return CanonicalIdentity(
            canonical_id=canonical_id,
            category=ident.category,
            parameters=params,
            source_identities=[ident.archetype],
            subjects=[ident.subject],
            confidence=ident.confidence,
            invariants=ident.invariants,
            behaviors=ident.behaviors,
        )

    @staticmethod
    def _refine_memo_params(ident, pdg, params):
        """Refine memo_table parameters from code evidence."""
        for nid in ident.evidence:
            node = pdg.nodes.get(nid)
            if not node:
                continue
            code = node.code
            if 'memo' in code:
                params['semantic_role'] = 'memoization'
            elif 'cache' in code:
                params['semantic_role'] = 'caching'
            elif 'dp' in code.lower():
                params['semantic_role'] = 'dp_table'
            elif 'lookup' in code.lower() or 'index' in code.lower():
                params['semantic_role'] = 'index'
            else:
                params['semantic_role'] = 'state_store'
        return params

    @staticmethod
    def _refine_accumulator_params(ident, pdg, params):
        """Refine accumulator parameters."""
        for nid in ident.evidence:
            node = pdg.nodes.get(nid)
            if not node:
                continue
            code = node.code
            if '+=' in code:
                params['operator'] = '+'
            elif '-=' in code:
                params['operator'] = '-'
                params['direction'] = 'decreasing'
            elif '*=' in code:
                params['operator'] = '*'
            elif 'sum' in code.lower():
                params['semantic_role'] = 'sum'
            elif 'count' in code.lower():
                params['semantic_role'] = 'count'
            elif 'total' in code.lower():
                params['semantic_role'] = 'total'
        return params

    @staticmethod
    def _refine_transition_params(ident, pdg, params):
        """Refine state transition parameters."""
        subjects = ident.subject if isinstance(ident.subject, list) else [ident.subject]
        # Find the tuple unpacking node
        for nid in ident.evidence:
            node = pdg.nodes.get(nid)
            if not node:
                continue
            code = node.code
            if ',' in code and '=' in code:
                lhs = code.split('=')[0].strip()
                vars_in_lhs = [v.strip() for v in lhs.split(',')]
                params['transition_vars'] = vars_in_lhs
                params['arity'] = len(vars_in_lhs)
        return params

    @staticmethod
    def _merge_parallel_transitions(identities: List[CanonicalIdentity]) -> List[CanonicalIdentity]:
        """Merge individual state_transition identities into parallel_state_transition."""
        transitions = [i for i in identities if i.canonical_id == 'parallel_state_transition']
        others = [i for i in identities if i.canonical_id != 'parallel_state_transition']

        if len(transitions) <= 1:
            return identities

        # Group by evidence overlap
        groups: List[List[CanonicalIdentity]] = []
        for t in transitions:
            placed = False
            for group in groups:
                # Check if evidence overlaps
                if any(s in t.subjects for g in group for s in g.subjects):
                    group.append(t)
                    placed = True
                    break
            if not placed:
                groups.append([t])

        merged = list(others)
        for group in groups:
            all_subjects = []
            all_source = []
            max_conf = 0
            for g in group:
                all_subjects.extend(g.subjects)
                all_source.extend(g.source_identities)
                max_conf = max(max_conf, g.confidence)

            merged.append(CanonicalIdentity(
                canonical_id='parallel_state_transition',
                category='variable',
                parameters={'transition_vars': sorted(set(all_subjects)), 'arity': len(set(all_subjects))},
                source_identities=sorted(set(all_source)),
                subjects=sorted(set(all_subjects)),
                confidence=max_conf,
                invariants=['atomic_swap', 'previous_value_used'],
                behaviors=['transitions', 'shifts_state'],
            ))

        return merged

    # ── Signature Computation ──

    @staticmethod
    def _compute_algorithm_signature(nf: NormalForm) -> str:
        algos = sorted(set(c.canonical_id for c in nf.canonical_identities if c.category == 'algorithm'))
        return '+'.join(algos) if algos else 'none'

    @staticmethod
    def _compute_structure_signature(nf: NormalForm) -> str:
        structs = sorted(set(c.canonical_id for c in nf.canonical_identities if c.category == 'structure'))
        return '+'.join(structs) if structs else 'none'

    @staticmethod
    def _compute_control_signature(nf: NormalForm) -> str:
        controls = sorted(set(c.canonical_id for c in nf.canonical_identities if c.category == 'control'))
        return '+'.join(controls) if controls else 'none'

    @staticmethod
    def _compute_complexity_shape(nf: NormalForm, pdg) -> str:
        """Infer complexity shape from canonical identities."""
        has_dp = any(c.canonical_id == 'dp_optimization' for c in nf.canonical_identities)
        has_loop = any(c.canonical_id == 'bounded_iterator' for c in nf.canonical_identities)
        has_nested = False

        if pdg:
            # Check for nested loops
            loop_headers = [n for n in pdg.nodes.values() if 'for' in n.code or 'while' in n.code]
            if len(loop_headers) >= 2:
                # Check indentation nesting
                for i, a in enumerate(loop_headers):
                    for b in loop_headers[i+1:]:
                        if b.indent > a.indent:
                            has_nested = True
                            break

        if has_dp and has_loop:
            return 'linear_iterative_dp'
        elif has_nested:
            return 'nested_iterative'
        elif has_loop:
            return 'linear_iterative'
        elif any(c.canonical_id == 'lifo_traversal' for c in nf.canonical_identities):
            return 'recursive_dfs'
        elif any(c.canonical_id == 'fifo_traversal' for c in nf.canonical_identities):
            return 'iterative_bfs'
        else:
            return 'sequential'
