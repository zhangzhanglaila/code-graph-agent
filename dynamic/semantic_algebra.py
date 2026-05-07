"""Semantic Algebra — Composable operators over RuntimePDG + Facts.

Every query decomposes into a pipeline of primitive operators:

    SelectNodes → Traverse → Filter → GroupBy → Sort → Limit → Narrate

    WHY memo      = SelectNodes(var=memo) → Traverse(backward,data) → Narrate(slice)
    TRACE a       = SelectNodes(var=a) → CollectHistory → Narrate(variable)
    SHOW loops    = SelectFacts(kind=loop.*) → Filter → Sort → Limit
    ROOTS memo    = SelectNodes(var=memo) → Traverse(backward,data) → Filter(is_root)
    IMPACT arr    = SelectNodes(var=arr) → Traverse(forward,data) → Narrate(impact)
    COMPARE 5 10  = SelectNodes(step=5,10) → CompareNodes
    STATS         = ComputeStats

The QueryPlanner converts a SemanticQuery AST into a LogicalPlan (operator DAG).
The PlanExecutor runs the plan and records a QueryTrace.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .query_dsl import (
    SemanticQuery, WhyQuery, TraceQuery, ImpactQuery, ShowQuery,
    RootsQuery, CompareQuery, StatsQuery, HelpQuery, ComposedQuery,
    QueryTrace,
)


# ─── Logical Operators ──────────────────────────────────────────

@dataclass
class OpResult:
    """Carries data through the operator pipeline."""
    nodes: List[int] = field(default_factory=list)          # step IDs
    edges: List[Tuple[int, int, str]] = field(default_factory=list)  # (src, tgt, kind)
    facts: List[Any] = field(default_factory=list)          # SemanticFact objects
    history: List[Tuple[int, Any]] = field(default_factory=list)  # (step, VarVersion)
    narrative: Any = None                                    # Narrative object
    diffs: List[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    root_causes: List[int] = field(default_factory=list)
    depth_map: Dict[int, int] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d: dict = {'success': True}
        if self.nodes:
            d['steps'] = self.nodes
        if self.edges:
            d['edge_count'] = len(self.edges)
        if self.facts:
            d['facts'] = [f.to_dict() if hasattr(f, 'to_dict') else f for f in self.facts]
            d['count'] = len(self.facts)
        if self.history:
            d['history'] = [
                {'step': sid, 'version': vv.version, 'value': vv.value, 'type': vv.type}
                for sid, vv in self.history
            ]
            d['versions'] = len(self.history)
        if self.narrative:
            d['narrative'] = self.narrative.to_dict() if hasattr(self.narrative, 'to_dict') else self.narrative
            d['text'] = self.narrative.to_text() if hasattr(self.narrative, 'to_text') else ''
        if self.diffs:
            d['diffs'] = self.diffs
            d['diff_count'] = len(self.diffs)
        if self.stats:
            d['pdg'] = self.stats
        if self.root_causes:
            d['root_causes'] = self.root_causes
        if self.depth_map:
            d['depth_map'] = {str(k): v for k, v in self.depth_map.items()}
        d.update(self.metadata)
        return d


class Operator:
    """Base class for logical operators."""
    name: str = 'base'

    def execute(self, ctx: OpResult, pdg: Any, facts: list, engine: Any, trace: QueryTrace) -> OpResult:
        raise NotImplementedError


class SelectNodes(Operator):
    """Select starting nodes from the PDG."""
    name = 'select_nodes'

    def __init__(self, var: str = '', step: int = -1, code_pattern: str = ''):
        self.var = var
        self.step = step
        self.code_pattern = code_pattern

    def execute(self, ctx, pdg, facts, engine, trace):
        t0 = time.time()
        nodes = []

        if self.step >= 0:
            if self.step in pdg.nodes:
                nodes = [self.step]
        elif self.var:
            for nid, node in sorted(pdg.nodes.items()):
                if self.var in node.ast_reads or self.var in node.ast_writes:
                    nodes.append(nid)
            # If no direct match, search code
            if not nodes:
                for nid, node in sorted(pdg.nodes.items()):
                    if self.var.lower() in node.code.lower():
                        nodes.append(nid)
        elif self.code_pattern:
            for nid, node in sorted(pdg.nodes.items()):
                if self.code_pattern in node.code:
                    nodes.append(nid)

        # Default: last node
        if not nodes and pdg.nodes:
            last = max(pdg.nodes.keys())
            nodes = [last]

        trace.add('select', f'Selected {len(nodes)} nodes (var={self.var!r}, step={self.step})',
                   duration_ms=(time.time() - t0) * 1000)
        ctx.nodes = nodes
        return ctx


class SelectFacts(Operator):
    """Select facts matching a pattern."""
    name = 'select_facts'

    def __init__(self, pattern: str = 'all', limit: int = 20):
        self.pattern = pattern.lower()
        self.limit = limit

    def execute(self, ctx, pdg, facts, engine, trace):
        t0 = time.time()
        matched = []
        for fact in facts:
            if self.pattern == 'all':
                matched.append(fact)
            elif self.pattern in fact.kind or self.pattern in fact.description.lower() or self.pattern in fact.subject.lower():
                matched.append(fact)
        ctx.facts = matched[:self.limit]
        ctx.metadata['total'] = len(facts)
        trace.add('select', f'Selected {len(ctx.facts)}/{len(facts)} facts (pattern={self.pattern!r})',
                   duration_ms=(time.time() - t0) * 1000)
        return ctx


class Traverse(Operator):
    """Walk the PDG graph."""
    name = 'traverse'

    def __init__(self, direction: str = 'backward', edge_kind: str = 'data'):
        self.direction = direction
        self.edge_kind = edge_kind

    def execute(self, ctx, pdg, facts, engine, trace):
        t0 = time.time()
        if not ctx.nodes:
            return ctx

        # Use the LAST selected node as target (most recent write)
        target = ctx.nodes[-1]
        node = pdg.nodes.get(target)
        var = ''
        if node:
            var = node.ast_reads[0] if node.ast_reads else (node.ast_writes[0] if node.ast_writes else '')

        if self.direction == 'backward':
            sr = pdg.backward_slice(target, var)
            ctx.nodes = sr.steps
            ctx.edges = [(e.source, e.target, e.kind) for e in sr.edges]
            ctx.root_causes = sr.root_causes
            ctx.depth_map = sr.depth_map
            ctx.metadata['target_step'] = target
            ctx.metadata['target_var'] = var
        else:
            impact = pdg.forward_impact(target, var)
            ctx.nodes = impact.steps
            ctx.edges = [(e.source, e.target, e.kind) for e in impact.edges]
            ctx.root_causes = impact.root_causes
            ctx.metadata['source_step'] = target
            ctx.metadata['source_var'] = var

        trace.add('traverse', f'{self.direction} traverse: {len(ctx.nodes)} nodes, {len(ctx.edges)} edges',
                   duration_ms=(time.time() - t0) * 1000)
        return ctx


class CollectHistory(Operator):
    """Collect variable version history."""
    name = 'collect_history'

    def __init__(self, var: str = ''):
        self.var = var

    def execute(self, ctx, pdg, facts, engine, trace):
        t0 = time.time()
        ctx.history = pdg.get_variable_history(self.var)
        ctx.metadata['variable'] = self.var
        trace.add('traverse', f'Variable history: {len(ctx.history)} versions',
                   duration_ms=(time.time() - t0) * 1000)
        return ctx


class FilterNodes(Operator):
    """Filter nodes by predicate."""
    name = 'filter_nodes'

    def __init__(self, predicate: str = 'is_root', value: Any = None):
        self.predicate = predicate
        self.value = value

    def execute(self, ctx, pdg, facts, engine, trace):
        t0 = time.time()
        original = len(ctx.nodes)

        if self.predicate == 'is_root':
            ctx.nodes = [n for n in ctx.nodes if n in ctx.root_causes]
        elif self.predicate == 'depth_gt':
            ctx.nodes = [n for n in ctx.nodes if ctx.depth_map.get(n, 0) > (self.value or 0)]
        elif self.predicate == 'depth_lt':
            ctx.nodes = [n for n in ctx.nodes if ctx.depth_map.get(n, 0) < (self.value or 0)]

        trace.add('filter', f'Filter({self.predicate}): {original} → {len(ctx.nodes)} nodes',
                   duration_ms=(time.time() - t0) * 1000)
        return ctx


class FilterFacts(Operator):
    """Filter facts by field predicate."""
    name = 'filter_facts'

    def __init__(self, field: str = '', op: str = '>', value: Any = None):
        self.field = field
        self.op = op
        self.value = value

    def execute(self, ctx, pdg, facts, engine, trace):
        t0 = time.time()
        original = len(ctx.facts)
        filtered = []
        for fact in ctx.facts:
            d = fact.to_dict() if hasattr(fact, 'to_dict') else fact
            val = d.get(self.field) or d.get('metadata', {}).get(self.field)
            if val is None:
                if self.field == 'evidence':
                    val = len(d.get('evidence', []))
                else:
                    continue
            if self._cmp(val, self.op, self.value):
                filtered.append(fact)
        ctx.facts = filtered
        trace.add('filter', f'FilterFacts({self.field} {self.op} {self.value}): {original} → {len(filtered)}',
                   duration_ms=(time.time() - t0) * 1000)
        return ctx

    @staticmethod
    def _cmp(a, op, b):
        try:
            if op == '>': return a > b
            if op == '<': return a < b
            if op == '>=': return a >= b
            if op == '<=': return a <= b
            if op == '==': return a == b
            if op == '!=': return a != b
            if op == 'contains': return str(b).lower() in str(a).lower()
        except TypeError:
            return False
        return False


class Sort(Operator):
    """Sort results by field."""
    name = 'sort'

    def __init__(self, field: str = '', desc: bool = False):
        self.field = field
        self.desc = desc

    def execute(self, ctx, pdg, facts, engine, trace):
        if ctx.facts:
            ctx.facts.sort(
                key=lambda f: (f.to_dict() if hasattr(f, 'to_dict') else f).get(self.field, 0),
                reverse=self.desc,
            )
        if ctx.history:
            ctx.history.sort(key=lambda h: getattr(h[1], self.field, 0) if hasattr(h[1], self.field) else 0, reverse=self.desc)
        return ctx


class Limit(Operator):
    """Limit result count."""
    name = 'limit'

    def __init__(self, n: int = 20):
        self.n = n

    def execute(self, ctx, pdg, facts, engine, trace):
        ctx.facts = ctx.facts[:self.n]
        ctx.nodes = ctx.nodes[:self.n]
        ctx.history = ctx.history[:self.n]
        return ctx


class CompareNodes(Operator):
    """Compare two execution nodes."""
    name = 'compare'

    def __init__(self, step_a: int = -1, step_b: int = -1, var: str = ''):
        self.step_a = step_a
        self.step_b = step_b
        self.var = var

    def execute(self, ctx, pdg, facts, engine, trace):
        t0 = time.time()
        node_a = pdg.nodes.get(self.step_a)
        node_b = pdg.nodes.get(self.step_b)
        if not node_a or not node_b:
            ctx.metadata['error'] = 'One or both steps not found'
            return ctx

        diffs = []
        all_vars = set(node_a.vars.keys()) | set(node_b.vars.keys())
        for var in sorted(all_vars):
            va, vb = node_a.vars.get(var), node_b.vars.get(var)
            if va and vb:
                if va.value != vb.value or va.version != vb.version:
                    diffs.append({'var': var, 'a_value': va.value, 'b_value': vb.value,
                                  'a_version': va.version, 'b_version': vb.version, 'type': 'changed'})
            elif va:
                diffs.append({'var': var, 'a_value': va.value, 'b_value': None, 'type': 'removed'})
            elif vb:
                diffs.append({'var': var, 'a_value': None, 'b_value': vb.value, 'type': 'added'})

        ctx.diffs = diffs
        ctx.metadata['step_a'] = self.step_a
        ctx.metadata['step_b'] = self.step_b
        ctx.metadata['code_a'] = node_a.code
        ctx.metadata['code_b'] = node_b.code
        trace.add('select', f'Compared: {len(diffs)} diffs', duration_ms=(time.time() - t0) * 1000)
        return ctx


class ComputeStats(Operator):
    """Compute graph statistics."""
    name = 'stats'

    def execute(self, ctx, pdg, facts, engine, trace):
        t0 = time.time()
        ctx.stats = pdg.stats()
        ctx.stats['facts_count'] = len(facts)
        ctx.stats['fact_kinds'] = list(set(f.kind for f in facts))
        trace.add('select', 'Computed stats', duration_ms=(time.time() - t0) * 1000)
        return ctx


class Narrate(Operator):
    """Generate narrative from current context."""
    name = 'narrate'

    def __init__(self, mode: str = 'slice'):
        self.mode = mode  # 'slice' | 'variable' | 'impact' | 'roots'

    def execute(self, ctx, pdg, facts, engine, trace):
        t0 = time.time()

        if self.mode == 'slice' and ctx.nodes:
            from .pdg import SliceResult
            sr = SliceResult(
                target_step=ctx.metadata.get('target_step', ctx.nodes[0] if ctx.nodes else 0),
                target_var=ctx.metadata.get('target_var', ''),
                steps=ctx.nodes,
                edges=[],
                root_causes=ctx.root_causes,
                depth_map=ctx.depth_map,
                explanation=[],
            )
            ctx.narrative = engine.explain_backward_slice(sr)
        elif self.mode == 'variable':
            var = ctx.metadata.get('variable', '')
            ctx.narrative = engine.explain_variable(var)
        elif self.mode == 'impact' and ctx.nodes:
            from .pdg import SliceResult
            sr = SliceResult(
                target_step=ctx.metadata.get('source_step', ctx.nodes[0] if ctx.nodes else 0),
                target_var=ctx.metadata.get('source_var', ''),
                steps=ctx.nodes,
                edges=[],
                root_causes=ctx.root_causes,
                depth_map=ctx.depth_map,
                explanation=[],
            )
            ctx.narrative = engine.explain_impact(sr)

        n_segs = len(ctx.narrative.segments) if ctx.narrative and hasattr(ctx.narrative, 'segments') else 0
        trace.add('narrate', f'Generated narrative: {n_segs} segments',
                   duration_ms=(time.time() - t0) * 1000)
        return ctx


# ─── Logical Plan ───────────────────────────────────────────────

class LogicalPlan:
    """A pipeline of operators to execute against PDG + Facts + Engine."""

    def __init__(self, operators: List[Operator], query_kind: str = ''):
        self.operators = operators
        self.query_kind = query_kind

    def execute(self, pdg: Any, facts: list, engine: Any, trace: QueryTrace) -> OpResult:
        ctx = OpResult()
        for op in self.operators:
            ctx = op.execute(ctx, pdg, facts, engine, trace)
        ctx.metadata['query'] = self.query_kind
        return ctx

    def describe(self) -> List[str]:
        """Human-readable pipeline description."""
        return [f'{op.name}({", ".join(f"{k}={v}" for k, v in op.__dict__.items() if v and k != "name")})'
                for op in self.operators]


# ─── Query Planner ─────────────────────────────────────────────

class QueryPlanner:
    """Converts a SemanticQuery AST into a LogicalPlan.

    This is the core of the Semantic Algebra — every query type decomposes
    into the same primitive operators over the PDG.
    """

    def plan(self, query: SemanticQuery) -> LogicalPlan:
        if isinstance(query, ComposedQuery):
            return self._plan_composed(query)
        elif isinstance(query, WhyQuery):
            return self._plan_why(query)
        elif isinstance(query, TraceQuery):
            return self._plan_trace(query)
        elif isinstance(query, ImpactQuery):
            return self._plan_impact(query)
        elif isinstance(query, ShowQuery):
            return self._plan_show(query)
        elif isinstance(query, RootsQuery):
            return self._plan_roots(query)
        elif isinstance(query, CompareQuery):
            return self._plan_compare(query)
        elif isinstance(query, StatsQuery):
            return self._plan_stats(query)
        elif isinstance(query, HelpQuery):
            return LogicalPlan([], query_kind='help')
        else:
            return LogicalPlan([], query_kind='unknown')

    def _plan_why(self, q: WhyQuery) -> LogicalPlan:
        ops = [
            SelectNodes(var=q.target, step=q.target_step),
            Traverse(direction='backward', edge_kind='data'),
            Narrate(mode='slice'),
        ]
        return LogicalPlan(ops, query_kind='why')

    def _plan_trace(self, q: TraceQuery) -> LogicalPlan:
        ops = [
            CollectHistory(var=q.variable),
            Narrate(mode='variable'),
        ]
        return LogicalPlan(ops, query_kind='trace')

    def _plan_impact(self, q: ImpactQuery) -> LogicalPlan:
        ops = [
            SelectNodes(var=q.source, step=q.source_step),
            Traverse(direction='forward', edge_kind='data'),
            Narrate(mode='impact'),
        ]
        return LogicalPlan(ops, query_kind='impact')

    def _plan_show(self, q: ShowQuery) -> LogicalPlan:
        ops = [
            SelectFacts(pattern=q.pattern, limit=q.limit),
        ]
        return LogicalPlan(ops, query_kind='show')

    def _plan_roots(self, q: RootsQuery) -> LogicalPlan:
        ops = [
            SelectNodes(var=q.target, step=q.target_step),
            Traverse(direction='backward', edge_kind='data'),
            FilterNodes(predicate='is_root'),
        ]
        return LogicalPlan(ops, query_kind='roots')

    def _plan_compare(self, q: CompareQuery) -> LogicalPlan:
        ops = [
            CompareNodes(step_a=q.step_a, step_b=q.step_b, var=q.var),
        ]
        return LogicalPlan(ops, query_kind='compare')

    def _plan_stats(self, q: StatsQuery) -> LogicalPlan:
        return LogicalPlan([ComputeStats()], query_kind='stats')

    def _plan_composed(self, q: ComposedQuery) -> LogicalPlan:
        plan1 = self.plan(q.first)
        plan2 = self.plan(q.second)

        ops = list(plan1.operators) + list(plan2.operators)

        # Insert filter after the second plan's data-producing operator
        if q.where_field:
            ops.append(FilterFacts(field=q.where_field, op=q.where_op, value=q.where_value))

        if q.order_by:
            ops.append(Sort(field=q.order_by, desc=q.order_desc))

        return LogicalPlan(ops, query_kind=f'composed({plan1.query_kind}→{plan2.query_kind})')
