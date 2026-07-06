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
    PatternNarrativeRequest, SubproblemGraphRequest, AnalyzeFullRequest,
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
            "success": True,
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
        ds_result = trace_ds_function(func, *(
            __import__("api.input_inference", fromlist=["infer_args"]).infer_args(func, req.code)[0]
        ))

        if isinstance(ds_result, tuple):
            _, ds_timeline = ds_result
        else:
            ds_timeline = ds_result

        if not ds_timeline or not hasattr(ds_timeline, 'steps'):
            return {"success": True, "steps": [], "total_steps": 0, "ds_viz_url": "", "note": "No heap objects traced"}

        # Build steps data
        steps_data = []
        for step in ds_timeline.steps:
            nodes = {}
            for obj_id, snap in step.objects.items():
                nodes[str(obj_id)] = {
                    "id": obj_id, "type": snap.type_name, "val": snap.val_repr,
                    "attrs": snap.attributes, "refs": {k: v for k, v in snap.ref_ids.items()},
                    "changed": obj_id in step.changed_objects,
                }
            edges = []
            for obj_id, snap in step.objects.items():
                for attr, target_id in snap.ref_ids.items():
                    if str(target_id) in nodes:
                        is_changed = any(
                            cid == obj_id and attr == ref_attr
                            for cid, ref_attr, _ in step.changed_refs
                        )
                        edges.append({"from": obj_id, "to": target_id, "label": attr, "changed": is_changed})
            var_bindings = {}
            for var_name, obj_id in step.var_to_obj.items():
                if obj_id in step.objects:
                    var_bindings[var_name] = obj_id
            steps_data.append({
                "index": step.step_index, "line": step.line_number,
                "code": step.code_line, "func": step.function_name,
                "nodes": nodes, "edges": edges, "var_bindings": var_bindings,
                "changed_objects": step.changed_objects,
                "changed_refs": [(c[0], c[1], c[2]) for c in step.changed_refs],
            })

        # Generate HTML visualization
        import tempfile
        viz_path = os.path.join(tempfile.gettempdir(), f"ds_viz_{id(ds_timeline)}.html")
        render_ds_timeline(ds_timeline, output_path=viz_path)

        return {
            "success": True,
            "steps": steps_data,
            "total_steps": len(steps_data),
            "ds_viz_url": viz_path,
            "func_name": req.func_name,
            "result": repr(result),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "error_type": type(e).__name__}
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
        explanation = explain_result(timeline, result, req.func_name)
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
        explanations = _explain_steps(steps_data, req.func_name)

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


@router.post("/api/analyze_full")
async def analyze_full(req: AnalyzeFullRequest, container: AppContainer = Depends(get_container)):
    """Unified analysis endpoint — returns everything in one clean response."""
    func_file = None
    try:
        # 1. Execute code and build timeline
        module, func, timeline, result, func_file = prepare_execution(
            req.code, req.func_name, req.language,
        )

        # 2. Build semantic context (PDG + facts)
        ctx = build_semantic_context(timeline)

        # 3. Build insight
        insight_resp = build_insight_response(req.code, req.func_name, req.language)

        # 4. Build step explanations
        steps_data = build_steps_data(timeline)

        # 5. Build causal chain (from backward slice)
        causal_chain = []
        causal_sentences = []
        root_causes = []
        if ctx.get("pdg") and timeline.steps:
            last = timeline.steps[-1]
            target_var = last.ast_reads[0] if last.ast_reads else (last.ast_writes[0] if last.ast_writes else '')
            try:
                sr = ctx["pdg"].backward_slice(last.step_index, target_var)
                causal_chain = [
                    {"step": e.source, "target": e.target, "var": e.var, "kind": e.kind}
                    for e in sr.edges[:20]
                ]
                root_causes = sr.root_causes[:5]
            except Exception:
                pass

        # 6. Detect patterns
        from reasoning.pattern_detector import detect_patterns
        patterns = detect_patterns(ctx.get("facts", []), ctx.get("pdg"))

        # 7. Build variable evolution summary
        var_summary = {}
        for step in timeline.steps:
            for var_name, snap in step.variables.items():
                if var_name not in var_summary:
                    var_summary[var_name] = {
                        "name": var_name,
                        "first_value": snap.value_repr,
                        "last_value": snap.value_repr,
                        "type": snap.value_type,
                        "changes": 0,
                        "first_step": step.step_index,
                        "last_step": step.step_index,
                    }
                var_summary[var_name]["last_value"] = snap.value_repr
                var_summary[var_name]["last_step"] = step.step_index
                if var_name in step.changed_vars:
                    var_summary[var_name]["changes"] += 1

        # 8. Build mini timeline (key steps only)
        key_timeline = []
        for step in timeline.steps:
            changed = list(step.changed_vars) if step.changed_vars else []
            event = ""
            if step.new_vars:
                event = "new_vars"
            if changed:
                event = "changed"
            if "return" in step.code_line.lower():
                event = "return"
            if "for " in step.code_line or "while " in step.code_line:
                event = "loop"
            if changed or event in ("loop", "return", "call", "branch"):
                key_timeline.append({
                    "step": step.step_index,
                    "line": step.line_number,
                    "code": step.code_line.strip(),
                    "changed_vars": changed,
                    "event": event,
                })

        # 9. Build natural language summary
        insight_obj = insight_resp.get("insight")
        algo = insight_obj.algorithm_type if insight_obj else "unknown"
        one_liner = insight_obj.one_liner if insight_obj else ""
        confidence = insight_obj.confidence if insight_obj else 0
        phases_raw = insight_obj.phases if insight_obj else []
        pattern_names = [p.name for p in patterns]
        result_str = repr(result) if result is not None else "None"
        summary = f"{req.func_name}() 使用 {algo} 算法"
        if "memoization" in pattern_names:
            summary += "，通过 memo 缓存避免重复计算"
        if "loop.accumulation" in pattern_names:
            summary += "，循环累积结果"
        summary += f"。最终返回 {result_str}。"

        phases = []
        for ph in phases_raw:
            phases.append({
                "name": ph.name,
                "start_step": ph.start_step,
                "end_step": ph.end_step,
                "description": ph.description,
                "key_variables": ph.key_variables,
                "step_count": ph.step_count,
            })

        return {
            "success": True,
            "summary": summary,
            "one_liner": one_liner,
            "algorithm": algo,
            "confidence": confidence,
            "result": result_str,
            "total_steps": len(timeline.steps),
            "key_patterns": [
                {"name": p.name, "description": p.description, "confidence": p.confidence, "complexity": p.complexity}
                for p in patterns
            ],
            "variables": var_summary,
            "key_timeline": key_timeline,
            "causal_chain": causal_chain[:15],
            "root_causes": root_causes,
            "phases": phases,
            "visualizations": {
                "graph_url": "/output/causal_graph.html" if ctx.get("pdg") else None,
            },
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
