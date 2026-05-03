"""In-memory causal graph with optional Neo4j backend."""

from __future__ import annotations
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from core.edge_types import EdgeType
from core.node import CodeNode


class CausalGraph:
    """Directed graph of code causal relationships."""

    def __init__(self):
        self.nodes: Dict[str, CodeNode] = {}
        self.edges: List[Tuple[str, str, EdgeType, dict]] = []  # src, dst, type, props
        self._adj_out: Dict[str, List[Tuple[str, EdgeType]]] = defaultdict(list)
        self._adj_in: Dict[str, List[Tuple[str, EdgeType]]] = defaultdict(list)

    # ── Node operations ──────────────────────────────────────────────

    def add_node(self, node: CodeNode) -> None:
        self.nodes[node.node_id] = node

    def get_node(self, node_id: str) -> Optional[CodeNode]:
        return self.nodes.get(node_id)

    def has_node(self, node_id: str) -> bool:
        return node_id in self.nodes

    # ── Edge operations ──────────────────────────────────────────────

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        edge_type: EdgeType,
        props: Optional[dict] = None,
    ) -> None:
        self.edges.append((source_id, target_id, edge_type, props or {}))
        self._adj_out[source_id].append((target_id, edge_type))
        self._adj_in[target_id].append((source_id, edge_type))

    def get_outgoing(self, node_id: str) -> List[Tuple[str, EdgeType]]:
        return self._adj_out.get(node_id, [])

    def get_incoming(self, node_id: str) -> List[Tuple[str, EdgeType]]:
        return self._adj_in.get(node_id, [])

    # ── Traversal ────────────────────────────────────────────────────

    def reverse_bfs(self, start_id: str, max_depth: int = 50) -> List[List[str]]:
        """BFS backwards from a node, returning layers of ancestors."""
        visited: Set[str] = {start_id}
        layers: List[List[str]] = [[start_id]]
        frontier = [start_id]

        for _ in range(max_depth):
            next_frontier: List[str] = []
            for nid in frontier:
                for parent_id, _ in self.get_incoming(nid):
                    if parent_id not in visited:
                        visited.add(parent_id)
                        next_frontier.append(parent_id)
            if not next_frontier:
                break
            layers.append(next_frontier)
            frontier = next_frontier

        return layers

    def find_chain(
        self, start_id: str, edge_filter: Optional[Set[EdgeType]] = None
    ) -> List[List[Tuple[str, str, EdgeType]]]:
        """Return all causal chains from start_id backwards."""
        chains: List[List[Tuple[str, str, EdgeType]]] = []
        self._dfs_chains(start_id, [], chains, set(), edge_filter)
        return chains

    def _dfs_chains(
        self,
        current: str,
        path: List[Tuple[str, str, EdgeType]],
        results: List[List[Tuple[str, str, EdgeType]]],
        visited: Set[str],
        edge_filter: Optional[Set[EdgeType]],
    ) -> None:
        incoming = self.get_incoming(current)
        if not incoming:
            if path:
                results.append(list(path))
            return

        for parent_id, etype in incoming:
            if edge_filter and etype not in edge_filter:
                continue
            if parent_id in visited:
                continue
            visited.add(parent_id)
            path.append((parent_id, current, etype))
            self._dfs_chains(parent_id, path, results, visited, edge_filter)
            path.pop()
            visited.discard(parent_id)

    # ── Merge support ────────────────────────────────────────────────

    def merge_from(self, other: CausalGraph) -> None:
        """Merge another graph into this one (deduplication by node_id)."""
        for nid, node in other.nodes.items():
            if nid not in self.nodes:
                self.nodes[nid] = node
            else:
                existing = self.nodes[nid]
                if not existing.code_content and node.code_content:
                    existing.code_content = node.code_content
                if not existing.semantic_label and node.semantic_label:
                    existing.semantic_label = node.semantic_label

        for src, dst, etype, props in other.edges:
            edge_key = (src, dst, etype)
            existing_keys = {(s, d, t) for s, d, t, _ in self.edges}
            if edge_key not in existing_keys:
                self.add_edge(src, dst, etype, props)

    # ── Export ────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [
                {"source": s, "target": t, "type": e.value, "props": p}
                for s, t, e, p in self.edges
            ],
        }

    def stats(self) -> dict:
        type_counts: Dict[str, int] = defaultdict(int)
        for _, _, etype, _ in self.edges:
            type_counts[etype.value] += 1
        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "edge_types": dict(type_counts),
        }
