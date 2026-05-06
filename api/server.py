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

        # Use the function's compiled file path for tracing (the temp file used during import)
        func_file = os.path.abspath(func.__code__.co_filename)
        tmp_path = _write_temp_code(req.code, req.language)

        # Record execution — trace the file the function was actually compiled from
        result, timeline = record_function(func, target_files={func_file})

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
        func_file = os.path.abspath(func.__code__.co_filename)
        tmp_path = _write_temp_code(req.code, req.language)

        # Record execution
        result, timeline = record_function(func, target_files={func_file})

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
            func_file = os.path.abspath(func.__code__.co_filename)
            tmp_path = _write_temp_code(req.code, req.language)
            result, timeline = record_function(func, target_files={func_file})
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
            func_file = os.path.abspath(func.__code__.co_filename)
            tmp_path = _write_temp_code(req.code, req.language)
            result, timeline = record_function(func, target_files={func_file})
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
            func_file = os.path.abspath(func.__code__.co_filename)
            tmp_path = _write_temp_code(req.code, req.language)
            result, timeline = record_function(func, target_files={func_file})
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


def _infer_problem_size(args):
    """Infer problem size from function arguments (State Abstraction Layer).

    Maps raw args to a single numeric state representing the "problem size"
    that the recurrence operates on.

    Rules:
    - Single numeric arg -> that value (fib(n) -> n)
    - Two numeric args -> absolute difference (binary_search lo,hi -> hi-lo)
    - List arg -> length (merge_sort(arr) -> len(arr))
    - 3+ numeric args -> largest range pair
    """
    numeric_args = [a for a in args if isinstance(a, (int, float))]

    # Check for list arguments (actual lists or string representations)
    # Only use list length when there are NO numeric args (e.g., merge_sort(arr))
    # When numeric args exist, they represent the recursion parameters (e.g., bs(arr, lo, hi))
    for a in args:
        if isinstance(a, (list, tuple)):
            if len(numeric_args) == 0:
                return len(a)
        if isinstance(a, str) and a.startswith('[') and a.endswith(']'):
            if len(numeric_args) == 0:
                inner = a[1:-1].strip()
                if not inner:
                    return 0
                return inner.count(',') + 1

    if len(numeric_args) == 0:
        return None

    if len(numeric_args) == 1:
        return numeric_args[0]

    if len(numeric_args) == 2:
        a, b = numeric_args
        if a < b:
            return b - a
        return max(a, b)

    if len(numeric_args) >= 3:
        # For functions like bs(arr, target, lo, hi) or partition(arr, lo, hi),
        # the last two args are typically the bounds that define problem size.
        lo, hi = numeric_args[-2], numeric_args[-1]
        last_pair_range = abs(hi - lo)
        if last_pair_range > 0:
            return last_pair_range
        return max(numeric_args)

    return None


def _derive_complexity_from_dag(dag_nodes, dag_edges, total_count, unique_count):
    """State-based symbolic recurrence engine.

    Instead of analyzing raw arg deltas, this:
    1. Infers "problem size" (state) from each node's arguments
    2. Computes state transitions (delta and ratio) along DAG edges
    3. Constructs the recurrence from state transitions (not statistics)
    4. Derives complexity from the recurrence structure

    Returns dict with recurrence, terms, state_size, complexity, explanation.
    """
    import re as _re
    import statistics

    if not dag_nodes:
        return {"recurrence": "T(n) = O(1)", "without_cache": "O(1)", "with_cache": "O(1)",
                "speedup": "none", "explanation": "Constant work.", "recurrence_terms": [],
                "state_size": "none"}

    targets = set(e["to"] for e in dag_edges)
    roots = [n for n in dag_nodes if n["id"] not in targets]
    root = roots[0] if roots else dag_nodes[0]

    children_map = {}
    for e in dag_edges:
        children_map.setdefault(e["from"], []).append(e["to"])

    max_depth = 0
    node_depths = {root["id"]: 0}
    queue = [root["id"]]
    while queue:
        current = queue.pop(0)
        d = node_depths[current]
        max_depth = max(max_depth, d)
        for child in children_map.get(current, []):
            if child not in node_depths:
                node_depths[child] = d + 1
                queue.append(child)

    shared_nodes = [n for n in dag_nodes if n["call_count"] > 1]
    has_reuse = len(shared_nodes) > 0

    # Step 1: Parse arguments from node IDs
    node_args = {}
    func_name = root["id"].split("(")[0] if "(" in root["id"] else ""

    for node in dag_nodes:
        nid = node["id"]
        match = _re.search(r"\((.+)\)\s*$", nid)
        if match:
            args_str = match.group(1)
            args = []
            # Bracket-aware splitting: don't split commas inside [...] or (...)
            tokens = []
            depth = 0
            current = ""
            for ch in args_str:
                if ch in '([':
                    depth += 1
                    current += ch
                elif ch in ')]':
                    depth -= 1
                    current += ch
                elif ch == ',' and depth == 0:
                    tokens.append(current)
                    current = ""
                else:
                    current += ch
            if current:
                tokens.append(current)
            for part in tokens:
                part = part.strip()
                if not part:
                    continue
                if part.startswith('[') and part.endswith(']'):
                    args.append(part)
                    continue
                try:
                    args.append(int(part))
                except ValueError:
                    try:
                        args.append(float(part))
                    except ValueError:
                        args.append(part)
            if args:
                node_args[nid] = args

    # Step 2: Infer problem size (state) for each node
    node_state = {}
    state_inference = "none"

    for nid, args in node_args.items():
        size = _infer_problem_size(args)
        if size is not None:
            node_state[nid] = size

    if node_state:
        root_state = node_state.get(root["id"])
        root_args = node_args.get(root["id"], [])
        numeric_args = [a for a in root_args if isinstance(a, (int, float))]
        if len(numeric_args) == 1:
            state_inference = f"single arg ({numeric_args[0]})"
        elif len(numeric_args) == 2 and root_state == abs(numeric_args[1] - numeric_args[0]):
            state_inference = f"range: |{numeric_args[1]} - {numeric_args[0]}| = {root_state}"
        elif len(numeric_args) >= 3:
            state_inference = f"last pair range: |{numeric_args[-1]} - {numeric_args[-2]}| = {root_state}"
        else:
            state_inference = f"inferred = {root_state}"

    # Step 3: Compute state transitions along DAG edges
    state_deltas = []

    for edge in dag_edges:
        parent_id, child_id = edge["from"], edge["to"]
        ps = node_state.get(parent_id)
        cs = node_state.get(child_id)
        if ps is not None and cs is not None:
            delta = cs - ps
            ratio = cs / ps if ps != 0 else None
            state_deltas.append((ps, cs, delta, ratio))

    # Step 4: Construct recurrence from state transitions
    from collections import Counter

    parent_transitions = {}
    for ps, cs, delta, ratio in state_deltas:
        parent_transitions.setdefault(ps, set()).add((delta, round(ratio, 4) if ratio else None))

    recurrence_terms = []
    state_size_desc = state_inference
    recursion_pattern = "unknown"
    shrink_class = "none"
    execution_type = "unknown"

    # Step 3.5: Detect AND vs OR recursion via call tree structure
    # AND = both children execute (merge sort), OR = choose one (binary search)
    # Heuristic: in AND recursion, most internal nodes have >1 child (branching)
    # In OR recursion, many nodes have only 1 child (linear path with dead branches)
    root_node = roots[0] if roots else dag_nodes[0]
    root_children = children_map.get(root_node["id"], [])
    non_leaf_nodes = [n for n in dag_nodes if children_map.get(n["id"])]
    multi_child_nodes = [n for n in non_leaf_nodes if len(children_map.get(n["id"], [])) > 1]
    if non_leaf_nodes:
        multi_child_ratio = len(multi_child_nodes) / len(non_leaf_nodes)
        avg_children_count = sum(len(children_map.get(n["id"], [])) for n in non_leaf_nodes) / len(non_leaf_nodes)
        # AND: most nodes branch (merge sort: every level splits)
        # OR: few nodes branch (binary search: only root + some intermediates)
        if multi_child_ratio >= 0.5 and avg_children_count >= 1.8:
            execution_type = "AND"
        else:
            execution_type = "OR"

    if parent_transitions:
        # Collect all child deltas and ratios across all transitions
        all_deltas = []
        all_ratios = []
        for ps, transitions in parent_transitions.items():
            for d, r in transitions:
                all_deltas.append(d)
                if r is not None and 0 < r < 1:
                    all_ratios.append(r)

        unique_deltas = set(all_deltas)
        has_delta_minus_1 = -1 in unique_deltas
        has_delta_minus_2 = -2 in unique_deltas

        # 1. Identify shrink class via median ratio (transfer function family)
        if all_ratios:
            median_r = statistics.median(all_ratios)

            if 0.4 <= median_r <= 0.6:
                shrink_class = "n/2"
            elif 0.2 <= median_r < 0.4:
                shrink_class = "n/3"

        # 2. Build recurrence terms from shrink class + execution type
        if shrink_class == "n/2":
            if execution_type == "AND":
                # Merge sort pattern: both branches execute
                child_count = len(root_children) if root_children else 2
                recurrence_terms.append(f"{child_count}T(n/2)")
                recursion_pattern = "divide_and_conquer"
            else:
                recurrence_terms.append("T(n/2)")
                recursion_pattern = "binary_search"
        elif shrink_class == "n/3":
            if execution_type == "AND":
                child_count = len(root_children) if root_children else 3
                recurrence_terms.append(f"{child_count}T(n/3)")
                recursion_pattern = "divide_and_conquer"
            else:
                recurrence_terms.append("T(n/3)")
                recursion_pattern = "binary_search"

        # 3. Check delta-based patterns (Fibonacci, countdown, constant decrement)
        if not recurrence_terms:
            if has_delta_minus_1 and has_delta_minus_2:
                recurrence_terms.append("T(n-1)")
                recurrence_terms.append("T(n-2)")
                recursion_pattern = "tree_recursion"
            elif has_delta_minus_1 and len(unique_deltas) == 1:
                recurrence_terms.append("T(n-1)")
                recursion_pattern = "linear_recursion"
            elif any(d < -1 for d in unique_deltas):
                for d in sorted(unique_deltas):
                    if d < 0:
                        recurrence_terms.append(f"T(n{d:+g})".replace("+", ""))
                recursion_pattern = "linear_recursion"

        # If no ratio pattern, use delta-based terms
        if not recurrence_terms:
            delta_signature = Counter()
            for ps, transitions in parent_transitions.items():
                deltas = tuple(sorted(set(d for d, r in transitions)))
                delta_signature[deltas] += 1

            most_common_deltas, count = delta_signature.most_common(1)[0]
            for delta in most_common_deltas:
                if delta == -1:
                    recurrence_terms.append("T(n-1)")
                elif delta == -2:
                    recurrence_terms.append("T(n-2)")
                elif delta < 0:
                    recurrence_terms.append(f"T(n{delta:+g})".replace("+", ""))
                elif delta > 0:
                    recurrence_terms.append(f"T(n+{delta:g})")
            recursion_pattern = "linear_recursion"

    # Filter out T(n) self-loops when other terms exist
    if "T(n)" in recurrence_terms and len(recurrence_terms) > 1:
        recurrence_terms = [t for t in recurrence_terms if t != "T(n)"]

    unique_terms = recurrence_terms

    # Step 5: Classify complexity from recurrence structure
    has_t_n_minus_1 = any("n-1" in t for t in unique_terms)
    has_t_n_minus_2 = any("n-2" in t for t in unique_terms)
    has_t_n_div_2 = any("n/2" in t for t in unique_terms)
    has_t_n_div_3 = any("n/3" in t for t in unique_terms)

    # Extract coefficient from terms like "2T(n/2)"
    dc_coeff = 1
    for t in unique_terms:
        m = _re.match(r"(\d+)T\(n/\d+\)", t)
        if m:
            dc_coeff = int(m.group(1))
            break

    non_leaf = [n for n in dag_nodes if children_map.get(n["id"])]
    avg_branch = sum(len(children_map.get(n["id"], [])) for n in non_leaf) / max(len(non_leaf), 1)

    if unique_terms:
        rhs = " + ".join(unique_terms)
        recurrence = f"T(n) = {rhs}"
    else:
        recurrence = "T(n) = O(1)"

    if has_t_n_minus_1 and has_t_n_minus_2:
        complexity_class = "O(phi^n) ~ O(1.618^n)"
        explanation = (
            "T(n) = T(n-1) + T(n-2) defines the Fibonacci recurrence. "
            "The characteristic equation is x^2 = x + 1, with dominant root "
            "phi = (1+sqrt(5))/2 ~ 1.618. The solution grows as O(phi^n)."
        )
    elif has_t_n_div_2:
        if dc_coeff > 1:
            # Master Theorem: aT(n/b) with a > 1
            import math
            exponent = math.log(dc_coeff) / math.log(2)
            if abs(exponent - round(exponent)) < 0.01:
                exponent = round(exponent)
            if exponent == 1:
                complexity_class = "O(n log n)"
                explanation = (
                    f"T(n) = {dc_coeff}T(n/2) splits into {dc_coeff} subproblems of size n/2. "
                    f"By the Master Theorem, a=b=2, so T(n) = O(n log n)."
                )
            else:
                complexity_class = f"O(n^{exponent:.2f})"
                explanation = (
                    f"T(n) = {dc_coeff}T(n/2) splits into {dc_coeff} subproblems of size n/2. "
                    f"By the Master Theorem, T(n) = O(n^(log_2({dc_coeff}))) = O(n^{exponent:.2f})."
                )
        else:
            complexity_class = "O(log n)"
            explanation = (
                "T(n) = T(n/2) means each call halves the problem size. "
                "After k levels, size is n/2^k = 1 when k = log_2(n), so T(n) = O(log n)."
            )
    elif has_t_n_div_3:
        if dc_coeff > 1:
            import math
            exponent = math.log(dc_coeff) / math.log(3)
            complexity_class = f"O(n^{exponent:.2f})"
            explanation = (
                f"T(n) = {dc_coeff}T(n/3) splits into {dc_coeff} subproblems of size n/3. "
                f"By the Master Theorem, T(n) = O(n^(log_3({dc_coeff}))) = O(n^{exponent:.2f})."
            )
        else:
            complexity_class = "O(log n)"
            explanation = (
                "T(n) = T(n/3) means each call thirds the problem size. "
                "After k levels, size is n/3^k = 1 when k = log_3(n), so T(n) = O(log n)."
            )
    elif has_t_n_minus_1 and len(unique_terms) == 1:
        complexity_class = "O(n)"
        explanation = (
            "T(n) = T(n-1) + c reduces n by 1 each call. "
            "The recursion makes n calls, each O(1), giving T(n) = O(n)."
        )
    elif len(unique_terms) >= 2:
        num_terms = len(unique_terms)
        complexity_class = f"O({num_terms}^n)"
        explanation = (
            f"T(n) = {' + '.join(unique_terms)} has {num_terms} recursive branches. "
            f"The call tree grows as {num_terms}^n, which is exponential."
        )
    else:
        complexity_class = "O(n)"
        explanation = "The recurrence reduces the problem by a constant each call."

    if has_reuse:
        with_cache = f"O(n) -- {unique_count} unique subproblems solved once"
        speedup = f"{total_count / max(unique_count, 1):.1f}x fewer computations with caching"
    elif total_count > unique_count:
        with_cache = f"O(n) -- {unique_count} unique subproblems"
        speedup = "some reuse detected"
    else:
        with_cache = "O(n) -- already optimal"
        speedup = "no overlapping subproblems"

    # Step 6: Generate semantic explanation (the "why" narrative)
    semantic_lines = []
    if recursion_pattern == "divide_and_conquer":
        b = 2 if has_t_n_div_2 else 3
        semantic_lines.append(f"This is a divide-and-conquer algorithm.")
        semantic_lines.append(f"Each call splits into {dc_coeff} subproblem(s) of size n/{b}.")
        if execution_type == "AND":
            semantic_lines.append(f"Execution: AND — all {dc_coeff} branches execute independently.")
        else:
            semantic_lines.append(f"Execution: OR — only one branch is explored per call.")
        semantic_lines.append(f"Therefore: T(n) = {recurrence.split(' = ')[1]}")
        semantic_lines.append(f"By the Master Theorem → {complexity_class}")
    elif recursion_pattern == "binary_search":
        semantic_lines.append(f"This is a search algorithm with halving.")
        semantic_lines.append(f"Each call halves the search space (n → n/2).")
        semantic_lines.append(f"Execution: OR — only one branch is explored per call.")
        semantic_lines.append(f"Therefore: T(n) = T(n/2)")
        semantic_lines.append(f"After log_2(n) levels, the search space is exhausted → O(log n)")
    elif recursion_pattern == "tree_recursion":
        semantic_lines.append(f"This is tree recursion with multiple recursive branches.")
        terms_desc = " + ".join(unique_terms)
        semantic_lines.append(f"Each call spawns: {terms_desc}")
        semantic_lines.append(f"Execution: AND — all branches execute, then results combine.")
        semantic_lines.append(f"The call tree grows exponentially → {complexity_class}")
    elif recursion_pattern == "linear_recursion":
        semantic_lines.append(f"This is linear recursion.")
        semantic_lines.append(f"Each call reduces the problem by a constant step.")
        semantic_lines.append(f"Execution: OR — single chain of calls, no branching.")
        semantic_lines.append(f"Therefore: {recurrence}, which makes {total_count} calls → {complexity_class}")
    else:
        semantic_lines.append(explanation)

    semantic_explanation = "\n".join(semantic_lines)

    return {
        "recurrence": recurrence,
        "recurrence_terms": unique_terms,
        "state_size": state_size_desc,
        "depth": max_depth,
        "without_cache": complexity_class + f" -- {total_count} calls for {unique_count} unique subproblems",
        "with_cache": with_cache,
        "speedup": speedup,
        "total_calls": total_count,
        "unique_calls": unique_count,
        "shared_subproblems": [{"id": n["id"], "called": n["call_count"]} for n in shared_nodes[:10]],
        "explanation": explanation,
        "semantic_explanation": semantic_explanation,
        # Semantic output
        "pattern": recursion_pattern,
        "shrink": shrink_class,
        "execution": execution_type,
        "branching_factor": round(avg_branch, 1),
        "median_ratio": round(statistics.median(all_ratios), 3) if all_ratios else None,
    }


def _detect_combine_operation(code: str, func_name: str) -> dict:
    """Detect how child results are combined in a recursive function.

    Returns dict with:
      - operation: "add" | "subtract" | "multiply" | "max" | "min" | "concat" | "merge" | "unknown"
      - operation_label: human-readable label for UI
      - pattern_hint: detected algorithm pattern (fibonacci, merge_sort, etc.)
      - pattern_description: one-line description
    """
    import ast as _ast

    result = {
        "operation": "unknown",
        "operation_label": "Combine",
        "pattern_hint": None,
        "pattern_description": None,
    }

    try:
        tree = _ast.parse(code)
    except SyntaxError:
        return result

    # Find the function
    func_node = None
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            if node.name == func_name:
                func_node = node
                break
    if not func_node:
        return result

    # Find return statements
    returns = []
    for node in _ast.walk(func_node):
        if isinstance(node, _ast.Return) and node.value:
            returns.append(node.value)

    if not returns:
        return result

    # Analyze the most complex return expression
    def _classify_expr(node):
        """Recursively classify a return expression."""
        if isinstance(node, _ast.BinOp):
            if isinstance(node.op, _ast.Add):
                return "add"
            if isinstance(node.op, _ast.Sub):
                return "subtract"
            if isinstance(node.op, _ast.Mult):
                return "multiply"
            if isinstance(node.op, _ast.Div):
                return "divide"
            if isinstance(node.op, _ast.FloorDiv):
                return "divide"
        if isinstance(node, _ast.Call):
            if isinstance(node.func, _ast.Attribute):
                method = node.func.attr
                if method in ('extend', 'append', 'insert'):
                    return "concat"
                if method in ('update', 'add'):
                    return "merge"
            # max(a, b) / min(a, b)
            if isinstance(node.func, _ast.Name):
                if node.func.id == 'max':
                    return "max"
                if node.func.id == 'min':
                    return "min"
                if node.func.id == 'sorted':
                    return "merge"
                if node.func.id in ('zip', 'map', 'filter'):
                    return "concat"
        if isinstance(node, _ast.ListComp):
            return "concat"
        if isinstance(node, _ast.BoolOp):
            if isinstance(node.op, _ast.And):
                return "and"
            if isinstance(node.op, _ast.Or):
                return "or"
        return None

    # Check all returns, pick the one with recursive calls
    best_op = None
    for ret_node in returns:
        op = _classify_expr(ret_node)
        if op:
            best_op = op
            break
        # Check children (e.g., return f(x) + g(y))
        for child in _ast.walk(ret_node):
            if child is ret_node:
                continue
            op = _classify_expr(child)
            if op:
                best_op = op
                break
        if best_op:
            break

    if not best_op:
        # Heuristic: check code patterns
        code_lower = code.lower()
        if '+' in code and func_name.lower() in code_lower:
            best_op = "add"
        elif 'merge' in code_lower or 'extend' in code_lower:
            best_op = "merge"
        elif 'max(' in code_lower:
            best_op = "max"
        elif 'min(' in code_lower:
            best_op = "min"
        elif 'sorted(' in code_lower:
            best_op = "merge"

    operation_labels = {
        "add": "ADD",
        "subtract": "SUBTRACT",
        "multiply": "MULTIPLY",
        "divide": "DIVIDE",
        "max": "MAX",
        "min": "MIN",
        "concat": "CONCAT",
        "merge": "MERGE",
        "and": "AND",
        "or": "OR",
    }

    result["operation"] = best_op or "unknown"
    result["operation_label"] = operation_labels.get(best_op, "COMBINE")

    # Pattern detection from operation + code hints
    code_lower = code.lower()
    func_lower = func_name.lower()

    if best_op == "add" and ('fib' in func_lower or 'fibonacci' in code_lower):
        result["pattern_hint"] = "fibonacci"
        result["pattern_description"] = "Fibonacci recurrence: each call splits into two smaller calls, results sum"
    elif best_op == "merge" or (best_op == "concat" and 'sort' in code_lower):
        result["pattern_hint"] = "merge_sort"
        result["pattern_description"] = "Divide & Conquer: split problem, solve both halves, merge results"
    elif ('binary' in code_lower or 'bisect' in code_lower or ('mid' in code_lower and 'return' in code_lower)):
        result["pattern_hint"] = "binary_search"
        result["pattern_description"] = "Binary Search: halve search space each step"
    elif best_op == "max" and ('rob' in func_lower or 'knapsack' in code_lower):
        result["pattern_hint"] = "dp_decision"
        result["pattern_description"] = "Decision DP: choose max between include/exclude"
    elif best_op == "min" and ('coin' in code_lower or 'distance' in code_lower or 'edit' in code_lower):
        result["pattern_hint"] = "dp_optimization"
        result["pattern_description"] = "Optimization DP: find minimum cost path"
    elif best_op == "add" and any(x in code_lower for x in ['range(', 'for i in']):
        result["pattern_hint"] = "accumulation"
        result["pattern_description"] = "Accumulation: recursive sum over a range"
    elif best_op in ("concat", "merge"):
        result["pattern_hint"] = "divide_and_conquer"
        result["pattern_description"] = "Divide & Conquer: split, solve, combine"
    elif best_op == "add":
        result["pattern_hint"] = "linear_recursion"
        result["pattern_description"] = "Linear recursion with additive combination"

    return result


def _dag_to_tree_layout(dag_nodes, dag_edges, max_display=50):
    """Layout the call tree for frontend visualization.

    Returns: { 'nodes': [...], 'edges': [...], 'level_info': [...], 'width': int, 'height': int }
    """
    if not dag_nodes:
        return {'nodes': [], 'edges': [], 'level_info': [], 'width': 0, 'height': 0}

    # Find root
    targets = set(e['to'] for e in dag_edges)
    roots = [n for n in dag_nodes if n['id'] not in targets]
    root_id = roots[0]['id'] if roots else dag_nodes[0]['id']

    # BFS layout by depth
    children_map = {}
    for e in dag_edges:
        children_map.setdefault(e['from'], []).append(e['to'])

    # Assign positions and track levels
    positions = {}
    levels = {}  # depth → [node_ids]
    node_depths = {}
    queue = [(root_id, 0)]
    visited = set()
    while queue:
        node_id, depth = queue.pop(0)
        if node_id in visited:
            continue
        visited.add(node_id)
        positions[node_id] = depth
        node_depths[node_id] = depth
        levels.setdefault(depth, []).append(node_id)
        for child in children_map.get(node_id, []):
            if child not in visited:
                queue.append((child, depth + 1))

    # Compute state size per node (reuse _infer_problem_size logic inline)
    def _quick_state(nid):
        import re as _re
        m = _re.search(r"\((.+)\)\s*$", nid)
        if not m:
            return None
        args_str = m.group(1)
        tokens, depth_p, cur = [], 0, ""
        for ch in args_str:
            if ch in "([":
                depth_p += 1; cur += ch
            elif ch in ")]":
                depth_p -= 1; cur += ch
            elif ch == ',' and depth_p == 0:
                tokens.append(cur); cur = ""
            else:
                cur += ch
        if cur:
            tokens.append(cur)
        nums = []
        has_list = False
        for t in tokens:
            t = t.strip()
            if t.startswith('[') and t.endswith(']'):
                has_list = True; continue
            try:
                nums.append(int(t))
            except ValueError:
                try:
                    nums.append(float(t))
                except ValueError:
                    pass
        if has_list and not nums:
            inner = t[1:-1].strip()
            return inner.count(',') + 1 if inner else 0
        if len(nums) >= 3:
            return abs(nums[-1] - nums[-2])
        if len(nums) == 2:
            return abs(nums[1] - nums[0]) if nums[0] < nums[1] else max(nums)
        if len(nums) == 1:
            return nums[0]
        return None

    node_states = {}
    for nid in visited:
        s = _quick_state(nid)
        if s is not None:
            node_states[nid] = s

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
                'depth': depth,
                'state_size': node_states.get(nid),
            })

    # Layout edges with annotation (branch label, size label)
    layout_edges = []
    for e in dag_edges:
        if e['from'] in node_positions and e['to'] in node_positions:
            parent_size = node_states.get(e['from'])
            child_size = node_states.get(e['to'])
            edge_label = ""
            size_label = ""
            if parent_size is not None and child_size is not None and parent_size > 0:
                ratio = child_size / parent_size
                if 0.4 <= ratio <= 0.6:
                    size_label = f"n/2"
                elif 0.2 < ratio < 0.4:
                    size_label = f"n/3"
                elif ratio < 1:
                    size_label = f"n-{parent_size - child_size}"
            layout_edges.append({
                'from': e['from'],
                'to': e['to'],
                'from_pos': node_positions[e['from']],
                'to_pos': node_positions[e['to']],
                'label': edge_label,
                'size_label': size_label,
            })

    # Compute level info for recursion level view
    # level_cost = node_count × avg_problem_size → total work at this level
    level_info = []
    for depth in sorted(levels.keys()):
        ids_at_level = levels[depth]
        node_count = len(ids_at_level)
        sizes_at_level = [node_states.get(nid) for nid in ids_at_level if node_states.get(nid) is not None]
        avg_size = sum(sizes_at_level) / len(sizes_at_level) if sizes_at_level else None
        total_calls_at_level = sum(
            next((n.get("call_count", 1) for n in dag_nodes if n["id"] == nid), 1)
            for nid in ids_at_level
        )
        # Total cost at this level = number of nodes × average problem size
        level_cost = node_count * avg_size if avg_size else None
        level_info.append({
            'depth': depth,
            'node_count': node_count,
            'total_calls': total_calls_at_level,
            'avg_problem_size': round(avg_size, 1) if avg_size else None,
            'level_cost': round(level_cost, 1) if level_cost else None,
            'node_ids': ids_at_level[:10],
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
        'level_info': level_info,
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

        # Trace execution — call with inferred args, or no args if all have defaults
        result, tree = _trace_recursive_calls(func, tuple(default_args))

        if tree is None:
            return {
                "success": True,
                "is_recursive": False,
                "narrative": "This function does not appear to use recursion.",
            }

        # Build DAG
        dag_nodes, dag_edges, unique_count, total_count = _build_subproblem_dag(tree)

        # Serialize call tree (strip internal _parent refs, limit depth for payload)
        def _serialize_tree(node, depth=0):
            if node is None or depth > 12:
                return None
            return {
                'id': node['id'],
                'args': node.get('args', []),
                'result': node.get('result'),
                'children': [_serialize_tree(c, depth + 1) for c in node.get('children', []) if c],
            }
        call_tree = _serialize_tree(tree)

        # Derive complexity
        complexity = _derive_complexity_from_dag(dag_nodes, dag_edges, total_count, unique_count)

        # Detect combine operation + pattern from code
        op_info = _detect_combine_operation(req.code, func_name)
        complexity["combine_operation"] = op_info["operation"]
        complexity["combine_operation_label"] = op_info["operation_label"]
        if op_info["pattern_hint"]:
            complexity["pattern_hint"] = op_info["pattern_hint"]
            complexity["pattern_description"] = op_info["pattern_description"]

        # Auto summary
        complexity["auto_summary"] = {
            "total_calls": total_count,
            "unique_subproblems": unique_count,
            "repeated_calls": total_count - unique_count,
            "depth": complexity.get("depth", 0),
            "branching_factor": complexity.get("branching_factor", 0),
            "complexity": complexity.get("without_cache", "").split(" --")[0],
            "optimized_complexity": complexity.get("with_cache", ""),
            "speedup": complexity.get("speedup", ""),
            "operation": op_info["operation_label"],
            "pattern": op_info.get("pattern_description") or complexity.get("pattern", ""),
            "has_memoization_benefit": total_count > unique_count * 1.5,
        }

        # Cognitive narrative: human-readable explanation
        complexity["cognitive_narrative"] = _generate_cognitive_narrative(complexity, func_name)

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
            'call_tree': call_tree,
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


def _generate_cognitive_narrative(complexity: dict, func_name: str = '') -> str:
    """Generate a teaching narrative with cognitive conflict.

    Pipeline: baseline → tension → trigger → peak → aftermath
    Peak is selected by what is MOST COUNTER-INTUITIVE, not most important.
    Uses \\n\\n to separate thinking steps (rendered as paragraphs).
    """
    total = complexity.get('total_calls', 0)
    unique = complexity.get('unique_calls', 0)
    depth = complexity.get('depth', 0)
    branching = complexity.get('branching_factor', 0)
    operation = complexity.get('combine_operation', 'unknown')
    pattern_hint = complexity.get('pattern_hint', '')
    complexity_class = complexity.get('without_cache', '').split(' --')[0]
    optimized = complexity.get('with_cache', '').split(' --')[0]
    speedup = complexity.get('speedup', '')
    shared = complexity.get('shared_subproblems', [])
    name = func_name or 'This function'

    has_redundancy = shared and total > unique * 1.5

    # --- Pick the peak type: what is most counter-intuitive? ---
    if has_redundancy and speedup and speedup != 'none':
        peak_type = 'illusion_of_work'  # "you think you're solving N, but really solving same K"
    elif branching >= 2 and depth >= 4 and total > 20:
        peak_type = 'explosion'  # "it doesn't grow, it explodes"
    elif depth <= 3 and total > 10:
        peak_type = 'hidden_cost'  # "looks small, work is hiding"
    else:
        peak_type = 'structure'  # efficient algorithm, the insight is the structure

    parts = []

    # === Step 1: Baseline (quiet) — metaphor drives explanation ===
    if pattern_hint == 'fibonacci':
        parts.append(
            f"This process behaves like a tree.\n\n"
            f"Each step grows two new branches."
        )
    elif pattern_hint == 'merge_sort':
        parts.append(
            f"Think of a deck of cards.\n\n"
            f"Split it in half. Sort each half.\n\n"
            f"Weave the two sorted halves back together."
        )
    elif pattern_hint == 'binary_search':
        parts.append(
            f"Imagine looking up a word in a dictionary.\n\n"
            f"Flip to the middle. Too far? Flip to the middle of what is left."
        )
    elif pattern_hint == 'dp_decision':
        parts.append(f"At each item, you make a choice: take it or leave it.")
    elif pattern_hint == 'dp_optimization':
        parts.append(f"Like a GPS that checks every route to find the shortest.")
    elif operation == 'merge':
        parts.append(f"Split. Sort each half. Merge back together.")
    else:
        parts.append(f"{name} breaks a problem into smaller versions of itself.")

    # === Step 2: Build tension (light) — numbers, scale ===
    if branching >= 2 and total > unique:
        parts.append(
            f"Each problem splits into {int(branching)} subproblems.\n\n"
            f"That creates {total} calls in total."
        )
    elif branching >= 2:
        parts.append(
            f"Each problem splits into {int(branching)} subproblems.\n\n"
            f"The recursion goes {depth} levels deep."
        )
    elif total > 1:
        parts.append(f"The recursion goes {depth} levels deep, making {total} calls.")

    # === Step 3: Mechanism (quiet) ===
    if operation == 'add' and branching >= 2:
        parts.append(f"Each subproblem returns a number. The caller adds them.")
    elif operation == 'add':
        parts.append(f"Each step adds its piece to the total.")
    elif operation == 'merge':
        parts.append(f"Each half returns a sorted list. The caller merges them.")
    elif operation == 'max':
        parts.append(f"Two options are tried. The better one wins.")
    elif operation == 'min':
        parts.append(f"The cheapest option is chosen at each step.")

    # === Step 4: Trigger + Peak (Expectation → Break → Replace) + Locking ===
    if peak_type == 'illusion_of_work':
        # Expectation → Break → Replace
        parts.append(
            f"Why does that matter?\n\n"
            f"It looks like {total} problems.\n\n"
            f"It is not.\n\n"
            f"You are solving the same {unique} problems again and again."
        )
        # Locking: cement the understanding
        parts.append(
            f"That is why naive recursion feels slow.\n\n"
            f"Not because the problem is big.\n\n"
            f"Because the work is repeated."
        )
        # Aftermath
        parts.append(
            f"Without caching: {complexity_class}.\n\n"
            f"With caching: {optimized}.\n\n"
            f"That is a {speedup} difference."
        )
    elif peak_type == 'explosion':
        # Expectation → Break → Replace
        parts.append(
            f"At first, it feels manageable.\n\n"
            f"Then each step creates more work than the last.\n\n"
            f"It does not grow.\n\n"
            f"It explodes."
        )
        # Locking
        parts.append(
            f"This is the nature of exponential growth.\n\n"
            f"Small inputs are fine. Large inputs are impossible."
        )
        if complexity_class:
            parts.append(f"That is {complexity_class}.")
    elif peak_type == 'hidden_cost':
        # Expectation → Break → Replace
        parts.append(
            f"It looks small.\n\n"
            f"Only {depth} levels deep.\n\n"
            f"But the work is not in the depth.\n\n"
            f"It is in the branching."
        )
        # Locking
        parts.append(
            f"{total} calls, hidden behind a shallow tree."
        )
        if complexity_class:
            parts.append(f"That is {complexity_class}.")
    elif peak_type == 'structure':
        if pattern_hint == 'fibonacci':
            parts.append(
                f"The work doubles at every level.\n\n"
                f"That is exponential growth."
            )
        elif pattern_hint == 'merge_sort':
            parts.append(
                f"Each level does the same amount of work.\n\n"
                f"Equal work per level, log n levels.\n\n"
                f"That is O(n log n)."
            )
        elif pattern_hint == 'binary_search':
            parts.append(
                f"You never look at the same element twice.\n\n"
                f"That is why it is O(log n)."
            )
        elif pattern_hint == 'dp_decision' and shared:
            parts.append(f"Many paths lead to the same subproblem. Caching avoids solving them twice.")
        elif pattern_hint == 'dp_optimization' and shared:
            parts.append(f"Overlapping subproblems mean repeated work. Memoization eliminates the redundancy.")
        elif complexity_class and complexity_class.startswith('O('):
            parts.append(f"This gives {complexity_class} time complexity.")

    return '\n\n'.join(parts)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
