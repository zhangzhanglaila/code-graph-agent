"""Runtime Program Dependence Graph (PDG).

Decouples the graph structure from the raw execution timeline.
Provides a unified query interface for slicing, impact analysis,
and causal reasoning over dynamic execution data.

Graph structure:
    RuntimeNode — one per execution step
    RuntimeEdge — data / control / call / parameter dependencies
    RuntimePDG  — the graph with query methods
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from collections import defaultdict, deque


@dataclass
class VarVersion:
    """A variable's state at a specific program point."""
    name: str
    version: int            # SSA version
    value: str              # repr
    type: str
    memory_id: int
    is_changed: bool = False
    is_new: bool = False


@dataclass
class RuntimeNode:
    """A node in the Program Dependence Graph — one per execution step."""
    id: int                 # step_index
    line: int
    code: str
    func: str
    vars: Dict[str, VarVersion]
    ast_reads: List[str]
    ast_writes: List[str]
    ssa_versions: Dict[str, int]
    depth: int = 0
    call_id: int = 0
    block_id: int = 0
    indent: int = 0


@dataclass
class RuntimeEdge:
    """A directed edge in the PDG."""
    source: int             # source node id (step_index)
    target: int             # target node id
    kind: str               # 'data' | 'control' | 'call' | 'parameter' | 'return'
    var: str = ''           # variable name (for data edges)
    source_version: int = 0
    target_version: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass
class SliceResult:
    """Result of a backward or forward slice."""
    target_step: int
    target_var: str
    steps: List[int]                # step indices in the slice
    edges: List[RuntimeEdge]        # edges traversed
    root_causes: List[int]          # steps with no incoming deps in the slice
    depth_map: Dict[int, int]       # step → distance from target
    explanation: List[str]          # human-readable explanation lines


class RuntimePDG:
    """Program Dependence Graph built from an ExecutionTimeline.

    Provides:
    - Unified graph structure (nodes + typed edges)
    - Backward / forward slicing
    - Variable history queries
    - Path finding between nodes
    - Graph statistics
    """

    def __init__(self):
        self.nodes: Dict[int, RuntimeNode] = {}
        self.edges: List[RuntimeEdge] = []
        # Indexes for fast lookup
        self._edges_from: Dict[int, List[RuntimeEdge]] = defaultdict(list)
        self._edges_to: Dict[int, List[RuntimeEdge]] = defaultdict(list)
        self._data_edges: Dict[Tuple[int, str], List[RuntimeEdge]] = defaultdict(list)

    # ─── Construction ─────────────────────────────────────────────

    @classmethod
    def from_timeline(cls, timeline) -> 'RuntimePDG':
        """Build a RuntimePDG from an ExecutionTimeline."""
        pdg = cls()

        # Build nodes
        for step in timeline.steps:
            var_versions = {}
            for name, snap in step.variables.items():
                var_versions[name] = VarVersion(
                    name=name,
                    version=step.ssa_versions.get(name, 0),
                    value=snap.value_repr,
                    type=snap.value_type,
                    memory_id=snap.memory_id,
                    is_changed=name in step.changed_vars,
                    is_new=name in step.new_vars,
                )
            node = RuntimeNode(
                id=step.step_index,
                line=step.line_number,
                code=step.code_line,
                func=step.function_name,
                vars=var_versions,
                ast_reads=step.ast_reads,
                ast_writes=step.ast_writes,
                ssa_versions=step.ssa_versions,
                depth=step.depth,
                call_id=step.call_id,
                block_id=step.block_id,
                indent=step.indent,
            )
            pdg.add_node(node)

        # Build data edges from RAW dependencies
        for dd in timeline.data_dependencies:
            pdg.add_edge(RuntimeEdge(
                source=dd.source_step,
                target=dd.target_step,
                kind='data',
                var=dd.variable,
                source_version=dd.source_version,
                target_version=dd.target_version,
            ))

        # Build control edges from block_meta
        block_meta = timeline.block_meta or {}
        step_to_block = {s.step_index: s.block_id for s in timeline.steps}
        for bid, meta in block_meta.items():
            cond_step = meta.get('condition_step', -1)
            if cond_step < 0:
                continue
            # Connect condition to all steps in controlled blocks
            for step in timeline.steps:
                if step.block_id == bid:
                    pdg.add_edge(RuntimeEdge(
                        source=cond_step,
                        target=step.step_index,
                        kind='control',
                    ))

        # Build call edges from call_events
        for evt in timeline.call_events:
            if evt.caller_step is not None and evt.callee_first_step is not None:
                pdg.add_edge(RuntimeEdge(
                    source=evt.caller_step,
                    target=evt.callee_first_step,
                    kind='call',
                    metadata={'call_id': evt.call_id, 'function': evt.function_name},
                ))

        # Build parameter edges
        for pb in timeline.parameter_bindings:
            pdg.add_edge(RuntimeEdge(
                source=pb.caller_step,
                target=pb.caller_step,  # parameter binding is at call site
                kind='parameter',
                var=pb.caller_var,
                metadata={
                    'callee_param': pb.callee_param,
                    'is_alias': pb.is_alias,
                    'call_id': pb.call_id,
                },
            ))

        return pdg

    # ─── Graph mutation ───────────────────────────────────────────

    def add_node(self, node: RuntimeNode) -> None:
        self.nodes[node.id] = node

    def add_edge(self, edge: RuntimeEdge) -> None:
        self.edges.append(edge)
        self._edges_from[edge.source].append(edge)
        self._edges_to[edge.target].append(edge)
        if edge.kind == 'data' and edge.var:
            self._data_edges[(edge.target, edge.var)].append(edge)

    # ─── Backward slicing ─────────────────────────────────────────

    def backward_slice(self, target_step: int, target_var: str = '') -> SliceResult:
        """Dynamic backward slice from a target step.

        Follows data edges, control edges, and parameter edges backward.
        Returns a SliceResult with the slice set, edges, root causes, and explanation.
        """
        visited: Set[int] = set()
        edges_used: List[RuntimeEdge] = []
        depth_map: Dict[int, int] = {}
        queue: deque = deque([(target_step, target_var, 0)])

        while queue:
            step_id, var, depth = queue.popleft()
            if step_id in visited:
                continue
            visited.add(step_id)
            depth_map[step_id] = depth

            # 1. Data edges: follow edges TO this step
            for edge in self._edges_to.get(step_id, []):
                if edge.kind == 'data':
                    if var and edge.var != var:
                        continue
                    edges_used.append(edge)
                    if edge.source not in visited:
                        queue.append((edge.source, edge.var, depth + 1))

            # 2. Control edges: follow condition dependencies
            for edge in self._edges_to.get(step_id, []):
                if edge.kind == 'control':
                    edges_used.append(edge)
                    if edge.source not in visited:
                        queue.append((edge.source, '', depth + 1))

            # 3. Parameter edges: follow caller → callee
            for edge in self._edges_to.get(step_id, []):
                if edge.kind == 'parameter':
                    edges_used.append(edge)
                    if edge.source not in visited:
                        queue.append((edge.source, edge.var, depth + 1))

            # 4. Also follow ALL reads at this step through data edges
            node = self.nodes.get(step_id)
            if node:
                for read_var in node.ast_reads:
                    if read_var == var:
                        continue
                    for edge in self._data_edges.get((step_id, read_var), []):
                        edges_used.append(edge)
                        if edge.source not in visited:
                            queue.append((edge.source, read_var, depth + 1))

        # Identify root causes: steps in slice with no incoming data/control edges
        root_causes = []
        for sid in visited:
            has_incoming = any(
                e.source in visited and e.kind in ('data', 'control')
                for e in self._edges_to.get(sid, [])
            )
            if not has_incoming:
                root_causes.append(sid)

        # Generate explanation
        explanation = self._explain_slice(target_step, target_var, visited, edges_used, depth_map)

        return SliceResult(
            target_step=target_step,
            target_var=target_var,
            steps=sorted(visited),
            edges=edges_used,
            root_causes=sorted(root_causes),
            depth_map=depth_map,
            explanation=explanation,
        )

    # ─── Forward impact analysis ──────────────────────────────────

    def forward_impact(self, source_step: int, source_var: str = '') -> SliceResult:
        """Forward impact analysis from a source step.

        Traces forward through data, control, and call edges.
        """
        visited: Set[int] = set()
        edges_used: List[RuntimeEdge] = []
        depth_map: Dict[int, int] = {}
        queue: deque = deque([(source_step, source_var, 0)])

        while queue:
            step_id, var, depth = queue.popleft()
            if step_id in visited:
                continue
            visited.add(step_id)
            depth_map[step_id] = depth

            for edge in self._edges_from.get(step_id, []):
                if edge.kind == 'data':
                    if var and edge.var != var:
                        continue
                    edges_used.append(edge)
                    if edge.target not in visited:
                        queue.append((edge.target, edge.var, depth + 1))
                elif edge.kind == 'control':
                    edges_used.append(edge)
                    if edge.target not in visited:
                        queue.append((edge.target, '', depth + 1))
                elif edge.kind == 'call':
                    edges_used.append(edge)
                    if edge.target not in visited:
                        queue.append((edge.target, '', depth + 1))

        # Leaf nodes: steps in impact set with no outgoing edges
        leaf_nodes = []
        for sid in visited:
            has_outgoing = any(
                e.target in visited and e.kind in ('data', 'control', 'call')
                for e in self._edges_from.get(sid, [])
            )
            if not has_outgoing:
                leaf_nodes.append(sid)

        explanation = self._explain_impact(source_step, source_var, visited, edges_used, depth_map)

        return SliceResult(
            target_step=source_step,
            target_var=source_var,
            steps=sorted(visited),
            edges=edges_used,
            root_causes=sorted(leaf_nodes),  # "leaves" for forward
            depth_map=depth_map,
            explanation=explanation,
        )

    # ─── Variable history ─────────────────────────────────────────

    def get_variable_history(self, var_name: str) -> List[Tuple[int, VarVersion]]:
        """Get all SSA versions of a variable across the execution."""
        history = []
        for node in sorted(self.nodes.values(), key=lambda n: n.id):
            if var_name in node.vars:
                history.append((node.id, node.vars[var_name]))
        return history

    def get_version_chain(self, var_name: str) -> List[RuntimeEdge]:
        """Get the chain of data edges that define a variable's SSA versions."""
        chain = []
        for edge in self.edges:
            if edge.kind == 'data' and edge.var == var_name:
                chain.append(edge)
        return sorted(chain, key=lambda e: e.target)

    # ─── Path queries ─────────────────────────────────────────────

    def get_path_between(self, source: int, target: int, max_depth: int = 50) -> Optional[List[int]]:
        """Find shortest path between two nodes (BFS)."""
        if source == target:
            return [source]
        visited: Set[int] = {source}
        queue: deque = deque([(source, [source])])
        while queue:
            current, path = queue.popleft()
            if len(path) > max_depth:
                continue
            for edge in self._edges_from.get(current, []):
                if edge.target == target:
                    return path + [target]
                if edge.target not in visited:
                    visited.add(edge.target)
                    queue.append((edge.target, path + [edge.target]))
        return None

    # ─── Graph statistics ─────────────────────────────────────────

    def stats(self) -> dict:
        """Return graph statistics."""
        kind_counts = defaultdict(int)
        for e in self.edges:
            kind_counts[e.kind] += 1
        vars_tracked = set()
        for node in self.nodes.values():
            vars_tracked.update(node.vars.keys())
        return {
            'nodes': len(self.nodes),
            'edges': len(self.edges),
            'edge_kinds': dict(kind_counts),
            'variables': len(vars_tracked),
            'max_depth': max((n.depth for n in self.nodes.values()), default=0),
            'functions': len(set(n.func for n in self.nodes.values())),
        }

    # ─── Explanation generation ───────────────────────────────────

    def _explain_slice(
        self,
        target_step: int,
        target_var: str,
        steps: Set[int],
        edges: List[RuntimeEdge],
        depth_map: Dict[int, int],
    ) -> List[str]:
        """Generate human-readable explanation for a backward slice."""
        lines = []
        target_node = self.nodes.get(target_step)
        if not target_node:
            return lines

        lines.append(f"Target: step #{target_step} — `{target_node.code}`")
        if target_var:
            lines.append(f"Tracing variable: {target_var}")
        lines.append(f"Slice contains {len(steps)} steps (out of {len(self.nodes)})")
        lines.append("")

        # Group edges by kind
        data_edges = [e for e in edges if e.kind == 'data']
        control_edges = [e for e in edges if e.kind == 'control']

        if data_edges:
            lines.append("Data flow:")
            for edge in sorted(data_edges, key=lambda e: depth_map.get(e.target, 0)):
                src = self.nodes.get(edge.source)
                tgt = self.nodes.get(edge.target)
                if src and tgt:
                    lines.append(
                        f"  `{src.code}` → `{tgt.code}` via `{edge.var}`"
                    )

        if control_edges:
            lines.append("")
            lines.append("Control dependencies:")
            for edge in sorted(control_edges, key=lambda e: depth_map.get(e.target, 0)):
                src = self.nodes.get(edge.source)
                tgt = self.nodes.get(edge.target)
                if src and tgt:
                    lines.append(f"  `{src.code}` controls `{tgt.code}`")

        if self.nodes:
            root_nodes = [self.nodes[s] for s in sorted(
                set(s for s in steps if not any(
                    e.source in steps and e.kind in ('data', 'control')
                    for e in self._edges_to.get(s, [])
                ))
            )]
            if root_nodes:
                lines.append("")
                lines.append("Root causes:")
                for node in root_nodes[:5]:
                    lines.append(f"  #{node.id} — `{node.code}` (line {node.line})")

        return lines

    def _explain_impact(
        self,
        source_step: int,
        source_var: str,
        steps: Set[int],
        edges: List[RuntimeEdge],
        depth_map: Dict[int, int],
    ) -> List[str]:
        """Generate human-readable explanation for forward impact."""
        lines = []
        source_node = self.nodes.get(source_step)
        if not source_node:
            return lines

        lines.append(f"Source: step #{source_step} — `{source_node.code}`")
        if source_var:
            lines.append(f"Variable: {source_var}")
        lines.append(f"Impact set: {len(steps)} steps")
        lines.append("")

        data_edges = [e for e in edges if e.kind == 'data']
        if data_edges:
            lines.append("Data flow:")
            for edge in sorted(data_edges, key=lambda e: depth_map.get(e.target, 0)):
                src = self.nodes.get(edge.source)
                tgt = self.nodes.get(edge.target)
                if src and tgt:
                    lines.append(
                        f"  `{src.code}` → `{tgt.code}` via `{edge.var}`"
                    )

        leaf_nodes = [self.nodes[s] for s in sorted(
            set(s for s in steps if not any(
                e.target in steps and e.kind in ('data', 'control', 'call')
                for e in self._edges_from.get(s, [])
            ))
        )]
        if leaf_nodes:
            lines.append("")
            lines.append("Affected outputs:")
            for node in leaf_nodes[:5]:
                lines.append(f"  #{node.id} — `{node.code}` (line {node.line})")

        return lines

    # ─── Serialization ────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize the PDG to a dict (for API responses)."""
        return {
            'nodes': {
                str(nid): {
                    'id': n.id,
                    'line': n.line,
                    'code': n.code,
                    'func': n.func,
                    'depth': n.depth,
                    'call_id': n.call_id,
                    'block_id': n.block_id,
                    'ast_reads': n.ast_reads,
                    'ast_writes': n.ast_writes,
                    'ssa_versions': n.ssa_versions,
                }
                for nid, n in self.nodes.items()
            },
            'edges': [
                {
                    'source': e.source,
                    'target': e.target,
                    'kind': e.kind,
                    'var': e.var,
                    'source_version': e.source_version,
                    'target_version': e.target_version,
                    'metadata': e.metadata,
                }
                for e in self.edges
            ],
            'stats': self.stats(),
        }
