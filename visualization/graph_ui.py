"""Interactive causal graph visualization using Pyvis."""

from __future__ import annotations
import json
import os
from typing import List, Optional

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

    def render_timeline(
        self,
        timeline,
        output_path: str = "execution_timeline.html",
        title: str = "Execution Timeline",
    ) -> str:
        """Render execution timeline as interactive step-by-step visualization.

        Args:
            timeline: ExecutionTimeline from StateRecorder
            output_path: Output HTML file path
            title: Page title

        Returns:
            Absolute path to the generated HTML file
        """
        steps_data = []
        all_vars = set()

        for step in timeline.steps:
            var_states = {}
            for name, snap in step.variables.items():
                all_vars.add(name)
                var_states[name] = {
                    "value": snap.value_repr,
                    "type": snap.value_type,
                    "mem_id": snap.memory_id,
                    "changed": name in step.changed_vars,
                    "is_new": name in step.new_vars,
                    "ref": snap.is_reference_to,
                }

            steps_data.append({
                "index": step.step_index,
                "file": os.path.basename(step.file_path),
                "file_full": step.file_path,
                "line": step.line_number,
                "code": step.code_line,
                "func": step.function_name,
                "vars": var_states,
                "changed": step.changed_vars,
                "new_vars": step.new_vars,
                "removed": step.removed_vars,
            })

        steps_json = json.dumps(steps_data, ensure_ascii=False)
        vars_list = sorted(all_vars)

        abs_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)

        html = _TIMELINE_HTML.format(
            title=title,
            steps_json=steps_json,
            total_steps=len(steps_data),
            vars_list=", ".join(vars_list),
        )

        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(html)
        return abs_path

    def render_unified(
        self,
        graph: CausalGraph,
        timeline,
        output_path: str = "unified_view.html",
        title: str = "WHY + HOW: Unified View",
        highlight_chain: Optional[list] = None,
        insight=None,
    ) -> str:
        """Render causal graph + timeline in a single interactive page.

        Clicking a timeline step highlights the corresponding graph node.
        """
        # Prepare graph data
        nodes_data = []
        for nid, node in graph.nodes.items():
            style = NODE_STYLES.get(node.node_type, NODE_STYLES["CODE"])
            nodes_data.append({
                "id": nid,
                "label": f"{os.path.basename(node.file_path)}:{node.line_number}",
                "color": style["color"],
                "border": style["border"],
                "shape": style["shape"],
                "title": node.semantic_label or node.code_content[:60],
                "file": node.file_path,
                "line": node.line_number,
            })

        edges_data = []
        for src, dst, etype, _ in graph.edges:
            es = EDGE_STYLES.get(etype, {"color": "#999", "dashes": False})
            edges_data.append({
                "from": src, "to": dst,
                "color": es["color"],
                "dashes": es["dashes"],
                "title": es["title"],
            })

        # Prepare timeline data
        steps_data = []
        all_vars = set()
        for step in timeline.steps:
            var_states = {}
            for name, snap in step.variables.items():
                all_vars.add(name)
                var_states[name] = {
                    "value": snap.value_repr,
                    "type": snap.value_type,
                    "changed": name in step.changed_vars,
                    "is_new": name in step.new_vars,
                }
            steps_data.append({
                "index": step.step_index,
                "file": os.path.basename(step.file_path),
                "file_full": step.file_path,
                "line": step.line_number,
                "code": step.code_line,
                "func": step.function_name,
                "vars": var_states,
                "changed": step.changed_vars,
                "new_vars": step.new_vars,
            })

        abs_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)

        # Insight data
        insight_html = ""
        if insight:
            insight_html = f"""
            <div style="background:#1a1a3e;border:1px solid #e94560;border-radius:6px;padding:12px 16px;margin-bottom:8px;">
                <div style="color:#e94560;font-weight:bold;font-size:13px;">INSIGHT ({insight.algorithm_type}, {insight.confidence:.0%})</div>
                <div style="color:#ffd700;font-size:14px;margin-top:4px;">{insight.one_liner}</div>
                <div style="margin-top:8px;">
                    {''.join(f'<span style="background:#0f3460;color:#a8d8ea;padding:2px 8px;border-radius:10px;font-size:11px;margin-right:6px;">{p.name} ({p.confidence:.0%})</span>' for p in insight.patterns)}
                </div>
            </div>"""

        html = _UNIFIED_HTML.format(
            title=title,
            nodes_json=json.dumps(nodes_data, ensure_ascii=False),
            edges_json=json.dumps(edges_data, ensure_ascii=False),
            steps_json=json.dumps(steps_data, ensure_ascii=False),
            total_steps=len(steps_data),
            total_nodes=len(nodes_data),
            insight_html=insight_html,
        )

        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(html)
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


_TIMELINE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'Consolas','Monaco','Courier New',monospace; background:#1a1a2e; color:#eee; }}
.header {{ background:#16213e; padding:16px 24px; border-bottom:2px solid #0f3460; }}
.header h1 {{ font-size:18px; color:#e94560; }}
.header .stats {{ font-size:12px; color:#888; margin-top:4px; }}
.container {{ display:flex; height:calc(100vh - 80px); }}

/* Left: code panel */
.code-panel {{ width:45%; border-right:2px solid #0f3460; overflow-y:auto; padding:12px; }}
.code-line {{ padding:4px 8px; cursor:pointer; border-radius:3px; font-size:13px; line-height:1.6; white-space:pre; }}
.code-line:hover {{ background:#16213e; }}
.code-line.active {{ background:#0f3460; border-left:3px solid #e94560; }}
.code-line.executed {{ color:#a8d8ea; }}
.code-line .line-no {{ color:#555; display:inline-block; width:40px; text-align:right; margin-right:12px; }}
.code-line .step-badge {{ background:#e94560; color:#fff; font-size:10px; padding:1px 5px; border-radius:8px; margin-left:8px; }}

/* Right: state panel */
.state-panel {{ width:55%; overflow-y:auto; padding:16px; }}
.step-header {{ font-size:14px; color:#e94560; margin-bottom:12px; padding-bottom:8px; border-bottom:1px solid #333; }}
.step-header .step-num {{ font-size:28px; font-weight:bold; }}
.step-header .func {{ color:#a8d8ea; }}

/* Variable table */
.var-table {{ width:100%; border-collapse:collapse; font-size:12px; }}
.var-table th {{ text-align:left; padding:6px 10px; background:#16213e; color:#e94560; border-bottom:1px solid #0f3460; }}
.var-table td {{ padding:5px 10px; border-bottom:1px solid #222; }}
.var-table tr.changed {{ background:#1a1a0a; }}
.var-table tr.changed td {{ color:#ffd700; }}
.var-table tr.is-new td {{ color:#00ff88; }}
.var-name {{ color:#a8d8ea; font-weight:bold; }}
.var-value {{ color:#ddd; }}
.var-type {{ color:#666; font-size:11px; }}
.var-ref {{ color:#ff6b6b; font-size:11px; }}
.var-changed-badge {{ background:#ffd700; color:#000; font-size:10px; padding:1px 4px; border-radius:3px; }}
.var-new-badge {{ background:#00ff88; color:#000; font-size:10px; padding:1px 4px; border-radius:3px; }}
.var-removed {{ color:#666; text-decoration:line-through; }}

/* Controls */
.controls {{ display:flex; gap:8px; margin-bottom:16px; align-items:center; }}
.btn {{ background:#0f3460; color:#eee; border:1px solid #e94560; padding:6px 16px; cursor:pointer; border-radius:3px; font-size:13px; }}
.btn:hover {{ background:#e94560; }}
.btn:disabled {{ opacity:0.3; cursor:default; }}
.slider {{ flex:1; }}
.speed {{ color:#888; font-size:12px; }}
.current-step {{ font-size:20px; color:#e94560; font-weight:bold; min-width:60px; text-align:center; }}

/* Pointer visualization */
.pointer-box {{ margin-top:16px; padding:12px; background:#16213e; border-radius:6px; }}
.pointer-box h3 {{ color:#e94560; font-size:13px; margin-bottom:8px; }}
.ptr-row {{ display:flex; align-items:center; gap:8px; padding:3px 0; font-size:12px; }}
.ptr-name {{ color:#a8d8ea; min-width:80px; }}
.ptr-arrow {{ color:#e94560; }}
.ptr-target {{ color:#ffd700; }}
.ptr-new {{ color:#00ff88; font-size:10px; }}
.ptr-changed {{ color:#ff6b6b; font-size:10px; }}
</style>
</head>
<body>
<div class="header">
    <h1>{title}</h1>
    <div class="stats">Steps: {total_steps} | Variables tracked: {vars_list}</div>
</div>
<div class="container">
    <div class="code-panel" id="codePanel"></div>
    <div class="state-panel" id="statePanel">
        <div class="controls">
            <button class="btn" id="btnPrev" onclick="prevStep()">&#9664; Prev</button>
            <button class="btn" id="btnPlay" onclick="togglePlay()">&#9654; Play</button>
            <button class="btn" id="btnNext" onclick="nextStep()">Next &#9654;</button>
            <input type="range" class="slider" id="slider" min="0" max="0" value="0" oninput="goToStep(+this.value)">
            <span class="current-step" id="stepNum">0</span>
            <span class="speed">Speed: <input type="number" id="speedInput" value="500" min="50" max="3000" step="50" style="width:60px;background:#16213e;color:#eee;border:1px solid #333"> ms</span>
        </div>
        <div id="stepDetail"></div>
    </div>
</div>

<script>
var steps = {steps_json};
var currentStep = 0;
var playing = false;
var playTimer = null;

// Build code panel: collect unique lines across all steps
var codeMap = {{}};
var codeOrder = [];
steps.forEach(function(s) {{
    var key = s.file + ":" + s.line;
    if (!codeMap[key]) {{
        codeMap[key] = {{ file:s.file, line:s.line, code:s.code, steps:[] }};
        codeOrder.push(key);
    }}
    codeMap[key].steps.push(s.index);
}});

var codePanel = document.getElementById("codePanel");
codeOrder.forEach(function(key) {{
    var info = codeMap[key];
    var div = document.createElement("div");
    div.className = "code-line executed";
    div.id = "code-" + key.replace(/[^a-zA-Z0-9]/g, "_");
    div.innerHTML = '<span class="line-no">' + info.line + '</span>' + escapeHtml(info.code);
    div.onclick = function() {{ goToStep(info.steps[0]); }};
    codePanel.appendChild(div);
}});

function escapeHtml(s) {{
    return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}}

function goToStep(idx) {{
    currentStep = Math.max(0, Math.min(idx, steps.length - 1));
    document.getElementById("slider").value = currentStep;
    document.getElementById("stepNum").textContent = currentStep;
    renderStep();
}}

function nextStep() {{ goToStep(currentStep + 1); }}
function prevStep() {{ goToStep(currentStep - 1); }}

function togglePlay() {{
    playing = !playing;
    document.getElementById("btnPlay").textContent = playing ? "\\u23F9 Pause" : "\\u25B6 Play";
    if (playing) playNext();
    else if (playTimer) {{ clearTimeout(playTimer); playTimer = null; }}
}}

function playNext() {{
    if (!playing) return;
    var speed = parseInt(document.getElementById("speedInput").value) || 500;
    if (currentStep < steps.length - 1) {{
        nextStep();
        playTimer = setTimeout(playNext, speed);
    }} else {{
        playing = false;
        document.getElementById("btnPlay").textContent = "\\u25B6 Play";
    }}
}}

function renderStep() {{
    var s = steps[currentStep];

    // Highlight active code line
    document.querySelectorAll(".code-line").forEach(function(el) {{
        el.classList.remove("active");
    }});
    var codeKey = s.file + ":" + s.line;
    var codeId = "code-" + codeKey.replace(/[^a-zA-Z0-9]/g, "_");
    var activeEl = document.getElementById(codeId);
    if (activeEl) {{
        activeEl.classList.add("active");
        activeEl.scrollIntoView({{ block:"center", behavior:"smooth" }});
        // Add step badge
        var existing = activeEl.querySelector(".step-badge");
        if (!existing) {{
            var badge = document.createElement("span");
            badge.className = "step-badge";
            badge.textContent = "step " + s.index;
            activeEl.appendChild(badge);
        }} else {{
            existing.textContent = "step " + s.index;
        }}
    }}

    // Render state panel
    var html = '';
    html += '<div class="step-header">';
    html += '<span class="step-num">Step ' + s.index + '</span> ';
    html += '<span class="func">' + s.file + ':' + s.line + ' in ' + s.func + '()</span>';
    html += '<br><code style="color:#a8d8ea">' + escapeHtml(s.code) + '</code>';
    html += '</div>';

    // Changes summary
    if (s.changed.length || s.new_vars.length || s.removed.length) {{
        html += '<div style="margin-bottom:12px;font-size:12px">';
        if (s.changed.length) html += '<div style="color:#ffd700">Changed: ' + s.changed.join(", ") + '</div>';
        if (s.new_vars.length) html += '<div style="color:#00ff88">New: ' + s.new_vars.join(", ") + '</div>';
        if (s.removed.length) html += '<div style="color:#666">Removed: ' + s.removed.join(", ") + '</div>';
        html += '</div>';
    }}

    // Variable table
    var varNames = Object.keys(s.vars);
    if (varNames.length) {{
        html += '<table class="var-table">';
        html += '<tr><th>Variable</th><th>Value</th><th>Type</th><th>State</th></tr>';
        varNames.forEach(function(name) {{
            var v = s.vars[name];
            var rowClass = v.changed ? 'changed' : (v.is_new ? 'is-new' : '');
            html += '<tr class="' + rowClass + '">';
            html += '<td><span class="var-name">' + escapeHtml(name) + '</span></td>';
            html += '<td><span class="var-value">' + escapeHtml(v.value) + '</span></td>';
            html += '<td><span class="var-type">' + escapeHtml(v.type) + '</span></td>';
            html += '<td>';
            if (v.is_new) html += '<span class="var-new-badge">NEW</span> ';
            if (v.changed) html += '<span class="var-changed-badge">CHANGED</span> ';
            if (v.ref) html += '<span class="var-ref">\\u2192 ' + escapeHtml(v.ref) + '</span>';
            html += '</td></tr>';
        }});
        html += '</table>';
    }} else {{
        html += '<div style="color:#666;font-size:12px">No local variables</div>';
    }}

    // Pointer / reference box
    var refs = [];
    varNames.forEach(function(name) {{
        var v = s.vars[name];
        if (v.ref) refs.push({{ from:name, to:v.ref }});
    }});
    if (refs.length) {{
        html += '<div class="pointer-box"><h3>References</h3>';
        refs.forEach(function(r) {{
            html += '<div class="ptr-row">';
            html += '<span class="ptr-name">' + escapeHtml(r.from) + '</span>';
            html += '<span class="ptr-arrow">\\u2192</span>';
            html += '<span class="ptr-target">' + escapeHtml(r.to) + '</span>';
            html += '</div>';
        }});
        html += '</div>';
    }}

    document.getElementById("stepDetail").innerHTML = html;
}}

// Keyboard shortcuts
document.addEventListener("keydown", function(e) {{
    if (e.key === "ArrowRight" || e.key === "l") nextStep();
    else if (e.key === "ArrowLeft" || e.key === "h") prevStep();
    else if (e.key === " ") {{ e.preventDefault(); togglePlay(); }}
}});

// Init
document.getElementById("slider").max = steps.length - 1;
goToStep(0);
</script>
</body>
</html>"""


_UNIFIED_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'Consolas','Monaco','Courier New',monospace; background:#1a1a2e; color:#eee; }}
.header {{ background:#16213e; padding:12px 20px; border-bottom:2px solid #0f3460; display:flex; justify-content:space-between; align-items:center; }}
.header h1 {{ font-size:16px; color:#e94560; }}
.header .stats {{ font-size:11px; color:#888; }}
.main {{ display:flex; height:calc(100vh - 50px); }}

/* Left: Causal Graph */
.graph-panel {{ width:50%; position:relative; }}
.graph-panel iframe {{ width:100%; height:100%; border:none; }}

/* Right: Timeline */
.timeline-panel {{ width:50%; border-left:2px solid #0f3460; display:flex; flex-direction:column; }}
.controls {{ display:flex; gap:6px; padding:8px 12px; background:#16213e; align-items:center; flex-shrink:0; }}
.btn {{ background:#0f3460; color:#eee; border:1px solid #e94560; padding:4px 12px; cursor:pointer; border-radius:3px; font-size:12px; }}
.btn:hover {{ background:#e94560; }}
.slider {{ flex:1; }}
.current-step {{ font-size:16px; color:#e94560; font-weight:bold; min-width:40px; text-align:center; }}

.timeline-scroll {{ flex:1; overflow-y:auto; padding:8px; }}
.step-card {{ background:#16213e; border:1px solid #0f3460; border-radius:4px; padding:8px 10px; margin-bottom:4px; cursor:pointer; font-size:12px; }}
.step-card:hover {{ border-color:#e94560; }}
.step-card.active {{ border-color:#e94560; background:#1a1a3e; }}
.step-card .step-head {{ display:flex; justify-content:space-between; }}
.step-card .step-num {{ color:#e94560; font-weight:bold; }}
.step-card .step-code {{ color:#a8d8ea; margin-top:2px; }}
.step-card .step-changes {{ color:#ffd700; font-size:11px; margin-top:2px; }}
.step-card .step-vars {{ margin-top:4px; font-size:11px; }}
.step-card .var-row {{ display:flex; gap:8px; padding:1px 0; }}
.step-card .var-name {{ color:#a8d8ea; min-width:60px; }}
.step-card .var-val {{ color:#ddd; }}
.step-card .var-changed {{ color:#ffd700; font-weight:bold; }}
.step-card .var-new {{ color:#00ff88; }}

/* Graph highlight overlay */
.graph-highlight {{ position:absolute; top:10px; left:10px; background:rgba(233,69,96,0.9); color:#fff; padding:6px 12px; border-radius:4px; font-size:12px; z-index:10; pointer-events:none; display:none; }}
</style>
</head>
<body>
<div class="header">
    <h1>{title}</h1>
    <div class="stats">Graph: {total_nodes} nodes | Timeline: {total_steps} steps | Click timeline step to highlight graph node</div>
</div>
{insight_html}
<div class="main">
    <div class="graph-panel">
        <div class="graph-highlight" id="graphHighlight"></div>
        <div id="graphCanvas" style="width:100%;height:100%;background:#fff;"></div>
    </div>
    <div class="timeline-panel">
        <div class="controls">
            <button class="btn" onclick="prevStep()">&#9664;</button>
            <button class="btn" id="btnPlay" onclick="togglePlay()">&#9654;</button>
            <button class="btn" onclick="nextStep()">&#9654;</button>
            <input type="range" class="slider" id="slider" min="0" max="0" value="0" oninput="goToStep(+this.value)">
            <span class="current-step" id="stepNum">0</span>
        </div>
        <div class="timeline-scroll" id="timelineScroll"></div>
    </div>
</div>

<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<script>
var nodesData = {nodes_json};
var edgesData = {edges_json};
var steps = {steps_json};
var currentStep = 0;
var playing = false;
var playTimer = null;
var network = null;

// Build vis graph
var nodes = new vis.DataSet(nodesData.map(function(n) {{
    return {{
        id: n.id,
        label: n.label,
        color: {{ background: n.color, border: n.border }},
        shape: n.shape,
        title: n.title,
        borderWidth: 2,
        font: {{ size: 11 }}
    }};
}}));

var edges = new vis.DataSet(edgesData.map(function(e) {{
    return {{
        from: e.from, to: e.to,
        color: e.color,
        dashes: e.dashes,
        title: e.title,
        width: 1,
        arrows: 'to'
    }};
}}));

var container = document.getElementById('graphCanvas');
network = new vis.Network(container, {{ nodes: nodes, edges: edges }}, {{
    physics: {{ solver: 'forceAtlas2Based', forceAtlas2Based: {{ gravitationalConstant: -50, springLength: 150 }} }},
    interaction: {{ hover: true, tooltipDelay: 100 }}
}});

// Build timeline cards
var timelineDiv = document.getElementById('timelineScroll');
steps.forEach(function(s, i) {{
    var card = document.createElement('div');
    card.className = 'step-card';
    card.id = 'step-card-' + i;

    var headHtml = '<div class="step-head"><span class="step-num">Step ' + s.index + '</span><span style="color:#888">' + s.file + ':' + s.line + '</span></div>';
    var codeHtml = '<div class="step-code">' + escapeHtml(s.code) + '</div>';
    var changesHtml = '';
    if (s.changed.length || s.new_vars.length) {{
        changesHtml = '<div class="step-changes">';
        if (s.changed.length) changesHtml += 'Changed: ' + s.changed.join(', ') + ' ';
        if (s.new_vars.length) changesHtml += 'New: ' + s.new_vars.join(', ');
        changesHtml += '</div>';
    }}

    card.innerHTML = headHtml + codeHtml + changesHtml;
    card.onclick = function() {{ goToStep(i); }};
    timelineDiv.appendChild(card);
}});

function escapeHtml(s) {{ return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }}

function goToStep(idx) {{
    currentStep = Math.max(0, Math.min(idx, steps.length - 1));
    document.getElementById('slider').value = currentStep;
    document.getElementById('stepNum').textContent = currentStep;

    // Highlight timeline card
    document.querySelectorAll('.step-card').forEach(function(c) {{ c.classList.remove('active'); }});
    var card = document.getElementById('step-card-' + currentStep);
    if (card) {{
        card.classList.add('active');
        card.scrollIntoView({{ block: 'nearest', behavior: 'smooth' }});
    }}

    // Highlight graph node
    var s = steps[currentStep];
    var nodeId = s.file_full + ':' + s.line;
    // Try to find matching node
    var matchNode = null;
    nodesData.forEach(function(n) {{
        if (n.line === s.line && (n.file === s.file_full || n.file.endsWith(s.file))) {{
            matchNode = n.id;
        }}
    }});

    if (matchNode) {{
        // Highlight node in graph
        nodes.update({{ id: matchNode, borderWidth: 4, color: {{ background: '#FFEB3B', border: '#F57F17' }} }});
        network.selectNodes([matchNode]);
        network.focus(matchNode, {{ scale: 1.2, animation: true }});

        // Show overlay
        var overlay = document.getElementById('graphHighlight');
        overlay.textContent = 'Step ' + s.index + ': ' + s.file + ':' + s.line;
        overlay.style.display = 'block';
    }}

    // Reset previous highlights
    nodesData.forEach(function(n) {{
        if (n.id !== matchNode) {{
            nodes.update({{ id: n.id, borderWidth: 2, color: {{ background: n.color, border: n.border }} }});
        }}
    }});
}}

function nextStep() {{ goToStep(currentStep + 1); }}
function prevStep() {{ goToStep(currentStep - 1); }}

function togglePlay() {{
    playing = !playing;
    document.getElementById('btnPlay').textContent = playing ? '\\u23F9' : '\\u25B6';
    if (playing) playNext();
    else if (playTimer) {{ clearTimeout(playTimer); playTimer = null; }}
}}

function playNext() {{
    if (!playing) return;
    if (currentStep < steps.length - 1) {{
        nextStep();
        playTimer = setTimeout(playNext, 300);
    }} else {{
        playing = false;
        document.getElementById('btnPlay').textContent = '\\u25B6';
    }}
}}

document.addEventListener('keydown', function(e) {{
    if (e.key === 'ArrowRight') nextStep();
    else if (e.key === 'ArrowLeft') prevStep();
    else if (e.key === ' ') {{ e.preventDefault(); togglePlay(); }}
}});

document.getElementById('slider').max = steps.length - 1;
goToStep(0);
</script>
</body>
</html>"""
