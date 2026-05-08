"""Semantic Ontology — The world model of execution semantics.

Defines the taxonomy, relationships, and abstraction hierarchy of all
semantic concepts in the system. This is the "brain" that knows:

    memo_table is_a state_cache
    state_cache is_a key_value_storage
    memo_table enables dynamic_programming
    visited_set similar_to memo_table
    accumulator opposite_of stateless_computation

The ontology answers: "What is this thing, in the universe of all things?"

Structure:
    Concept → Category → Family → Species

    state_management
        state_cache
            memo_table
            visited_set
            lookup_table
        state_transition
            parallel_swap
            rolling_update

    traversal
        depth_first
            stack_dfs
            recursive_dfs
        breadth_first
            queue_bfs

    optimization
        dynamic_programming
            top_down_memo
            bottom_up_tab
        greedy
            local_choice
            sorted_greedy

Usage:
    ontology = SemanticOntology.default()
    concept = ontology.get('memo_table')
    print(concept.parents)       # ['state_cache']
    print(concept.children)      # ['top_down_memo']
    print(concept.related)       # [('enables', 'dynamic_programming'), ...]
    ancestors = ontology.ancestors('memo_table')  # ['state_cache', 'key_value_storage']
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class SemanticConcept:
    """A concept in the semantic ontology."""
    id: str                     # unique identifier, e.g., 'memo_table'
    label: str                  # human-readable name
    category: str               # top-level category
    family: str                 # sub-category

    # Taxonomy
    parents: List[str] = field(default_factory=list)     # is_a relationships
    children: List[str] = field(default_factory=list)     # subtypes

    # Semantics
    behaviors: List[str] = field(default_factory=list)    # what it does
    invariants: List[str] = field(default_factory=list)   # what must hold
    signatures: List[str] = field(default_factory=list)   # how to recognize it

    # Relationships
    related: List[Tuple[str, str]] = field(default_factory=list)  # (relation, target)

    # Metadata
    complexity_implication: str = ''   # e.g., 'O(1) lookup', 'O(n) traversal'
    common_mistakes: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'label': self.label,
            'category': self.category,
            'family': self.family,
            'parents': self.parents,
            'children': self.children,
            'behaviors': self.behaviors,
            'invariants': self.invariants,
            'signatures': self.signatures,
            'related': [{'relation': r, 'target': t} for r, t in self.related],
            'complexity_implication': self.complexity_implication,
            'common_mistakes': self.common_mistakes,
        }


class SemanticOntology:
    """The semantic world model."""

    def __init__(self):
        self.concepts: Dict[str, SemanticConcept] = {}
        # Indexes
        self._by_category: Dict[str, List[str]] = {}
        self._by_family: Dict[str, List[str]] = {}

    def add(self, concept: SemanticConcept):
        self.concepts[concept.id] = concept
        self._by_category.setdefault(concept.category, []).append(concept.id)
        self._by_family.setdefault(concept.family, []).append(concept.id)

    def get(self, concept_id: str) -> Optional[SemanticConcept]:
        return self.concepts.get(concept_id)

    def ancestors(self, concept_id: str) -> List[str]:
        """Get all ancestors (transitive is_a)."""
        result = []
        visited = set()
        queue = [concept_id]
        while queue:
            cid = queue.pop(0)
            if cid in visited:
                continue
            visited.add(cid)
            concept = self.concepts.get(cid)
            if concept:
                for parent in concept.parents:
                    if parent not in visited:
                        result.append(parent)
                        queue.append(parent)
        return result

    def descendants(self, concept_id: str) -> List[str]:
        """Get all descendants (transitive subtypes)."""
        result = []
        visited = set()
        queue = [concept_id]
        while queue:
            cid = queue.pop(0)
            if cid in visited:
                continue
            visited.add(cid)
            concept = self.concepts.get(cid)
            if concept:
                for child in concept.children:
                    if child not in visited:
                        result.append(child)
                        queue.append(child)
        return result

    def siblings(self, concept_id: str) -> List[str]:
        """Get concepts that share a parent."""
        concept = self.concepts.get(concept_id)
        if not concept:
            return []
        siblings = set()
        for parent_id in concept.parents:
            parent = self.concepts.get(parent_id)
            if parent:
                for child in parent.children:
                    if child != concept_id:
                        siblings.add(child)
        return sorted(siblings)

    def related_by(self, concept_id: str, relation: str) -> List[str]:
        """Get concepts related by a specific relation."""
        concept = self.concepts.get(concept_id)
        if not concept:
            return []
        return [t for r, t in concept.related if r == relation]

    def find_by_behavior(self, behavior: str) -> List[SemanticConcept]:
        """Find concepts that exhibit a behavior."""
        return [c for c in self.concepts.values() if behavior in c.behaviors]

    def find_by_invariant(self, invariant: str) -> List[SemanticConcept]:
        """Find concepts that share an invariant."""
        return [c for c in self.concepts.values() if invariant in c.invariants]

    def categories(self) -> List[str]:
        return sorted(self._by_category.keys())

    def families(self) -> List[str]:
        return sorted(self._by_family.keys())

    def category_members(self, category: str) -> List[SemanticConcept]:
        return [self.concepts[cid] for cid in self._by_category.get(category, [])]

    def family_members(self, family: str) -> List[SemanticConcept]:
        return [self.concepts[cid] for cid in self._by_family.get(family, [])]

    def path_between(self, from_id: str, to_id: str) -> Optional[List[str]]:
        """Find shortest path between two concepts."""
        if from_id == to_id:
            return [from_id]
        visited = set()
        queue = [(from_id, [from_id])]
        while queue:
            current, path = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            concept = self.concepts.get(current)
            if not concept:
                continue
            neighbors = concept.parents + concept.children + [t for _, t in concept.related]
            for neighbor in neighbors:
                if neighbor == to_id:
                    return path + [neighbor]
                if neighbor not in visited:
                    queue.append((neighbor, path + [neighbor]))
        return None

    def summary(self) -> dict:
        return {
            'total_concepts': len(self.concepts),
            'categories': {cat: len(ids) for cat, ids in self._by_category.items()},
            'families': {fam: len(ids) for fam, ids in self._by_family.items()},
            'total_relationships': sum(len(c.related) for c in self.concepts.values()),
        }

    def to_dict(self) -> dict:
        return {
            'concepts': {k: v.to_dict() for k, v in self.concepts.items()},
            'summary': self.summary(),
        }

    # ── Default Ontology ──

    @classmethod
    def default(cls) -> 'SemanticOntology':
        """Build the default execution semantics ontology."""
        ont = cls()

        # ── State Management ──

        ont.add(SemanticConcept(
            id='state_management', label='State Management',
            category='state', family='state_management',
            behaviors=['stores_runtime_state'],
        ))

        ont.add(SemanticConcept(
            id='state_cache', label='State Cache',
            category='state', family='state_management',
            parents=['state_management'],
            behaviors=['stores_intermediate_results', 'supports_lookup'],
            invariants=['key_stability', 'deterministic_lookup'],
            complexity_implication='O(1) amortized lookup',
        ))

        ont.add(SemanticConcept(
            id='memo_table', label='Memoization Table',
            category='state', family='state_management',
            parents=['state_cache'],
            behaviors=['caches_computed_values', 'prevents_recomputation'],
            invariants=['key_stability', 'value_immutability_after_write'],
            signatures=['dict_type', 'indexed_write', 'indexed_read'],
            complexity_implication='O(1) lookup, reduces exponential to polynomial',
            common_mistakes=['missing_cache_invalidation', 'wrong_key_type'],
            related=[('enables', 'dynamic_programming'), ('similar_to', 'visited_set'),
                     ('prevents', 'redundant_computation')],
        ))

        ont.add(SemanticConcept(
            id='visited_set', label='Visited Set',
            category='state', family='state_management',
            parents=['state_cache'],
            behaviors=['tracks_explored_states', 'prevents_cycles'],
            invariants=['no_duplicates', 'monotonic_growth'],
            signatures=['set_type', 'membership_test', 'add_operation'],
            complexity_implication='O(1) membership test',
            common_mistakes=['forgetting_to_add', 'wrong_equality'],
            related=[('prevents', 'infinite_loop'), ('similar_to', 'memo_table'),
                     ('enables', 'graph_traversal')],
        ))

        ont.add(SemanticConcept(
            id='lookup_table', label='Lookup Table',
            category='state', family='state_management',
            parents=['state_cache'],
            behaviors=['maps_keys_to_values', 'supports_random_access'],
            invariants=['key_uniqueness'],
            related=[('similar_to', 'memo_table')],
        ))

        ont.add(SemanticConcept(
            id='state_transition', label='State Transition',
            category='state', family='state_management',
            parents=['state_management'],
            behaviors=['transforms_state', 'advances_computation'],
            invariants=['deterministic_transition'],
            signatures=['tuple_unpack_self_ref'],
            related=[('enables', 'iterative_algorithm')],
        ))

        ont.add(SemanticConcept(
            id='parallel_swap', label='Parallel State Swap',
            category='state', family='state_management',
            parents=['state_transition'],
            behaviors=['atomically_swaps_multiple_variables'],
            invariants=['atomicity', 'previous_value_preservation'],
            signatures=['tuple_unpack', 'comma_assignment'],
            related=[('implements', 'fibonacci_recurrence')],
        ))

        ont.add(SemanticConcept(
            id='rolling_update', label='Rolling State Update',
            category='state', family='state_management',
            parents=['state_transition'],
            behaviors=['shifts_window_of_state'],
            invariants=['window_size_stability'],
            related=[('enables', 'sliding_window')],
        ))

        # ── Accumulation ──

        ont.add(SemanticConcept(
            id='accumulation', label='Accumulation',
            category='computation', family='accumulation',
            behaviors=['aggregates_values_over_time'],
        ))

        ont.add(SemanticConcept(
            id='monotonic_accumulator', label='Monotonic Accumulator',
            category='computation', family='accumulation',
            parents=['accumulation'],
            behaviors=['aggregates_with_single_direction'],
            invariants=['monotonic_growth', 'numeric_type'],
            signatures=['self_referential_update', 'augmented_assignment'],
            common_mistakes=['integer_overflow', 'wrong_direction'],
            related=[('driven_by', 'loop_counter')],
        ))

        ont.add(SemanticConcept(
            id='conditional_accumulator', label='Conditional Accumulator',
            category='computation', family='accumulation',
            parents=['accumulation'],
            behaviors=['aggregates_with_filter'],
            invariants=['selective_addition'],
            related=[('combines', 'predicate_filter')],
        ))

        # ── Iteration ──

        ont.add(SemanticConcept(
            id='iteration', label='Iteration',
            category='control', family='iteration',
            behaviors=['repeats_computation'],
        ))

        ont.add(SemanticConcept(
            id='bounded_iterator', label='Bounded Iterator',
            category='control', family='iteration',
            parents=['iteration'],
            behaviors=['iterates_over_finite_range'],
            invariants=['monotonic', 'bounded_range', 'integer'],
            signatures=['loop_header_target', 'range_iteration'],
            complexity_implication='O(n) where n = range',
            related=[('drives', 'monotonic_accumulator'), ('drives', 'memo_table')],
        ))

        ont.add(SemanticConcept(
            id='unbounded_iterator', label='Unbounded Iterator',
            category='control', family='iteration',
            parents=['iteration'],
            behaviors=['iterates_until_condition'],
            invariants=['termination_guarantee'],
            common_mistakes=['infinite_loop', 'missing_termination'],
        ))

        # ── Traversal ──

        ont.add(SemanticConcept(
            id='traversal', label='Graph Traversal',
            category='algorithm', family='traversal',
            behaviors=['visits_all_reachable_nodes'],
        ))

        ont.add(SemanticConcept(
            id='depth_first', label='Depth-First Traversal',
            category='algorithm', family='traversal',
            parents=['traversal'],
            behaviors=['explores_deeper_first'],
            invariants=['lifo_order'],
            related=[('uses', 'stack_dfs'), ('uses', 'visited_set')],
        ))

        ont.add(SemanticConcept(
            id='breadth_first', label='Breadth-First Traversal',
            category='algorithm', family='traversal',
            parents=['traversal'],
            behaviors=['explores_level_by_level'],
            invariants=['fifo_order', 'shortest_path_in_unweighted'],
            related=[('uses', 'queue_bfs'), ('uses', 'visited_set')],
        ))

        ont.add(SemanticConcept(
            id='stack_dfs', label='Stack-based DFS',
            category='structure', family='traversal',
            parents=['depth_first'],
            behaviors=['explicit_stack_management'],
            signatures=['append_pop_pattern'],
            related=[('implements', 'depth_first')],
        ))

        ont.add(SemanticConcept(
            id='queue_bfs', label='Queue-based BFS',
            category='structure', family='traversal',
            parents=['breadth_first'],
            behaviors=['explicit_queue_management'],
            signatures=['append_pop0_pattern'],
            related=[('implements', 'breadth_first')],
        ))

        # ── Optimization ──

        ont.add(SemanticConcept(
            id='optimization', label='Optimization Strategy',
            category='algorithm', family='optimization',
            behaviors=['improves_computational_efficiency'],
        ))

        ont.add(SemanticConcept(
            id='dynamic_programming', label='Dynamic Programming',
            category='algorithm', family='optimization',
            parents=['optimization'],
            behaviors=['memoizes_subproblems', 'builds_solution_incrementally'],
            invariants=['optimal_substructure', 'overlapping_subproblems'],
            complexity_implication='Reduces exponential to polynomial',
            common_mistakes=['missing_base_case', 'wrong_state_definition', 'missing_memoization'],
            related=[('enabled_by', 'memo_table'), ('uses', 'state_transition'),
                     ('opposite_of', 'brute_force')],
        ))

        ont.add(SemanticConcept(
            id='top_down_memo', label='Top-Down Memoization',
            category='algorithm', family='optimization',
            parents=['dynamic_programming'],
            behaviors=['recursive_with_cache'],
            invariants=['cache_hit_consistency'],
            related=[('uses', 'memo_table')],
        ))

        ont.add(SemanticConcept(
            id='bottom_up_tab', label='Bottom-Up Tabulation',
            category='algorithm', family='optimization',
            parents=['dynamic_programming'],
            behaviors=['iterative_table_filling'],
            invariants=['dependency_order'],
            related=[('uses', 'bounded_iterator')],
        ))

        ont.add(SemanticConcept(
            id='greedy', label='Greedy Strategy',
            category='algorithm', family='optimization',
            parents=['optimization'],
            behaviors=['makes_locally_optimal_choices'],
            invariants=['greedy_choice_property', 'optimal_substructure'],
            common_mistakes=['wrong_greedy_choice', 'missing_proof'],
            related=[('opposite_of', 'dynamic_programming')],
        ))

        ont.add(SemanticConcept(
            id='sliding_window', label='Sliding Window',
            category='algorithm', family='optimization',
            parents=['optimization'],
            behaviors=['maintains_window_invariant', 'slides_across_sequence'],
            invariants=['window_size_or_condition'],
            related=[('uses', 'rolling_update')],
        ))

        # ── Control Flow ──

        ont.add(SemanticConcept(
            id='dedup_guard', label='Deduplication Guard',
            category='control', family='guards',
            behaviors=['prevents_duplicate_processing'],
            invariants=['uniqueness_enforcement'],
            signatures=['membership_negation'],
            related=[('guards', 'visited_set')],
        ))

        ont.add(SemanticConcept(
            id='early_termination', label='Early Termination',
            category='control', family='guards',
            behaviors=['exits_before_normal_completion'],
            signatures=['conditional_return'],
            related=[('optimizes', 'iteration')],
        ))

        ont.add(SemanticConcept(
            id='convergence_check', label='Convergence Check',
            category='control', family='guards',
            behaviors=['detects_fixed_point'],
            invariants=['reaches_stable_state'],
            related=[('terminates', 'unbounded_iterator')],
        ))

        # ── Abstraction Hierarchy ──

        ont.add(SemanticConcept(
            id='key_value_storage', label='Key-Value Storage',
            category='abstraction', family='data_model',
            behaviors=['stores_pairs', 'supports_lookup'],
            children=['state_cache', 'lookup_table'],
        ))

        ont.add(SemanticConcept(
            id='brute_force', label='Brute Force',
            category='algorithm', family='optimization',
            parents=['optimization'],
            behaviors=['exhaustive_search'],
            complexity_implication='Exponential or factorial',
            related=[('opposite_of', 'dynamic_programming'), ('opposite_of', 'greedy')],
        ))

        return ont


# ─── Ontology-Aware Identity Enrichment ──────────────────────────

class OntologyEnricher:
    """Enriches semantic identities with ontology knowledge."""

    def __init__(self, ontology: SemanticOntology):
        self.ontology = ontology

    def enrich(self, identity) -> dict:
        """Add ontology context to a SemanticIdentity."""
        concept = self.ontology.get(identity.archetype)
        if not concept:
            return {}

        return {
            'concept': concept.label,
            'category': concept.category,
            'family': concept.family,
            'ancestors': self.ontology.ancestors(identity.archetype),
            'siblings': self.ontology.siblings(identity.archetype),
            'related_concepts': [
                {'relation': r, 'target': t, 'target_label': (self.ontology.get(t) or type('', (), {'label': t})).label}
                for r, t in concept.related
            ],
            'complexity_implication': concept.complexity_implication,
            'common_mistakes': concept.common_mistakes,
            'behaviors': concept.behaviors,
            'invariants': concept.invariants,
        }

    def enrich_graph(self, identity_graph) -> dict:
        """Enrich an entire identity graph with ontology context."""
        enriched = {}
        for ident in identity_graph.identities:
            enriched[ident.archetype] = self.enrich(ident)
        return enriched
