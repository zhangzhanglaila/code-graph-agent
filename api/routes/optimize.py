"""Optimize routes — feedback loop, consolidation, concepts, validation."""

from __future__ import annotations
import os
import sys

from fastapi import APIRouter

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from api.schemas.optimize import ActionOutcomeRequest, PrepareExecutionRequest, ConceptQueryRequest

router = APIRouter()


@router.post("/api/action_outcome")
async def record_action_outcome(req: ActionOutcomeRequest):
    """Record the outcome of applying an action."""
    from dynamic.semantic.narrator import get_feedback_loop, ExecutionMetrics

    feedback_loop = get_feedback_loop()
    pre_metrics = ExecutionMetrics(
        step_count=req.step_count_before,
        time_complexity=req.time_complexity_before,
        invariant_violations=req.invariant_violations_before,
        total_calls=req.total_calls_before,
    )
    post_metrics = ExecutionMetrics(
        step_count=req.step_count_after,
        time_complexity=req.time_complexity_after,
        invariant_violations=req.invariant_violations_after,
        total_calls=req.total_calls_after,
    )

    try:
        execution = feedback_loop.record_outcome(
            execution_id=req.execution_id,
            post_metrics=post_metrics,
            code_after=req.code_after,
            user_feedback=req.user_feedback,
            notes=req.notes,
        )
        return {
            'success': True,
            'execution_id': execution.execution_id,
            'delta_metrics': execution.delta_metrics,
            'memory_summary': feedback_loop.memory.summary(),
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}


@router.get("/api/feedback_loop_status")
async def feedback_loop_status():
    """Get the current state of the feedback loop."""
    from dynamic.semantic.narrator import get_feedback_loop
    feedback_loop = get_feedback_loop()
    return {'success': True, 'summary': feedback_loop.summary()}


@router.post("/api/prepare_execution")
async def prepare_execution(req: PrepareExecutionRequest):
    """Prepare an action for execution tracking."""
    from dynamic.semantic.narrator import get_feedback_loop, Action, ExecutionMetrics

    feedback_loop = get_feedback_loop()
    action = Action(action_type=req.action_type, title=req.action_title, description='')
    pre_metrics = ExecutionMetrics(
        step_count=req.step_count,
        time_complexity=req.time_complexity,
        invariant_violations=req.invariant_violations,
        total_calls=req.total_calls,
    )
    execution_id = feedback_loop.prepare_execution(action=action, pre_metrics=pre_metrics, code_before=req.code_before)
    return {'success': True, 'execution_id': execution_id}


@router.get("/api/consolidation_status")
async def consolidation_status():
    """Get memory consolidation status."""
    from dynamic.semantic.narrator import get_consolidation_engine
    engine = get_consolidation_engine()
    return {'success': True, 'summary': engine.summary()}


@router.post("/api/consolidate")
async def trigger_consolidation():
    """Manually trigger memory consolidation."""
    from dynamic.semantic.narrator import get_consolidation_engine
    engine = get_consolidation_engine()
    engine.consolidate()
    return {'success': True, 'summary': engine.summary()}


@router.post("/api/query_concepts")
async def query_concepts(req: ConceptQueryRequest):
    """Query concept memory for relevant concepts."""
    from dynamic.semantic.narrator import get_consolidation_engine
    engine = get_consolidation_engine()
    context = {}
    if req.action_type:
        context['action_type'] = req.action_type
    if req.tags:
        context['tags'] = req.tags
    concepts = engine.concept_memory.get_relevant(context, top_k=req.top_k)
    return {
        'success': True,
        'concepts': [
            {
                'concept_id': c.concept_id, 'name': c.name, 'description': c.description,
                'pattern': c.pattern, 'action_type': c.action_type, 'confidence': c.confidence,
                'evidence_count': c.evidence_count, 'success_rate': c.success_rate,
                'tags': c.tags, 'use_count': c.use_count,
            }
            for c in concepts
        ],
    }


@router.get("/api/concept_summary")
async def concept_summary():
    """Get concept memory summary."""
    from dynamic.semantic.narrator import get_consolidation_engine
    engine = get_consolidation_engine()
    memory = engine.concept_memory
    top_concepts = sorted(memory.concepts.values(), key=lambda c: c.confidence, reverse=True)[:10]
    return {
        'success': True,
        'summary': memory.summary(),
        'top_concepts': [
            {
                'name': c.name, 'description': c.description, 'confidence': c.confidence,
                'evidence_count': c.evidence_count, 'success_rate': c.success_rate,
            }
            for c in top_concepts
        ],
    }


@router.get("/api/validation_status")
async def validation_status():
    """Get concept validation status."""
    from dynamic.semantic.narrator import get_validation_engine, get_consolidation_engine
    validation_engine = get_validation_engine()
    consolidation_engine = get_consolidation_engine()
    lifecycle_counts = {}
    for concept in consolidation_engine.concept_memory.concepts.values():
        state = getattr(concept, 'lifecycle', 'emerging')
        lifecycle_counts[state] = lifecycle_counts.get(state, 0) + 1
    return {'success': True, 'summary': validation_engine.summary(), 'lifecycle_distribution': lifecycle_counts}


@router.post("/api/validate_concepts")
async def validate_concepts():
    """Manually trigger concept validation."""
    from dynamic.semantic.narrator import get_validation_engine, get_consolidation_engine
    validation_engine = get_validation_engine()
    consolidation_engine = get_consolidation_engine()
    results = validation_engine.validate_all(consolidation_engine.concept_memory, consolidation_engine.experience_buffer)
    return {'success': True, 'results': {k: v.value for k, v in results.items()}, 'summary': validation_engine.summary()}


@router.get("/api/invalid_concepts")
async def invalid_concepts():
    """Get all invalid concepts."""
    from dynamic.semantic.narrator import get_validation_engine
    validation_engine = get_validation_engine()
    invalid = validation_engine.invalidator.get_invalid_concepts()
    return {
        'success': True,
        'invalid_concepts': [
            {
                'concept_id': c.concept_id, 'name': c.name, 'description': c.description,
                'confidence': c.confidence, 'evidence_count': c.evidence_count,
                'success_rate': c.success_rate,
                'reason': validation_engine.invalidator.invalidation_reasons.get(c.concept_id, 'unknown'),
            }
            for c in invalid
        ],
    }


@router.get("/api/validation_history")
async def validation_history(concept_id: str = ''):
    """Get validation history for a concept."""
    from dynamic.semantic.narrator import get_validation_engine
    validation_engine = get_validation_engine()
    if concept_id:
        history = validation_engine.validator.get_validation_history(concept_id)
    else:
        history = validation_engine.validator.validation_history[-50:]
    return {
        'success': True,
        'history': [
            {
                'concept_id': r.concept_id, 'timestamp': r.timestamp,
                'old_state': r.old_state.value, 'new_state': r.new_state.value,
                'reason': r.reason, 'evidence_count': r.evidence_count,
                'success_rate': r.success_rate, 'counter_examples': r.counter_examples,
            }
            for r in history
        ],
    }
