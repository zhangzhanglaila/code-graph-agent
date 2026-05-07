"""Layer 2+3: Narrative Planning + Natural Language Realization.

Takes semantic facts and produces human-readable explanations.

Layer 2 — Narrative Planning:
    Decides WHAT to say and in WHAT ORDER.
    Plans a narrative structure (not just dumping facts).

Layer 3 — Natural Language Realization:
    Converts planned narrative into fluent text.
    Uses templates + variable evolution data.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict


@dataclass
class NarrativeSegment:
    """One segment of a planned narrative."""
    role: str           # 'setup' | 'flow' | 'branch' | 'loop' | 'result' | 'root_cause'
    heading: str        # short heading for this segment
    content: str        # the narrative text
    facts: List[int]    # indices into the facts list
    priority: int = 0   # lower = more important

    def to_dict(self) -> dict:
        return {
            'role': self.role,
            'heading': self.heading,
            'content': self.content,
            'priority': self.priority,
        }


@dataclass
class Narrative:
    """A complete explanation narrative."""
    title: str
    summary: str                    # one-line summary
    segments: List[NarrativeSegment]
    variable_stories: List[dict]    # per-variable evolution stories
    metadata: dict = field(default_factory=dict)

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


class NarrativeEngine:
    """Plans and generates explanations from semantic facts + PDG.

    Usage:
        engine = NarrativeEngine(pdg, facts)
        narrative = engine.explain_backward_slice(slice_result)
    """

    def __init__(self, pdg, facts):
        self.pdg = pdg
        self.facts = facts
        self._fact_by_kind: Dict[str, list] = defaultdict(list)
        for i, f in enumerate(facts):
            self._fact_by_kind[f.kind].append((i, f))

    # ─── Main entry points ────────────────────────────────────────

    def explain_backward_slice(self, slice_result) -> Narrative:
        """Generate a narrative explaining a backward slice."""
        target_node = self.pdg.nodes.get(slice_result.target_step)
        if not target_node:
            return Narrative(
                title="Explanation",
                summary="No target step found.",
                segments=[],
                variable_stories=[],
            )

        # Layer 2: Plan the narrative structure
        segments = []

        # 1. Setup: what is the target?
        segments.append(self._plan_target(target_node, slice_result.target_var))

        # 2. Root causes
        root_facts = self._fact_by_kind.get('causal.root_cause', [])
        if slice_result.root_causes:
            segments.append(self._plan_root_causes(slice_result.root_causes))

        # 3. Data flow story
        data_segments = self._plan_data_flow(slice_result)
        segments.extend(data_segments)

        # 4. Loop story (if any)
        loop_segments = self._plan_loop_story(slice_result)
        segments.extend(loop_segments)

        # 5. Control flow story
        control_segments = self._plan_control_story(slice_result)
        segments.extend(control_segments)

        # 6. Result
        segments.append(self._plan_result(target_node, slice_result))

        # Layer 3: Realize variable evolution stories
        variable_stories = self._realize_variable_stories(slice_result)

        # Generate summary
        summary = self._realize_summary(target_node, slice_result)

        return Narrative(
            title=f"Why does `{target_node.code}` produce its value?",
            summary=summary,
            segments=segments,
            variable_stories=variable_stories,
            metadata={
                'target_step': slice_result.target_step,
                'slice_size': len(slice_result.steps),
                'root_causes': slice_result.root_causes,
            },
        )

    def explain_variable(self, var_name: str) -> Narrative:
        """Generate a narrative explaining a variable's evolution."""
        history = self.pdg.get_variable_history(var_name)
        chain = self.pdg.get_version_chain(var_name)

        if not history:
            return Narrative(
                title=f"Variable: {var_name}",
                summary=f"No history found for `{var_name}`.",
                segments=[],
                variable_stories=[],
            )

        segments = []

        # Setup
        first_step, first_vv = history[0]
        segments.append(NarrativeSegment(
            role='setup',
            heading='Origin',
            content=f"`{var_name}` is first defined at step #{first_step} with value `{first_vv.value}`.",
            facts=[],
            priority=0,
        ))

        # Evolution
        if len(history) > 1:
            story = self._build_evolution_story(var_name, history)
            segments.append(NarrativeSegment(
                role='flow',
                heading='Evolution',
                content=story,
                facts=[],
                priority=1,
            ))

        # Last value
        last_step, last_vv = history[-1]
        segments.append(NarrativeSegment(
            role='result',
            heading='Final Value',
            content=f"`{var_name}` ends at step #{last_step} with value `{last_vv.value}` (version #{last_vv.version}).",
            facts=[],
            priority=2,
        ))

        return Narrative(
            title=f"Variable: {var_name}",
            summary=f"`{var_name}` evolves through {len(history)} versions.",
            segments=segments,
            variable_stories=[{
                'name': var_name,
                'story': self._build_evolution_story(var_name, history),
                'versions': len(history),
                'first_value': first_vv.value,
                'last_value': last_vv.value,
            }],
        )

    def explain_impact(self, impact_result) -> Narrative:
        """Generate a narrative explaining forward impact."""
        source_node = self.pdg.nodes.get(impact_result.target_step)
        if not source_node:
            return Narrative(
                title="Impact Analysis",
                summary="No source step found.",
                segments=[],
                variable_stories=[],
            )

        segments = []

        # Setup
        segments.append(NarrativeSegment(
            role='setup',
            heading='Source',
            content=f"The analysis starts at step #{impact_result.target_step}: `{source_node.code}`",
            facts=[],
            priority=0,
        ))

        # Impact flow
        data_edges = [e for e in impact_result.edges if e.kind == 'data']
        if data_edges:
            flow_lines = []
            for edge in sorted(data_edges, key=lambda e: impact_result.depth_map.get(e.target, 0))[:8]:
                src = self.pdg.nodes.get(edge.source)
                tgt = self.pdg.nodes.get(edge.target)
                if src and tgt:
                    flow_lines.append(f"  `{src.code}` → `{tgt.code}` via `{edge.var}`")
            segments.append(NarrativeSegment(
                role='flow',
                heading='Data Flow',
                content='\n'.join(flow_lines),
                facts=[],
                priority=1,
            ))

        # Affected outputs
        leaves = impact_result.root_causes  # leaf nodes in forward
        if leaves:
            leaf_lines = []
            for lid in leaves[:5]:
                node = self.pdg.nodes.get(lid)
                if node:
                    leaf_lines.append(f"  #{lid}: `{node.code}`")
            segments.append(NarrativeSegment(
                role='result',
                heading='Affected Outputs',
                content='\n'.join(leaf_lines),
                facts=[],
                priority=2,
            ))

        return Narrative(
            title=f"Impact: `{source_node.code}`",
            summary=f"This step affects {len(impact_result.steps)} downstream steps.",
            segments=segments,
            variable_stories=[],
        )

    # ─── Planning helpers ─────────────────────────────────────────

    def _plan_target(self, node, var: str) -> NarrativeSegment:
        code = node.code.strip()
        if var:
            content = f"We want to understand why `{var}` has its value at step #{node.id}: `{code}`"
        else:
            content = f"We want to understand what determines the result of step #{node.id}: `{code}`"
        return NarrativeSegment(
            role='setup',
            heading='Target',
            content=content,
            facts=[],
            priority=0,
        )

    def _plan_root_causes(self, root_causes: list) -> NarrativeSegment:
        lines = []
        for rid in sorted(root_causes)[:5]:
            node = self.pdg.nodes.get(rid)
            if node:
                lines.append(f"  #{rid}: `{node.code}` (line {node.line})")
        content = "The root causes of this value are:\n" + '\n'.join(lines)
        return NarrativeSegment(
            role='root_cause',
            heading='Root Causes',
            content=content,
            facts=[],
            priority=1,
        )

    def _plan_data_flow(self, slice_result) -> List[NarrativeSegment]:
        """Plan data flow narrative segments."""
        segments = []
        data_edges = [e for e in slice_result.edges if e.kind == 'data']
        if not data_edges:
            return segments

        # Group by variable
        by_var: Dict[str, list] = defaultdict(list)
        for edge in data_edges:
            by_var[edge.var].append(edge)

        for var, edges in by_var.items():
            if len(edges) < 2:
                continue
            chain = sorted(edges, key=lambda e: e.target)
            first_src = self.pdg.nodes.get(chain[0].source)
            last_tgt = self.pdg.nodes.get(chain[-1].target)
            if first_src and last_tgt:
                segments.append(NarrativeSegment(
                    role='flow',
                    heading=f'Data Flow: {var}',
                    content=self._describe_data_chain(var, chain),
                    facts=[],
                    priority=3,
                ))

        return segments

    def _plan_loop_story(self, slice_result) -> List[NarrativeSegment]:
        """Plan loop-related narrative segments."""
        segments = []
        loop_facts = self._fact_by_kind.get('loop.iteration', [])
        accum_facts = self._fact_by_kind.get('loop.accumulation', [])

        for idx, fact in loop_facts:
            # Check if this loop is in the slice
            if any(s in slice_result.steps for s in fact.evidence):
                segments.append(NarrativeSegment(
                    role='loop',
                    heading='Loop',
                    content=fact.description,
                    facts=[idx],
                    priority=4,
                ))

        for idx, fact in accum_facts:
            if any(s in slice_result.steps for s in fact.evidence):
                segments.append(NarrativeSegment(
                    role='loop',
                    heading=f'Accumulation: {fact.subject}',
                    content=fact.description,
                    facts=[idx],
                    priority=5,
                ))

        return segments

    def _plan_control_story(self, slice_result) -> List[NarrativeSegment]:
        """Plan control flow narrative segments."""
        segments = []
        control_edges = [e for e in slice_result.edges if e.kind == 'control']
        if not control_edges:
            return segments

        seen_conditions = set()
        for edge in control_edges:
            if edge.source not in seen_conditions:
                seen_conditions.add(edge.source)
                cond_node = self.pdg.nodes.get(edge.source)
                if cond_node:
                    segments.append(NarrativeSegment(
                        role='branch',
                        heading='Control',
                        content=f"The condition `{cond_node.code.strip()}` (step #{edge.source}) controls the execution path.",
                        facts=[],
                        priority=6,
                    ))

        return segments

    def _plan_result(self, node, slice_result) -> NarrativeSegment:
        content = f"The final result at step #{node.id} is determined by {len(slice_result.steps)} preceding steps."
        return NarrativeSegment(
            role='result',
            heading='Result',
            content=content,
            facts=[],
            priority=10,
        )

    # ─── Realization helpers ──────────────────────────────────────

    def _realize_variable_stories(self, slice_result) -> List[dict]:
        """Generate per-variable evolution stories for the slice."""
        stories = []
        # Find variables involved in the slice
        vars_in_slice: Set[str] = set()
        for edge in slice_result.edges:
            if edge.kind == 'data' and edge.var:
                vars_in_slice.add(edge.var)

        for var in sorted(vars_in_slice):
            history = self.pdg.get_variable_history(var)
            # Filter to steps in the slice
            slice_history = [(sid, vv) for sid, vv in history if sid in slice_result.steps]
            if len(slice_history) >= 2:
                stories.append({
                    'name': var,
                    'story': self._build_evolution_story(var, slice_history),
                    'versions': len(slice_history),
                    'first_value': slice_history[0][1].value,
                    'last_value': slice_history[-1][1].value,
                })

        return stories

    def _build_evolution_story(self, var: str, history: list) -> str:
        """Build a narrative for a variable's evolution."""
        if len(history) < 2:
            return f"`{var}` has a single value: {history[0][1].value}"

        values = []
        for sid, vv in history:
            node = self.pdg.nodes.get(sid)
            code = node.code if node else '?'
            values.append(f"v{vv.version}=`{vv.value}`")

        if len(values) <= 4:
            chain_str = ' → '.join(values)
        else:
            chain_str = f"{values[0]} → ... → {values[-1]}"

        return f"`{var}` evolves: {chain_str} ({len(values)} versions)"

    def _describe_data_chain(self, var: str, chain: list) -> str:
        """Describe a chain of data flow edges for a variable."""
        if len(chain) == 1:
            edge = chain[0]
            src = self.pdg.nodes.get(edge.source)
            tgt = self.pdg.nodes.get(edge.target)
            if src and tgt:
                return f"`{var}` flows from `{src.code}` to `{tgt.code}`"

        lines = [f"`{var}` flows through {len(chain)} steps:"]
        for edge in chain[:5]:
            src = self.pdg.nodes.get(edge.source)
            tgt = self.pdg.nodes.get(edge.target)
            if src and tgt:
                lines.append(f"  `{src.code}` → `{tgt.code}`")
        if len(chain) > 5:
            lines.append(f"  ... ({len(chain) - 5} more)")
        return '\n'.join(lines)

    def _realize_summary(self, node, slice_result) -> str:
        """Generate a one-line summary."""
        var = slice_result.target_var
        n_roots = len(slice_result.root_causes)
        n_steps = len(slice_result.steps)

        root_verb = 'are' if n_roots != 1 else 'is'
        root_suffix = 's' if n_roots != 1 else ''
        if var:
            return (
                f"`{var}` at step #{node.id} is determined by {n_steps} steps. "
                f"The root cause{root_suffix} {root_verb} {n_roots} source{root_suffix}."
            )
        return f"Step #{node.id} depends on {n_steps} steps with {n_roots} root cause{root_suffix}."
