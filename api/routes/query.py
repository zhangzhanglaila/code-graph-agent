"""Query routes — unified query API with temporal support."""

from __future__ import annotations
import os
import sys

from fastapi import APIRouter, Depends

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from dynamic.query.dsl import parse_query
from dynamic.query.temporal import parse_temporal_query, TemporalQuery
from dynamic.query.protocol import QueryEnvelope, QueryResponse
from dynamic.query.remote import RemoteQueryHandler
from dynamic.query.execution_metrics import execution_metrics
from dynamic.semantic.identity import SemanticIdentifier
from dynamic.semantic.identity_normalizer import IdentityNormalizer
from dynamic.semantic.fingerprint import SemanticFingerprint

from api.services.analysis import prepare_execution
from api.schemas.query import QueryRequest
from api.container import get_container, AppContainer

router = APIRouter()


@router.post("/api/query")
async def unified_query(req: QueryRequest, container: AppContainer = Depends(get_container)):
    """Unified query endpoint — supports both structured and NL queries."""
    func_file = None
    try:
        module, func, timeline, result, func_file = prepare_execution(
            req.code, req.func_name, req.language,
        )

        with execution_metrics.stage('pipeline_build'):
            pipeline = container.build_pipeline(timeline)
        pdg, facts, engine, executor = pipeline.pdg, pipeline.facts, pipeline.engine, pipeline.executor

        # Natural language query via text field
        if req.text:
            inner, temporal = parse_temporal_query(req.text)
            if temporal:
                parsed = TemporalQuery(kind='temporal', inner=inner, temporal=temporal, raw=req.text)
            else:
                parsed = inner
            result = executor.execute(parsed)
            identities = SemanticIdentifier.identify(pdg, facts)
            normal_form = IdentityNormalizer.normalize(identities, pdg)
            fingerprint = SemanticFingerprint.generate(pdg, facts)
            result['identities'] = identities.to_dict()
            result['fingerprint'] = fingerprint.to_dict()
            return result

        qtype = req.query.get('type', '')

        if qtype == 'backward_slice':
            target_step = req.query.get('target_step', len(timeline.steps) - 1)
            target_var = req.query.get('target_var', '')
            if not target_var and timeline.steps:
                last = timeline.steps[target_step] if target_step < len(timeline.steps) else timeline.steps[-1]
                target_var = last.ast_reads[0] if last.ast_reads else ''
            sr = pdg.backward_slice(target_step, target_var)
            narrative = engine.explain_backward_slice(sr)
            return {
                "success": True, "type": "backward_slice",
                "target_step": target_step, "target_var": target_var,
                "steps": sr.steps, "root_causes": sr.root_causes,
                "depth_map": {str(k): v for k, v in sr.depth_map.items()},
                "edge_count": len(sr.edges), "narrative": narrative.to_dict(),
                "pdg_stats": pdg.stats(),
            }

        elif qtype == 'forward_impact':
            source_step = req.query.get('source_step', 0)
            source_var = req.query.get('source_var', '')
            sr = pdg.forward_impact(source_step, source_var)
            narrative = engine.explain_impact(sr)
            return {
                "success": True, "type": "forward_impact",
                "source_step": source_step, "source_var": source_var,
                "steps": sr.steps, "leaf_nodes": sr.root_causes,
                "depth_map": {str(k): v for k, v in sr.depth_map.items()},
                "narrative": narrative.to_dict(),
            }

        elif qtype == 'explain_variable':
            var = req.query.get('var', '')
            narrative = engine.explain_variable(var)
            return {
                "success": True, "type": "explain_variable", "var": var,
                "narrative": narrative.to_dict(),
                "history": [
                    {"step": sid, "version": vv.version, "value": vv.value, "type": vv.type}
                    for sid, vv in pdg.get_variable_history(var)
                ],
            }

        elif qtype == 'explain_slice':
            target_step = req.query.get('target_step', len(timeline.steps) - 1)
            target_var = req.query.get('target_var', '')
            if not target_var and timeline.steps:
                last = timeline.steps[target_step] if target_step < len(timeline.steps) else timeline.steps[-1]
                target_var = last.ast_reads[0] if last.ast_reads else ''
            sr = pdg.backward_slice(target_step, target_var)
            narrative = engine.explain_backward_slice(sr)
            return {"success": True, "type": "explain_slice", "narrative": narrative.to_dict(), "text": narrative.to_text()}

        elif qtype == 'facts':
            return {"success": True, "type": "facts", "facts": [f.to_dict() for f in facts], "count": len(facts)}

        elif qtype == 'stats':
            return {
                "success": True, "type": "stats", "pdg": pdg.stats(),
                "timeline_steps": len(timeline.steps),
                "data_dependencies": len(timeline.data_dependencies),
            }

        elif qtype == 'variable_history':
            var = req.query.get('var', '')
            history = pdg.get_variable_history(var)
            return {
                "success": True, "type": "variable_history", "var": var,
                "history": [
                    {"step": sid, "version": vv.version, "value": vv.value, "type": vv.type, "memory_id": vv.memory_id}
                    for sid, vv in history
                ],
            }

        elif qtype == 'version_chain':
            var = req.query.get('var', '')
            chain = pdg.get_version_chain(var)
            return {
                "success": True, "type": "version_chain", "var": var,
                "chain": [
                    {"source": e.source, "target": e.target, "source_version": e.source_version, "target_version": e.target_version}
                    for e in chain
                ],
            }

        else:
            return {"success": False, "error": f"Unknown query type: {qtype}"}

    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        if func_file and os.path.exists(func_file):
            try:
                os.unlink(func_file)
            except OSError:
                pass


@router.post("/api/query/remote")
async def remote_query(envelope_dict: dict, container: AppContainer = Depends(get_container)):
    """Remote query execution endpoint.

    Accepts a QueryEnvelope (JSON), executes through the full
    plan → optimize → execute pipeline, returns QueryResponse.

    Used by RemoteQueryClient for distributed execution.
    """
    func_file = None
    try:
        envelope = QueryEnvelope.from_dict(envelope_dict)

        code = envelope.params.get('code', '')
        if not code:
            return QueryResponse.error_response('No code in params').to_dict()

        module, func, timeline, result, func_file = prepare_execution(
            code, envelope.params.get('func_name', ''),
            envelope.params.get('language', 'python'),
        )

        pipeline = container.build_pipeline(timeline)
        handler = RemoteQueryHandler(pipeline.pdg, pipeline.facts, pipeline.engine)
        response = handler.handle(envelope)
        return response.to_dict()

    except Exception as e:
        return QueryResponse.error_response(str(e)).to_dict()
    finally:
        if func_file and os.path.exists(func_file):
            try:
                os.unlink(func_file)
            except OSError:
                pass
