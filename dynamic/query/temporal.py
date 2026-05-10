"""Temporal Query — Time-travel operators for semantic queries.

Extends the query DSL with temporal clauses:

    WHY memo AT step 15          — backward slice from step 15 only
    TRACE a BETWEEN 5..20        — variable history within steps 5-20
    SHOW mutations BEFORE return  — facts before the return statement
    SHOW loops AFTER step 10     — facts after step 10

The PDG already contains all execution data. Temporal operators filter
which nodes/facts are visible to the query, enabling time-travel semantics.

Operators:
    TemporalFilter — filters nodes/facts by temporal predicate
    SnapshotOperator — take a PDG snapshot at a specific step
    WindowOperator — restrict to a step range
"""

from __future__ import annotations
import re
import time
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from .dsl import (
    SemanticQuery, WhyQuery, TraceQuery, ShowQuery, RootsQuery,
    ImpactQuery, ComposedQuery, StatsQuery, parse_query, _parse_single,
)
from .algebra import Operator, LogicalPlan, OpResult, QueryPlanner


# ─── Temporal Predicates ────────────────────────────────────────

@dataclass(frozen=True)
class TemporalPredicate:
    """A temporal constraint on a query."""
    mode: str           # 'at' | 'before' | 'after' | 'between'
    step: int = -1      # for 'at'
    step_a: int = -1    # for 'between' (start)
    step_b: int = -1    # for 'between' (end)
    marker: str = ''    # for 'before'/'after' (e.g., 'return', 'exception', 'loop')

    def describe(self) -> str:
        if self.mode == 'at':
            return f'AT step {self.step}'
        elif self.mode == 'before':
            return f'BEFORE {self.marker or f"step {self.step}"}'
        elif self.mode == 'after':
            return f'AFTER {self.marker or f"step {self.step}"}'
        elif self.mode == 'between':
            return f'BETWEEN {self.step_a}..{self.step_b}'
        return self.mode


@dataclass(frozen=True)
class TemporalQuery(SemanticQuery):
    """A query with temporal constraints."""
    kind: str = 'temporal'
    inner: SemanticQuery = None
    temporal: TemporalPredicate = None


# ─── Temporal Operators ─────────────────────────────────────────

class TemporalFilter(Operator):
    """Filter nodes/facts by temporal predicate."""
    name = 'temporal_filter'

    def __init__(self, predicate: TemporalPredicate):
        self.predicate = predicate

    def execute(self, ctx: OpResult, pdg: Any, facts: list, engine: Any, trace: Any) -> OpResult:
        t0 = time.time()
        original_nodes = len(ctx.nodes)
        original_facts = len(ctx.facts)

        if self.predicate.mode == 'at':
            # Only keep the specific step
            ctx.nodes = [n for n in ctx.nodes if n == self.predicate.step]
            ctx.facts = [f for f in ctx.facts
                         if self.predicate.step in (f.evidence if hasattr(f, 'evidence') else [])]

        elif self.predicate.mode == 'before':
            step = self._resolve_marker(self.predicate.marker, self.predicate.step, pdg)
            if step >= 0:
                ctx.nodes = [n for n in ctx.nodes if n < step]
                ctx.facts = [f for f in ctx.facts
                             if all(e < step for e in (f.evidence if hasattr(f, 'evidence') else []))]

        elif self.predicate.mode == 'after':
            step = self._resolve_marker(self.predicate.marker, self.predicate.step, pdg)
            if step >= 0:
                ctx.nodes = [n for n in ctx.nodes if n > step]
                ctx.facts = [f for f in ctx.facts
                             if any(e > step for e in (f.evidence if hasattr(f, 'evidence') else []))]

        elif self.predicate.mode == 'between':
            a, b = self.predicate.step_a, self.predicate.step_b
            ctx.nodes = [n for n in ctx.nodes if a <= n <= b]
            ctx.facts = [f for f in ctx.facts
                         if any(a <= e <= b for e in (f.evidence if hasattr(f, 'evidence') else []))]

        # Also filter history if present
        if ctx.history:
            if self.predicate.mode == 'at':
                ctx.history = [(sid, vv) for sid, vv in ctx.history if sid == self.predicate.step]
            elif self.predicate.mode == 'before':
                step = self._resolve_marker(self.predicate.marker, self.predicate.step, pdg)
                if step >= 0:
                    ctx.history = [(sid, vv) for sid, vv in ctx.history if sid < step]
            elif self.predicate.mode == 'after':
                step = self._resolve_marker(self.predicate.marker, self.predicate.step, pdg)
                if step >= 0:
                    ctx.history = [(sid, vv) for sid, vv in ctx.history if sid > step]
            elif self.predicate.mode == 'between':
                a, b = self.predicate.step_a, self.predicate.step_b
                ctx.history = [(sid, vv) for sid, vv in ctx.history if a <= sid <= b]

        trace.add('filter', f'Temporal {self.predicate.describe()}: nodes {original_nodes}→{len(ctx.nodes)}, facts {original_facts}→{len(ctx.facts)}',
                   duration_ms=(time.time() - t0) * 1000)
        return ctx

    @staticmethod
    def _resolve_marker(marker: str, fallback: int, pdg) -> int:
        """Resolve a temporal marker to a step number."""
        if fallback >= 0:
            return fallback
        if not marker:
            return -1

        marker_lower = marker.lower()
        # Search for marker in node code
        for nid, node in sorted(pdg.nodes.items()):
            if marker_lower in node.code.lower():
                return nid

        # Special markers
        if marker_lower in ('return', 'end'):
            for nid, node in sorted(pdg.nodes.items(), reverse=True):
                if 'return' in node.code.lower():
                    return nid
        if marker_lower in ('exception', 'error'):
            for nid, node in sorted(pdg.nodes.items()):
                if 'exception' in node.code.lower() or 'error' in node.code.lower():
                    return nid

        return fallback


class SnapshotOperator(Operator):
    """Take a PDG snapshot at a specific step — freeze variable state.

    Unlike TemporalFilter which filters existing results, SnapshotOperator
    captures the variable state at a given step and produces a synthetic
    result showing all variables and their values at that point in time.

    Usage in plan:
        SnapshotOperator(step=15)  → shows variable state at step 15
    """
    name = 'snapshot'

    def __init__(self, step: int):
        self.step = step

    def execute(self, ctx: OpResult, pdg: Any, facts: list, engine: Any, trace: Any) -> OpResult:
        t0 = time.time()

        node = pdg.nodes.get(self.step)
        if not node:
            trace.add('snapshot', f'Snapshot AT {self.step}: step not found',
                       duration_ms=(time.time() - t0) * 1000)
            return ctx

        # Capture variable state at this step
        snapshot = {}
        if hasattr(node, 'vars'):
            for var_name, var_version in node.vars.items():
                snapshot[var_name] = {
                    'value': var_version.value if hasattr(var_version, 'value') else str(var_version),
                    'type': var_version.type if hasattr(var_version, 'type') else '',
                    'version': var_version.version if hasattr(var_version, 'version') else 0,
                }

        # Replace context with snapshot data
        ctx.nodes = [self.step]
        ctx.metadata['snapshot'] = snapshot
        ctx.metadata['snapshot_step'] = self.step
        ctx.metadata['snapshot_code'] = node.code if hasattr(node, 'code') else ''

        trace.add('snapshot', f'Snapshot AT {self.step}: {len(snapshot)} variables captured',
                   duration_ms=(time.time() - t0) * 1000)
        return ctx


class WindowOperator(Operator):
    """Restrict query results to a step range window.

    Similar to TemporalFilter(mode='between'), but as a standalone
    operator that can be composed in any plan position.

    Usage in plan:
        WindowOperator(start=5, end=20)  → only steps 5-20 visible
    """
    name = 'window'

    def __init__(self, start: int = 0, end: int = -1):
        self.start = start
        self.end = end  # -1 means "to the end"

    def execute(self, ctx: OpResult, pdg: Any, facts: list, engine: Any, trace: Any) -> OpResult:
        t0 = time.time()
        original_nodes = len(ctx.nodes)
        original_facts = len(ctx.facts)

        # Determine effective end
        end = self.end if self.end >= 0 else (max(pdg.nodes.keys()) if pdg.nodes else 0)

        # Filter nodes
        ctx.nodes = [n for n in ctx.nodes if self.start <= n <= end]

        # Filter facts
        ctx.facts = [f for f in ctx.facts
                     if any(self.start <= e <= end
                            for e in (f.evidence if hasattr(f, 'evidence') else []))]

        # Filter history
        if ctx.history:
            ctx.history = [(sid, vv) for sid, vv in ctx.history
                           if self.start <= sid <= end]

        # Filter edges
        if ctx.edges:
            ctx.edges = [(s, t, k) for s, t, k in ctx.edges
                         if self.start <= s <= end and self.start <= t <= end]

        ctx.metadata['window_start'] = self.start
        ctx.metadata['window_end'] = end

        trace.add('filter', f'Window [{self.start}..{end}]: nodes {original_nodes}→{len(ctx.nodes)}, facts {original_facts}→{len(ctx.facts)}',
                   duration_ms=(time.time() - t0) * 1000)
        return ctx


# ─── Temporal Parser ────────────────────────────────────────────

_TEMPORAL_PATTERNS = [
    # "SNAPSHOT AT 15" — capture variable state at step 15
    (r'^snapshot\s+at\s+(?:step\s+)?(\d+)$', 'snapshot'),
    # "WHY memo AT step 15"
    (r'^(.+?)\s+at\s+step\s+(\d+)$', 'at'),
    # "WHY memo AT 15"
    (r'^(.+?)\s+at\s+(\d+)$', 'at'),
    # "TRACE a BETWEEN 5..20" or "TRACE a BETWEEN 5 AND 20"
    (r'^(.+?)\s+between\s+(\d+)\s*(?:\.\.|\s+and\s+)\s*(\d+)$', 'between'),
    # "WINDOW 5..20" — restrict to step range
    (r'^window\s+(\d+)\s*(?:\.\.|\s+to\s+)\s*(\d+)$', 'window'),
    # "SHOW mutations BEFORE return"
    (r'^(.+?)\s+before\s+(.+)$', 'before'),
    # "SHOW loops AFTER step 10"
    (r'^(.+?)\s+after\s+step\s+(\d+)$', 'after_step'),
    # "SHOW loops AFTER 10"
    (r'^(.+?)\s+after\s+(\d+)$', 'after_step'),
    # "SHOW loops AFTER for"
    (r'^(.+?)\s+after\s+(\w+)$', 'after_marker'),
]


def parse_temporal_query(text: str) -> Tuple[SemanticQuery, Optional[TemporalPredicate]]:
    """Parse a query with optional temporal clauses.

    Returns (inner_query, temporal_predicate) or (query, None) if no temporal clause.
    """
    text = text.strip()

    for pattern, mode in _TEMPORAL_PATTERNS:
        m = re.match(pattern, text, re.IGNORECASE)
        if not m:
            continue

        if mode == 'snapshot':
            step = int(m.group(1))
            # Snapshot uses a StatsQuery as inner (no real inner query needed)
            from .dsl import StatsQuery
            return StatsQuery(kind='stats'), TemporalPredicate(mode='at', step=step)

        if mode == 'window':
            step_a = int(m.group(1))
            step_b = int(m.group(2))
            from .dsl import ShowQuery
            return ShowQuery(kind='show', pattern='all'), TemporalPredicate(mode='between', step_a=step_a, step_b=step_b)

        inner_text = m.group(1).strip()

        if mode == 'at':
            step = int(m.group(2))
            inner = _parse_single(inner_text)
            return inner, TemporalPredicate(mode='at', step=step)

        elif mode == 'between':
            step_a = int(m.group(2))
            step_b = int(m.group(3))
            inner = _parse_single(inner_text)
            return inner, TemporalPredicate(mode='between', step_a=step_a, step_b=step_b)

        elif mode == 'before':
            marker = m.group(2).strip()
            inner = _parse_single(inner_text)
            if marker.isdigit():
                return inner, TemporalPredicate(mode='before', step=int(marker))
            return inner, TemporalPredicate(mode='before', marker=marker)

        elif mode == 'after_step':
            step = int(m.group(2))
            inner = _parse_single(inner_text)
            return inner, TemporalPredicate(mode='after', step=step)

        elif mode == 'after_marker':
            marker = m.group(2).strip()
            inner = _parse_single(inner_text)
            return inner, TemporalPredicate(mode='after', marker=marker)

    # No temporal clause found
    return _parse_single(text), None


# ─── Temporal Query Planner ────────────────────────────────────

class TemporalQueryPlanner(QueryPlanner):
    """Extends QueryPlanner with temporal operators."""

    def plan_with_temporal(self, query: SemanticQuery, temporal: Optional[TemporalPredicate] = None) -> LogicalPlan:
        """Plan a query, inserting temporal filter if present."""
        base_plan = self.plan(query)

        if temporal is None:
            return base_plan

        # For snapshot: use SnapshotOperator instead of TemporalFilter
        if temporal.mode == 'at' and isinstance(query, StatsQuery):
            return LogicalPlan(
                [SnapshotOperator(step=temporal.step)],
                query_kind=f'snapshot(AT {temporal.step})',
            )

        # For window: use WindowOperator
        if temporal.mode == 'between' and isinstance(query, ShowQuery) and query.pattern == 'all':
            return LogicalPlan(
                [WindowOperator(start=temporal.step_a, end=temporal.step_b),
                 *base_plan.operators],
                query_kind=f'window({temporal.step_a}..{temporal.step_b})',
            )

        # Insert temporal filter after the data-producing operator
        ops = list(base_plan.operators)

        # Find the right insertion point — after traverse/history, before narrate
        insert_idx = len(ops)
        for i, op in enumerate(ops):
            if op.name == 'narrate':
                insert_idx = i
                break

        ops.insert(insert_idx, TemporalFilter(temporal))

        return LogicalPlan(ops, query_kind=f'{base_plan.query_kind}+temporal({temporal.describe()})')
