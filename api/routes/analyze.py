"""Analyze routes — code analysis, insight, explanation, pattern recognition."""

from __future__ import annotations
import os
import sys

from fastapi import APIRouter, Depends

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from static.python_analyzer import PythonAnalyzer
from static.config_linker import ConfigLinker
from dynamic.runtime.ds_tracer import trace_ds_function
from fusion.merge_engine import MergeEngine
from query.root_cause import RootCauseQuery
from visualization.graph_ui import GraphVisualizer
from visualization.ds_viz import render_ds_timeline

from api.services.helpers import write_temp_code, cache_get, compute_control_edges, compute_loop_groups
from api.services.analysis import (
    prepare_execution, build_steps_data, build_semantic_context, build_insight_response,
)
from api.schemas.analyze import (
    AnalyzeRequest, InsightRequest, DSVizRequest, RunRequest,
    ExplainRequest, ExplainStepsRequest, ExplainStepFocusRequest,
    PatternNarrativeRequest, SubproblemGraphRequest,
)
from api.container import get_container, AppContainer

router = APIRouter()
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")


# ── Routes ───────────────────────────────────────────────────────

@router.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    """Full causal analysis of code."""
    tmp_path = None
    try:
        tmp_path = write_temp_code(req.code, req.language)
        analyzer = PythonAnalyzer()
        graph = analyzer.analyze_file(tmp_path)

        if req.config:
            linker = ConfigLinker()
            config_path = write_temp_code(req.config, "yaml")
            config_graph = linker.build_graph(config_path, [tmp_path])
            graph.merge_from(config_graph)
            os.unlink(config_path)

        error_chain = []
        if req.error_line:
            node_id = f"{tmp_path}:{req.error_line}"
            if graph.has_node(node_id):
                query = RootCauseQuery(graph)
                error_chain = query.get_root_cause_chain(node_id)

        viz = GraphVisualizer()
        viz.render(
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


@router.post("/api/insight")
async def get_insight(req: InsightRequest, container: AppContainer = Depends(get_container)):
    """Get cognitive-level insight for code."""
    return container.analysis_service.build_insight_response(req.code, req.func_name, req.language)


@router.post("/api/ds-viz")
async def ds_viz(req: DSVizRequest):
    """Data structure visualization."""
    func_file = None
    try:
        module, func, timeline, result, func_file = prepare_execution(
            req.code, req.func_name, req.language,
        )
        ds_steps = trace_ds_function(func, *(
            __import__("api.input_inference", fromlist=["infer_args"]).infer_args(func, req.code)[0]
        ))
        if ds_steps:
            viz_data = render_ds_timeline(ds_steps)
        else:
            viz_data = {"steps": [], "note": "No heap objects traced"}
        return {"success": True, **viz_data}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        if func_file:
            try:
                os.unlink(func_file)
            except OSError:
                pass


@router.post("/api/run")
async def run_code(req: RunRequest):
    """Run code and return result."""
    from api.sandbox import run_sandboxed
    try:
        result = run_sandboxed(req.code, req.func_name, req.timeout)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/explain")
async def explain(req: ExplainRequest):
    """Generate explanation for code."""
    func_file = None
    try:
        module, func, timeline, result, func_file = prepare_execution(
            req.code, req.func_name, req.language,
        )
        from reasoning.result_explainer import explain_result
        explanation = explain_result(timeline, result, req.func_name, provider=req.provider, api_key=req.api_key)
        return {"success": True, "explanation": explanation}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        if func_file:
            try:
                os.unlink(func_file)
            except OSError:
                pass


@router.post("/api/explain_steps")
async def explain_steps(req: ExplainStepsRequest):
    """Generate step-by-step explanations."""
    func_file = None
    try:
        module, func, timeline, result, func_file = prepare_execution(
            req.code, req.func_name, req.language,
        )
        steps_data = build_steps_data(timeline)
        control_edges = compute_control_edges(steps_data)
        loop_groups = compute_loop_groups(steps_data)

        from reasoning.step_explainer import explain_steps as _explain_steps
        explanations = _explain_steps(steps_data, req.func_name, provider=req.provider, api_key=req.api_key)

        from api.services.helpers import cache_put
        session_id = req.session_id or str(id(timeline))
        cache_put(session_id, {
            "timeline": timeline,
            "steps_data": steps_data,
            "result": result,
        })

        return {
            "success": True,
            "explanations": explanations,
            "control_edges": control_edges,
            "loop_groups": loop_groups,
            "session_id": session_id,
        }
    except Exception as e:
        import traceback
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
    finally:
        if func_file:
            try:
                os.unlink(func_file)
            except OSError:
                pass


@router.post("/api/explain_step_focus")
async def explain_step_focus(req: ExplainStepFocusRequest):
    """Focused explanation for a specific step."""
    try:
        cached = cache_get(req.session_id)
        if not cached:
            return {"success": False, "error": "Session expired. Re-run analysis."}

        steps_data = cached["steps_data"]
        if req.step_index < 0 or req.step_index >= len(steps_data):
            return {"success": False, "error": f"Step index {req.step_index} out of range"}

        from reasoning.step_explainer import explain_step_focused
        result = explain_step_focused(
            steps_data, req.step_index,
            window_before=req.window_before,
            window_after=req.window_after,
            provider=req.provider, api_key=req.api_key,
        )
        return {"success": True, **result}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/pattern_narrative")
async def pattern_narrative(req: PatternNarrativeRequest):
    """Detect and narrate algorithmic patterns."""
    func_file = None
    try:
        module, func, timeline, result, func_file = prepare_execution(
            req.code, req.func_name, req.language,
        )
        ctx = build_semantic_context(timeline)

        from reasoning.pattern_detector import detect_patterns
        patterns = detect_patterns(ctx["facts"], ctx["pdg"])

        return {
            "success": True,
            "patterns": [p.to_dict() for p in patterns],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        if func_file:
            try:
                os.unlink(func_file)
            except OSError:
                pass


@router.post("/api/subproblem_graph")
async def subproblem_graph(req: SubproblemGraphRequest):
    """Build subproblem dependency graph."""
    func_file = None
    try:
        module, func, timeline, result, func_file = prepare_execution(
            req.code, req.func_name, req.language,
        )
        ctx = build_semantic_context(timeline)

        from reasoning.subproblem_builder import build_subproblem_graph
        graph = build_subproblem_graph(ctx["pdg"], ctx["facts"])

        return {"success": True, **graph}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        if func_file:
            try:
                os.unlink(func_file)
            except OSError:
                pass


@router.get("/api/health")
async def health():
    return {"status": "ok", "version": "2.0"}
