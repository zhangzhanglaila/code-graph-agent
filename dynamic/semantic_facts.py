"""Layer 1: Semantic Fact Extraction.

Transforms the raw PDG graph into high-level semantic facts:
- Data flow patterns (chain, fan-in, fan-out)
- Loop patterns (accumulation, iteration, filter)
- Control patterns (branch, guard, early return)
- Variable evolution (SSA chain, mutation, rebind)
- Causal patterns (root cause, divergence, convergence)

These facts are the bridge between the graph and natural language.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict


@dataclass
class SemanticFact:
    """A high-level semantic fact extracted from the PDG."""
    kind: str               # fact type (see FACT_KINDS below)
    subject: str            # primary entity (variable, step, block)
    description: str        # human-readable one-liner
    evidence: List[int]     # step indices that support this fact
    confidence: float = 1.0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'kind': self.kind,
            'subject': self.subject,
            'description': self.description,
            'evidence': self.evidence,
            'confidence': self.confidence,
            'metadata': self.metadata,
        }


# ─── Fact kinds ───────────────────────────────────────────────────
# data_flow.chain        — A → B → C (sequential data flow)
# data_flow.fan_in       — A, B → C (multiple sources converge)
# data_flow.fan_out      — A → B, C (one source feeds multiple targets)
# loop.accumulation      — var grows over loop iterations
# loop.iteration         — loop body executes N times
# loop.filter            — conditional inside loop filters items
# control.branch         — if/else creates two paths
# control.guard          — condition gates execution
# control.early_return   — return inside conditional
# variable.evolution     — SSA version chain for a variable
# variable.rebind        — variable reassigned to new object
# variable.mutation      — same object modified in place
# variable.alias         — two names point to same object
# causal.root_cause      — source with no incoming deps
# causal.convergence     — multiple paths lead to same result
# causal.divergence      — one point fans out to multiple effects


class FactExtractor:
    """Extracts semantic facts from a RuntimePDG.

    Usage:
        extractor = FactExtractor(pdg)
        facts = extractor.extract_all()
    """

    def __init__(self, pdg):
        self.pdg = pdg
        self._facts: List[SemanticFact] = []

    def extract_all(self) -> List[SemanticFact]:
        """Run all extractors and return deduplicated facts."""
        self._facts = []
        self._extract_variable_evolution()
        self._extract_data_flow_patterns()
        self._extract_loop_patterns()
        self._extract_control_patterns()
        self._extract_causal_patterns()
        return self._facts

    # ─── Variable Evolution ───────────────────────────────────────

    def _extract_variable_evolution(self) -> None:
        """Extract SSA version chains — the most powerful fact type."""
        # Group data edges by variable
        var_edges: Dict[str, list] = defaultdict(list)
        for edge in self.pdg.edges:
            if edge.kind == 'data' and edge.var:
                var_edges[edge.var].append(edge)

        for var_name, edges in var_edges.items():
            if len(edges) < 2:
                continue

            # Build version chain: sorted by target step
            chain = sorted(edges, key=lambda e: e.target)
            versions = []
            for edge in chain:
                src_node = self.pdg.nodes.get(edge.source)
                tgt_node = self.pdg.nodes.get(edge.target)
                if src_node and tgt_node:
                    src_val = src_node.vars.get(var_name)
                    tgt_val = tgt_node.vars.get(var_name)
                    versions.append({
                        'step': edge.target,
                        'version': edge.target_version,
                        'value': tgt_val.value if tgt_val else '?',
                        'code': tgt_node.code,
                    })

            if len(versions) >= 2:
                # Detect pattern: accumulation, oscillation, monotonic
                values = [v['value'] for v in versions]
                pattern = self._classify_evolution(values)

                self._facts.append(SemanticFact(
                    kind='variable.evolution',
                    subject=var_name,
                    description=self._describe_evolution(var_name, versions, pattern),
                    evidence=[v['step'] for v in versions],
                    metadata={
                        'versions': versions,
                        'pattern': pattern,
                        'total_versions': len(versions),
                    },
                ))

                # Detect mutation vs rebind
                for edge in chain:
                    tgt_node = self.pdg.nodes.get(edge.target)
                    if tgt_node and var_name in tgt_node.vars:
                        vv = tgt_node.vars[var_name]
                        if vv.is_changed and not vv.is_new:
                            # Check if same memory_id (mutation) or different (rebind)
                            src_node = self.pdg.nodes.get(edge.source)
                            if src_node and var_name in src_node.vars:
                                src_vv = src_node.vars[var_name]
                                if src_vv.memory_id == vv.memory_id:
                                    self._facts.append(SemanticFact(
                                        kind='variable.mutation',
                                        subject=var_name,
                                        description=f"`{var_name}` mutated in place at step #{edge.target}",
                                        evidence=[edge.target],
                                        metadata={'step': edge.target, 'code': tgt_node.code},
                                    ))
                                else:
                                    self._facts.append(SemanticFact(
                                        kind='variable.rebind',
                                        subject=var_name,
                                        description=f"`{var_name}` rebound to new object at step #{edge.target}",
                                        evidence=[edge.target],
                                        metadata={'step': edge.target, 'code': tgt_node.code},
                                    ))

    def _classify_evolution(self, values: list) -> str:
        """Classify the pattern of a variable's value evolution."""
        if len(values) < 2:
            return 'static'
        # Try numeric
        try:
            nums = [float(v) for v in values if v not in ('None', 'True', 'False', '{}', '[]', 'set()')]
            if len(nums) >= 2:
                if all(nums[i] <= nums[i+1] for i in range(len(nums)-1)):
                    return 'monotonic_increasing'
                if all(nums[i] >= nums[i+1] for i in range(len(nums)-1)):
                    return 'monotonic_decreasing'
                if all(nums[i] < nums[i+1] for i in range(len(nums)-1)):
                    return 'strictly_increasing'
        except (ValueError, TypeError):
            pass
        # Check for accumulation pattern (list/dict growing)
        if any('append' in str(v) or 'update' in str(v) for v in values):
            return 'accumulation'
        return 'changing'

    def _describe_evolution(self, var: str, versions: list, pattern: str) -> str:
        """Generate a human-readable description of variable evolution."""
        n = len(versions)
        first_val = versions[0]['value']
        last_val = versions[-1]['value']

        if pattern == 'monotonic_increasing':
            return f"`{var}` increases monotonically: {first_val} → ... → {last_val} ({n} versions)"
        elif pattern == 'monotonic_decreasing':
            return f"`{var}` decreases monotonically: {first_val} → ... → {last_val} ({n} versions)"
        elif pattern == 'strictly_increasing':
            return f"`{var}` grows: {first_val} → ... → {last_val} ({n} versions)"
        elif pattern == 'accumulation':
            return f"`{var}` accumulates over {n} iterations"
        else:
            return f"`{var}` evolves through {n} versions: {first_val} → ... → {last_val}"

    # ─── Data Flow Patterns ───────────────────────────────────────

    def _extract_data_flow_patterns(self) -> None:
        """Detect fan-in, fan-out, and chain patterns."""
        # Count incoming/outgoing data edges per node
        incoming: Dict[int, int] = defaultdict(int)
        outgoing: Dict[int, int] = defaultdict(int)
        incoming_vars: Dict[int, Set[str]] = defaultdict(set)
        outgoing_vars: Dict[int, Set[str]] = defaultdict(set)

        for edge in self.pdg.edges:
            if edge.kind == 'data':
                incoming[edge.target] += 1
                outgoing[edge.source] += 1
                incoming_vars[edge.target].add(edge.var)
                outgoing_vars[edge.source].add(edge.var)

        # Fan-in: node reads from multiple different variables/sources
        for node_id, count in incoming.items():
            if count >= 3 and len(incoming_vars[node_id]) >= 2:
                node = self.pdg.nodes.get(node_id)
                if node:
                    self._facts.append(SemanticFact(
                        kind='data_flow.fan_in',
                        subject=node.code,
                        description=f"Step #{node_id} converges {count} data flows from {len(incoming_vars[node_id])} variables",
                        evidence=[node_id],
                        metadata={
                            'step': node_id,
                            'incoming_count': count,
                            'variables': sorted(incoming_vars[node_id]),
                        },
                    ))

        # Fan-out: node feeds into multiple different targets
        for node_id, count in outgoing.items():
            if count >= 3 and len(outgoing_vars[node_id]) >= 2:
                node = self.pdg.nodes.get(node_id)
                if node:
                    self._facts.append(SemanticFact(
                        kind='data_flow.fan_out',
                        subject=node.code,
                        description=f"Step #{node_id} fans out to {count} downstream steps",
                        evidence=[node_id],
                        metadata={
                            'step': node_id,
                            'outgoing_count': count,
                            'variables': sorted(outgoing_vars[node_id]),
                        },
                    ))

    # ─── Loop Patterns ────────────────────────────────────────────

    def _extract_loop_patterns(self) -> None:
        """Detect loop accumulation, iteration, and filter patterns."""
        # Find loop headers (for/while with control edges to body)
        loop_headers: Dict[int, List[int]] = defaultdict(list)
        for edge in self.pdg.edges:
            if edge.kind == 'control':
                src_node = self.pdg.nodes.get(edge.source)
                if src_node and ('for ' in src_node.code or 'while ' in src_node.code):
                    loop_headers[edge.source].append(edge.target)

        for header_id, body_ids in loop_headers.items():
            header_node = self.pdg.nodes.get(header_id)
            if not header_node:
                continue

            # Count iterations (how many times body steps appear)
            body_set = set(body_ids)
            iteration_count = len(body_ids) // max(1, len(set(
                self.pdg.nodes[bid].line for bid in body_ids if bid in self.pdg.nodes
            )))

            self._facts.append(SemanticFact(
                kind='loop.iteration',
                subject=header_node.code,
                description=f"Loop executes {iteration_count} iterations",
                evidence=[header_id] + sorted(body_set)[:5],
                metadata={
                    'header_step': header_id,
                    'body_steps': sorted(body_set),
                    'iterations': iteration_count,
                },
            ))

            # Detect accumulation: variables that grow across iterations
            # Find variables written inside the loop body
            body_writes: Dict[str, List[int]] = defaultdict(list)
            for bid in body_set:
                node = self.pdg.nodes.get(bid)
                if node:
                    for w in node.ast_writes:
                        body_writes[w].append(bid)

            for var, write_steps in body_writes.items():
                if len(write_steps) >= 2:
                    self._facts.append(SemanticFact(
                        kind='loop.accumulation',
                        subject=var,
                        description=f"`{var}` is written {len(write_steps)} times across loop iterations",
                        evidence=sorted(write_steps),
                        metadata={'variable': var, 'write_count': len(write_steps)},
                    ))

            # Detect filter: conditional inside loop body
            for bid in body_set:
                node = self.pdg.nodes.get(bid)
                if node and ('if ' in node.code or 'elif ' in node.code):
                    self._facts.append(SemanticFact(
                        kind='loop.filter',
                        subject=node.code,
                        description=f"Loop filters items via `{node.code.strip()}`",
                        evidence=[bid, header_id],
                        metadata={'condition_step': bid, 'loop_header': header_id},
                    ))

    # ─── Control Patterns ─────────────────────────────────────────

    def _extract_control_patterns(self) -> None:
        """Detect branch, guard, and early return patterns."""
        # Find branch points (if/elif/else)
        for node in self.pdg.nodes.values():
            if node.code.startswith(('if ', 'elif ')):
                # Find what this condition controls
                controlled = [
                    e.target for e in self.pdg.edges
                    if e.kind == 'control' and e.source == node.id
                ]
                if controlled:
                    self._facts.append(SemanticFact(
                        kind='control.branch',
                        subject=node.code,
                        description=f"Branch `{node.code.strip()}` controls {len(controlled)} steps",
                        evidence=[node.id] + controlled[:3],
                        metadata={
                            'condition_step': node.id,
                            'controlled_steps': controlled,
                        },
                    ))

            # Early return detection
            if node.code.startswith('return ') and node.indent > 0:
                self._facts.append(SemanticFact(
                    kind='control.early_return',
                    subject=node.code,
                    description=f"Early return at step #{node.id}: `{node.code.strip()}`",
                    evidence=[node.id],
                    metadata={'step': node.id, 'indent': node.indent},
                ))

    # ─── Causal Patterns ──────────────────────────────────────────

    def _extract_causal_patterns(self) -> None:
        """Detect root causes, convergence, and divergence."""
        # Root causes: nodes with no incoming data edges
        incoming_data: Set[int] = set()
        for edge in self.pdg.edges:
            if edge.kind == 'data':
                incoming_data.add(edge.target)

        for node in self.pdg.nodes.values():
            if node.id not in incoming_data and node.ast_writes:
                self._facts.append(SemanticFact(
                    kind='causal.root_cause',
                    subject=node.code,
                    description=f"Root cause: `{node.code.strip()}` — source of data flow",
                    evidence=[node.id],
                    metadata={'step': node.id, 'writes': node.ast_writes},
                ))

        # Convergence: nodes that combine multiple data flows
        incoming_count: Dict[int, int] = defaultdict(int)
        for edge in self.pdg.edges:
            if edge.kind == 'data':
                incoming_count[edge.target] += 1

        for node_id, count in incoming_count.items():
            if count >= 3:
                node = self.pdg.nodes.get(node_id)
                if node:
                    self._facts.append(SemanticFact(
                        kind='causal.convergence',
                        subject=node.code,
                        description=f"Convergence point: `{node.code.strip()}` receives {count} data flows",
                        evidence=[node_id],
                        metadata={'step': node_id, 'incoming_count': count},
                    ))
