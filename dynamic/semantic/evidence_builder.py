"""Evidence Builder — converts QueryResult into graph-free EvidenceCollection.

This module has ZERO references to PDG/model/runtime.
It consumes only SemanticQueryResult types (BackwardSliceResult, etc.)
which carry pre-resolved step data.

Usage:
    evidence = build_backward_slice_evidence(slice_result, facts)
    evidence = build_variable_evidence(trace_result)
    evidence = build_impact_evidence(impact_result, facts)
"""

from __future__ import annotations
from collections import defaultdict
from typing import Any, Dict, List, Set

from dynamic.semantic.evidence import (
    ResolvedStep, DataFlowChain, ControlCondition,
    VariableEvolution, FactEvidence, EvidenceCollection,
)
from dynamic.semantic.query_result import (
    BackwardSliceResult, ForwardImpactResult, VariableTraceResult,
    ResolvedStepInfo,
)


def _make_step(step_id: int, resolved: Dict[int, ResolvedStepInfo]) -> ResolvedStep:
    """Create a ResolvedStep from pre-resolved data."""
    info = resolved.get(step_id)
    if info:
        return ResolvedStep(id=step_id, code=info.code, line=info.line)
    return ResolvedStep(id=step_id, code='', line=0)


def build_backward_slice_evidence(result: BackwardSliceResult, facts: list) -> EvidenceCollection:
    """Build evidence from a BackwardSliceResult."""
    resolved = result.resolved_steps
    var = result.target_var

    # Target
    target = _make_step(result.target_step, resolved)

    # Root causes
    root_causes = [_make_step(rid, resolved) for rid in (result.root_causes or [])[:5]]

    # Data flows — group edges by variable
    data_edges = [e for e in (result.edges or []) if e.kind == 'data']
    by_var: Dict[str, list] = defaultdict(list)
    for edge in data_edges:
        by_var[edge.var].append(edge)

    data_flows = []
    for v, edges in by_var.items():
        if len(edges) < 2:
            continue
        chain = sorted(edges, key=lambda e: e.target)
        steps = []
        seen = set()
        for edge in chain:
            if edge.source not in seen:
                steps.append(_make_step(edge.source, resolved))
                seen.add(edge.source)
            if edge.target not in seen:
                steps.append(_make_step(edge.target, resolved))
                seen.add(edge.target)
        data_flows.append(DataFlowChain(variable=v, steps=steps))

    # Control conditions
    control_edges = [e for e in (result.edges or []) if e.kind == 'control']
    seen_conditions = set()
    control_conditions = []
    for edge in control_edges:
        if edge.source not in seen_conditions:
            seen_conditions.add(edge.source)
            cond = _make_step(edge.source, resolved)
            if cond.code:
                control_conditions.append(ControlCondition(
                    condition_step=cond,
                    description=f"The condition `{cond.code.strip()}` (step #{edge.source}) controls the execution path.",
                ))

    # Loop facts
    steps_set = set(result.steps or [])
    loop_facts = _extract_facts_by_kind(facts, 'loop.iteration', steps_set)
    accumulation_facts = _extract_facts_by_kind(facts, 'loop.accumulation', steps_set)

    # Variable evolutions
    variable_evolutions = _build_variable_evolutions_from_edges(result, facts)

    return EvidenceCollection(
        kind='backward_slice',
        target=target,
        target_var=var,
        root_causes=root_causes,
        data_flows=data_flows,
        control_conditions=control_conditions,
        variable_evolutions=variable_evolutions,
        loop_facts=loop_facts,
        accumulation_facts=accumulation_facts,
        step_count=len(result.steps or []),
        root_cause_count=len(result.root_causes or []),
        metadata={
            'target_step': result.target_step,
            'slice_size': len(result.steps or []),
            'root_causes': list(result.root_causes or []),
        },
    )


def build_variable_evidence(result: VariableTraceResult) -> EvidenceCollection:
    """Build evidence from a VariableTraceResult."""
    var_name = result.variable
    history = result.history

    if not history:
        return EvidenceCollection(
            kind='variable',
            target_var=var_name,
            variable_evolutions=[],
            step_count=0,
            metadata={'variable': var_name, 'versions': 0},
        )

    target = ResolvedStep(id=history[0][0], code='', line=0)

    versions = []
    for step_id, vv in history:
        versions.append({
            'step_id': step_id,
            'value': str(getattr(vv, 'value', '')),
            'version': getattr(vv, 'version', 0),
        })

    evolutions = [VariableEvolution(variable=var_name, versions=versions)]

    return EvidenceCollection(
        kind='variable',
        target=target,
        target_var=var_name,
        variable_evolutions=evolutions,
        step_count=len(history),
        metadata={'variable': var_name, 'versions': len(history)},
    )


def build_impact_evidence(result: ForwardImpactResult, facts: list = None) -> EvidenceCollection:
    """Build evidence from a ForwardImpactResult."""
    resolved = result.resolved_steps
    source = _make_step(result.target_step, resolved)

    # Impact flows
    data_edges = [e for e in (result.edges or []) if e.kind == 'data']
    impact_flows = []
    if data_edges:
        sorted_edges = sorted(data_edges, key=lambda e: result.depth_map.get(e.target, 0))[:8]
        steps = []
        seen = set()
        for edge in sorted_edges:
            if edge.source not in seen:
                steps.append(_make_step(edge.source, resolved))
                seen.add(edge.source)
            if edge.target not in seen:
                steps.append(_make_step(edge.target, resolved))
                seen.add(edge.target)
        if steps:
            impact_flows.append(DataFlowChain(variable='', steps=steps))

    # Affected outputs
    affected_outputs = [_make_step(lid, resolved) for lid in (result.root_causes or [])[:5]]

    return EvidenceCollection(
        kind='impact',
        target=source,
        impact_flows=impact_flows,
        affected_outputs=affected_outputs,
        step_count=len(result.steps or []),
        metadata={
            'source_step': result.target_step,
            'impact_size': len(result.steps or []),
        },
    )


# ── Helpers ──────────────────────────────────────────────────────

def _extract_facts_by_kind(facts, kind: str, steps: set) -> List[FactEvidence]:
    """Extract facts of a given kind that relate to the given steps."""
    result = []
    for i, fact in enumerate(facts):
        if getattr(fact, 'kind', '') == kind:
            if any(s in steps for s in getattr(fact, 'evidence', [])):
                result.append(FactEvidence(
                    index=i,
                    kind=fact.kind,
                    subject=getattr(fact, 'subject', ''),
                    description=getattr(fact, 'description', ''),
                    evidence_steps=list(getattr(fact, 'evidence', [])),
                ))
    return result


def _build_variable_evolutions_from_edges(result: BackwardSliceResult, facts: list) -> List[VariableEvolution]:
    """Build variable evolution evidence from a BackwardSliceResult.

    Extracts variable names from data-flow edges and builds version chains
    from the edge's source_version/target_version fields.
    """
    edges = result.edges or []
    data_edges = [e for e in edges if e.kind == 'data' and e.var]

    # Group edges by variable
    by_var: Dict[str, list] = defaultdict(list)
    for edge in data_edges:
        by_var[edge.var].append(edge)

    evolutions = []
    for var, var_edges in by_var.items():
        # Build version chain from edges
        versions = []
        seen = set()
        # Sort by target step to get chronological order
        sorted_edges = sorted(var_edges, key=lambda e: e.target)
        for edge in sorted_edges:
            # Source version
            src_key = (edge.source, edge.source_version)
            if src_key not in seen:
                seen.add(src_key)
                info = result.resolved_steps.get(edge.source)
                versions.append({
                    'step_id': edge.source,
                    'value': info.code.strip() if info and info.code else '',
                    'version': edge.source_version,
                })
            # Target version
            tgt_key = (edge.target, edge.target_version)
            if tgt_key not in seen:
                seen.add(tgt_key)
                info = result.resolved_steps.get(edge.target)
                versions.append({
                    'step_id': edge.target,
                    'value': info.code.strip() if info and info.code else '',
                    'version': edge.target_version,
                })

        if versions:
            evolutions.append(VariableEvolution(variable=var, versions=versions))

    return evolutions
