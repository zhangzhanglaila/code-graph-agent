"""Evidence Builder — the ONLY module that touches the semantic model.

Converts model + query results into graph-free EvidenceCollection objects.
After this, all downstream consumers (Planner, Renderer) are graph-free.

Usage:
    evidence = build_backward_slice_evidence(model, facts, slice_result)
    evidence = build_variable_evidence(model, 'x')
    evidence = build_impact_evidence(model, impact_result)
"""

from __future__ import annotations
from collections import defaultdict
from typing import Any, Dict, List, Set

from dynamic.semantic.evidence import (
    ResolvedStep, DataFlowChain, ControlCondition,
    VariableEvolution, FactEvidence, EvidenceCollection,
)


def _resolve_node(model, node_id: int) -> ResolvedStep:
    """Resolve a node ID to a ResolvedStep. The single graph access point."""
    node = model.nodes.get(node_id)
    if node:
        return ResolvedStep(id=node_id, code=node.code, line=node.line)
    return ResolvedStep(id=node_id, code='', line=0)


def build_backward_slice_evidence(model, facts, slice_result) -> EvidenceCollection:
    """Build evidence from a backward slice query result."""
    # Target
    target = _resolve_node(model, slice_result.target_step)
    var = getattr(slice_result, 'target_var', '')

    # Root causes
    root_causes = [_resolve_node(model, rid) for rid in (slice_result.root_causes or [])[:5]]

    # Data flows — group edges by variable
    data_edges = [e for e in (slice_result.edges or []) if getattr(e, 'kind', '') == 'data']
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
                steps.append(_resolve_node(model, edge.source))
                seen.add(edge.source)
            if edge.target not in seen:
                steps.append(_resolve_node(model, edge.target))
                seen.add(edge.target)
        data_flows.append(DataFlowChain(variable=v, steps=steps))

    # Control conditions
    control_edges = [e for e in (slice_result.edges or []) if getattr(e, 'kind', '') == 'control']
    seen_conditions = set()
    control_conditions = []
    for edge in control_edges:
        if edge.source not in seen_conditions:
            seen_conditions.add(edge.source)
            cond = _resolve_node(model, edge.source)
            if cond.code:
                control_conditions.append(ControlCondition(
                    condition_step=cond,
                    description=f"The condition `{cond.code.strip()}` (step #{edge.source}) controls the execution path.",
                ))

    # Loop facts
    loop_facts = _extract_facts_by_kind(facts, 'loop.iteration', slice_result.steps)
    accumulation_facts = _extract_facts_by_kind(facts, 'loop.accumulation', slice_result.steps)

    # Variable evolutions
    variable_evolutions = _build_variable_evolutions(model, slice_result)

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
        step_count=len(slice_result.steps or []),
        root_cause_count=len(slice_result.root_causes or []),
        metadata={
            'target_step': slice_result.target_step,
            'slice_size': len(slice_result.steps or []),
            'root_causes': list(slice_result.root_causes or []),
        },
    )


def build_variable_evidence(model, var_name: str) -> EvidenceCollection:
    """Build evidence from a variable history query."""
    history = model.get_variable_history(var_name)

    target = None
    if history:
        first_step, first_vv = history[0]
        target = ResolvedStep(id=first_step, code='', line=0)

    # Build evolution
    versions = []
    for step_id, vv in history:
        versions.append({
            'step_id': step_id,
            'value': str(getattr(vv, 'value', '')),
            'version': getattr(vv, 'version', 0),
        })

    evolutions = []
    if versions:
        evolutions.append(VariableEvolution(variable=var_name, versions=versions))

    return EvidenceCollection(
        kind='variable',
        target=target,
        target_var=var_name,
        variable_evolutions=evolutions,
        step_count=len(history),
        metadata={'variable': var_name, 'versions': len(history)},
    )


def build_impact_evidence(model, impact_result) -> EvidenceCollection:
    """Build evidence from a forward impact query result."""
    source = _resolve_node(model, impact_result.target_step)

    # Impact flows
    data_edges = [e for e in (impact_result.edges or []) if getattr(e, 'kind', '') == 'data']
    impact_flows = []
    if data_edges:
        sorted_edges = sorted(data_edges, key=lambda e: impact_result.depth_map.get(e.target, 0))[:8]
        steps = []
        seen = set()
        for edge in sorted_edges:
            if edge.source not in seen:
                steps.append(_resolve_node(model, edge.source))
                seen.add(edge.source)
            if edge.target not in seen:
                steps.append(_resolve_node(model, edge.target))
                seen.add(edge.target)
        if steps:
            impact_flows.append(DataFlowChain(variable='', steps=steps))

    # Affected outputs
    affected_outputs = [_resolve_node(model, lid) for lid in (impact_result.root_causes or [])[:5]]

    return EvidenceCollection(
        kind='impact',
        target=source,
        impact_flows=impact_flows,
        affected_outputs=affected_outputs,
        step_count=len(impact_result.steps or []),
        metadata={
            'source_step': impact_result.target_step,
            'impact_size': len(impact_result.steps or []),
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


def _build_variable_evolutions(model, slice_result) -> List[VariableEvolution]:
    """Build variable evolution evidence for a backward slice."""
    evolutions = []
    vars_in_slice: Set[str] = set()
    for edge in (slice_result.edges or []):
        if getattr(edge, 'kind', '') == 'data' and edge.var:
            vars_in_slice.add(edge.var)

    for var in sorted(vars_in_slice):
        history = model.get_variable_history(var)
        slice_history = [(sid, vv) for sid, vv in history if sid in (slice_result.steps or set())]
        if len(slice_history) >= 2:
            versions = []
            for sid, vv in slice_history:
                versions.append({
                    'step_id': sid,
                    'value': str(getattr(vv, 'value', '')),
                    'version': getattr(vv, 'version', 0),
                })
            evolutions.append(VariableEvolution(variable=var, versions=versions))

    return evolutions
