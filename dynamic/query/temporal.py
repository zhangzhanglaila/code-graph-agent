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
    ImpactQuery, ComposedQuery, parse_query, _parse_single,
)
from .algebra import Operator, LogicalPlan, OpResult, QueryPlanner


# ─── Temporal Predicates ────────────────────────────────────────

@dataclass
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


@dataclass
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


# ─── Temporal Parser ────────────────────────────────────────────

_TEMPORAL_PATTERNS = [
    # "WHY memo AT step 15"
    (r'^(.+?)\s+at\s+step\s+(\d+)$', 'at'),
    # "WHY memo AT 15"
    (r'^(.+?)\s+at\s+(\d+)$', 'at'),
    # "TRACE a BETWEEN 5..20" or "TRACE a BETWEEN 5 AND 20"
    (r'^(.+?)\s+between\s+(\d+)\s*(?:\.\.|\s+and\s+)\s*(\d+)$', 'between'),
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
