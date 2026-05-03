"""Root cause query engine — traverse causal graph to find error origins."""

from __future__ import annotations
from typing import Dict, List, Optional, Set

from core.graph import CausalGraph
from core.node import CodeNode
from core.edge_types import EdgeType


class RootCauseQuery:
    """Query the causal graph for root causes and code existence reasons."""

    def __init__(self, graph: CausalGraph):
        self.graph = graph

    def get_root_cause_chain(
        self,
        node_id: str,
        max_depth: int = 20,
    ) -> List[dict]:
        """Trace backwards from an error node to find the root cause chain.

        Returns a list of chain links, each with:
        - node_id, file_path, line_number, code_content, semantic_label
        - edge_type: how this node connects to the next (towards error)
        - depth: distance from the error node
        """
        chain: List[dict] = []
        visited: Set[str] = set()
        self._trace_back(node_id, chain, visited, depth=0, max_depth=max_depth)
        return chain

    def _trace_back(
        self,
        current_id: str,
        chain: List[dict],
        visited: Set[str],
        depth: int,
        max_depth: int,
    ) -> None:
        if depth > max_depth or current_id in visited:
            return
        visited.add(current_id)

        node = self.graph.get_node(current_id)
        if not node:
            return

        incoming = self.graph.get_incoming(current_id)

        chain.append({
            "node_id": current_id,
            "file_path": node.file_path,
            "line_number": node.line_number,
            "code_content": node.code_content,
            "node_type": node.node_type,
            "semantic_label": node.semantic_label,
            "depth": depth,
            "incoming_edges": [
                {"from": src, "type": etype.value}
                for src, etype in incoming
            ],
        })

        # Prioritize THROWS edges, then CONFIG_INFLUENCE, then others
        priority_order = [
            EdgeType.THROWS,
            EdgeType.CONFIG_INFLUENCE,
            EdgeType.DATA_DEPENDENCY,
            EdgeType.CALL_RELATION,
            EdgeType.RUNTIME_TRACE,
            EdgeType.CONTROL_FLOW,
        ]

        sorted_incoming = sorted(
            incoming,
            key=lambda x: priority_order.index(x[1]) if x[1] in priority_order else 99,
        )

        for parent_id, etype in sorted_incoming:
            self._trace_back(parent_id, chain, visited, depth + 1, max_depth)

    def get_code_existence_reason(self, node_id: str) -> dict:
        """Get the reason why a code line exists.

        Returns structured info about:
        - The code line and its purpose
        - What depends on it
        - What it depends on
        - Removal consequence
        """
        node = self.graph.get_node(node_id)
        if not node:
            return {"error": f"Node {node_id} not found"}

        # Incoming dependencies (what this line depends on)
        depends_on = []
        for src_id, etype in self.graph.get_incoming(node_id):
            src = self.graph.get_node(src_id)
            if src:
                depends_on.append({
                    "node_id": src_id,
                    "edge_type": etype.value,
                    "code_content": src.code_content,
                    "semantic_label": src.semantic_label,
                })

        # Outgoing dependents (what depends on this line)
        depended_by = []
        for dst_id, etype in self.graph.get_outgoing(node_id):
            dst = self.graph.get_node(dst_id)
            if dst:
                depended_by.append({
                    "node_id": dst_id,
                    "edge_type": etype.value,
                    "code_content": dst.code_content,
                    "semantic_label": dst.semantic_label,
                })

        # Use stored LLM analysis if available
        llm_analysis = node.root_cause_info or {}

        return {
            "node_id": node_id,
            "file_path": node.file_path,
            "line_number": node.line_number,
            "code_content": node.code_content,
            "semantic_label": node.semantic_label,
            "existence_reason": node.existence_reason,
            "depends_on": depends_on,
            "depended_by": depended_by,
            "llm_analysis": llm_analysis,
        }

    def find_error_nodes(self) -> List[CodeNode]:
        """Find all nodes marked as ERROR type."""
        return [n for n in self.graph.nodes.values() if n.node_type == "ERROR"]

    def find_config_influenced_nodes(self, config_key: str) -> List[CodeNode]:
        """Find all code nodes influenced by a specific config key."""
        config_nid = CodeNode.config_id(config_key)
        influenced = []
        for dst_id, etype in self.graph.get_outgoing(config_nid):
            if etype == EdgeType.CONFIG_INFLUENCE:
                node = self.graph.get_node(dst_id)
                if node:
                    influenced.append(node)
        return influenced

    def get_full_chain_display(self, node_id: str, max_depth: int = 20) -> str:
        """Get a human-readable display of the causal chain."""
        chain = self.get_root_cause_chain(node_id, max_depth)
        if not chain:
            return f"No causal chain found for {node_id}"

        lines = ["=== Causal Chain (error → root cause) ===\n"]
        for i, link in enumerate(chain):
            indent = "  " * i
            edge_info = ""
            if link["incoming_edges"]:
                edge_types = [e["type"] for e in link["incoming_edges"]]
                edge_info = f" [{', '.join(edge_types)}]"

            lines.append(
                f"{indent}{'🔴 ' if link['node_type'] == 'ERROR' else '  '}"
                f"{link['node_id']}: {link['code_content']}"
                f"{edge_info}"
            )
            if link["semantic_label"]:
                lines.append(f"{indent}  → {link['semantic_label']}")

        lines.append(f"\nRoot cause: {chain[-1]['node_id']}")
        lines.append(f"  {chain[-1]['code_content']}")
        return "\n".join(lines)
