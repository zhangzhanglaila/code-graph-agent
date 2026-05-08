"""Semantic Identity — Recognize WHAT something is, not just WHAT it does.

Two different code snippets can be semantically identical:
    memo[i] = a          →  dynamic_programming_state_write
    cache[k] = v          →  dynamic_programming_state_write
    lookup[key] = compute →  dynamic_programming_state_write

This module identifies semantic archetypes from runtime behavior.

Identity categories:
    Variable Archetypes:  loop_counter, memo_table, accumulator, state_transition
    Control Archetypes:   dedup_guard, cycle_prevention, convergence_check
    Structure Archetypes: stack_dfs, queue_bfs, heap_priority, hash_lookup
    Algorithm Archetypes: dynamic_programming, greedy, divide_and_conquer, sliding_window

Each identity carries:
    - invariants:  properties that must hold (e.g., counter is monotonic)
    - signatures:  behavioral patterns that indicate this identity
    - behaviors:   what this identity does (e.g., accumulates, caches, traverses)

Usage:
    identities = SemanticIdentifier.identify(pdg, facts)
    for ident in identities:
        print(ident.archetype, ident.confidence, ident.evidence)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Any
import re


# ─── Identity Data Model ────────────────────────────────────────

@dataclass
class SemanticIdentity:
    """A recognized semantic archetype in the execution."""
    archetype: str          # e.g., 'loop_counter', 'memo_table', 'accumulator'
    category: str           # 'variable' | 'control' | 'structure' | 'algorithm'
    subject: str            # what it applies to (variable name, node id, etc.)
    confidence: float       # 0.0 - 1.0
    invariants: List[str]   # properties that must hold
    signatures: List[str]   # behavioral patterns detected
    behaviors: List[str]    # what this identity does
    evidence: List[int]     # step IDs that support this identity
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'archetype': self.archetype,
            'category': self.category,
            'subject': self.subject,
            'confidence': round(self.confidence, 3),
            'invariants': self.invariants,
            'signatures': self.signatures,
            'behaviors': self.behaviors,
            'evidence': self.evidence[:10],
            'metadata': self.metadata,
        }

    def describe(self) -> str:
        inv = ', '.join(self.invariants[:3]) if self.invariants else 'none'
        return f'{self.archetype}({self.subject}) conf={self.confidence:.2f} invariants=[{inv}]'


@dataclass
class IdentityGraph:
    """All identities in an execution, with relationships."""
    identities: List[SemanticIdentity] = field(default_factory=list)
    # Relationships between identities
    relationships: List[Tuple[str, str, str]] = field(default_factory=list)  # (from, to, type)

    def by_archetype(self, archetype: str) -> List[SemanticIdentity]:
        return [i for i in self.identities if i.archetype == archetype]

    def by_category(self, category: str) -> List[SemanticIdentity]:
        return [i for i in self.identities if i.category == category]

    def by_subject(self, subject: str) -> List[SemanticIdentity]:
        return [i for i in self.identities if i.subject == subject]

    def top(self, n: int = 10) -> List[SemanticIdentity]:
        return sorted(self.identities, key=lambda i: -i.confidence)[:n]

    def summary(self) -> str:
        cats = {}
        for ident in self.identities:
            cats[ident.category] = cats.get(ident.category, 0) + 1
        parts = [f'{cat}: {n}' for cat, n in sorted(cats.items())]
        return f'IdentityGraph: {len(self.identities)} identities ({", ".join(parts)})'

    def to_dict(self) -> dict:
        return {
            'identities': [i.to_dict() for i in self.identities],
            'relationships': [{'from': a, 'to': b, 'type': t} for a, b, t in self.relationships],
            'summary': self.summary(),
        }


# ─── Semantic Identifier ────────────────────────────────────────

class SemanticIdentifier:
    """Recognizes semantic archetypes from SemanticExecutionModel (or RuntimePDG)."""

    @classmethod
    def identify(cls, model, facts) -> IdentityGraph:
        """Identify all semantic archetypes in an execution."""
        graph = IdentityGraph()

        # Run all recognizers
        cls._recognize_variable_archetypes(model, facts, graph)
        cls._recognize_control_archetypes(model, facts, graph)
        cls._recognize_structure_archetypes(model, facts, graph)
        cls._recognize_algorithm_archetypes(model, facts, graph)

        # Deduplicate and rank
        graph.identities = cls._deduplicate(graph.identities)
        graph.identities.sort(key=lambda i: -i.confidence)

        # Infer relationships
        cls._infer_relationships(graph)

        return graph

    # ── Variable Archetypes ──

    @classmethod
    def _recognize_variable_archetypes(cls, pdg, facts, graph: IdentityGraph):
        for var_name in cls._get_all_variables(pdg):
            history = pdg.get_variable_history(var_name)
            if len(history) < 2:
                continue

            cls._check_loop_counter(var_name, history, pdg, facts, graph)
            cls._check_accumulator(var_name, history, pdg, facts, graph)
            cls._check_memo_table(var_name, history, pdg, facts, graph)
            cls._check_state_transition(var_name, history, pdg, facts, graph)
            cls._check_boundary_condition(var_name, history, pdg, facts, graph)
            cls._check_visited_set(var_name, history, pdg, facts, graph)

    @classmethod
    def _check_loop_counter(cls, var, history, pdg, facts, graph):
        """Detect loop counter: i in for i in range(n)"""
        signatures = []
        invariants = []
        confidence = 0.0

        # Signature 1: monotonic increment
        values = [int(vv.value) for _, vv in history if vv.value.lstrip('-').isdigit()]
        if len(values) >= 3:
            diffs = [values[i+1] - values[i] for i in range(len(values)-1)]
            if all(d == 1 for d in diffs):
                signatures.append('monotonic_increment_by_1')
                confidence += 0.4
            elif all(d >= 0 for d in diffs):
                signatures.append('monotonic_non_decreasing')
                confidence += 0.2

        # Signature 2: used in loop header
        for node in pdg.nodes.values():
            if var in node.ast_reads and 'for' in node.code and 'range' in node.code:
                signatures.append('loop_header_target')
                confidence += 0.4
                break

        # Signature 3: used as index
        for node in pdg.nodes.values():
            if var in node.ast_reads and ('[' in node.code and ']' in node.code):
                signatures.append('used_as_index')
                confidence += 0.1
                break

        if confidence >= 0.4:
            graph.identities.append(SemanticIdentity(
                archetype='loop_counter',
                category='variable',
                subject=var,
                confidence=min(confidence, 1.0),
                invariants=['monotonic', 'bounded_range', 'integer'],
                signatures=signatures,
                behaviors=['iterates', 'indexes'],
                evidence=[sid for sid, _ in history[:5]],
            ))

    @classmethod
    def _check_accumulator(cls, var, history, pdg, facts, graph):
        """Detect accumulator: total += x, sum = sum + val"""
        signatures = []
        confidence = 0.0

        # Signature 1: augmented assignment
        for node in pdg.nodes.values():
            if var in node.ast_writes and var in node.ast_reads:
                code = node.code
                if f'{var} +=' in code or f'{var} =' in code:
                    signatures.append('self_referential_update')
                    confidence += 0.5
                    break

        # Signature 2: values are monotonically increasing
        values = []
        for _, vv in history:
            try:
                values.append(float(vv.value))
            except (ValueError, TypeError):
                pass
        if len(values) >= 3:
            if all(values[i+1] >= values[i] for i in range(len(values)-1)):
                signatures.append('monotonic_growth')
                confidence += 0.3

        # Signature 3: numeric type
        if history and history[0][1].type in ('int', 'float'):
            signatures.append('numeric_type')
            confidence += 0.1

        if confidence >= 0.4:
            graph.identities.append(SemanticIdentity(
                archetype='accumulator',
                category='variable',
                subject=var,
                confidence=min(confidence, 1.0),
                invariants=['monotonic_growth', 'numeric'],
                signatures=signatures,
                behaviors=['aggregates', 'sums'],
                evidence=[sid for sid, _ in history[:5]],
            ))

    @classmethod
    def _check_memo_table(cls, var, history, pdg, facts, graph):
        """Detect memo/cache table: memo[key] = value"""
        signatures = []
        confidence = 0.0

        # Signature 1: dict type
        if history and history[0][1].type == 'dict':
            signatures.append('dict_type')
            confidence += 0.3

        # Signature 2: indexed write
        for node in pdg.nodes.values():
            if var in node.ast_reads and re.search(rf'{var}\[.+\]\s*=', node.code):
                signatures.append('indexed_write')
                confidence += 0.4
                break

        # Signature 3: indexed read (lookup)
        for node in pdg.nodes.values():
            if var in node.ast_reads and re.search(rf'{var}\[.+\]', node.code) and '=' not in node.code.split(var)[0]:
                signatures.append('indexed_read')
                confidence += 0.2
                break

        # Signature 4: growing size
        sizes = []
        for _, vv in history:
            try:
                sizes.append(len(eval(vv.value)) if vv.value.startswith('{') else 0)
            except:
                pass
        if len(sizes) >= 2 and all(sizes[i+1] >= sizes[i] for i in range(len(sizes)-1)):
            signatures.append('growing_size')
            confidence += 0.2

        if confidence >= 0.4:
            graph.identities.append(SemanticIdentity(
                archetype='memo_table',
                category='variable',
                subject=var,
                confidence=min(confidence, 1.0),
                invariants=['key_value_mapping', 'monotonic_growth'],
                signatures=signatures,
                behaviors=['caches', 'lookups', 'stores'],
                evidence=[sid for sid, _ in history[:5]],
            ))

    @classmethod
    def _check_state_transition(cls, var, history, pdg, facts, graph):
        """Detect state variable: a, b = b, a + b"""
        signatures = []
        confidence = 0.0

        # Signature 1: tuple unpacking with self-reference
        for node in pdg.nodes.values():
            if var in node.ast_writes and var in node.ast_reads:
                code = node.code
                if ',' in code and '=' in code:
                    lhs, rhs = code.split('=', 1)
                    if var in lhs and var in rhs:
                        signatures.append('tuple_unpack_self_ref')
                        confidence += 0.5

        # Signature 2: paired with another variable
        for node in pdg.nodes.values():
            if var in node.ast_writes:
                other_writes = [w for w in node.ast_writes if w != var]
                if other_writes:
                    signatures.append(f'paired_with_{other_writes[0]}')
                    confidence += 0.3

        if confidence >= 0.4:
            graph.identities.append(SemanticIdentity(
                archetype='state_transition',
                category='variable',
                subject=var,
                confidence=min(confidence, 1.0),
                invariants=['previous_value_used', 'atomic_swap'],
                signatures=signatures,
                behaviors=['transitions', 'shifts_state'],
                evidence=[sid for sid, _ in history[:5]],
            ))

    @classmethod
    def _check_boundary_condition(cls, var, history, pdg, facts, graph):
        """Detect boundary/guard variable"""
        signatures = []
        confidence = 0.0

        # Used in condition
        for node in pdg.nodes.values():
            if var in node.ast_reads and ('if' in node.code or 'while' in node.code):
                signatures.append('used_in_condition')
                confidence += 0.4
                break

        # Boolean or comparison result
        if history and history[0][1].type == 'bool':
            signatures.append('boolean_type')
            confidence += 0.3

        if confidence >= 0.4:
            graph.identities.append(SemanticIdentity(
                archetype='boundary_condition',
                category='variable',
                subject=var,
                confidence=min(confidence, 1.0),
                invariants=['boolean_guard'],
                signatures=signatures,
                behaviors=['guards', 'controls_flow'],
                evidence=[sid for sid, _ in history[:3]],
            ))

    @classmethod
    def _check_visited_set(cls, var, history, pdg, facts, graph):
        """Detect visited/seen set"""
        signatures = []
        confidence = 0.0

        # Set type
        if history and history[0][1].type == 'set':
            signatures.append('set_type')
            confidence += 0.3

        # Membership test
        for node in pdg.nodes.values():
            if var in node.ast_reads and ('in ' + var in node.code or 'not in' in node.code):
                signatures.append('membership_test')
                confidence += 0.4
                break

        # Add operation
        for node in pdg.nodes.values():
            if var in node.ast_reads and '.add(' in node.code:
                signatures.append('add_operation')
                confidence += 0.2
                break

        if confidence >= 0.4:
            graph.identities.append(SemanticIdentity(
                archetype='visited_set',
                category='variable',
                subject=var,
                confidence=min(confidence, 1.0),
                invariants=['no_duplicates', 'monotonic_growth'],
                signatures=signatures,
                behaviors=['tracks_visited', 'prevents_cycles'],
                evidence=[sid for sid, _ in history[:5]],
            ))

    # ── Control Archetypes ──

    @classmethod
    def _recognize_control_archetypes(cls, pdg, facts, graph: IdentityGraph):
        for nid, node in pdg.nodes.items():
            code = node.code

            # Dedup guard: if x not in seen
            if 'not in' in code and ('seen' in code or 'visited' in code or 'memo' in code):
                graph.identities.append(SemanticIdentity(
                    archetype='dedup_guard',
                    category='control',
                    subject=f'step#{nid}',
                    confidence=0.8,
                    invariants=['prevents_duplicate_processing'],
                    signatures=['membership_negation'],
                    behaviors=['filters_duplicates'],
                    evidence=[nid],
                ))

            # Early return
            if code.strip().startswith('return') and nid < max(pdg.nodes.keys()):
                # Check if this is inside a condition
                for other in pdg.nodes.values():
                    if other.indent < node.indent and 'if' in other.code:
                        graph.identities.append(SemanticIdentity(
                            archetype='early_termination',
                            category='control',
                            subject=f'step#{nid}',
                            confidence=0.6,
                            invariants=['terminates_before_normal_flow'],
                            signatures=['conditional_return'],
                            behaviors=['short_circuits'],
                            evidence=[nid],
                        ))
                        break

            # Convergence check
            if any(f.kind == 'loop.accumulation' for f in facts if nid in f.evidence):
                for f in facts:
                    if f.kind == 'loop.accumulation' and nid in f.evidence:
                        if 'converge' in f.description.lower() or 'stable' in f.description.lower():
                            graph.identities.append(SemanticIdentity(
                                archetype='convergence_check',
                                category='control',
                                subject=f'step#{nid}',
                                confidence=0.7,
                                invariants=['reaches_fixed_point'],
                                signatures=['stability_detected'],
                                behaviors=['converges'],
                                evidence=[nid],
                            ))

    # ── Structure Archetypes ──

    @classmethod
    def _recognize_structure_archetypes(cls, pdg, facts, graph: IdentityGraph):
        all_code = ' '.join(n.code for n in pdg.nodes.values())

        # Stack (DFS)
        if '.append(' in all_code and '.pop()' in all_code:
            graph.identities.append(SemanticIdentity(
                archetype='stack_dfs',
                category='structure',
                subject='execution',
                confidence=0.8,
                invariants=['lifo_order'],
                signatures=['append_pop_pattern'],
                behaviors=['depth_first_traversal'],
                evidence=[n.id for n in pdg.nodes.values() if '.append(' in n.code or '.pop()' in n.code][:5],
            ))

        # Queue (BFS)
        if '.append(' in all_code and '.pop(0)' in all_code:
            graph.identities.append(SemanticIdentity(
                archetype='queue_bfs',
                category='structure',
                subject='execution',
                confidence=0.8,
                invariants=['fifo_order'],
                signatures=['append_pop0_pattern'],
                behaviors=['breadth_first_traversal'],
                evidence=[n.id for n in pdg.nodes.values() if '.append(' in n.code or '.pop(0)' in n.code][:5],
            ))

        # Heap/Priority Queue
        if 'heapq' in all_code or 'heappush' in all_code or 'heappop' in all_code:
            graph.identities.append(SemanticIdentity(
                archetype='heap_priority',
                category='structure',
                subject='execution',
                confidence=0.9,
                invariants=['min_heap_order'],
                signatures=['heapq_operations'],
                behaviors=['priority_selection'],
                evidence=[n.id for n in pdg.nodes.values() if 'heap' in n.code][:5],
            ))

        # Hash lookup
        lookup_count = sum(1 for n in pdg.nodes.values() if re.search(r'\w+\[.+\]', n.code) and '=' not in n.code.split('[')[0])
        if lookup_count >= 3:
            graph.identities.append(SemanticIdentity(
                archetype='hash_lookup',
                category='structure',
                subject='execution',
                confidence=0.6,
                invariants=['o1_access'],
                signatures=[f'{lookup_count}_indexed_reads'],
                behaviors=['constant_time_lookup'],
                evidence=[n.id for n in pdg.nodes.values() if re.search(r'\w+\[.+\]', n.code)][:5],
            ))

    # ── Algorithm Archetypes ──

    @classmethod
    def _recognize_algorithm_archetypes(cls, pdg, facts, graph: IdentityGraph):
        # Dynamic Programming
        dp_signals = 0
        if graph.by_archetype('memo_table'):
            dp_signals += 1
        if any(f.kind == 'loop.accumulation' for f in facts):
            dp_signals += 1
        if graph.by_archetype('state_transition'):
            dp_signals += 1
        # Check for overlapping subproblems (same index written multiple times)
        index_writes = {}
        for node in pdg.nodes.values():
            m = re.search(r'(\w+)\[(.+?)\]\s*=', node.code)
            if m:
                var, idx = m.group(1), m.group(2)
                index_writes.setdefault(var, set()).add(idx)
        for var, indices in index_writes.items():
            if len(indices) > 2:
                dp_signals += 1
                break

        if dp_signals >= 2:
            graph.identities.append(SemanticIdentity(
                archetype='dynamic_programming',
                category='algorithm',
                subject='execution',
                confidence=min(0.5 + dp_signals * 0.15, 0.95),
                invariants=['optimal_substructure', 'overlapping_subproblems'],
                signatures=[f'{dp_signals}_dp_signals'],
                behaviors=['memoizes', 'builds_solution_bottom_up'],
                evidence=[],
                metadata={'signals': dp_signals},
            ))

        # Greedy
        greedy_signals = 0
        if any(f.kind == 'control.branch' for f in facts):
            greedy_signals += 1
        # Check for sorting before processing
        has_sort = any('sorted' in n.code or '.sort' in n.code for n in pdg.nodes.values())
        if has_sort:
            greedy_signals += 1
        # Check for min/max selection
        has_minmax = any('min(' in n.code or 'max(' in n.code for n in pdg.nodes.values())
        if has_minmax:
            greedy_signals += 1

        if greedy_signals >= 2:
            graph.identities.append(SemanticIdentity(
                archetype='greedy_selection',
                category='algorithm',
                subject='execution',
                confidence=min(0.4 + greedy_signals * 0.15, 0.85),
                invariants=['locally_optimal_choice'],
                signatures=[f'{greedy_signals}_greedy_signals'],
                behaviors=['selects_locally_optimal', 'sorts_then_processes'],
                evidence=[],
                metadata={'signals': greedy_signals},
            ))

        # Sliding Window
        window_signals = 0
        for node in pdg.nodes.values():
            code = node.code
            if re.search(r'while.*<.*len\(', code) or re.search(r'for.*range.*len\(', code):
                window_signals += 1
            if 'window' in code.lower() or 'left' in code.lower() and 'right' in code.lower():
                window_signals += 1
        if window_signals >= 1:
            # Check for two-pointer pattern
            ptr_vars = set()
            for node in pdg.nodes.values():
                if node.code.count('+=') >= 1 and any(v in node.code for v in ['left', 'right', 'start', 'end', 'i', 'j']):
                    ptr_vars.update(node.ast_writes)
            if len(ptr_vars) >= 2:
                window_signals += 1

        if window_signals >= 2:
            graph.identities.append(SemanticIdentity(
                archetype='sliding_window',
                category='algorithm',
                subject='execution',
                confidence=min(0.4 + window_signals * 0.15, 0.85),
                invariants=['window_invariant'],
                signatures=[f'{window_signals}_window_signals'],
                behaviors=['slides_window', 'maintains_subarray'],
                evidence=[],
                metadata={'signals': window_signals},
            ))

    # ── Helpers ──

    @staticmethod
    def _get_all_variables(pdg) -> Set[str]:
        vars = set()
        for node in pdg.nodes.values():
            vars.update(node.vars.keys())
        return vars

    @staticmethod
    def _deduplicate(identities: List[SemanticIdentity]) -> List[SemanticIdentity]:
        """Remove duplicate identities, keeping highest confidence."""
        best: Dict[str, SemanticIdentity] = {}
        for ident in identities:
            key = f'{ident.archetype}:{ident.subject}'
            if key not in best or ident.confidence > best[key].confidence:
                best[key] = ident
        return list(best.values())

    @staticmethod
    def _infer_relationships(graph: IdentityGraph):
        """Infer relationships between identities."""
        # memo_table → dynamic_programming
        for memo in graph.by_archetype('memo_table'):
            for dp in graph.by_archetype('dynamic_programming'):
                graph.relationships.append((memo.archetype, dp.archetype, 'enables'))

        # loop_counter + accumulator → aggregation pattern
        for counter in graph.by_archetype('loop_counter'):
            for acc in graph.by_archetype('accumulator'):
                graph.relationships.append((counter.archetype, acc.archetype, 'drives'))

        # state_transition → algorithm progression
        for st in graph.by_archetype('state_transition'):
            for dp in graph.by_archetype('dynamic_programming'):
                graph.relationships.append((st.archetype, dp.archetype, 'implements'))

        # visited_set + stack_dfs → graph traversal
        for vs in graph.by_archetype('visited_set'):
            for stack in graph.by_archetype('stack_dfs'):
                graph.relationships.append((vs.archetype, stack.archetype, 'guards'))
            for queue in graph.by_archetype('queue_bfs'):
                graph.relationships.append((vs.archetype, queue.archetype, 'guards'))
