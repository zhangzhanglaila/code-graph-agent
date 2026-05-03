"""Interactive causal graph visualization using Pyvis."""

from __future__ import annotations
import os
from typing import Optional

from core.graph import CausalGraph
from core.edge_types import EdgeType, EDGE_STYLES

# Node type styles
NODE_STYLES = {
    "CODE": {"color": "#90CAF9", "shape": "box", "border": "#1565C0"},
    "CONFIG": {"color": "#FFE082", "shape": "diamond", "border": "#FF8F00"},
    "ERROR": {"color": "#EF9A9A", "shape": "box", "border": "#C62828"},
    "ENTRY": {"color": "#A5D6A7", "shape": "ellipse", "border": "#2E7D32"},
}


class GraphVisualizer:
    """Generate interactive HTML visualization of causal graphs."""

    def render(
        self,
        graph: CausalGraph,
        output_path: str = "causal_graph.html",
        title: str = "Code Causal Graph",
        highlight_chain: Optional[list] = None,
    ) -> str:
        """Render graph to interactive HTML file.

        Args:
            graph: The causal graph to visualize
            output_path: Output HTML file path
            title: Page title
            highlight_chain: Optional list of node_ids to highlight as a chain

        Returns:
            Absolute path to the generated HTML file
        """
        try:
            from pyvis.network import Network
        except ImportError:
            return self._render_fallback(graph, output_path, title)

        net = Network(
            height="800px",
            width="100%",
            directed=True,
            notebook=False,
            bgcolor="#ffffff",
            font_color="#333333",
        )

        net.set_options("""
        {
            "physics": {
                "enabled": true,
                "solver": "forceAtlas2Based",
                "forceAtlas2Based": {
                    "gravitationalConstant": -50,
                    "centralGravity": 0.005,
                    "springLength": 150,
                    "springConstant": 0.08
                },
                "stabilization": {
                    "iterations": 100
                }
            },
            "interaction": {
                "hover": true,
                "tooltipDelay": 200
            },
            "edges": {
                "arrows": "to",
                "smooth": {
                    "type": "curvedCW",
                    "roundness": 0.2
                }
            }
        }
        """)

        highlight_set = set(highlight_chain) if highlight_chain else set()

        # Add nodes
        for nid, node in graph.nodes.items():
            style = NODE_STYLES.get(node.node_type, NODE_STYLES["CODE"])
            label = self._make_label(node)
            title_text = self._make_tooltip(node)

            is_highlighted = nid in highlight_set
            border_width = 4 if is_highlighted else 2
            font_size = 16 if is_highlighted else 12

            net.add_node(
                nid,
                label=label,
                title=title_text,
                color={
                    "background": style["color"],
                    "border": "#FF0000" if is_highlighted else style["border"],
                    "highlight": {"background": "#FFEB3B", "border": "#F57F17"},
                },
                shape=style["shape"],
                borderWidth=border_width,
                font={"size": font_size},
            )

        # Add edges
        for src, dst, etype, props in graph.edges:
            edge_style = EDGE_STYLES.get(etype, {"color": "#999", "dashes": False})
            is_chain_edge = (
                highlight_chain
                and src in highlight_set
                and dst in highlight_set
            )

            net.add_edge(
                src,
                dst,
                color=edge_style["color"],
                dashes=edge_style["dashes"],
                title=edge_style["title"],
                width=3 if is_chain_edge else 1,
                label=edge_style["title"] if is_chain_edge else "",
            )

        # Write HTML
        abs_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
        net.save_graph(abs_path)

        # Inject title and stats
        self._inject_header(abs_path, title, graph)
        return abs_path

    def _make_label(self, node) -> str:
        """Create display label for node."""
        fname = os.path.basename(node.file_path)
        label = f"{fname}:{node.line_number}"
        if node.semantic_label:
            label += f"\n{node.semantic_label[:40]}"
        return label

    def _make_tooltip(self, node) -> str:
        """Create rich tooltip for node."""
        parts = [
            f"<b>{node.node_id}</b>",
            f"Type: {node.node_type}",
            f"Code: <code>{node.code_content[:100]}</code>",
        ]
        if node.semantic_label:
            parts.append(f"Label: {node.semantic_label}")
        if node.existence_reason:
            parts.append(f"Purpose: {node.existence_reason}")
        if node.root_cause_info:
            rc = node.root_cause_info
            if "root_cause" in rc:
                parts.append(f"Root Cause: {rc['root_cause']}")
            if "confidence" in rc:
                parts.append(f"Confidence: {rc['confidence']}")
        return "<br>".join(parts)

    def _inject_header(self, html_path: str, title: str, graph: CausalGraph) -> None:
        """Inject title and stats header into the HTML file."""
        stats = graph.stats()
        header = f"""
        <div style="padding:10px;background:#f5f5f5;border-bottom:1px solid #ddd;font-family:sans-serif">
            <h2 style="margin:0">{title}</h2>
            <p style="margin:4px 0;color:#666">
                Nodes: {stats['nodes']} | Edges: {stats['edges']}
                {'| ' + ', '.join(f'{k}: {v}' for k,v in stats.get('edge_types',{}).items()) if stats.get('edge_types') else ''}
            </p>
            <div style="margin-top:8px">
                <b>Legend:</b>
                <span style="color:#1565C0">■ Code</span> &nbsp;
                <span style="color:#FF8F00">◆ Config</span> &nbsp;
                <span style="color:#C62828">■ Error</span> &nbsp;
                <span style="color:#2196F3">— Data Dep</span> &nbsp;
                <span style="color:#4CAF50">— Call</span> &nbsp;
                <span style="color:#FF9800">-- Config</span> &nbsp;
                <span style="color:#E91E63">— Runtime</span> &nbsp;
                <span style="color:#F44336">-- Throws</span>
            </div>
        </div>
        """
        try:
            with open(html_path, "r", encoding="utf-8") as f:
                content = f.read()
            content = content.replace("<body>", f"<body>\n{header}", 1)
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            pass

    def _render_fallback(self, graph: CausalGraph, output_path: str, title: str) -> str:
        """Fallback HTML rendering when pyvis is not installed."""
        stats = graph.stats()
        nodes_json = []
        for nid, n in graph.nodes.items():
            style = NODE_STYLES.get(n.node_type, NODE_STYLES["CODE"])
            nodes_json.append(
                f'{{id:"{nid}",label:"{os.path.basename(n.file_path)}:{n.line_number}",'
                f'color:"{style["color"]}",title:"{n.semantic_label}"}}'
            )
        edges_json = []
        for s, t, e, _ in graph.edges:
            es = EDGE_STYLES.get(e, {"color": "#999"})
            edges_json.append(f'{{from:"{s}",to:"{t}",color:"{es["color"]}"}}')

        html = f"""<!DOCTYPE html>
<html><head><title>{title}</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>body{{margin:0;font-family:sans-serif}} #graph{{height:80vh}} .info{{padding:10px;background:#f5f5f5}}</style>
</head><body>
<div class="info"><h2>{title}</h2><p>Nodes: {stats['nodes']} | Edges: {stats['edges']}</p></div>
<div id="graph"></div>
<script>
var nodes=new vis.DataSet([{','.join(nodes_json)}]);
var edges=new vis.DataSet([{','.join(edges_json)}]);
var container=document.getElementById('graph');
var data={{nodes:nodes,edges:edges}};
var options={{physics:{{solver:'forceAtlas2Based'}},interaction:{{hover:true}},edges:{{arrows:'to'}}}};
var network=new vis.Network(container,data,options);
</script></body></html>"""

        abs_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(html)
        return abs_path
