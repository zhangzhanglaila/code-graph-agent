"""Narrative View Layer — Planner + Renderer + backward-compat facade.

Architecture:
    NarrativePlanner — consumes EvidenceCollection, outputs ExplanationIR (graph-free)
    NarrativeRenderer — converts ExplanationIR → Narrative (zero graph access)
    NarrativeEngine — facade that builds evidence + delegates to Planner + Renderer

Narrative does NOT own semantics. It only consumes semantic results.
"""

from __future__ import annotations
from typing import Any, Dict, List, Set

from dynamic.semantic.evidence import EvidenceCollection, DataFlowChain, ResolvedStep
from dynamic.semantic.explanation import EvidenceUnit, ExplanationIR


# ── Legacy output types (kept for backward compatibility) ────────

class NarrativeSegment:
    """One segment of a planned narrative."""
    __slots__ = ('role', 'heading', 'content', 'facts', 'priority')

    def __init__(self, role: str, heading: str, content: str, facts: list, priority: int = 0):
        self.role = role
        self.heading = heading
        self.content = content
        self.facts = facts
        self.priority = priority

    def to_dict(self) -> dict:
        return {
            'role': self.role,
            'heading': self.heading,
            'content': self.content,
            'priority': self.priority,
        }


class Narrative:
    """A complete explanation narrative."""
    __slots__ = ('title', 'summary', 'segments', 'variable_stories', 'metadata')

    def __init__(self, title: str, summary: str, segments: list, variable_stories: list, metadata: dict = None):
        self.title = title
        self.summary = summary
        self.segments = segments
        self.variable_stories = variable_stories
        self.metadata = metadata or {}

    def to_dict(self) -> dict:
        return {
            'title': self.title,
            'summary': self.summary,
            'segments': [s.to_dict() for s in self.segments],
            'variable_stories': self.variable_stories,
            'metadata': self.metadata,
        }

    def to_text(self) -> str:
        """Render as plain text."""
        lines = [self.title, '=' * len(self.title), '', self.summary, '']
        for seg in sorted(self.segments, key=lambda s: s.priority):
            if seg.heading:
                lines.append(f"## {seg.heading}")
            lines.append(seg.content)
            lines.append('')
        if self.variable_stories:
            lines.append("## Variable Stories")
            for vs in self.variable_stories:
                lines.append(f"  {vs['name']}: {vs['story']}")
            lines.append('')
        return '\n'.join(lines)


# ── Planner: EvidenceCollection → ExplanationIR (graph-free) ─────

class NarrativePlanner:
    """Selects and organizes evidence into ExplanationIR.

    ZERO graph/model references. Consumes only EvidenceCollection.
    """

    def plan_backward_slice(self, evidence: EvidenceCollection) -> ExplanationIR:
        """Plan explanation for a backward slice."""
        units: List[EvidenceUnit] = []
        uid = 0
        target = evidence.target

        if not target or not target.code:
            return ExplanationIR(
                title="Explanation",
                summary="No target step found.",
                units=[],
                variable_stories=[],
            )

        var = evidence.target_var

        # 1. Target
        if var:
            desc = f"We want to understand why `{var}` has its value at step #{target.id}: `{target.code}`"
        else:
            desc = f"We want to understand what determines the result of step #{target.id}: `{target.code}`"
        units.append(EvidenceUnit(
            id=f"eu-{uid}", kind='target', heading='Target', description=desc,
            step_ids=[target.id], variables=[var] if var else [],
        ))
        uid += 1

        # 2. Root causes
        if evidence.root_causes:
            lines = []
            for rc in evidence.root_causes:
                if rc.code:
                    lines.append(f"  #{rc.id}: `{rc.code}` (line {rc.line})")
            if lines:
                units.append(EvidenceUnit(
                    id=f"eu-{uid}", kind='root_cause', heading='Root Causes',
                    description="The root causes of this value are:\n" + '\n'.join(lines),
                    step_ids=[rc.id for rc in evidence.root_causes],
                ))
                uid += 1

        # 3. Data flows
        for flow in evidence.data_flows:
            desc = self._describe_data_flow(flow)
            units.append(EvidenceUnit(
                id=f"eu-{uid}", kind='data_flow', heading=f'Data Flow: {flow.variable}',
                description=desc, variables=[flow.variable],
                step_ids=[s.id for s in flow.steps],
            ))
            uid += 1

        # 4. Loop facts
        for fact in evidence.loop_facts:
            units.append(EvidenceUnit(
                id=f"eu-{uid}", kind='loop', heading='Loop',
                description=fact.description, evidence_facts=[fact.index],
                step_ids=fact.evidence_steps,
            ))
            uid += 1
        for fact in evidence.accumulation_facts:
            units.append(EvidenceUnit(
                id=f"eu-{uid}", kind='loop', heading=f'Accumulation: {fact.subject}',
                description=fact.description, evidence_facts=[fact.index],
                step_ids=fact.evidence_steps,
            ))
            uid += 1

        # 5. Control conditions
        for cond in evidence.control_conditions:
            if cond.description:
                units.append(EvidenceUnit(
                    id=f"eu-{uid}", kind='branch', heading='Control',
                    description=cond.description,
                    step_ids=[cond.condition_step.id],
                ))
                uid += 1

        # 6. Result
        units.append(EvidenceUnit(
            id=f"eu-{uid}", kind='result', heading='Result',
            description=f"The final result at step #{target.id} is determined by {evidence.step_count} preceding steps.",
            step_ids=[target.id],
        ))

        # Variable stories
        variable_stories = self._build_variable_stories(evidence.variable_evolutions)

        # Summary
        n_roots = evidence.root_cause_count
        n_steps = evidence.step_count
        root_verb = 'are' if n_roots != 1 else 'is'
        root_suffix = 's' if n_roots != 1 else ''
        if var:
            summary = (
                f"`{var}` at step #{target.id} is determined by {n_steps} steps. "
                f"The root cause{root_suffix} {root_verb} {n_roots} source{root_suffix}."
            )
        else:
            summary = f"Step #{target.id} depends on {n_steps} steps with {n_roots} root cause{root_suffix}."

        return ExplanationIR(
            title=f"Why does `{target.code}` produce its value?",
            summary=summary,
            units=units,
            variable_stories=variable_stories,
            metadata=evidence.metadata,
        )

    def plan_variable(self, evidence: EvidenceCollection) -> ExplanationIR:
        """Plan explanation for a variable's evolution."""
        var_name = evidence.target_var
        if not evidence.variable_evolutions:
            return ExplanationIR(
                title=f"Variable: {var_name}",
                summary=f"No history found for `{var_name}`.",
                units=[],
                variable_stories=[],
            )

        evo = evidence.variable_evolutions[0]
        versions = evo.versions
        if not versions:
            return ExplanationIR(
                title=f"Variable: {var_name}",
                summary=f"No history found for `{var_name}`.",
                units=[],
                variable_stories=[],
            )

        units: List[EvidenceUnit] = []
        uid = 0
        first = versions[0]
        last = versions[-1]

        # Origin
        units.append(EvidenceUnit(
            id=f"eu-{uid}", kind='variable_origin', heading='Origin',
            description=f"`{var_name}` is first defined at step #{first['step_id']} with value `{first['value']}`.",
            step_ids=[first['step_id']], variables=[var_name],
        ))
        uid += 1

        # Evolution
        if len(versions) > 1:
            story = self._build_evolution_story_from_versions(var_name, versions)
            units.append(EvidenceUnit(
                id=f"eu-{uid}", kind='variable_evolution', heading='Evolution',
                description=story, variables=[var_name],
                step_ids=[v['step_id'] for v in versions],
            ))
            uid += 1

        # Final value
        units.append(EvidenceUnit(
            id=f"eu-{uid}", kind='variable_final', heading='Final Value',
            description=f"`{var_name}` ends at step #{last['step_id']} with value `{last['value']}` (version #{last['version']}).",
            step_ids=[last['step_id']], variables=[var_name],
        ))

        return ExplanationIR(
            title=f"Variable: {var_name}",
            summary=f"`{var_name}` evolves through {len(versions)} versions.",
            units=units,
            variable_stories=[{
                'name': var_name,
                'story': self._build_evolution_story_from_versions(var_name, versions),
                'versions': len(versions),
                'first_value': first['value'],
                'last_value': last['value'],
            }],
        )

    def plan_impact(self, evidence: EvidenceCollection) -> ExplanationIR:
        """Plan explanation for forward impact analysis."""
        source = evidence.target
        if not source or not source.code:
            return ExplanationIR(
                title="Impact Analysis",
                summary="No source step found.",
                units=[],
                variable_stories=[],
            )

        units: List[EvidenceUnit] = []
        uid = 0

        # Source
        units.append(EvidenceUnit(
            id=f"eu-{uid}", kind='source', heading='Source',
            description=f"The analysis starts at step #{source.id}: `{source.code}`",
            step_ids=[source.id],
        ))
        uid += 1

        # Impact flows
        for flow in evidence.impact_flows:
            lines = []
            for step in flow.steps:
                lines.append(f"  `{step.code}`")
            if lines:
                units.append(EvidenceUnit(
                    id=f"eu-{uid}", kind='impact_flow', heading='Data Flow',
                    description='\n'.join(lines),
                    step_ids=[s.id for s in flow.steps],
                ))
                uid += 1

        # Affected outputs
        if evidence.affected_outputs:
            leaf_lines = []
            for step in evidence.affected_outputs:
                if step.code:
                    leaf_lines.append(f"  #{step.id}: `{step.code}`")
            if leaf_lines:
                units.append(EvidenceUnit(
                    id=f"eu-{uid}", kind='affected_output', heading='Affected Outputs',
                    description='\n'.join(leaf_lines),
                    step_ids=[s.id for s in evidence.affected_outputs],
                ))

        return ExplanationIR(
            title=f"Impact: `{source.code}`",
            summary=f"This step affects {evidence.step_count} downstream steps.",
            units=units,
            variable_stories=[],
        )

    # ── Internal helpers (all operate on evidence, no graph) ─────

    def _build_variable_stories(self, evolutions) -> List[dict]:
        """Build variable stories from VariableEvolution evidence."""
        stories = []
        for evo in evolutions:
            if len(evo.versions) < 2:
                continue
            story = self._build_evolution_story_from_versions(evo.variable, evo.versions)
            stories.append({
                'name': evo.variable,
                'story': story,
                'versions': len(evo.versions),
                'first_value': evo.versions[0]['value'],
                'last_value': evo.versions[-1]['value'],
            })
        return stories

    def _build_evolution_story_from_versions(self, var: str, versions: list) -> str:
        """Build evolution narrative from version dicts."""
        if len(versions) < 2:
            return f"`{var}` has a single value: {versions[0]['value']}"

        values = [f"v{v['version']}=`{v['value']}`" for v in versions]
        if len(values) <= 4:
            chain_str = ' → '.join(values)
        else:
            chain_str = f"{values[0]} → ... → {values[-1]}"
        return f"`{var}` evolves: {chain_str} ({len(values)} versions)"

    def _describe_data_flow(self, flow: DataFlowChain) -> str:
        """Describe a data flow chain."""
        steps = flow.steps
        if len(steps) == 1:
            return f"`{flow.variable}` is at `{steps[0].code}`"
        if len(steps) == 2:
            return f"`{flow.variable}` flows from `{steps[0].code}` to `{steps[1].code}`"

        lines = [f"`{flow.variable}` flows through {len(steps)} steps:"]
        for step in steps[:5]:
            lines.append(f"  `{step.code}`")
        if len(steps) > 5:
            lines.append(f"  ... ({len(steps) - 5} more)")
        return '\n'.join(lines)


# ── Renderer: ExplanationIR → Narrative (zero graph access) ──────

class NarrativeRenderer:
    """Converts ExplanationIR into Narrative objects.

    ZERO references to model/graph/pdg.
    Only operates on pre-resolved data in ExplanationIR.
    """

    def render(self, ir: ExplanationIR) -> Narrative:
        """Render ExplanationIR into a Narrative."""
        segments = []
        for unit in ir.units:
            segments.append(NarrativeSegment(
                role=unit.kind,
                heading=unit.heading,
                content=unit.description,
                facts=unit.evidence_facts,
                priority=unit.priority,
            ))
        return Narrative(
            title=ir.title,
            summary=ir.summary,
            segments=segments,
            variable_stories=ir.variable_stories,
            metadata=ir.metadata,
        )

    def render_text(self, ir: ExplanationIR) -> str:
        """Render ExplanationIR as plain text."""
        narrative = self.render(ir)
        return narrative.to_text()


# ── Facade: backward-compatible NarrativeEngine ─────────────────

class NarrativeEngine:
    """Plans and generates explanations from semantic data.

    Backward-compatible facade — same API as before.
    Uses SemanticQueryEngine to produce typed results,
    then EvidenceBuilder → Planner → Renderer pipeline.

    Usage:
        engine = NarrativeEngine(model, facts)
        narrative = engine.explain_backward_slice(slice_result)

        # Or with pre-built PDG (avoids re-derivation):
        engine = NarrativeEngine(model, facts, pdg=pdg)
    """

    def __init__(self, model, facts, pdg=None):
        self._facts = facts
        self._planner = NarrativePlanner()
        self._renderer = NarrativeRenderer()

        # Build the query engine — the single entry point for all queries
        from dynamic.semantic.query_engine import SemanticQueryEngine
        if pdg is not None:
            self._query_engine = SemanticQueryEngine(pdg, model, facts)
        else:
            # Derive pdg from model (model has .nodes/.edges which are SemanticNode/SemanticEdge)
            # We need the original RuntimePDG, so we use model directly for query
            self._query_engine = SemanticQueryEngine(model, model, facts)

    @property
    def planner(self) -> NarrativePlanner:
        return self._planner

    @property
    def renderer(self) -> NarrativeRenderer:
        return self._renderer

    @property
    def query_engine(self):
        return self._query_engine

    def explain_backward_slice(self, slice_result) -> Narrative:
        """Explain a backward slice. Accepts either SliceResult or BackwardSliceResult."""
        from dynamic.semantic.evidence_builder import build_backward_slice_evidence, build_variable_evidence
        from dynamic.semantic.query_result import BackwardSliceResult

        # If already a BackwardSliceResult, use directly; otherwise wrap via engine
        if isinstance(slice_result, BackwardSliceResult):
            result = slice_result
        else:
            result = self._query_engine.backward_slice(
                step=slice_result.target_step,
                variable=getattr(slice_result, 'target_var', ''),
            )
        evidence = build_backward_slice_evidence(result, self._facts)

        # Enrich with full variable histories for variables found in edges
        edge_vars = set()
        for edge in (result.edges or []):
            if edge.var:
                edge_vars.add(edge.var)
        if result.target_var:
            edge_vars.add(result.target_var)

        for var in edge_vars:
            try:
                trace_result = self._query_engine.variable_trace(var)
                var_evidence = build_variable_evidence(trace_result)
                if var_evidence.variable_evolutions:
                    evidence.variable_evolutions.extend(var_evidence.variable_evolutions)
            except Exception:
                pass  # Variable may not exist in PDG

        ir = self._planner.plan_backward_slice(evidence)
        return self._renderer.render(ir)

    def explain_variable(self, var_name: str) -> Narrative:
        """Explain a variable's evolution."""
        from dynamic.semantic.evidence_builder import build_variable_evidence
        result = self._query_engine.variable_trace(var_name)
        evidence = build_variable_evidence(result)
        ir = self._planner.plan_variable(evidence)
        return self._renderer.render(ir)

    def explain_impact(self, impact_result) -> Narrative:
        """Explain forward impact. Accepts either SliceResult or ForwardImpactResult."""
        from dynamic.semantic.evidence_builder import build_impact_evidence
        from dynamic.semantic.query_result import ForwardImpactResult

        if isinstance(impact_result, ForwardImpactResult):
            result = impact_result
        else:
            result = self._query_engine.forward_impact(
                step=impact_result.target_step,
                variable=getattr(impact_result, 'target_var', ''),
            )
        evidence = build_impact_evidence(result, self._facts)
        ir = self._planner.plan_impact(evidence)
        return self._renderer.render(ir)
