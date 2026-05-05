"""FastAPI backend — connects Python analysis engine to Vue frontend."""

from __future__ import annotations
import importlib
import json
import os
import sys
import tempfile
import time
import uuid
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from core.graph import CausalGraph
from static.python_analyzer import PythonAnalyzer
from static.config_linker import ConfigLinker
from dynamic.state_recorder import record_function
from dynamic.ds_tracer import trace_ds_function
from dynamic.exception_parser import ExceptionParser
from fusion.merge_engine import MergeEngine
from reasoning.result_explainer import explain_result
from reasoning.insight_summarizer import summarize_insight
from query.root_cause import RootCauseQuery
from visualization.graph_ui import GraphVisualizer
from visualization.ds_viz import render_ds_timeline
from api.sandbox import run_sandboxed
from reasoning.llm_reasoner import LLMReasoner
from reasoning.importance import compute_importance

app = FastAPI(title="Why-Code-Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve output directory for generated HTML files
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")

# Session cache — avoid re-executing code for explain endpoints
SESSION_CACHE: dict = {}
SESSION_TTL = 600  # 10 minutes


def _cache_put(session_id: str, data: dict):
    SESSION_CACHE[session_id] = {**data, "_ts": time.time()}
    # Evict expired
    now = time.time()
    expired = [k for k, v in SESSION_CACHE.items() if now - v.get("_ts", 0) > SESSION_TTL]
    for k in expired:
        del SESSION_CACHE[k]


def _cache_get(session_id: str) -> dict | None:
    entry = SESSION_CACHE.get(session_id)
    if not entry:
        return None
    if time.time() - entry.get("_ts", 0) > SESSION_TTL:
        del SESSION_CACHE[session_id]
        return None
    return entry


# ── Request/Response models ─────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    code: str
    language: str = "python"
    error_line: Optional[int] = None
    config: Optional[str] = None


class InsightRequest(BaseModel):
    code: str
    func_name: str = ""
    language: str = "python"


class DSVizRequest(BaseModel):
    code: str
    func_name: str = ""
    language: str = "python"


class RunRequest(BaseModel):
    code: str
    func_name: str = ""
    timeout: int = 10


class ExplainRequest(BaseModel):
    code: str
    func_name: str = ""
    language: str = "python"
    provider: str = "mock"  # mock | anthropic | openai
    api_key: str = ""


class ExplainStepsRequest(BaseModel):
    code: str = ""
    func_name: str = ""
    language: str = "python"
    provider: str = "mock"
    api_key: str = ""
    session_id: str = ""


class ExplainStepFocusRequest(BaseModel):
    code: str = ""
    func_name: str = ""
    language: str = "python"
    step_index: int = 0
    window_before: int = 2
    window_after: int = 2
    provider: str = "mock"
    api_key: str = ""
    session_id: str = ""


# ── Helpers ──────────────────────────────────────────────────────────

def _write_temp_code(code: str, language: str) -> str:
    """Write code to a temp file and return the path."""
    ext = {"python": ".py", "javascript": ".js", "typescript": ".ts"}.get(language, ".py")
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=ext, delete=False, encoding="utf-8")
    tmp.write(code)
    tmp.close()
    return tmp.name


def _compute_control_edges(steps_data: list) -> list:
    """Compute control flow edges from the timeline.

    For each if/for/while step, find the steps inside its body
    (deeper indentation, consecutive) and create control edges.
    """
    import ast as _ast
    edges = []
    stack = []  # (step_index, indent_level)

    for i, step in enumerate(steps_data):
        code = step.get("code", "").rstrip()
        if not code:
            continue

        indent = len(code) - len(code.lstrip())
        code_stripped = code.lstrip()

        # Pop stack when indentation decreases
        while stack and stack[-1][1] >= indent:
            stack.pop()

        # If we're inside a control structure, add edge from that structure to us
        if stack:
            parent_idx = stack[-1][0]
            # Only add if not already a data edge (avoid duplicates later)
            edges.append({"from": parent_idx, "to": step["index"], "type": "control"})

        # Detect control structures
        is_control = False
        for prefix in ("if ", "elif ", "for ", "while ", "try:", "except ", "else:"):
            if code_stripped.startswith(prefix):
                is_control = True
                break

        if is_control:
            stack.append((step["index"], indent))

    return edges


def _compute_loop_groups(steps_data: list) -> list:
    """Detect loop iteration groups — consecutive steps from the same source line.

    Returns list of {line, steps: [step_indices], label: "iteration N"}.
    """
    if not steps_data:
        return []

    groups = []
    current_line = None
    current_steps = []
    iteration = 0

    for step in steps_data:
        line = step.get("line", 0)
        code = step.get("code", "").lstrip()

        # Detect loop headers
        is_loop_header = any(code.startswith(p) for p in ("for ", "while "))

        if line == current_line and not is_loop_header:
            # Same source line — part of same iteration group
            current_steps.append(step["index"])
        else:
            # New line or loop header
            if current_steps and len(current_steps) >= 3:
                # Only group if 3+ steps from same line (actual loop body)
                groups.append({
                    "line": current_line,
                    "steps": current_steps,
                    "label": f"iteration {iteration}",
                })
                iteration += 1
            elif current_steps:
                iteration = 0
            current_line = line
            current_steps = [step["index"]]

    # Final group
    if current_steps and len(current_steps) >= 3:
        groups.append({
            "line": current_line,
            "steps": current_steps,
            "label": f"iteration {iteration}",
        })

    return groups


def _extract_func_name(code: str, func_name: str) -> str:
    """Extract function name from code if not provided."""
    if func_name:
        return func_name
    # Find first function definition
    for line in code.splitlines():
        line = line.strip()
        if line.startswith("def "):
            return line[4:].split("(")[0].strip()
    return ""


def _import_code_as_module(code: str, module_name: str = "_user_code"):
    """Import user code as a module."""
    tmp_path = _write_temp_code(code, "python")
    spec = importlib.util.spec_from_file_location(module_name, tmp_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    os.unlink(tmp_path)
    return module


# ── Endpoints ────────────────────────────────────────────────────────

@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    """Full causal analysis of code."""
    tmp_path = None
    try:
        tmp_path = _write_temp_code(req.code, req.language)
        analyzer = PythonAnalyzer()
        graph = analyzer.analyze_file(tmp_path)

        # Config linking
        if req.config:
            linker = ConfigLinker()
            config_path = _write_temp_code(req.config, "yaml")
            config_graph = linker.build_graph(config_path, [tmp_path])
            graph.merge_from(config_graph)
            os.unlink(config_path)

        # Error chain
        error_chain = []
        if req.error_line:
            node_id = f"{tmp_path}:{req.error_line}"
            if graph.has_node(node_id):
                query = RootCauseQuery(graph)
                error_chain = query.get_root_cause_chain(node_id)

        # Render graph
        viz = GraphVisualizer()
        html_path = viz.render(
            graph,
            output_path=os.path.join(OUTPUT_DIR, "causal_graph.html"),
            highlight_chain=[link["node_id"] for link in error_chain] if error_chain else None,
        )

        stats = graph.stats()

        return {
            "stats": stats,
            "error_chain": error_chain,
            "graph_url": "/output/causal_graph.html",
            "nodes": [n.to_dict() for n in graph.nodes.values()],
            "edges": [{"source": s, "target": t, "type": e.value} for s, t, e, _ in graph.edges],
        }
    except Exception as e:
        return {"success": False, "error": str(e), "error_type": type(e).__name__}
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@app.post("/api/insight")
async def get_insight(req: InsightRequest):
    """Get cognitive-level insight for code."""
    tmp_path = None
    try:
        func_name = _extract_func_name(req.code, req.func_name)
        if not func_name:
            return {"success": False, "error": "No function found in code. Define a function to analyze."}

        module = _import_code_as_module(req.code)
        func = getattr(module, func_name)

        tmp_path = _write_temp_code(req.code, req.language)

        # Record execution
        result, timeline = record_function(func, target_files={os.path.abspath(tmp_path)})

        # Generate insight
        insight = summarize_insight(timeline, result, func_name)

        # Generate explanation
        explanation = explain_result(timeline, result, func_name)

        # Render timeline
        viz = GraphVisualizer()
        html_path = viz.render_timeline(
            timeline,
            output_path=os.path.join(OUTPUT_DIR, "execution_timeline.html"),
            title=f"Timeline: {func_name}()",
        )

        # Steps data for frontend
        steps_data = []
        for step in timeline.steps:
            var_states = {}
            for name, snap in step.variables.items():
                var_states[name] = {
                    "value": snap.value_repr,
                    "type": snap.value_type,
                    "changed": name in step.changed_vars,
                    "is_new": name in step.new_vars,
                }
            steps_data.append({
                "index": step.step_index,
                "file": os.path.basename(step.file_path),
                "line": step.line_number,
                "code": step.code_line,
                "func": step.function_name,
                "vars": var_states,
                "changed": step.changed_vars,
                "new_vars": step.new_vars,
            })

        # Cache for explain endpoints
        session_id = str(uuid.uuid4())[:8]
        _cache_put(session_id, {
            "code": req.code,
            "func_name": func_name,
            "language": req.language,
            "steps_data": steps_data,
            "insight": insight,
            "result": result,
            "timeline": timeline,
        })

        return {
            "success": True,
            "session_id": session_id,
            "result": result,
            "func_name": func_name,
            "insight": {
                "one_liner": insight.one_liner,
                "algorithm_type": insight.algorithm_type,
                "confidence": insight.confidence,
                "patterns": [{"name": p.name, "confidence": p.confidence, "description": p.description} for p in insight.patterns],
                "phases": [{"name": p.name, "start_step": p.start_step, "end_step": p.end_step, "description": p.description, "key_variables": p.key_variables, "step_count": p.step_count} for p in insight.phases],
                "explanation_levels": insight.explanation_levels,
            },
            "explanation": explanation,
            "timeline": steps_data,
            "timeline_url": "/output/execution_timeline.html",
            "total_steps": len(steps_data),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "error_type": type(e).__name__}
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@app.post("/api/ds-viz")
async def get_ds_viz(req: DSVizRequest):
    """Data structure visualization."""
    tmp_path = None
    try:
        func_name = _extract_func_name(req.code, req.func_name)
        if not func_name:
            return {"success": False, "error": "No function found in code. Define a function to analyze."}

        module = _import_code_as_module(req.code)
        func = getattr(module, func_name)

        tmp_path = _write_temp_code(req.code, req.language)

        result, timeline = trace_ds_function(func, target_files={os.path.abspath(tmp_path)})

        # Render
        html_path = render_ds_timeline(
            timeline,
            output_path=os.path.join(OUTPUT_DIR, "ds_visualization.html"),
            title=f"Data Structure: {func_name}()",
        )

        # Steps data for frontend
        steps_data = []
        for step in timeline.steps:
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

            var_bindings = {}
            for var_name, obj_id in step.var_to_obj.items():
                if obj_id in step.objects:
                    var_bindings[var_name] = obj_id

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
                "nodes": nodes,
                "edges": edges,
                "var_bindings": var_bindings,
                "changed_objects": step.changed_objects,
            })

        return {
            "success": True,
            "result": result,
            "func_name": func_name,
            "steps": steps_data,
            "total_steps": len(steps_data),
            "ds_viz_url": "/output/ds_visualization.html",
        }
    except Exception as e:
        return {"success": False, "error": str(e), "error_type": type(e).__name__}
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@app.post("/api/run")
async def run_code(req: RunRequest):
    """Run code in sandboxed subprocess."""
    func_name = _extract_func_name(req.code, req.func_name)
    result = run_sandboxed(
        code=req.code,
        func_name=func_name,
        timeout=req.timeout,
    )
    if not result["success"]:
        return {
            "success": False,
            "error": result["error"],
            "timed_out": result["timed_out"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
        }
    return {
        "success": True,
        "result": result["result"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
    }


@app.post("/api/explain")
async def explain_code(req: ExplainRequest):
    """LLM-powered execution-aware code explanation."""
    tmp_path = None
    try:
        func_name = _extract_func_name(req.code, req.func_name)
        if not func_name:
            return {"success": False, "error": "No function found in code. Define a function to analyze."}

        module = _import_code_as_module(req.code)
        func = getattr(module, func_name)
        tmp_path = _write_temp_code(req.code, req.language)

        # Record execution
        result, timeline = record_function(func, target_files={os.path.abspath(tmp_path)})

        # Generate insight data
        insight = summarize_insight(timeline, result, func_name)
        explanation = explain_result(timeline, result, func_name)

        # Format steps for LLM
        steps_data = []
        for step in timeline.steps:
            var_states = {}
            for name, snap in step.variables.items():
                var_states[name] = {
                    "value": snap.value_repr,
                    "type": snap.value_type,
                    "changed": name in step.changed_vars,
                }
            steps_data.append({
                "index": step.step_index,
                "line": step.line_number,
                "code": step.code_line,
                "vars": var_states,
                "changed": step.changed_vars or step.new_vars,
            })

        # Format lineage for LLM
        lineage_text = ""
        if explanation.get("lineage"):
            parts = []
            for item in explanation["lineage"]:
                event = item["event"]
                var = item["variable"]
                val = item["value"]
                if event == "created":
                    parts.append(f"{var} = {val} (step {item['step']})")
                else:
                    prev = item.get("prev_value", "?")
                    parts.append(f"{var}: {prev} -> {val} (step {item['step']})")
            lineage_text = "\n".join(parts)

        # Call LLM
        reasoner = LLMReasoner(
            provider=req.provider,
            api_key=req.api_key or None,
        )
        llm_explanation = reasoner.explain_execution(
            code=req.code,
            func_name=func_name,
            result=result,
            timeline_steps=steps_data,
            patterns=[{"name": p.name, "confidence": p.confidence, "description": p.description} for p in insight.patterns],
            phases=[{"name": p.name, "start_step": p.start_step, "end_step": p.end_step, "description": p.description} for p in insight.phases],
            lineage=lineage_text,
        )

        return {
            "success": True,
            "llm_explanation": llm_explanation,
            "result": result,
            "func_name": func_name,
            "total_steps": len(steps_data),
            "patterns_count": len(insight.patterns),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "error_type": type(e).__name__}
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@app.post("/api/explain_steps")
async def explain_steps(req: ExplainStepsRequest):
    """Batch step-by-step AI explanations for timeline. Uses cache if session_id provided."""
    try:
        # Try cache first
        cached = _cache_get(req.session_id) if req.session_id else None
        if cached:
            code = cached["code"]
            func_name = cached["func_name"]
            steps_data = cached["steps_data"]
            insight = cached["insight"]
        else:
            if not req.code:
                return {"success": False, "error": "No code or session_id provided."}
            func_name = _extract_func_name(req.code, req.func_name)
            if not func_name:
                return {"success": False, "error": "No function found in code."}

            module = _import_code_as_module(req.code)
            func = getattr(module, func_name)
            tmp_path = _write_temp_code(req.code, req.language)
            result, timeline = record_function(func, target_files={os.path.abspath(tmp_path)})
            insight = summarize_insight(timeline, result, func_name)
            os.unlink(tmp_path)

            steps_data = []
            for step in timeline.steps:
                var_states = {}
                for name, snap in step.variables.items():
                    var_states[name] = {
                        "value": snap.value_repr,
                        "type": snap.value_type,
                        "changed": name in step.changed_vars,
                        "is_new": name in step.new_vars,
                    }
                steps_data.append({
                    "index": step.step_index,
                    "line": step.line_number,
                    "code": step.code_line,
                    "vars": var_states,
                    "changed": step.changed_vars,
                    "new_vars": step.new_vars,
                })
            code = req.code

        algorithm_summary = insight.one_liner if hasattr(insight, 'one_liner') else (insight.get("one_liner", "") if isinstance(insight, dict) else "")

        reasoner = LLMReasoner(provider=req.provider, api_key=req.api_key or None)
        explanations = reasoner.explain_steps_batch(
            code=code,
            func_name=func_name,
            timeline_steps=steps_data,
            algorithm_summary=algorithm_summary,
        )

        # Hybrid importance: merge structural + dynamic + LLM signals
        llm_map = {e.get("step", i): e for i, e in enumerate(explanations)}
        enriched = []
        for i, step in enumerate(steps_data):
            llm = llm_map.get(step["index"], llm_map.get(i, {}))
            prev_vars = steps_data[i - 1]["vars"] if i > 0 else None
            future = steps_data[i + 1:i + 4]  # next 3 steps for impact analysis
            hybrid = compute_importance(
                code_line=step["code"],
                changed_vars=step.get("changed", []),
                new_vars=step.get("new_vars", []),
                all_vars=step.get("vars", {}),
                prev_vars=prev_vars,
                llm_importance=llm.get("importance"),
                llm_turning_point=llm.get("turning_point", False),
                future_steps=future,
            )
            enriched.append({
                "step": step["index"],
                "explanation": llm.get("explanation", ""),
                "importance": hybrid["label"],
                "importance_score": hybrid["score"],
                "importance_reasons": hybrid["reasons"],
                "importance_explanation": hybrid.get("explanation", ""),
                "affects": hybrid.get("affects", []),
                "signals": hybrid["signals"],
                "turning_point": llm.get("turning_point", False),
            })

        # Relative ranking: compute percentile within trace
        if enriched:
            scores = [e["importance_score"] for e in enriched]
            n = len(scores)
            for e in enriched:
                e["importance_percentile"] = round(
                    sum(1 for s in scores if s <= e["importance_score"]) / n, 3
                )

        # Control flow edges + loop folding
        cf_edges = _compute_control_edges(steps_data)
        loop_groups = _compute_loop_groups(steps_data)

        return {
            "success": True,
            "explanations": enriched,
            "control_edges": cf_edges,
            "loop_groups": loop_groups,
            "total_steps": len(steps_data),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "error_type": type(e).__name__}


@app.post("/api/explain_step_focus")
async def explain_step_focus(req: ExplainStepFocusRequest):
    """Focused explanation for a single step. Uses cache if session_id provided."""
    try:
        # Try cache first
        cached = _cache_get(req.session_id) if req.session_id else None
        if cached:
            code = cached["code"]
            func_name = cached["func_name"]
            steps_data = cached["steps_data"]
            insight = cached["insight"]
        else:
            if not req.code:
                return {"success": False, "error": "No code or session_id provided."}
            func_name = _extract_func_name(req.code, req.func_name)
            if not func_name:
                return {"success": False, "error": "No function found in code."}

            module = _import_code_as_module(req.code)
            func = getattr(module, func_name)
            tmp_path = _write_temp_code(req.code, req.language)
            result, timeline = record_function(func, target_files={os.path.abspath(tmp_path)})
            insight = summarize_insight(timeline, result, func_name)
            os.unlink(tmp_path)

            steps_data = []
            for step in timeline.steps:
                var_states = {}
                for name, snap in step.variables.items():
                    var_states[name] = {
                        "value": snap.value_repr,
                        "type": snap.value_type,
                        "changed": name in step.changed_vars,
                    }
                steps_data.append({
                    "index": step.step_index,
                    "line": step.line_number,
                    "code": step.code_line,
                    "vars": var_states,
                    "changed": step.changed_vars,
                })
            code = req.code

        if req.step_index >= len(steps_data):
            return {"success": False, "error": f"Step {req.step_index} out of range (0-{len(steps_data)-1})"}

        algorithm_summary = insight.one_liner if hasattr(insight, 'one_liner') else (insight.get("one_liner", "") if isinstance(insight, dict) else "")

        reasoner = LLMReasoner(provider=req.provider, api_key=req.api_key or None)
        explanation = reasoner.explain_step_focus(
            code=code,
            func_name=func_name,
            timeline_steps=steps_data,
            target_step=req.step_index,
            window=(-req.window_before, req.window_after),
            algorithm_summary=algorithm_summary,
        )

        # Hybrid importance
        step = steps_data[req.step_index]
        prev_vars = steps_data[req.step_index - 1]["vars"] if req.step_index > 0 else None
        future = steps_data[req.step_index + 1:req.step_index + 4]
        hybrid = compute_importance(
            code_line=step["code"],
            changed_vars=step.get("changed", []),
            new_vars=step.get("new_vars", []),
            all_vars=step.get("vars", {}),
            prev_vars=prev_vars,
            llm_importance=explanation.get("importance"),
            llm_turning_point=explanation.get("turning_point", False),
            future_steps=future,
        )
        explanation["importance_score"] = hybrid["score"]
        explanation["importance_reasons"] = hybrid["reasons"]
        explanation["importance_explanation"] = hybrid.get("explanation", "")
        explanation["affects"] = hybrid.get("affects", [])
        explanation["signals"] = hybrid["signals"]
        explanation["importance"] = hybrid["label"]

        return {"success": True, "explanation": explanation}
    except Exception as e:
        return {"success": False, "error": str(e), "error_type": type(e).__name__}


# ── Semantic Algorithm Understanding ──────────────────────────────────

def _detect_semantic_properties(code: str, steps_data: list, control_edges: list) -> dict:
    """Detect computational properties with evidence and confidence.

    Instead of matching pattern names, we detect semantic properties:
    - overlapping_subproblems: same computation appears multiple times
    - result_reuse: previously computed results are retrieved and used
    - divide_structure: problem is split into independent subproblems
    - early_termination: loop exits before exhausting all candidates
    - accumulation: state grows incrementally through iteration
    - state_evolution: variables transform through a sequence of operations
    """
    import ast as _ast
    import re as _re

    try:
        tree = _ast.parse(code)
    except:
        tree = None

    defined_funcs = set()
    if tree:
        for node in _ast.walk(tree):
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                defined_funcs.add(node.name)

    code_lines = [s.get('code', '').strip() for s in steps_data]
    all_code = ' '.join(code_lines)
    num_steps = len(steps_data)

    # ── Evidence gathering ────────────────────────────────────────────

    # 1. Self-recursion evidence
    recursion_evidence = []
    for func in defined_funcs:
        pat = _re.compile(r'\b' + _re.escape(func) + r'\s*\(')
        for i, line in enumerate(code_lines):
            if pat.search(line) and i > 0:
                recursion_evidence.append(f"line {i}: '{line.strip()}' calls {func}()")

    # 2. Base case evidence (semantic: terminates recursion for simple inputs)
    base_case_evidence = []
    base_case_patterns = [
        (r'if\s+len\(\w+\)\s*<=\s*1\s*:', 'length <= 1 check'),
        (r'if\s+len\(\w+\)\s*==\s*0\s*:', 'empty check'),
        (r'if\s+not\s+\w+\s*:', 'falsy check'),
        (r'if\s+\w+\s*==\s*[01]\s*:', 'equals 0/1 check'),
        (r'if\s+\w+\s*<=\s*1\s*:', 'value <= 1 check'),
        (r'if\s+lo\s*>=\s*hi\s*:', 'bounds converge check'),
    ]
    for line_i, line in enumerate(code_lines):
        for pat, desc in base_case_patterns:
            if _re.search(pat, line):
                base_case_evidence.append(f"line {line_i}: '{line}' — {desc}")

    # 3. Result caching evidence (semantic: writes to and reads from a lookup structure)
    cache_write_evidence = []
    cache_read_evidence = []
    cache_stores = {}  # var_name → evidence lines
    for line_i, line in enumerate(code_lines):
        # Write: var[key] = expr
        write_match = _re.search(r'(\w+)\[([^\]]+)\]\s*=\s*(.+)', line)
        if write_match and not _re.search(r'(self|cls)\.', line):
            var_name = write_match.group(1)
            if var_name not in ('self', 'cls'):
                cache_write_evidence.append(f"line {line_i}: '{line}' — stores result in {var_name}")
                cache_stores.setdefault(var_name, []).append(line_i)
    for line_i, line in enumerate(code_lines):
        # Read: var[key] in a non-assignment context (or return)
        for var_name in cache_stores:
            if var_name + '[' in line and not _re.search(rf'{var_name}\[[^\]]+\]\s*=', line):
                cache_read_evidence.append(f"line {line_i}: '{line}' — retrieves from {var_name}")

    # 4. Overlapping subproblems evidence (semantic: recursive calls with similar structure)
    overlap_evidence = []
    if len(recursion_evidence) >= 2:
        overlap_evidence.append(f"{len(recursion_evidence)} recursive calls suggest overlapping subproblems")
    # Check if multiple recursive calls appear on the same line (e.g., fib(n-1) + fib(n-2))
    multi_call_lines = [line for line in code_lines if sum(1 for f in defined_funcs if f + '(' in line) >= 2]
    for line in multi_call_lines:
        overlap_evidence.append(f"'{line}' — multiple recursive calls create overlapping subproblems")

    # 5. Partition evidence (semantic: splits input into subsets)
    partition_evidence = []
    for line_i, line in enumerate(code_lines):
        if _re.search(r'\[.*for\s+\w+\s+in\s+\w+.*if\s+.*[<>]', line):
            partition_evidence.append(f"line {line_i}: '{line}' — filters input into a subset")
        if _re.search(r'\[.*for\s+\w+\s+in\s+\w+.*if\s+.*[<>=]', line):
            partition_evidence.append(f"line {line_i}: '{line}' — partitions based on condition")

    # 6. Merge evidence (semantic: combines sub-results)
    merge_evidence = []
    for line_i, line in enumerate(code_lines):
        if _re.search(r'return\s+.*\+.*\[', line) or _re.search(r'return\s+\[.*\+', line):
            merge_evidence.append(f"line {line_i}: '{line}' — combines sub-results")
        elif _re.search(r'return\s+\w+\s*\+\s*\w+', line) and recursion_evidence:
            merge_evidence.append(f"line {line_i}: '{line}' — merges recursive results")

    # 7. Early termination evidence (semantic: returns before loop exhausts)
    early_term_evidence = []
    in_loop = False
    loop_depth = 0
    for line_i, line in enumerate(code_lines):
        if _re.match(r'(for|while)\s', line):
            in_loop = True
            loop_depth += 1
        elif _re.match(r'return\s', line) and in_loop:
            early_term_evidence.append(f"line {line_i}: '{line}' — exits loop early with result")
        elif line.startswith('break') and in_loop:
            early_term_evidence.append(f"line {line_i}: '{line}' — breaks out of loop")

    # 8. Accumulation evidence (semantic: state grows through iteration)
    accum_evidence = []
    for line_i, line in enumerate(code_lines):
        if _re.search(r'\w+\s*\+=\s*', line):
            var = _re.match(r'(\w+)\s*\+=', line).group(1)
            accum_evidence.append(f"line {line_i}: '{line}' — accumulates into {var}")
        if '.append(' in line:
            accum_evidence.append(f"line {line_i}: '{line}' — grows collection")
        if '.add(' in line:
            accum_evidence.append(f"line {line_i}: '{line}' — adds to set")

    # 9. State evolution evidence (semantic: variables transform)
    evolution_evidence = []
    for line_i, line in enumerate(code_lines):
        if _re.search(r'\w+\s*,\s*\w+\s*=\s*\w+\s*,\s*\w+', line):
            evolution_evidence.append(f"line {line_i}: '{line}' — simultaneous state update")
        elif _re.match(r'(\w+)\s*=\s*\1\s*[+\-*/]', line):
            evolution_evidence.append(f"line {line_i}: '{line}' — iterative refinement")

    # 10. Loop iteration evidence
    loop_evidence = []
    for line_i, line in enumerate(code_lines):
        if _re.match(r'for\s+\w+\s+in\s+range\(', line):
            loop_evidence.append(f"line {line_i}: '{line}' — iterates over range")
        elif _re.match(r'for\s+\w+\s+in\s+', line):
            loop_evidence.append(f"line {line_i}: '{line}' — iterates over collection")
        elif _re.match(r'while\s+', line):
            loop_evidence.append(f"line {line_i}: '{line}' — condition-driven iteration")

    # ── Property scoring ──────────────────────────────────────────────

    properties = {}

    # Overlapping subproblems + result reuse (→ memoization)
    if recursion_evidence and (cache_write_evidence or cache_read_evidence):
        overlap_conf = min(0.5 + 0.15 * len(overlap_evidence) + 0.1 * len(cache_write_evidence) + 0.1 * len(cache_read_evidence), 0.95)
        reuse_conf = min(0.5 + 0.15 * len(cache_read_evidence) + 0.1 * len(cache_write_evidence), 0.95)
        properties['overlapping_subproblems'] = {
            'confidence': round(overlap_conf, 2),
            'evidence': overlap_evidence + recursion_evidence,
        }
        properties['result_reuse'] = {
            'confidence': round(reuse_conf, 2),
            'evidence': cache_write_evidence + cache_read_evidence,
        }

    # Divide structure (→ divide and conquer)
    if recursion_evidence and (partition_evidence or merge_evidence):
        div_conf = min(0.4 + 0.2 * len(partition_evidence) + 0.2 * len(merge_evidence) + 0.1 * len(base_case_evidence), 0.95)
        properties['divide_structure'] = {
            'confidence': round(div_conf, 2),
            'evidence': partition_evidence + merge_evidence + base_case_evidence,
        }

    # Pure recursion (no caching, no merge)
    if recursion_evidence and 'overlapping_subproblems' not in properties and 'divide_structure' not in properties:
        rec_conf = min(0.5 + 0.15 * len(base_case_evidence) + 0.1 * len(recursion_evidence), 0.9)
        properties['recursive_decomposition'] = {
            'confidence': round(rec_conf, 2),
            'evidence': recursion_evidence + base_case_evidence,
        }

    # Early termination (→ search / short-circuit)
    if early_term_evidence:
        et_conf = min(0.5 + 0.15 * len(early_term_evidence), 0.9)
        properties['early_termination'] = {
            'confidence': round(et_conf, 2),
            'evidence': early_term_evidence,
        }

    # Accumulation
    if accum_evidence:
        acc_conf = min(0.4 + 0.15 * len(accum_evidence) + 0.1 * len(loop_evidence), 0.9)
        properties['accumulation'] = {
            'confidence': round(acc_conf, 2),
            'evidence': accum_evidence + loop_evidence,
        }

    # State evolution
    if evolution_evidence:
        ev_conf = min(0.4 + 0.15 * len(evolution_evidence), 0.85)
        properties['state_evolution'] = {
            'confidence': round(ev_conf, 2),
            'evidence': evolution_evidence,
        }

    # Iteration (base property, always present if loops exist)
    if loop_evidence and 'accumulation' not in properties and 'early_termination' not in properties:
        properties['iteration'] = {
            'confidence': min(0.4 + 0.1 * len(loop_evidence), 0.8),
            'evidence': loop_evidence,
        }

    # If nothing detected, mark as sequential
    if not properties:
        properties['sequential'] = {
            'confidence': 0.5,
            'evidence': ['No distinctive computational pattern detected'],
        }

    # Sort by confidence
    sorted_props = sorted(properties.items(), key=lambda x: x[1]['confidence'], reverse=True)

    # Derive the dominant pattern name for backward compatibility
    prop_to_pattern = {
        'overlapping_subproblems': 'memoization',
        'result_reuse': 'memoization',
        'divide_structure': 'divide_and_conquer',
        'recursive_decomposition': 'recursion',
        'early_termination': 'search',
        'accumulation': 'accumulation',
        'state_evolution': 'state_transformation',
        'iteration': 'iteration',
        'sequential': 'sequential',
    }
    # Use the highest-confidence property to determine pattern name
    dominant_prop = sorted_props[0][0]
    pattern_name = prop_to_pattern.get(dominant_prop, 'sequential')

    return {
        'properties': {k: v for k, v in sorted_props},
        'dominant': sorted_props[0][0],
        'pattern_name': pattern_name,
    }


def _generate_semantic_narrative(analysis: dict, steps_data: list, func_name: str = '') -> dict:
    """Generate property-based narrative + complexity reasoning.

    Returns: { 'narrative': str, 'complexity': str, 'properties': list[str] }
    """
    import re as _re

    props = analysis['properties']
    code_lines = [s.get('code', '').strip() for s in steps_data]
    num_steps = len(steps_data)

    # Identify key variables for domain inference
    key_vars = set()
    for s in steps_data:
        for v in s.get('changed', []):
            if v not in ('self', 'i', 'j', 'k'):
                key_vars.add(v)

    # ── Build narrative from properties ───────────────────────────────

    sentences = []

    # Opening: describe the core computational strategy
    has_overlap = 'overlapping_subproblems' in props
    has_reuse = 'result_reuse' in props
    has_divide = 'divide_structure' in props
    has_recursion = 'recursive_decomposition' in props
    has_early = 'early_termination' in props
    has_accum = 'accumulation' in props
    has_evolution = 'state_evolution' in props

    if has_overlap and has_reuse:
        # Memoization: describe the WHY, not the pattern name
        sentences.append(
            "This algorithm avoids redundant computation by identifying that the same subproblems appear multiple times, "
            "and caching their results so each unique subproblem is solved only once."
        )
        if any(p in props for p, _ in props.items() if p == 'overlapping_subproblems'):
            evidence = props.get('overlapping_subproblems', {}).get('evidence', [])
            multi_calls = [e for e in evidence if 'multiple recursive calls' in e]
            if multi_calls:
                sentences.append("The branching recursive structure creates overlapping subproblems — the same inputs are reached through different call paths.")

    elif has_divide:
        sentences.append(
            "This algorithm breaks the problem into smaller independent subproblems, solves each one separately, "
            "then combines the partial results into the final answer."
        )
        merge_ev = props.get('divide_structure', {}).get('evidence', [])
        merge_lines = [e for e in merge_ev if 'combines' in e or 'merges' in e]
        if merge_lines:
            sentences.append("The merge step is where the divide-and-conquer structure becomes visible — partial solutions are combined to form larger solutions.")

    elif has_recursion:
        sentences.append(
            "This algorithm solves the problem by breaking it into smaller instances of the same problem, "
            "handling the simplest cases directly and building up from there."
        )

    elif has_early and has_accum:
        sentences.append(
            "This algorithm iterates through candidates, accumulating state, and terminates early as soon as the answer is found — "
            "avoiding unnecessary work on the remaining elements."
        )

    elif has_early:
        sentences.append(
            "This algorithm searches for a specific condition and stops as soon as it's found, "
            "rather than exhaustively examining every candidate."
        )

    elif has_accum:
        builds_list = any('.append(' in e for e in props.get('accumulation', {}).get('evidence', []))
        if builds_list:
            sentences.append(
                "This algorithm processes each element in the input, selectively building a result collection "
                "by adding elements that satisfy the criteria."
            )
        else:
            sentences.append(
                "This algorithm computes its result by iterating through the input and maintaining a running state — "
                "each element contributes to the final answer."
            )

    elif has_evolution:
        sentences.append(
            "This algorithm transforms its state through a sequence of operations, "
            "where each step builds on the previous state to converge toward the result."
        )

    else:
        sentences.append(
            f"This algorithm executes {num_steps} steps to produce its result."
        )

    # Middle: add property-specific insights
    if has_overlap and has_reuse:
        sentences.append(
            "The key insight is that without caching, the same subproblems would be solved repeatedly — "
            "caching eliminates this exponential blowup by ensuring each result is computed at most once."
        )

    if any('partition' in str(v) or 'filters' in str(v) for v in props.values()):
        sentences.append(
            "The partitioning step divides the input space, and the algorithm recurses independently on each partition."
        )

    # ── Complexity reasoning ──────────────────────────────────────────

    complexity_parts = []

    if has_overlap and has_reuse:
        complexity_parts.append(
            "Without caching, the branching recursion would revisit the same subproblems exponentially many times. "
            "By storing and reusing results, each unique subproblem is solved exactly once, "
            "reducing the effective work from exponential to linear in the number of unique inputs."
        )
    elif has_divide:
        complexity_parts.append(
            "The divide-and-conquer structure means the problem size is halved at each level of recursion. "
            "The total work depends on the cost of splitting, solving subproblems, and merging."
        )
    elif has_early:
        complexity_parts.append(
            "Early termination means the algorithm doesn't always examine every element — "
            "in the best case it finds the answer immediately; in the worst case it scans everything."
        )
    elif has_accum:
        complexity_parts.append(
            "The algorithm visits each element exactly once, making it linear in the size of the input."
        )

    return {
        'narrative': ' '.join(sentences),
        'complexity': ' '.join(complexity_parts) if complexity_parts else '',
        'properties': list(props.keys()),
    }


@app.post("/api/pattern_narrative")
async def pattern_narrative(req: ExplainStepsRequest):
    """Detect semantic algorithm properties and generate understanding-based narrative."""
    try:
        cached = _cache_get(req.session_id) if req.session_id else None
        if cached:
            steps_data = cached["steps_data"]
            code = cached["code"]
            func_name = cached["func_name"]
        else:
            if not req.code:
                return {"success": False, "error": "No code or session_id provided."}
            func_name = _extract_func_name(req.code, req.func_name)
            if not func_name:
                return {"success": False, "error": "No function found in code."}
            module = _import_code_as_module(req.code)
            func = getattr(module, func_name)
            tmp_path = _write_temp_code(req.code, req.language)
            result, timeline = record_function(func, target_files={os.path.abspath(tmp_path)})
            os.unlink(tmp_path)
            steps_data = []
            for step in timeline.steps:
                var_states = {}
                for name, snap in step.variables.items():
                    var_states[name] = {"value": snap.value_repr, "type": snap.value_type, "changed": name in step.changed_vars}
                steps_data.append({
                    "index": step.step_index, "line": step.line_number,
                    "code": step.code_line, "vars": var_states,
                    "changed": step.changed_vars, "new_vars": list(step.new_vars),
                })
            code = req.code

        control_edges = _compute_control_edges(steps_data)

        # Semantic analysis
        analysis = _detect_semantic_properties(code, steps_data, control_edges)
        result = _generate_semantic_narrative(analysis, steps_data, func_name)

        # Build evidence summary for frontend
        evidence_summary = {}
        for prop_name, prop_data in analysis['properties'].items():
            evidence_summary[prop_name] = {
                'confidence': prop_data['confidence'],
                'evidence_count': len(prop_data['evidence']),
                'evidence_sample': prop_data['evidence'][:3],  # top 3 for display
            }

        return {
            "success": True,
            "pattern": analysis['pattern_name'],
            "dominant_property": analysis['dominant'],
            "properties": evidence_summary,
            "narrative": result['narrative'],
            "complexity": result['complexity'],
            "property_names": result['properties'],
        }
    except Exception as e:
        return {"success": False, "error": str(e), "error_type": type(e).__name__}


# ── Subproblem Graph: Call DAG + Complexity Derivation ────────────────

def _trace_recursive_calls(func, args=(), kwargs=None):
    """Instrument a recursive function by rewriting its bytecode to trace calls.

    Returns: (result, trace_tree) where trace_tree is:
    { 'id': str, 'args': str, 'children': [...], 'result': any }
    """
    import dis
    import types
    if kwargs is None:
        kwargs = {}

    func_name = func.__name__
    call_stack = []
    root = [None]

    # Build a traced version by wrapping the function
    # We intercept calls by modifying the function's globals
    # and using a sentinel to detect recursion

    call_log = []  # list of (depth, args_tuple, result, children_indices)
    depth_counter = [0]
    child_map = {}  # depth → list of child depths

    original_code = func.__code__

    # Strategy: run the function with a patched global that wraps each recursive call
    # This works because Python resolves names at call time via globals()

    def make_traced(func, call_tree_ref):
        """Create a traced wrapper that builds a call tree."""
        import types as _types

        original = func

        def traced(*a, **kw):
            call_id = f"{func_name}({', '.join(repr(x) for x in a)})"
            node = {'id': call_id, 'args': [repr(x) for x in a], 'children': [], 'result': None}

            if call_tree_ref[0] is None:
                call_tree_ref[0] = node
            else:
                # Find current parent: the deepest node in the stack that's still building
                # We use a simple approach: each call appends to the current leaf
                pass

            # We need to track parent-child relationships
            # Use a stack-based approach
            node['_parent'] = None
            if call_stack:
                node['_parent'] = call_stack[-1]
                call_stack[-1]['children'].append(node)
            call_stack.append(node)

            # Replace the function's own reference in its globals
            old_ref = original.__globals__.get(func_name)
            original.__globals__[func_name] = traced

            try:
                result = original(*a, **kw)
                node['result'] = result
                return result
            finally:
                call_stack.pop()
                original.__globals__[func_name] = old_ref

        return traced

    traced_func = make_traced(func, root)
    try:
        result = traced_func(*args, **kwargs)
    except RecursionError:
        result = None
        if root[0] is None:
            root[0] = {'id': f'{func_name}(...)', 'args': [], 'children': [], 'result': 'RecursionError'}

    return result, root[0]


def _build_subproblem_dag(root):
    """Convert call tree to DAG by merging identical subproblems.

    Returns: (dag_nodes, dag_edges, unique_count, total_count)
    - dag_nodes: list of { 'id': str, 'args': str, 'call_count': int, 'result': any }
    - dag_edges: list of { 'from': str, 'to': str }
    """
    if root is None:
        return [], [], 0, 0

    # Count occurrences of each unique call
    call_counts = {}  # id → count
    edges = []  # (parent_id, child_id)
    all_nodes = {}  # id → { id, args, result, children_ids }
    total_count = [0]

    def walk(node, parent_id=None):
        total_count[0] += 1
        call_id = node['id']
        call_counts[call_id] = call_counts.get(call_id, 0) + 1

        if call_id not in all_nodes:
            all_nodes[call_id] = {
                'id': call_id,
                'args': node.get('args', []),
                'result': node.get('result'),
                'children': [],
            }

        if parent_id and parent_id != call_id:
            edge_key = (parent_id, call_id)
            if edge_key not in edges:
                edges.append(edge_key)
                all_nodes[parent_id]['children'].append(call_id)

        for child in node.get('children', []):
            walk(child, call_id)

    walk(root)

    dag_nodes = []
    for nid, ndata in all_nodes.items():
        dag_nodes.append({
            'id': nid,
            'args': ndata['args'],
            'result': ndata['result'],
            'call_count': call_counts[nid],
        })

    dag_edges = [{'from': e[0], 'to': e[1]} for e in edges]

    return dag_nodes, dag_edges, len(all_nodes), total_count[0]


def _derive_complexity_from_dag(dag_nodes, dag_edges, total_count, unique_count):
    """Symbolic recurrence engine: extract parameter deltas from DAG edges,
    build the actual recurrence relation, and derive exact complexity.

    Returns: {
        'recurrence': str,
        'recurrence_terms': list[str],
        'branching_factor': float,
        'depth': int,
        'without_cache': str,
        'with_cache': str,
        'speedup': str,
        'explanation': str,
    }
    """
    import re as _re

    if not dag_nodes:
        return {'recurrence': 'T(n) = O(1)', 'without_cache': 'O(1)', 'with_cache': 'O(1)', 'speedup': 'none',
                'explanation': 'Constant work.', 'recurrence_terms': []}

    # Find root
    targets = set(e['to'] for e in dag_edges)
    roots = [n for n in dag_nodes if n['id'] not in targets]
    root = roots[0] if roots else dag_nodes[0]

    children_map = {}
    for e in dag_edges:
        children_map.setdefault(e['from'], []).append(e['to'])

    # Compute depth
    max_depth = 0
    node_depths = {root['id']: 0}
    queue = [root['id']]
    while queue:
        current = queue.pop(0)
        d = node_depths[current]
        max_depth = max(max_depth, d)
        for child in children_map.get(current, []):
            if child not in node_depths:
                node_depths[child] = d + 1
                queue.append(child)

    shared_nodes = [n for n in dag_nodes if n['call_count'] > 1]
    has_reuse = len(shared_nodes) > 0

    # ── Step 1: Parse arguments from node IDs ─────────────────────────
    # "fib(5)" → [5], "binary_search(arr, 15, 0, 20)" → [15, 0, 20]
    node_args = {}  # node_id → list of int args
    func_name = root['id'].split('(')[0] if '(' in root['id'] else ''

    for node in dag_nodes:
        nid = node['id']
        match = _re.search(r'\(([^)]*)\)\s*$', nid)
        if match:
            args_str = match.group(1)
            args = []
            for part in args_str.split(','):
                part = part.strip()
                try:
                    args.append(int(part))
                except ValueError:
                    try:
                        args.append(float(part))
                    except ValueError:
                        pass  # non-numeric arg (e.g. list), skip
            if args:
                node_args[nid] = args

    # ── Step 2: Extract parameter deltas from DAG edges ───────────────
    # For each edge parent→child, compute delta = child_args - parent_args
    # Also detect range patterns (binary search) and list splitting (merge sort)

    parent_children_deltas = {}  # parent_id → { arg_pos → [deltas] }
    arg_deltas = {}  # arg_position → list of all deltas
    proportional_deltas = {}  # arg_position → list of (child/parent) ratios

    # Range pattern detection: for each parent, look at pairs of args that form ranges
    # e.g., (lo, hi) → detect if children get (lo, mid) and (mid+1, hi)
    range_split_evidence = []  # list of (parent_range, child_ranges)

    for edge in dag_edges:
        parent_id, child_id = edge['from'], edge['to']
        p_args = node_args.get(parent_id)
        c_args = node_args.get(child_id)
        if not p_args or not c_args:
            continue

        num_args = min(len(p_args), len(c_args))
        for i in range(num_args):
            pa, ca = p_args[i], c_args[i]
            if isinstance(pa, (int, float)) and isinstance(ca, (int, float)):
                delta = ca - pa
                arg_deltas.setdefault(i, []).append(delta)
                parent_children_deltas.setdefault(parent_id, {}).setdefault(i, []).append(delta)
                if pa != 0:
                    proportional_deltas.setdefault(i, []).append(ca / pa)

        # Detect range splitting: check if (arg[i], arg[j]) pair is being split
        for i in range(num_args):
            for j in range(i + 1, num_args):
                pa_i, pa_j = p_args[i], p_args[j]
                ca_i, ca_j = c_args[i], c_args[j]
                if isinstance(pa_i, (int, float)) and isinstance(pa_j, (int, float)):
                    parent_range = pa_j - pa_i
                    child_range = ca_j - ca_i
                    if parent_range > 0 and 0 < child_range < parent_range:
                        ratio = child_range / parent_range
                        range_split_evidence.append({
                            'parent_id': parent_id, 'child_id': child_id,
                            'parent_range': parent_range, 'child_range': child_range,
                            'ratio': ratio, 'arg_pair': (i, j),
                        })

    # ── Step 3: Build symbolic recurrence from deltas ─────────────────
    # Strategy: for each arg position, look at what deltas each parent produces.
    # If most parents produce the SAME set of deltas, those are the recurrence terms.
    # Example: fib(8)→{fib(7): delta=-1, fib(6): delta=-2} → terms T(n-1) + T(n-2)

    from collections import Counter

    recurrence_terms = []
    delta_summary = {}

    # First check for range splitting patterns (binary search, etc.)
    if range_split_evidence:
        ratios = [e['ratio'] for e in range_split_evidence]
        ratio_counts = Counter(round(r, 2) for r in ratios)
        most_common_ratio, ratio_count = ratio_counts.most_common(1)[0]
        ratio_freq = ratio_count / len(ratios)

        if ratio_freq >= 0.5 and 0.3 < most_common_ratio < 0.7:
            # Halving pattern: each call reduces the range by ~50%
            recurrence_terms.append("T(n/2)")

    # Then check for simple delta patterns (fibonacci, countdown, etc.)
    # Skip if we already found a range split (avoid noise from non-size args like lo/hi)
    has_range_split = len(recurrence_terms) > 0

    if not has_range_split:
      for pos in arg_deltas:
        if not arg_deltas[pos]:
          continue

        # Collect the SET of unique deltas each parent produces for this arg position
        parent_delta_sets = []
        for pid, pos_deltas in parent_children_deltas.items():
          if pos in pos_deltas:
            parent_delta_sets.append(tuple(sorted(set(pos_deltas[pos]))))

        if not parent_delta_sets:
          continue

        # Find the most common delta SET (what most parents produce)
        set_counts = Counter(parent_delta_sets)
        most_common_set, set_count = set_counts.most_common(1)[0]
        set_freq = set_count / len(parent_delta_sets)

        # If the same delta set appears in most parents, use it as recurrence terms
        if set_freq >= 0.5:
          for delta in most_common_set:
            if delta == -1:
              term = "T(n-1)"
            elif delta == -2:
              term = "T(n-2)"
            elif delta < 0:
              term = f"T(n{delta:+g})".replace("+", "")
            elif delta > 0:
              term = f"T(n+{delta:g})"
            else:
              term = "T(n)"
            if term not in recurrence_terms:
              recurrence_terms.append(term)
        else:
          # Fallback: use individual delta frequencies
          delta_counts = Counter(arg_deltas[pos])
          for delta, count in delta_counts.most_common(2):
            freq = count / len(arg_deltas[pos])
            if freq >= 0.4:
              if delta == -1:
                term = "T(n-1)"
              elif delta == -2:
                term = "T(n-2)"
              elif delta < 0:
                term = f"T(n{delta:+g})".replace("+", "")
              elif delta > 0:
                term = f"T(n+{delta:g})"
              else:
                term = "T(n)"
              if term not in recurrence_terms:
                recurrence_terms.append(term)

    unique_terms = recurrence_terms

    # ── Step 4: Classify complexity ───────────────────────────────────
    has_t_n_minus_1 = any('n-1' in t for t in unique_terms)
    has_t_n_minus_2 = any('n-2' in t for t in unique_terms)
    has_t_n_div_2 = any('n/2' in t for t in unique_terms)
    has_t_rn = any('·n)' in t for t in unique_terms)

    # Average branching factor for the recurrence RHS
    non_leaf = [n for n in dag_nodes if children_map.get(n['id'])]
    avg_branch = sum(len(children_map.get(n['id'], [])) for n in non_leaf) / max(len(non_leaf), 1)

    # Build recurrence string
    if unique_terms:
        rhs = ' + '.join(unique_terms)
        recurrence = f"T(n) = {rhs}"
    elif avg_branch > 0:
        recurrence = f"T(n) = O(1) per step ({avg_branch:.1f} avg children)"
    else:
        recurrence = "T(n) = O(1)"

    # Classify without-cache complexity
    if has_t_n_minus_1 and has_t_n_minus_2:
        # Fibonacci-like: T(n) = T(n-1) + T(n-2) → O(φ^n) ≈ O(1.618^n)
        complexity_class = f"O(phi^n) ~ O(1.618^n)"
        explanation = (
            f"T(n) = T(n-1) + T(n-2) is the Fibonacci recurrence. "
            f"Its characteristic equation x^2 = x + 1 has root phi ~ 1.618, "
            f"so the solution grows as O(phi^n) -- exponential."
        )
    elif unique_terms and has_t_n_div_2:
        # Binary search: T(n) = T(n/2) → O(log n)
        complexity_class = "O(log n)"
        explanation = (
            f"Each recursive call halves the problem size. "
            f"After k calls the size is n/2^k. Setting n/2^k = 1 gives k = log₂(n), "
            f"so T(n) = O(log n)."
        )
    elif unique_terms and has_t_rn:
        # Proportional reduction
        ratio = list(delta_summary.values())[0].get('ratio', 0.5)
        complexity_class = f"O(log_{1/ratio:.1f}(n)) = O(log n)"
        explanation = f"Each call reduces the problem by factor {ratio:.2f}, giving logarithmic depth."
    elif has_t_n_minus_1 and len(unique_terms) == 1:
        # Linear recursion: T(n) = T(n-1) + O(1) → O(n)
        complexity_class = "O(n)"
        explanation = f"Each call reduces n by 1, making exactly n recursive calls — linear."
    elif len(unique_terms) >= 2 and has_t_n_minus_1:
        # Multiple branches from T(n-1)-like terms
        complexity_class = f"O({len(unique_terms)}^n)"
        explanation = (
            f"Each call spawns {len(unique_terms)} subcalls, each reducing n by a constant. "
            f"The call tree has branching factor {len(unique_terms)}, giving exponential growth."
        )
    elif avg_branch >= 1.5:
        complexity_class = f"O({avg_branch:.0f}^n)"
        explanation = (
            f"Average branching factor is {avg_branch:.1f}. "
            f"Without memoization, the call tree grows exponentially."
        )
    else:
        complexity_class = f"O(n)"
        explanation = "Linear recursion with constant work per call."

    # With-cache complexity
    if has_reuse:
        with_cache = f"O(n) — only {unique_count} unique subproblems solved once"
        speedup = f"{total_count / max(unique_count, 1):.1f}x fewer computations with caching"
    elif total_count > unique_count:
        with_cache = f"O(n) — {unique_count} unique subproblems"
        speedup = "some reuse detected"
    else:
        with_cache = f"O(n) — already optimal"
        speedup = "no overlapping subproblems"

    return {
        'recurrence': recurrence,
        'recurrence_terms': unique_terms,
        'branching_factor': round(avg_branch, 1),
        'depth': max_depth,
        'without_cache': complexity_class + f" — {total_count} calls for {unique_count} unique subproblems",
        'with_cache': with_cache,
        'speedup': speedup,
        'total_calls': total_count,
        'unique_calls': unique_count,
        'shared_subproblems': [{'id': n['id'], 'called': n['call_count']} for n in shared_nodes[:10]],
        'explanation': explanation,
    }


def _dag_to_tree_layout(dag_nodes, dag_edges, max_display=50):
    """Layout the call tree for frontend visualization.

    Returns: { 'nodes': [...], 'edges': [...], 'width': int, 'height': int }
    """
    if not dag_nodes:
        return {'nodes': [], 'edges': [], 'width': 0, 'height': 0}

    # Find root
    targets = set(e['to'] for e in dag_edges)
    roots = [n for n in dag_nodes if n['id'] not in targets]
    root_id = roots[0]['id'] if roots else dag_nodes[0]['id']

    # BFS layout by depth
    children_map = {}
    for e in dag_edges:
        children_map.setdefault(e['from'], []).append(e['to'])

    # Assign positions
    positions = {}
    levels = {}  # depth → [node_ids]
    queue = [(root_id, 0)]
    visited = set()
    while queue:
        node_id, depth = queue.pop(0)
        if node_id in visited:
            continue
        visited.add(node_id)
        positions[node_id] = depth
        levels.setdefault(depth, []).append(node_id)
        for child in children_map.get(node_id, []):
            if child not in visited:
                queue.append((child, depth + 1))

    # Build layout nodes
    node_w, node_h, gap_x, gap_y = 120, 36, 20, 12
    layout_nodes = []
    node_positions = {}  # id → { x, y }

    for depth, ids in sorted(levels.items()):
        x = depth * (node_w + gap_x)
        for i, nid in enumerate(ids):
            y = i * (node_h + gap_y)
            node_positions[nid] = {'x': x, 'y': y}
            ndata = next((n for n in dag_nodes if n['id'] == nid), {})
            short_id = nid if len(nid) <= 20 else nid[:18] + '…'
            layout_nodes.append({
                'id': nid,
                'x': x, 'y': y,
                'label': short_id,
                'result': ndata.get('result'),
                'call_count': ndata.get('call_count', 1),
                'is_reused': ndata.get('call_count', 1) > 1,
            })

    # Layout edges
    layout_edges = []
    for e in dag_edges:
        if e['from'] in node_positions and e['to'] in node_positions:
            layout_edges.append({
                'from': e['from'],
                'to': e['to'],
                'from_pos': node_positions[e['from']],
                'to_pos': node_positions[e['to']],
            })

    # Compute dimensions
    max_x = max((p['x'] for p in node_positions.values()), default=0) + node_w + 20
    max_y = max((p['y'] for p in node_positions.values()), default=0) + node_h + 20

    # Truncate if too large
    if len(layout_nodes) > max_display:
        layout_nodes = layout_nodes[:max_display]
        layout_edges = [e for e in layout_edges
                       if any(n['id'] == e['from'] for n in layout_nodes)
                       and any(n['id'] == e['to'] for n in layout_nodes)]

    return {
        'nodes': layout_nodes,
        'edges': layout_edges,
        'width': max_x,
        'height': max_y,
        'nodeW': node_w,
        'nodeH': node_h,
    }


@app.post("/api/subproblem_graph")
async def subproblem_graph(req: ExplainStepsRequest):
    """Trace recursive calls, build subproblem DAG, derive complexity."""
    try:
        if not req.code:
            return {"success": False, "error": "No code provided."}

        func_name = _extract_func_name(req.code, req.func_name)
        if not func_name:
            return {"success": False, "error": "No function found in code."}

        module = _import_code_as_module(req.code)
        func = getattr(module, func_name)

        # Determine sensible default args from function signature
        import inspect
        sig = inspect.signature(func)
        default_args = []
        for param_name, param in sig.parameters.items():
            if param.default is not inspect.Parameter.empty:
                continue  # has default, skip
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            # Try common test values
            default_args.append(8)  # default test input

        if not default_args:
            default_args = [8]

        # Trace execution
        result, tree = _trace_recursive_calls(func, tuple(default_args))

        if tree is None:
            return {
                "success": True,
                "is_recursive": False,
                "narrative": "This function does not appear to use recursion.",
            }

        # Build DAG
        dag_nodes, dag_edges, unique_count, total_count = _build_subproblem_dag(tree)

        # Derive complexity
        complexity = _derive_complexity_from_dag(dag_nodes, dag_edges, total_count, unique_count)

        # Layout for visualization
        layout = _dag_to_tree_layout(dag_nodes, dag_edges)

        # Generate performance narrative
        perf_narrative = _generate_performance_narrative(complexity, dag_nodes, func_name)

        return {
            "success": True,
            "is_recursive": True,
            "result": result,
            "dag": {
                'nodes': dag_nodes[:30],  # limit for payload
                'edges': dag_edges[:50],
                'unique_count': unique_count,
                'total_count': total_count,
            },
            'layout': layout,
            'complexity': complexity,
            'narrative': perf_narrative,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "error_type": type(e).__name__}


def _generate_performance_narrative(complexity: dict, dag_nodes: list, func_name: str = '') -> str:
    """Generate a narrative explaining WHY the algorithm is fast or slow."""
    parts = []

    total = complexity.get('total_calls', 0)
    unique = complexity.get('unique_calls', 0)
    shared = complexity.get('shared_subproblems', [])
    branching = complexity.get('branching_factor', 0)
    speedup = complexity.get('speedup', '')

    if shared:
        # Has overlapping subproblems
        worst = max((s['called'] for s in shared), default=1)
        worst_id = max(shared, key=lambda s: s['called'])['id']
        parts.append(
            f"Without caching, this algorithm makes {total} recursive calls to solve {unique} unique subproblems. "
            f"The subproblem {worst_id} alone is recomputed {worst} times."
        )
        parts.append(
            f"With caching, each subproblem is solved exactly once, reducing the work from {total} calls to {unique} — "
            f"a {speedup}."
        )
        parts.append(
            f"The root cause of the inefficiency is the branching factor of {branching}: "
            f"each call spawns {int(branching)} subcalls, and without reuse the call tree grows exponentially."
        )
    elif total > unique * 2:
        parts.append(
            f"This algorithm makes {total} calls but only {unique} are unique. "
            f"There is some redundancy, but not enough to form a clear overlapping pattern."
        )
    else:
        parts.append(
            f"This algorithm makes {total} calls with {unique} unique subproblems. "
            f"Each subproblem is solved at most once — the computation is already efficient."
        )

    return ' '.join(parts)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
