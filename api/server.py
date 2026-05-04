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

        return {
            "success": True,
            "explanations": explanations,
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

        return {"success": True, "explanation": explanation}
    except Exception as e:
        return {"success": False, "error": str(e), "error_type": type(e).__name__}


@app.get("/api/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
