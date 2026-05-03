"""Merge static and dynamic causal graphs into a unified graph."""

from __future__ import annotations
from typing import Dict, List, Optional, Set

from core.graph import CausalGraph
from core.node import CodeNode
from core.edge_types import EdgeType


class MergeEngine:
    """Fuse static analysis and runtime trace graphs."""

    def merge(
        self,
        static_graph: CausalGraph,
        dynamic_graphs: Optional[List[CausalGraph]] = None,
        config_graph: Optional[CausalGraph] = None,
        exception_graph: Optional[CausalGraph] = None,
    ) -> CausalGraph:
        """Merge all graphs into a unified causal graph."""
        merged = CausalGraph()

        # 1. Static graph as base
        merged.merge_from(static_graph)

        # 2. Merge config influence
        if config_graph:
            merged.merge_from(config_graph)

        # 3. Merge dynamic traces
        if dynamic_graphs:
            for dg in dynamic_graphs:
                self._merge_dynamic(merged, dg)

        # 4. Merge exception graph
        if exception_graph:
            self._merge_exception(merged, exception_graph)

        return merged

    def _merge_dynamic(self, base: CausalGraph, dynamic: CausalGraph) -> None:
        """Merge dynamic trace graph, linking runtime edges to static nodes."""
        for nid, node in dynamic.nodes.items():
            if base.has_node(nid):
                # Enhance existing static node with runtime info
                existing = base.get_node(nid)
                if not existing.semantic_label:
                    existing.semantic_label = node.semantic_label
                existing.node_type = "CODE"  # confirmed by runtime
            else:
                base.add_node(node)

        for src, dst, etype, props in dynamic.edges:
            edge_key = (src, dst, etype)
            existing_keys = {(s, d, t) for s, d, t, _ in base.edges}
            if edge_key not in existing_keys:
                base.add_edge(src, dst, etype, props)

    def _merge_exception(self, base: CausalGraph, exception: CausalGraph) -> None:
        """Merge exception graph, adding THROWS edges."""
        for nid, node in exception.nodes.items():
            if base.has_node(nid):
                existing = base.get_node(nid)
                if node.node_type == "ERROR":
                    existing.node_type = "ERROR"
                    existing.semantic_label = node.semantic_label
            else:
                base.add_node(node)

        for src, dst, etype, props in exception.edges:
            edge_key = (src, dst, etype)
            existing_keys = {(s, d, t) for s, d, t, _ in base.edges}
            if edge_key not in existing_keys:
                base.add_edge(src, dst, etype, props)

    def incremental_update(
        self,
        base: CausalGraph,
        changed_files: List[str],
        static_analyzer,
        dynamic_traces: Optional[List[CausalGraph]] = None,
    ) -> CausalGraph:
        """Incrementally update graph for changed files only."""
        # Remove old nodes for changed files
        nodes_to_remove: Set[str] = set()
        for nid, node in base.nodes.items():
            if node.file_path in changed_files:
                nodes_to_remove.add(nid)

        for nid in nodes_to_remove:
            del base.nodes[nid]

        # Remove edges involving removed nodes
        base.edges = [
            (s, t, e, p) for s, t, e, p in base.edges
            if s not in nodes_to_remove and t not in nodes_to_remove
        ]

        # Rebuild adjacency
        from collections import defaultdict
        base._adj_out = defaultdict(list)
        base._adj_in = defaultdict(list)
        for s, t, e, p in base.edges:
            base._adj_out[s].append((t, e))
            base._adj_in[t].append((s, e))

        # Re-analyze changed files and merge
        if static_analyzer:
            for fpath in changed_files:
                sub = static_analyzer.analyze_file(fpath)
                base.merge_from(sub)

        if dynamic_traces:
            for dg in dynamic_traces:
                self._merge_dynamic(base, dg)

        return base
