"""Replay routes — failure attribution, causal chain, backward slicing."""

from __future__ import annotations
import os
import sys

from fastapi import APIRouter, Depends

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from dynamic.runtime.pdg import RuntimePDG

from api.services.analysis import prepare_execution, build_steps_data, build_semantic_context
from api.schemas.replay import ReplayInsightRequest
from api.container import get_container, AppContainer

router = APIRouter()


@router.post("/api/failure_attribution")
async def failure_attribution(req: ReplayInsightRequest):
    """Analyze execution for failure attribution."""
    func_file = None
    try:
        module, func, timeline, result, func_file = prepare_execution(
            req.code, req.func_name, req.language,
        )
        steps_data = build_steps_data(timeline)

        from dynamic.semantic.failure_attribution import FailureAttribution
        attribution = FailureAttribution.analyze(steps_data)

        return {"success": True, "func_name": req.func_name, "attribution": attribution}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        if func_file and os.path.exists(func_file):
            try:
                os.unlink(func_file)
            except OSError:
                pass


@router.post("/api/causal_chain")
async def causal_chain(req: ReplayInsightRequest):
    """Analyze execution for causal chain."""
    func_file = None
    try:
        module, func, timeline, result, func_file = prepare_execution(
            req.code, req.func_name, req.language,
        )
        steps_data = build_steps_data(timeline)

        from dynamic.semantic.causal_chain import CausalChainEngine
        analysis = CausalChainEngine.analyze(steps_data, block_meta=timeline.block_meta)

        # Build call graph
        call_graph = []
        for evt in timeline.call_events:
            call_graph.append({
                "call_id": evt.call_id,
                "parent_call_id": evt.parent_call_id,
                "function": evt.function_name,
                "args": {k: v["value"] for k, v in evt.args.items()},
                "return_value": evt.return_value["value"] if evt.return_value else None,
                "depth": evt.depth,
                "start_line": evt.start_line,
                "end_line": evt.end_line,
            })

        param_bindings = [
            {"call_id": pb.call_id, "caller_var": pb.caller_var, "callee_param": pb.callee_param, "is_alias": pb.is_alias, "caller_step": pb.caller_step}
            for pb in timeline.parameter_bindings
        ]

        ret_bindings = [
            {"call_id": rb.call_id, "return_step": rb.return_step, "caller_step": rb.caller_step, "assigned_to": rb.assigned_to}
            for rb in timeline.return_bindings
        ]

        data_deps = [
            {"source_step": dd.source_step, "target_step": dd.target_step, "variable": dd.variable, "source_version": dd.source_version, "target_version": dd.target_version, "dependency_type": dd.dependency_type}
            for dd in timeline.data_dependencies
        ]

        # Build PDG and run backward slice
        pdg = RuntimePDG.from_timeline(timeline)
        backward = None
        if timeline.steps:
            last = timeline.steps[-1]
            target_var = last.ast_reads[0] if last.ast_reads else (last.ast_writes[0] if last.ast_writes else '')
            slice_result = pdg.backward_slice(last.step_index, target_var)
            backward = {
                'target_step': last.step_index, 'target_var': target_var,
                'steps': slice_result.steps, 'root_causes': slice_result.root_causes,
                'depth_map': {str(k): v for k, v in slice_result.depth_map.items()},
                'explanation': slice_result.explanation, 'edge_count': len(slice_result.edges),
            }

        return {
            "success": True, "func_name": req.func_name,
            "causal_chain": analysis,
            "block_meta": {str(k): v for k, v in timeline.block_meta.items()},
            "call_graph": call_graph, "parameter_bindings": param_bindings,
            "return_bindings": ret_bindings, "data_dependencies": data_deps,
            "pdg_stats": pdg.stats(), "backward_slice": backward,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        if func_file and os.path.exists(func_file):
            try:
                os.unlink(func_file)
            except OSError:
                pass


@router.post("/api/backward_slice")
async def backward_slice(req: ReplayInsightRequest):
    """Dynamic backward slicing."""
    func_file = None
    try:
        module, func, timeline, result, func_file = prepare_execution(
            req.code, req.func_name, req.language,
        )

        pdg = RuntimePDG.from_timeline(timeline)

        target_step = len(timeline.steps) - 1
        target_var = ''
        if timeline.steps:
            last_step = timeline.steps[-1]
            if last_step.ast_reads:
                target_var = last_step.ast_reads[0]
            elif last_step.ast_writes:
                target_var = last_step.ast_writes[0]

        if ':' in (req.func_name or ''):
            parts = req.func_name.split(':')
            if parts[0].isdigit():
                target_step = int(parts[0])
            if len(parts) > 1:
                target_var = parts[1]

        slice_result = pdg.backward_slice(target_step, target_var)

        steps_data = []
        for step in timeline.steps:
            if step.step_index not in slice_result.steps:
                continue
            var_states = {}
            for name, snap in step.variables.items():
                var_states[name] = {
                    "value": snap.value_repr, "type": snap.value_type,
                    "changed": name in step.changed_vars, "memory_id": snap.memory_id,
                }
            steps_data.append({
                "index": step.step_index, "line": step.line_number,
                "code": step.code_line, "func": step.function_name,
                "vars": var_states, "depth": step.depth, "call_id": step.call_id,
                "ast_reads": step.ast_reads, "ast_writes": step.ast_writes,
                "ssa_versions": step.ssa_versions,
            })

        return {
            "success": True, "func_name": req.func_name,
            "target_step": target_step, "target_var": target_var,
            "slice_steps": slice_result.steps,
            "slice_edges": [{'from': e.source, 'to': e.target, 'var': e.var, 'type': e.kind} for e in slice_result.edges],
            "root_causes": slice_result.root_causes,
            "depth_map": {str(k): v for k, v in slice_result.depth_map.items()},
            "explanation": slice_result.explanation, "steps": steps_data,
            "total_timeline_steps": len(timeline.steps),
            "slice_size": len(slice_result.steps), "pdg_stats": pdg.stats(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        if func_file and os.path.exists(func_file):
            try:
                os.unlink(func_file)
            except OSError:
                pass
