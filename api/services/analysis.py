"""Analysis service — orchestration layer between routes and engine.

Routes = transport (parse request, call service, return response)
Services = orchestration (business logic, calling multiple engines)
Dynamic = engine (pure computation)
"""

from __future__ import annotations
import inspect
import os
import sys
import traceback
from typing import Any, Dict, Optional, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from dynamic.runtime.recorder import record_function, ExecutionTimeline
from dynamic.runtime.pdg import RuntimePDG
from dynamic.semantic.facts import FactExtractor
from dynamic.semantic.narrative import NarrativeEngine
from api.input_inference import infer_args
from api.services.helpers import extract_func_name, import_code_as_module, cache_put


def prepare_execution(
    code: str, func_name: str = "", language: str = "python",
) -> Tuple[Any, Any, ExecutionTimeline, Any, Optional[str]]:
    """Common execution pipeline: extract func → import → infer args → record.

    Returns (module, func, timeline, result, func_file).
    Caller must clean up func_file.
    """
    func_name = extract_func_name(code, func_name)
    if not func_name:
        raise ValueError("No function found in code. Define a function to analyze.")

    module = import_code_as_module(code)
    func = getattr(module, func_name, None)
    if func is None:
        raise ValueError(f"Function '{func_name}' was not found as a top-level function in the submitted code.")
    if not inspect.isfunction(func) or getattr(func, "__module__", None) != module.__name__:
        raise ValueError(f"'{func_name}' is not a user-defined top-level function. Select or define a top-level function to analyze.")
    func_file = os.path.abspath(func.__code__.co_filename)

    inferred_args, arg_meta = infer_args(func, code)
    result, timeline = record_function(func, *inferred_args, target_files={func_file})

    return module, func, timeline, result, func_file


def build_steps_data(timeline: ExecutionTimeline) -> list:
    """Convert ExecutionTimeline to serializable step dicts."""
    steps_data = []
    for step in timeline.steps:
        var_states = {}
        for name, snap in step.variables.items():
            var_states[name] = {
                "value": snap.value_repr,
                "type": snap.value_type,
                "changed": name in step.changed_vars,
                "is_new": name in step.new_vars,
                "memory_id": snap.memory_id,
                "is_alias_of": snap.is_reference_to,
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
            "mutated": step.mutated_vars,
            "rebound": step.rebound_vars,
            "alias_groups": step.alias_groups,
            "container_deltas": step.container_deltas,
            "depth": step.depth,
            "indent": step.indent,
            "block_id": step.block_id,
            "call_id": step.call_id,
            "ast_reads": step.ast_reads,
            "ast_writes": step.ast_writes,
            "ssa_versions": step.ssa_versions,
        })
    return steps_data


def build_semantic_context(timeline: ExecutionTimeline) -> dict:
    """Build SemanticExecutionModel + facts + narrative engine from timeline."""
    from dynamic.semantic_ir import build_from_pdg

    pdg = RuntimePDG.from_timeline(timeline)
    model = build_from_pdg(pdg)  # lower to semantic IR
    facts = FactExtractor(model).extract_all()
    narrative_engine = NarrativeEngine(model, facts)

    # Build causal chain via backward slice on last step
    causal_chain = []
    root_causes = []
    if timeline.steps:
        last = timeline.steps[-1]
        target_var = last.ast_reads[0] if last.ast_reads else (last.ast_writes[0] if last.ast_writes else '')
        try:
            sr = pdg.backward_slice(last.step_index, target_var)
            causal_chain = [
                {'source': e.source, 'target': e.target, 'var': e.var, 'kind': e.kind}
                for e in sr.edges
            ]
            root_causes = sr.root_causes
        except Exception:
            pass

    return {
        "pdg": pdg,       # kept for backward_slice/forward_impact (runtime ops)
        "model": model,   # semantic IR — all semantic modules use this
        "facts": facts,
        "narrative_engine": narrative_engine,
        "causal_chain": causal_chain,
        "root_causes": root_causes,
    }


def build_insight_response(
    code: str, func_name: str = "", language: str = "python",
) -> dict:
    """Full insight pipeline: execute → analyze → build response."""
    func_file = None
    try:
        module, func, timeline, result, func_file = prepare_execution(code, func_name, language)
    except Exception as e:
        return {"success": False, "error": str(e), "error_type": type(e).__name__, "traceback": traceback.format_exc()}

    try:
        from reasoning.insight_summarizer import summarize_insight
        from reasoning.result_explainer import explain_result

        steps_data = build_steps_data(timeline)
        insight = summarize_insight(timeline, result, func_name)
        explanation = explain_result(timeline, result, func_name)

        # Semantic narration
        detected_patterns = _apply_narration(code, steps_data)

        # Semantic context
        ctx = build_semantic_context(timeline)

        session_id = str(id(timeline))
        cache_put(session_id, {
            "timeline": timeline,
            "steps_data": steps_data,
            "result": result,
            "pdg": ctx["pdg"],
            "facts": ctx["facts"],
            "narrative_engine": ctx["narrative_engine"],
        })

        return {
            "success": True,
            "session_id": session_id,
            "insight": insight,
            "explanation": explanation,
            "result": {"value": repr(result), "type": type(result).__name__},
            "timeline": steps_data,
            "steps": steps_data,
            "total_steps": len(steps_data),
            "causal_chain": ctx["causal_chain"],
            "root_causes": ctx["root_causes"],
            "narrative_engine": str(ctx["narrative_engine"]),
            "pdg_stats": {
                "nodes": ctx["pdg"].node_count,
                "edges": ctx["pdg"].edge_count,
                "data_edges": ctx["pdg"].data_edge_count,
                "control_edges": ctx["pdg"].control_edge_count,
            },
            "facts_count": len(ctx["facts"]),
            "detected_patterns": detected_patterns,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
    finally:
        if func_file:
            try:
                os.unlink(func_file)
            except OSError:
                pass


def _apply_narration(code: str, steps_data: list) -> list:
    """Apply semantic narration to steps data. Returns detected patterns."""
    try:
        from dynamic.semantic.narrator import SemanticNarrator
        narrator = SemanticNarrator(code)
        prev_depth = 0
        for sd in steps_data:
            event = narrator.analyze_step(
                sd.get("code", ""),
                sd.get("vars", {}),
                depth=sd.get("depth", 0),
                prev_depth=prev_depth,
                step_index=sd.get("index", 0),
                call_id=sd.get("call_id", 0),
            )
            sd["event_type"] = event.event_type
            sd["narration"] = event.narration
            sd["semantic_tags"] = event.semantic_tags
            sd["visual_priority"] = event.visual_priority
            if event.pointer_move:
                sd["pointer_move"] = {
                    "pointer": event.pointer_move.pointer,
                    "from_object": event.pointer_move.from_object,
                    "to_object": event.pointer_move.to_object,
                }
            prev_depth = sd.get("depth", 0)
        return narrator.detected_patterns
    except Exception:
        return []
