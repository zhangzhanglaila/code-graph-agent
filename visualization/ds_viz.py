"""Data Structure Visualization — renders nodes, edges, and pointer animation."""

from __future__ import annotations
import json
import os
from typing import Dict, List, Optional, Set, Tuple

from dynamic.ds_tracer import DSTimeline, DSStep, ObjectSnapshot


def render_ds_timeline(
    timeline: DSTimeline,
    output_path: str = "ds_visualization.html",
    title: str = "Data Structure Visualization",
) -> str:
    """Render data structure evolution as interactive HTML with pointer animation."""
    # Analyze all steps to build graph structure
    all_obj_ids: Set[int] = set()
    for step in timeline.steps:
        all_obj_ids.update(step.objects.keys())

    # Build step data for JS
    steps_data = []
    for step in timeline.steps:
        # Object nodes
        nodes = {}
        for obj_id, snap in step.objects.items():
            nodes[str(obj_id)] = {
                "id": obj_id,
                "type": snap.type_name,
                "val": snap.val_repr,
                "attrs": snap.attributes,
                "refs": {k: v for k, v in snap.ref_ids.items()},
                "changed": obj_id in step.changed_objects,
            }

        # Variable bindings
        var_bindings = {}
        for var_name, obj_id in step.var_to_obj.items():
            if obj_id in step.objects:
                var_bindings[var_name] = obj_id

        # Reference edges (from ref_ids)
        edges = []
        for obj_id, snap in step.objects.items():
            for attr, target_id in snap.ref_ids.items():
                if str(target_id) in nodes:
                    is_changed = any(
                        cid == obj_id and attr == ref_attr
                        for cid, ref_attr, _ in step.changed_refs
                    )
                    edges.append({
                        "from": obj_id,
                        "to": target_id,
                        "label": attr,
                        "changed": is_changed,
                    })

        steps_data.append({
            "index": step.step_index,
            "line": step.line_number,
            "code": step.code_line,
            "func": step.function_name,
            "nodes": nodes,
            "edges": edges,
            "var_bindings": var_bindings,
            "changed_objects": step.changed_objects,
            "changed_refs": [(c[0], c[1], c[2]) for c in step.changed_refs],
        })

    abs_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)

    html = _DS_HTML.format(
        title=title,
        steps_json=json.dumps(steps_data, ensure_ascii=False),
        total_steps=len(steps_data),
    )

    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(html)
    return abs_path


_DS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'Consolas','Monaco',monospace; background:#0d1117; color:#c9d1d9; }}

.header {{ background:#161b22; padding:12px 20px; border-bottom:1px solid #30363d; display:flex; justify-content:space-between; align-items:center; }}
.header h1 {{ font-size:16px; color:#58a6ff; }}
.header .stats {{ font-size:11px; color:#8b949e; }}

.layout {{ display:flex; height:calc(100vh - 50px); }}

/* Left: Canvas area */
.canvas-area {{ flex:1; position:relative; overflow:hidden; background:#0d1117; }}
canvas {{ display:block; }}

/* Right: Info panel */
.info-panel {{ width:380px; border-left:1px solid #30363d; display:flex; flex-direction:column; background:#161b22; }}

.controls {{ display:flex; gap:6px; padding:10px; border-bottom:1px solid #30363d; align-items:center; flex-shrink:0; }}
.btn {{ background:#21262d; color:#c9d1d9; border:1px solid #30363d; padding:5px 14px; cursor:pointer; border-radius:4px; font-size:12px; }}
.btn:hover {{ background:#30363d; border-color:#58a6ff; }}
.slider {{ flex:1; accent-color:#58a6ff; }}
.step-display {{ font-size:16px; color:#58a6ff; font-weight:bold; min-width:40px; text-align:center; }}
.speed-input {{ width:50px; background:#0d1117; color:#c9d1d9; border:1px solid #30363d; padding:2px 4px; font-size:11px; }}

.code-box {{ padding:10px; border-bottom:1px solid #30363d; flex-shrink:0; }}
.code-line {{ color:#a5d6ff; font-size:13px; }}
.line-no {{ color:#8b949e; font-size:11px; margin-right:8px; }}

.vars-box {{ padding:10px; border-bottom:1px solid #30363d; flex-shrink:0; }}
.vars-box h3 {{ color:#58a6ff; font-size:12px; margin-bottom:6px; }}
.var-row {{ display:flex; gap:8px; font-size:12px; padding:2px 0; }}
.var-name {{ color:#ff7b72; min-width:60px; }}
.var-obj {{ color:#79c0ff; }}
.var-pointer {{ color:#ffa657; }}

.objects-box {{ flex:1; overflow-y:auto; padding:10px; }}
.objects-box h3 {{ color:#58a6ff; font-size:12px; margin-bottom:6px; }}
.obj-card {{ background:#0d1117; border:1px solid #30363d; border-radius:4px; padding:8px; margin-bottom:6px; font-size:11px; }}
.obj-card.changed {{ border-color:#f0883e; background:#1c1206; }}
.obj-head {{ display:flex; justify-content:space-between; margin-bottom:4px; }}
.obj-type {{ color:#79c0ff; }}
.obj-id {{ color:#8b949e; }}
.obj-attr {{ display:flex; gap:6px; padding:1px 0; }}
.obj-attr-name {{ color:#ff7b72; min-width:50px; }}
.obj-attr-val {{ color:#c9d1d9; }}
.obj-attr-ref {{ color:#ffa657; }}

.legend {{ padding:10px; border-top:1px solid #30363d; font-size:10px; color:#8b949e; flex-shrink:0; }}
.legend-item {{ display:inline-flex; align-items:center; gap:4px; margin-right:12px; }}
.legend-dot {{ width:10px; height:10px; border-radius:50%; display:inline-block; }}
</style>
</head>
<body>
<div class="header">
    <h1>{title}</h1>
    <div class="stats">Steps: {total_steps} | Arrow keys / Space to navigate</div>
</div>
<div class="layout">
    <div class="canvas-area">
        <canvas id="canvas"></canvas>
    </div>
    <div class="info-panel">
        <div class="controls">
            <button class="btn" onclick="prevStep()">&#9664;</button>
            <button class="btn" id="btnPlay" onclick="togglePlay()">&#9654;</button>
            <button class="btn" onclick="nextStep()">&#9654;</button>
            <input type="range" class="slider" id="slider" min="0" max="0" value="0" oninput="goToStep(+this.value)">
            <span class="step-display" id="stepNum">0</span>
            <input type="number" class="speed-input" id="speedInput" value="600" min="100" max="3000" step="100" title="ms per step">
        </div>
        <div class="code-box">
            <div class="code-line" id="codeLine"><span class="line-no">-</span> -</div>
        </div>
        <div class="vars-box" id="varsBox">
            <h3>Pointers</h3>
        </div>
        <div class="objects-box" id="objectsBox">
            <h3>Objects</h3>
        </div>
        <div class="legend">
            <span class="legend-item"><span class="legend-dot" style="background:#58a6ff"></span> Normal</span>
            <span class="legend-item"><span class="legend-dot" style="background:#f0883e"></span> Changed</span>
            <span class="legend-item"><span class="legend-dot" style="background:#3fb950"></span> Pointer target</span>
            <span class="legend-item" style="color:#ffa657">→ reference arrow</span>
        </div>
    </div>
</div>

<script>
var steps = {steps_json};
var currentStep = 0;
var playing = false;
var playTimer = null;

// Canvas setup
var canvas = document.getElementById('canvas');
var ctx = canvas.getContext('2d');
var W, H;
function resize() {{
    var rect = canvas.parentElement.getBoundingClientRect();
    W = rect.width;
    H = rect.height;
    canvas.width = W * devicePixelRatio;
    canvas.height = H * devicePixelRatio;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
    renderCanvas();
}}
window.addEventListener('resize', resize);

// Node layout: force-directed simulation
var nodePositions = {{}};  // objId → position object

function layoutNodes(stepData) {{
    var ids = Object.keys(stepData.nodes);
    var changed = new Set(stepData.changed_objects.map(String));

    // Keep existing positions, add new ones
    ids.forEach(function(id) {{
        if (!nodePositions[id]) {{
            // New node: place near center with some randomness
            nodePositions[id] = {{
                x: W/2 + (Math.random()-0.5)*200,
                y: H/2 + (Math.random()-0.5)*200,
                vx: 0, vy: 0
            }};
        }}
    }});

    // Simple force simulation (a few iterations)
    for (var iter = 0; iter < 30; iter++) {{
        ids.forEach(function(id1) {{
            var p1 = nodePositions[id1];
            if (!p1) return;

            // Repulsion from other nodes
            ids.forEach(function(id2) {{
                if (id1 === id2) return;
                var p2 = nodePositions[id2];
                if (!p2) return;
                var dx = p1.x - p2.x;
                var dy = p1.y - p2.y;
                var dist = Math.sqrt(dx*dx + dy*dy) || 1;
                var force = 5000 / (dist * dist);
                p1.vx += (dx/dist) * force;
                p1.vy += (dy/dist) * force;
            }});

            // Attraction along edges
            stepData.edges.forEach(function(e) {{
                var from = nodePositions[String(e.from)];
                var to = nodePositions[String(e.to)];
                if (!from || !to) return;
                var dx = to.x - from.x;
                var dy = to.y - from.y;
                var dist = Math.sqrt(dx*dx + dy*dy) || 1;
                var force = (dist - 180) * 0.01;
                if (String(e.from) === id1) {{
                    p1.vx += (dx/dist) * force;
                    p1.vy += (dy/dist) * force;
                }} else if (String(e.to) === id1) {{
                    p1.vx -= (dx/dist) * force;
                    p1.vy -= (dy/dist) * force;
                }}
            }});

            // Center gravity
            p1.vx += (W/2 - p1.x) * 0.001;
            p1.vy += (H/2 - p1.y) * 0.001;
        }});

        // Apply velocities
        ids.forEach(function(id) {{
            var p = nodePositions[id];
            if (!p) return;
            p.x += p.vx * 0.5;
            p.y += p.vy * 0.5;
            p.vx *= 0.8;
            p.vy *= 0.8;
            // Bounds
            p.x = Math.max(40, Math.min(W-40, p.x));
            p.y = Math.max(40, Math.min(H-40, p.y));
        }});
    }}

    // Remove nodes no longer present
    Object.keys(nodePositions).forEach(function(id) {{
        if (ids.indexOf(id) === -1) delete nodePositions[id];
    }});
}}

function renderCanvas() {{
    ctx.clearRect(0, 0, W, H);

    if (!steps.length) return;
    var s = steps[currentStep];
    layoutNodes(s);

    var changed = new Set(s.changed_objects.map(String));
    var changedRefs = new Set();
    s.changed_refs.forEach(function(cr) {{
        changedRefs.add(cr[0] + ':' + cr[1]);
    }});

    // Draw edges
    s.edges.forEach(function(e) {{
        var from = nodePositions[String(e.from)];
        var to = nodePositions[String(e.to)];
        if (!from || !to) return;

        var isChanged = changedRefs.has(e.from + ':' + e.label);
        ctx.strokeStyle = isChanged ? '#f0883e' : '#30363d';
        ctx.lineWidth = isChanged ? 3 : 1.5;

        // Arrow
        var dx = to.x - from.x;
        var dy = to.y - from.y;
        var dist = Math.sqrt(dx*dx + dy*dy) || 1;
        var nodeR = 28;
        var startX = from.x + (dx/dist) * nodeR;
        var startY = from.y + (dy/dist) * nodeR;
        var endX = to.x - (dx/dist) * nodeR;
        var endY = to.y - (dy/dist) * nodeR;

        ctx.beginPath();
        ctx.moveTo(startX, startY);
        ctx.lineTo(endX, endY);
        ctx.stroke();

        // Arrowhead
        var angle = Math.atan2(endY - startY, endX - startX);
        ctx.beginPath();
        ctx.moveTo(endX, endY);
        ctx.lineTo(endX - 10*Math.cos(angle-0.4), endY - 10*Math.sin(angle-0.4));
        ctx.lineTo(endX - 10*Math.cos(angle+0.4), endY - 10*Math.sin(angle+0.4));
        ctx.closePath();
        ctx.fillStyle = isChanged ? '#f0883e' : '#30363d';
        ctx.fill();

        // Edge label
        var midX = (startX + endX) / 2;
        var midY = (startY + endY) / 2 - 8;
        ctx.fillStyle = isChanged ? '#ffa657' : '#8b949e';
        ctx.font = '10px Consolas';
        ctx.textAlign = 'center';
        ctx.fillText(e.label, midX, midY);
    }});

    // Draw nodes
    var varBindings = s.var_bindings || {{}};
    // Reverse: objId → [varNames]
    var objToVars = {{}};
    Object.keys(varBindings).forEach(function(vname) {{
        var oid = String(varBindings[vname]);
        if (!objToVars[oid]) objToVars[oid] = [];
        objToVars[oid].push(vname);
    }});

    Object.keys(s.nodes).forEach(function(id) {{
        var node = s.nodes[id];
        var pos = nodePositions[id];
        if (!pos) return;

        var isChanged = changed.has(id);
        var isPointerTarget = Object.values(varBindings).indexOf(parseInt(id)) >= 0;

        // Node circle
        ctx.beginPath();
        ctx.arc(pos.x, pos.y, 28, 0, Math.PI*2);
        ctx.fillStyle = isChanged ? '#1c1206' : '#161b22';
        ctx.fill();
        ctx.strokeStyle = isChanged ? '#f0883e' : (isPointerTarget ? '#3fb950' : '#58a6ff');
        ctx.lineWidth = isChanged ? 3 : 2;
        ctx.stroke();

        // Node value
        ctx.fillStyle = '#c9d1d9';
        ctx.font = 'bold 13px Consolas';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        var displayVal = node.val;
        // Extract the value field if it's a Node object
        if (node.attrs && node.attrs.val !== undefined) {{
            displayVal = node.attrs.val;
        }}
        ctx.fillText(displayVal, pos.x, pos.y);

        // Type label
        ctx.fillStyle = '#8b949e';
        ctx.font = '9px Consolas';
        ctx.fillText(node.type, pos.x, pos.y + 18);

        // Variable labels above node
        var vnames = objToVars[id] || [];
        if (vnames.length) {{
            ctx.fillStyle = '#ffa657';
            ctx.font = 'bold 11px Consolas';
            ctx.fillText(vnames.join(', '), pos.x, pos.y - 36);
        }}
    }});
}}

// Info panel rendering
function renderInfo() {{
    if (!steps.length) return;
    var s = steps[currentStep];

    // Code line
    document.getElementById('codeLine').innerHTML =
        '<span class="line-no">' + s.line + '</span> ' + escapeHtml(s.code);

    // Variables (pointers)
    var varsHtml = '<h3>Pointers</h3>';
    var vb = s.var_bindings || {{}};
    Object.keys(vb).forEach(function(vname) {{
        var oid = vb[vname];
        var node = s.nodes[String(oid)];
        var valStr = node ? (node.attrs && node.attrs.val !== undefined ? node.attrs.val : node.val) : '?';
        varsHtml += '<div class="var-row"><span class="var-name">' + escapeHtml(vname) +
                    '</span> <span class="var-obj">→ ' + escapeHtml(node ? node.type + '(' + valStr + ')' : 'null') + '</span></div>';
    }});
    if (!Object.keys(vb).length) varsHtml += '<div style="color:#8b949e;font-size:11px">No pointers</div>';
    document.getElementById('varsBox').innerHTML = varsHtml;

    // Objects
    var objHtml = '<h3>Objects</h3>';
    var nodeIds = Object.keys(s.nodes);
    nodeIds.forEach(function(id) {{
        var node = s.nodes[id];
        var isChanged = s.changed_objects.indexOf(parseInt(id)) >= 0;
        objHtml += '<div class="obj-card' + (isChanged ? ' changed' : '') + '">';
        objHtml += '<div class="obj-head"><span class="obj-type">' + escapeHtml(node.type) + '</span>';
        objHtml += '<span class="obj-id">id:' + id + (isChanged ? ' CHANGED' : '') + '</span></div>';
        // Attributes
        if (node.attrs) {{
            Object.keys(node.attrs).forEach(function(attr) {{
                var refId = node.refs && node.refs[attr];
                if (refId) {{
                    var refNode = s.nodes[String(refId)];
                    var refVal = refNode ? (refNode.attrs && refNode.attrs.val !== undefined ? refNode.attrs.val : refNode.val) : '?';
                    objHtml += '<div class="obj-attr"><span class="obj-attr-name">' + escapeHtml(attr) +
                               '</span> <span class="obj-attr-ref">→ ' + escapeHtml(refNode ? refNode.type + '(' + refVal + ')' : 'null(' + refId + ')') + '</span></div>';
                }} else {{
                    objHtml += '<div class="obj-attr"><span class="obj-attr-name">' + escapeHtml(attr) +
                               '</span> <span class="obj-attr-val">' + escapeHtml(node.attrs[attr]) + '</span></div>';
                }}
            }});
        }}
        objHtml += '</div>';
    }});
    if (!nodeIds.length) objHtml += '<div style="color:#8b949e;font-size:11px">No objects</div>';
    document.getElementById('objectsBox').innerHTML = objHtml;
}}

function escapeHtml(s) {{ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }}

function goToStep(idx) {{
    currentStep = Math.max(0, Math.min(idx, steps.length-1));
    document.getElementById('slider').value = currentStep;
    document.getElementById('stepNum').textContent = currentStep;
    renderCanvas();
    renderInfo();
}}

function nextStep() {{ goToStep(currentStep+1); }}
function prevStep() {{ goToStep(currentStep-1); }}

function togglePlay() {{
    playing = !playing;
    document.getElementById('btnPlay').textContent = playing ? '\\u23F9' : '\\u25B6';
    if (playing) playNext();
    else if (playTimer) {{ clearTimeout(playTimer); playTimer = null; }}
}}

function playNext() {{
    if (!playing) return;
    var speed = parseInt(document.getElementById('speedInput').value) || 600;
    if (currentStep < steps.length-1) {{
        nextStep();
        playTimer = setTimeout(playNext, speed);
    }} else {{
        playing = false;
        document.getElementById('btnPlay').textContent = '\\u25B6';
    }}
}}

document.addEventListener('keydown', function(e) {{
    if (e.key === 'ArrowRight' || e.key === 'l') nextStep();
    else if (e.key === 'ArrowLeft' || e.key === 'h') prevStep();
    else if (e.key === ' ') {{ e.preventDefault(); togglePlay(); }}
}});

document.getElementById('slider').max = steps.length - 1;
resize();
goToStep(0);
</script>
</body>
</html>"""
