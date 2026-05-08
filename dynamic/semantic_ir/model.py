"""Semantic Execution Model — language-agnostic IR for the semantic layer.

This is the contract between runtime and semantic layers.
All semantic modules consume SemanticExecutionModel — never RuntimePDG directly.

Design principles:
    - Language-agnostic: no Python-specific concepts leak through
    - Query-oriented: semantic modules call query methods, never walk the graph
    - Lazy-indexed: indexes built on first query, reused thereafter
    - Immutable-ish: built once, consumed many times
    - Versioned: schema version for artifact compatibility
"""

from __future__ import annotations
import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


SCHEMA_VERSION = "1.1.0"


class SemanticEdgeKind(str, Enum):
    DATA = "data"
    CONTROL = "control"


@dataclass
class SemanticVariable:
    """A variable snapshot at a specific execution point.

    Language-agnostic: value/type are always string representations.
    """
    name: str
    value: str           # string representation of the value
    type: str            # string representation of the type
    version: int         # SSA version number (0 if not versioned)
    is_changed: bool     # whether this variable changed at this step
    is_new: bool         # whether this variable was first seen at this step
    memory_id: Optional[str] = None  # object identity hint (for mutation detection)


@dataclass
class SemanticNode:
    """A single execution step in the semantic model.

    Represents one line/statement of execution, regardless of source language.
    """
    id: int                          # step index (0-based)
    code: str                        # source code text (or IR representation)
    line: int                        # source line number (0 if not applicable)
    indent: int                      # nesting depth (0 if not applicable)
    ast_reads: Set[str] = field(default_factory=set)   # variables read
    ast_writes: Set[str] = field(default_factory=set)  # variables written
    variables: Dict[str, SemanticVariable] = field(default_factory=dict)  # all variables at this step

    @property
    def vars(self) -> Dict[str, SemanticVariable]:
        """Backward-compatible alias for variables."""
        return self.variables

    def var(self, name: str) -> Optional[SemanticVariable]:
        return self.variables.get(name)


@dataclass
class SemanticEdge:
    """A dependency edge between two execution steps."""
    source: int              # source node id
    target: int              # target node id
    kind: SemanticEdgeKind   # data or control
    var: str = ""            # variable name (for data edges)
    source_version: int = 0  # SSA version at source
    target_version: int = 0  # SSA version at target


@dataclass
class VariableHistoryEntry:
    """One step in a variable's SSA history."""
    step_id: int
    variable: SemanticVariable

    def __iter__(self):
        """Support tuple unpacking: step_id, var = entry"""
        return iter((self.step_id, self.variable))

    def __getitem__(self, index):
        """Support subscript: entry[0] = step_id, entry[1] = variable"""
        return (self.step_id, self.variable)[index]


@dataclass
class VersionChainEntry:
    """One edge in a variable's version chain."""
    source: int
    target: int
    source_version: int
    target_version: int

    def __iter__(self):
        """Support tuple unpacking."""
        return iter((self.source, self.target, self.source_version, self.target_version))

    def __getitem__(self, index):
        """Support subscript."""
        return (self.source, self.target, self.source_version, self.target_version)[index]


class _LazyIndex:
    """Lazy-built indexes for SemanticExecutionModel queries.

    Built on first access, cached for all subsequent queries.
    """

    def __init__(self, nodes: Dict[int, SemanticNode], edges: List[SemanticEdge]):
        self._nodes = nodes
        self._edges = edges
        self._built = False

        # Edge indexes
        self._data_edges: Optional[List[SemanticEdge]] = None
        self._control_edges: Optional[List[SemanticEdge]] = None
        self._data_edges_by_var: Optional[Dict[str, List[SemanticEdge]]] = None
        self._control_edges_from: Optional[Dict[int, List[SemanticEdge]]] = None
        self._incoming_data: Optional[Dict[int, List[SemanticEdge]]] = None
        self._outgoing_data: Optional[Dict[int, List[SemanticEdge]]] = None
        self._incoming_control: Optional[Dict[int, List[SemanticEdge]]] = None
        self._outgoing_control: Optional[Dict[int, List[SemanticEdge]]] = None

        # Node indexes
        self._nodes_by_read: Optional[Dict[str, List[SemanticNode]]] = None
        self._nodes_by_write: Optional[Dict[str, List[SemanticNode]]] = None
        self._all_variables: Optional[Set[str]] = None

    def _ensure_built(self):
        if self._built:
            return
        self._built = True

        data_edges = []
        control_edges = []
        data_by_var: Dict[str, List[SemanticEdge]] = defaultdict(list)
        ctrl_from: Dict[int, List[SemanticEdge]] = defaultdict(list)
        in_data: Dict[int, List[SemanticEdge]] = defaultdict(list)
        out_data: Dict[int, List[SemanticEdge]] = defaultdict(list)
        in_ctrl: Dict[int, List[SemanticEdge]] = defaultdict(list)
        out_ctrl: Dict[int, List[SemanticEdge]] = defaultdict(list)
        nodes_by_read: Dict[str, List[SemanticNode]] = defaultdict(list)
        nodes_by_write: Dict[str, List[SemanticNode]] = defaultdict(list)
        all_vars: Set[str] = set()

        for e in self._edges:
            if e.kind == SemanticEdgeKind.DATA:
                data_edges.append(e)
                if e.var:
                    data_by_var[e.var].append(e)
                in_data[e.target].append(e)
                out_data[e.source].append(e)
            else:
                control_edges.append(e)
                ctrl_from[e.source].append(e)
                in_ctrl[e.target].append(e)
                out_ctrl[e.source].append(e)

        for node in self._nodes.values():
            for var in node.ast_reads:
                nodes_by_read[var].append(node)
            for var in node.ast_writes:
                nodes_by_write[var].append(node)
            all_vars.update(node.variables.keys())

        self._data_edges = data_edges
        self._control_edges = control_edges
        self._data_edges_by_var = dict(data_by_var)
        self._control_edges_from = dict(ctrl_from)
        self._incoming_data = dict(in_data)
        self._outgoing_data = dict(out_data)
        self._incoming_control = dict(in_ctrl)
        self._outgoing_control = dict(out_ctrl)
        self._nodes_by_read = dict(nodes_by_read)
        self._nodes_by_write = dict(nodes_by_write)
        self._all_variables = all_vars

    # ── Edge queries ──────────────────────────────────────────────

    @property
    def data_edges(self) -> List[SemanticEdge]:
        self._ensure_built()
        return self._data_edges

    @property
    def control_edges(self) -> List[SemanticEdge]:
        self._ensure_built()
        return self._control_edges

    def data_edges_for_var(self, var: str) -> List[SemanticEdge]:
        self._ensure_built()
        return self._data_edges_by_var.get(var, [])

    def control_edges_from(self, node_id: int) -> List[SemanticEdge]:
        self._ensure_built()
        return self._control_edges_from.get(node_id, [])

    def incoming_data_edges(self, node_id: int) -> List[SemanticEdge]:
        self._ensure_built()
        return self._incoming_data.get(node_id, [])

    def outgoing_data_edges(self, node_id: int) -> List[SemanticEdge]:
        self._ensure_built()
        return self._outgoing_data.get(node_id, [])

    def incoming_control_edges(self, node_id: int) -> List[SemanticEdge]:
        self._ensure_built()
        return self._incoming_control.get(node_id, [])

    def outgoing_control_edges(self, node_id: int) -> List[SemanticEdge]:
        self._ensure_built()
        return self._outgoing_control.get(node_id, [])

    # ── Node queries ──────────────────────────────────────────────

    def nodes_reading(self, var: str) -> List[SemanticNode]:
        self._ensure_built()
        return self._nodes_by_read.get(var, [])

    def nodes_writing(self, var: str) -> List[SemanticNode]:
        self._ensure_built()
        return self._nodes_by_write.get(var, [])

    @property
    def all_variables(self) -> Set[str]:
        self._ensure_built()
        return self._all_variables


class SemanticExecutionModel:
    """Language-agnostic execution model — the IR for all semantic analysis.

    Provides a query-based interface so semantic modules never walk the graph
    manually. All queries are backed by lazy indexes that build on first use.

    Usage:
        model = build_from_pdg(pdg)

        # Node queries — never iterate model.nodes.values() manually
        for node in model.nodes_reading("x"):
            ...
        for node in model.nodes_writing("x"):
            ...
        for node in model.branch_nodes():
            ...
        for node in model.loop_header_nodes():
            ...

        # Edge queries — never iterate model.edges manually
        for edge in model.data_edges_for_var("x"):
            ...
        for edge in model.control_edges_from(node_id):
            ...

        # Aggregate queries
        root_ids = model.root_node_ids()
        fan_in = model.fan_in_nodes(threshold=3)
    """

    def __init__(
        self,
        nodes: Dict[int, SemanticNode],
        edges: List[SemanticEdge],
        variable_histories: Dict[str, List[VariableHistoryEntry]] = None,
        version_chains: Dict[str, List[VersionChainEntry]] = None,
        schema_version: str = SCHEMA_VERSION,
    ):
        self._nodes = nodes
        self._edges = edges
        self._variable_histories = variable_histories or {}
        self._version_chains = version_chains or {}
        self._schema_version = schema_version
        self._stats = None  # lazy
        self._index = _LazyIndex(nodes, edges)

    # ── Topology (read-only access) ───────────────────────────────

    @property
    def nodes(self) -> Dict[int, SemanticNode]:
        return self._nodes

    @property
    def edges(self) -> List[SemanticEdge]:
        return self._edges

    # ── Variable queries ──────────────────────────────────────────

    def get_variable_history(self, var_name: str) -> List[VariableHistoryEntry]:
        """SSA history of a variable: [(step_id, SemanticVariable), ...]"""
        return self._variable_histories.get(var_name, [])

    def get_version_chain(self, var_name: str) -> List[VersionChainEntry]:
        """Version chain for a variable: [(source, target, src_ver, tgt_ver), ...]"""
        return self._version_chains.get(var_name, [])

    def get_all_variable_names(self) -> Set[str]:
        """All variable names seen across all steps."""
        return self._index.all_variables

    # ── Edge queries ──────────────────────────────────────────────

    def data_edges(self) -> List[SemanticEdge]:
        """All data dependency edges."""
        return self._index.data_edges

    def data_edges_for_var(self, var: str) -> List[SemanticEdge]:
        """Data edges that carry a specific variable."""
        return self._index.data_edges_for_var(var)

    def control_edges(self) -> List[SemanticEdge]:
        """All control dependency edges."""
        return self._index.control_edges

    def control_edges_from(self, node_id: int) -> List[SemanticEdge]:
        """Control edges originating from a node."""
        return self._index.control_edges_from(node_id)

    def incoming_data_edges(self, node_id: int) -> List[SemanticEdge]:
        """Data edges flowing into a node."""
        return self._index.incoming_data_edges(node_id)

    def outgoing_data_edges(self, node_id: int) -> List[SemanticEdge]:
        """Data edges flowing out of a node."""
        return self._index.outgoing_data_edges(node_id)

    def incoming_control_edges(self, node_id: int) -> List[SemanticEdge]:
        """Control edges flowing into a node."""
        return self._index.incoming_control_edges(node_id)

    def outgoing_control_edges(self, node_id: int) -> List[SemanticEdge]:
        """Control edges flowing out of a node."""
        return self._index.outgoing_control_edges(node_id)

    def incoming_data_edge_count(self, node_id: int) -> int:
        """Count of incoming data edges for a node."""
        return len(self._index.incoming_data_edges(node_id))

    def outgoing_data_edge_count(self, node_id: int) -> int:
        """Count of outgoing data edges for a node."""
        return len(self._index.outgoing_data_edges(node_id))

    def incoming_data_vars(self, node_id: int) -> Set[str]:
        """Variables flowing into a node via data edges."""
        return {e.var for e in self._index.incoming_data_edges(node_id) if e.var}

    def data_edges_as_tuples(self) -> List[Tuple[int, int, str]]:
        """Data edges as (source, target, var) tuples for backward compat."""
        return [(e.source, e.target, e.var) for e in self._index.data_edges]

    # ── Node queries ──────────────────────────────────────────────

    def nodes_reading(self, var: str) -> List[SemanticNode]:
        """Nodes that read a specific variable."""
        return self._index.nodes_reading(var)

    def nodes_writing(self, var: str) -> List[SemanticNode]:
        """Nodes that write a specific variable."""
        return self._index.nodes_writing(var)

    def nodes_matching_code(self, substring: str) -> List[SemanticNode]:
        """Nodes whose code contains the given substring."""
        return [n for n in self._nodes.values() if substring in n.code]

    def nodes_matching_code_regex(self, pattern: str) -> List[SemanticNode]:
        """Nodes whose code matches the given regex pattern."""
        regex = re.compile(pattern)
        return [n for n in self._nodes.values() if regex.search(n.code)]

    def branch_nodes(self) -> List[SemanticNode]:
        """Nodes that are branch points (if/elif/else)."""
        return [n for n in self._nodes.values()
                if n.code.lstrip().startswith(('if ', 'elif ', 'else:'))]

    def early_return_nodes(self) -> List[SemanticNode]:
        """Nodes that are return statements before the last node."""
        if not self._nodes:
            return []
        max_id = max(self._nodes.keys())
        return [n for n in self._nodes.values()
                if n.code.lstrip().startswith('return ') and n.id < max_id]

    def loop_header_nodes(self) -> List[SemanticNode]:
        """Nodes that are loop headers (for/while)."""
        return [n for n in self._nodes.values()
                if n.code.lstrip().startswith(('for ', 'while '))]

    def root_cause_nodes(self) -> List[SemanticNode]:
        """Nodes with no incoming data edges that write variables — origin points."""
        incoming_targets = {e.target for e in self._index.data_edges}
        return [n for n in self._nodes.values()
                if n.id not in incoming_targets and n.ast_writes]

    def fan_in_nodes(self, threshold: int = 3) -> List[SemanticNode]:
        """Nodes with threshold or more incoming data edges — convergence points."""
        return [n for n in self._nodes.values()
                if self.incoming_data_edge_count(n.id) >= threshold]

    def convergence_nodes(self, threshold: int = 3) -> List[SemanticNode]:
        """Alias for fan_in_nodes."""
        return self.fan_in_nodes(threshold)

    def fan_out_nodes(self, threshold: int = 3) -> List[SemanticNode]:
        """Nodes with threshold or more outgoing data edges — broadcast points."""
        return [n for n in self._nodes.values()
                if self.outgoing_data_edge_count(n.id) >= threshold]

    # ── SSA / version queries ─────────────────────────────────────

    def ssa_versions_for_var(self, var: str) -> List[Tuple[int, int]]:
        """All (step_id, version) pairs for a variable's SSA history."""
        return [(e.step_id, e.variable.version) for e in self.get_variable_history(var)]

    def last_node_with_var(self, var: str) -> Optional[SemanticNode]:
        """Last node that has a snapshot of the variable."""
        for node_id in sorted(self._nodes.keys(), reverse=True):
            node = self._nodes[node_id]
            if var in node.variables:
                return node
        return None

    def mutated_variables(self) -> Set[str]:
        """Variables that changed value after initial assignment (mutation detection)."""
        mutated = set()
        for var_name, history in self._variable_histories.items():
            if len(history) < 2:
                continue
            seen_values = set()
            for entry in history:
                v = entry.variable
                if v.value in seen_values:
                    # Value appeared before — could be mutation back to same value
                    # But if memory_id changed, it's a rebind not mutation
                    pass
                seen_values.add(v.value)
            # Check for is_changed flag
            for entry in history:
                if entry.variable.is_changed:
                    mutated.add(var_name)
                    break
        return mutated

    def variables_in_nodes(self, node_ids: Set[int]) -> Dict[str, List[SemanticVariable]]:
        """All variable snapshots across the given nodes, grouped by name."""
        result: Dict[str, List[SemanticVariable]] = defaultdict(list)
        for nid in node_ids:
            node = self._nodes.get(nid)
            if node:
                for var_name, var in node.variables.items():
                    result[var_name].append(var)
        return dict(result)

    # ── Graph structure queries ───────────────────────────────────

    def all_node_ids(self) -> Set[int]:
        """All node IDs in the model."""
        return set(self._nodes.keys())

    def root_node_ids(self) -> Set[int]:
        """Nodes with no incoming data edges — graph roots."""
        return set(self._nodes.keys()) - {e.target for e in self._index.data_edges}

    def leaf_node_ids(self) -> Set[int]:
        """Nodes with no outgoing data edges — graph leaves."""
        return set(self._nodes.keys()) - {e.source for e in self._index.data_edges}

    def all_code_joined(self, separator: str = "\n") -> str:
        """All node code joined into a single string."""
        return separator.join(n.code for n in self._nodes.values())

    # ── Statistics ────────────────────────────────────────────────

    def stats(self) -> dict:
        if self._stats is None:
            edge_kinds = {}
            for e in self._edges:
                edge_kinds[e.kind.value] = edge_kinds.get(e.kind.value, 0) + 1

            max_indent = max((n.indent for n in self._nodes.values()), default=0)

            self._stats = {
                "nodes": len(self._nodes),
                "edges": len(self._edges),
                "edge_kinds": edge_kinds,
                "variables": len(self._index.all_variables),
                "max_depth": max_indent,
                "schema_version": self._schema_version,
            }
        return self._stats

    # ── Schema version ────────────────────────────────────────────

    @property
    def schema_version(self) -> str:
        return self._schema_version

    # ── Convenience ───────────────────────────────────────────────

    def node_count(self) -> int:
        return len(self._nodes)

    def edge_count(self) -> int:
        return len(self._edges)

    def data_edge_count(self) -> int:
        return len(self._index.data_edges)

    def control_edge_count(self) -> int:
        return len(self._index.control_edges)


# ── Lowering pass: RuntimePDG → SemanticExecutionModel ──────────

def build_from_pdg(pdg) -> SemanticExecutionModel:
    """Lower a RuntimePDG into a SemanticExecutionModel.

    This is the ONLY place where runtime structures are touched.
    After this, all semantic modules work with SemanticExecutionModel only.
    """
    # Lower nodes
    nodes = {}
    for node_id, node in pdg.nodes.items():
        variables = {}
        for var_name, var_snap in (node.vars or {}).items():
            variables[var_name] = SemanticVariable(
                name=var_name,
                value=str(getattr(var_snap, "value", "")),
                type=str(getattr(var_snap, "type", "")),
                version=getattr(var_snap, "version", 0),
                is_changed=getattr(var_snap, "is_changed", False),
                is_new=getattr(var_snap, "is_new", False),
                memory_id=str(getattr(var_snap, "memory_id", "")) or None,
            )
        nodes[node_id] = SemanticNode(
            id=node_id,
            code=getattr(node, "code", ""),
            line=getattr(node, "line", 0),
            indent=getattr(node, "indent", 0),
            ast_reads=set(getattr(node, "ast_reads", []) or []),
            ast_writes=set(getattr(node, "ast_writes", []) or []),
            variables=variables,
        )

    # Lower edges
    edges = []
    for edge in pdg.edges:
        kind = SemanticEdgeKind.DATA if getattr(edge, "kind", "") == "data" else SemanticEdgeKind.CONTROL
        edges.append(SemanticEdge(
            source=getattr(edge, "source", 0),
            target=getattr(edge, "target", 0),
            kind=kind,
            var=getattr(edge, "var", ""),
            source_version=getattr(edge, "source_version", 0),
            target_version=getattr(edge, "target_version", 0),
        ))

    # Lower variable histories
    variable_histories = {}
    all_vars = set()
    for n in pdg.nodes.values():
        all_vars.update((n.vars or {}).keys())

    for var_name in all_vars:
        history = pdg.get_variable_history(var_name)
        entries = []
        for step_id, ver_var in history:
            sv = SemanticVariable(
                name=var_name,
                value=str(getattr(ver_var, "value", "")),
                type=str(getattr(ver_var, "type", "")),
                version=getattr(ver_var, "version", 0),
                is_changed=False,
                is_new=False,
                memory_id=str(getattr(ver_var, "memory_id", "")) or None,
            )
            entries.append(VariableHistoryEntry(step_id=step_id, variable=sv))
        variable_histories[var_name] = entries

    # Lower version chains
    version_chains = {}
    for var_name in all_vars:
        try:
            chain = pdg.get_version_chain(var_name)
            entries = []
            for e in chain:
                entries.append(VersionChainEntry(
                    source=getattr(e, "source", 0),
                    target=getattr(e, "target", 0),
                    source_version=getattr(e, "source_version", 0),
                    target_version=getattr(e, "target_version", 0),
                ))
            if entries:
                version_chains[var_name] = entries
        except Exception:
            pass

    return SemanticExecutionModel(
        nodes=nodes,
        edges=edges,
        variable_histories=variable_histories,
        version_chains=version_chains,
    )
