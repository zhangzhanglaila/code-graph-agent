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

from .dsl import (
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
        # Projection: only include requested fields
        project = self.metadata.get('project_fields')
        if project:
            project_set = set(project)
            if self.facts and 'facts' in project_set:
                d['facts'] = [self._project_fact(f, project_set) for f in self.facts]
                d['count'] = len(self.facts)
            if self.nodes and ('steps' in project_set or 'nodes' in project_set):
                d['steps'] = self.nodes
            if self.history and 'history' in project_set:
                d['history'] = [
                    self._project_history(sid, vv, project_set)
                    for sid, vv in self.history
                ]
                d['versions'] = len(self.history)
            if self.narrative and 'narrative' in project_set:
                d['narrative'] = self.narrative.to_dict() if hasattr(self.narrative, 'to_dict') else self.narrative
                d['text'] = self.narrative.to_text() if hasattr(self.narrative, 'to_text') else ''
            if self.root_causes and 'root_causes' in project_set:
                d['root_causes'] = self.root_causes
            if self.depth_map and 'depth_map' in project_set:
                d['depth_map'] = {str(k): v for k, v in self.depth_map.items()}
            if self.stats and 'stats' in project_set:
                d['pdg'] = self.stats
            d['projected'] = True
        else:
            # Full materialization (no projection)
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

    @staticmethod
    def _project_fact(fact, fields: set) -> dict:
        """Project a fact to only requested fields."""
        d = fact.to_dict() if hasattr(fact, 'to_dict') else fact
        if not fields or fields == {'facts'}:
            return d
        return {k: v for k, v in d.items() if k in fields}

    @staticmethod
    def _project_history(step_id, vv, fields: set) -> dict:
        """Project a history entry to only requested fields."""
        full = {'step': step_id, 'version': vv.version, 'value': vv.value, 'type': vv.type}
        if not fields or fields == {'history'}:
            return full
        return {k: v for k, v in full.items() if k in fields}


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
    """Select facts matching a pattern, with optional predicate pushdown.

    When filter_field/filter_op/filter_value are set, filtering happens
    DURING selection — not as a separate post-pass. This is predicate
    pushdown in physical execution.
    """
    name = 'select_facts'

    def __init__(self, pattern: str = 'all', limit: int = 20,
                 filter_field: str = '', filter_op: str = '', filter_value: Any = None):
        self.pattern = pattern.lower()
        self.limit = limit
        self.filter_field = filter_field
        self.filter_op = filter_op
        self.filter_value = filter_value

    def execute(self, ctx, pdg, facts, engine, trace):
        t0 = time.time()
        scanned = 0
        matched = []
        for fact in facts:
            scanned += 1
            # Pattern match
            if self.pattern != 'all':
                if self.pattern not in fact.kind and self.pattern not in fact.description.lower() and self.pattern not in fact.subject.lower():
                    continue
            # Predicate pushdown — filter DURING selection
            if self.filter_field:
                if not self._match_predicate(fact):
                    continue
            matched.append(fact)
            if len(matched) >= self.limit:
                break
        ctx.facts = matched
        ctx.metadata['total'] = len(facts)
        ctx.metadata['scanned'] = scanned
        ctx.metadata['selected'] = len(matched)
        if self.filter_field:
            ctx.metadata['pushed_filter'] = f'{self.filter_field}{self.filter_op}{self.filter_value}'
        trace.add('select', f'Selected {len(matched)}/{len(facts)} facts (pattern={self.pattern!r}'
                   + (f', filter={self.filter_field}{self.filter_op}{self.filter_value}' if self.filter_field else '') + ')',
                   duration_ms=(time.time() - t0) * 1000)
        return ctx

    def _match_predicate(self, fact) -> bool:
        """Check if fact matches the pushed-down predicate."""
        d = fact.to_dict() if hasattr(fact, 'to_dict') else fact
        val = d.get(self.filter_field) or d.get('metadata', {}).get(self.filter_field)
        if val is None and self.filter_field == 'evidence':
            val = len(d.get('evidence', []))
        if val is None:
            return False
        return FilterFacts._cmp(val, self.filter_op, self.filter_value)


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


class Project(Operator):
    """Project (prune) result fields — only materialize requested fields.

    When fields=['name', 'evidence'], OpResult.to_dict() only includes those.
    This is projection pruning: avoid serializing unused data.
    """
    name = 'project'

    def __init__(self, fields: List[str] = None):
        self.fields = fields or []

    def execute(self, ctx, pdg, facts, engine, trace):
        t0 = time.time()
        if self.fields:
            ctx.metadata['project_fields'] = self.fields
            ctx.metadata['projection_active'] = True
        trace.add('project', f'Projection: {self.fields or "all"}',
                   duration_ms=(time.time() - t0) * 1000)
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
            from ..runtime.pdg import SliceResult
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
            from ..runtime.pdg import SliceResult
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


# ─── Composition Operators ───────────────────────────────────────

class ComposePlan(Operator):
    """Execute two plans sequentially with context binding, then filter/sort the merged result.

    Execution flow:
        1. Execute first plan → first_ctx
        2. Execute second plan (with first_ctx's nodes as starting context)
        3. Merge results: second's output primary, first's narrative/facts attached
        4. Apply WHERE filter on the result dict
        5. Apply ORDER BY sort on the result dict
    """
    name = 'compose'

    def __init__(self, first: 'LogicalPlan', second: 'LogicalPlan',
                 where_field: str = '', where_op: str = '', where_value: Any = None,
                 order_by: str = '', order_desc: bool = False):
        self.first = first
        self.second = second
        self.where_field = where_field
        self.where_op = where_op
        self.where_value = where_value
        self.order_by = order_by
        self.order_desc = order_desc

    def execute(self, ctx, pdg, facts, engine, trace):
        t0 = time.time()

        # Phase 1: Execute the first query
        first_ctx = self.first.execute(pdg, facts, engine, trace)

        # Phase 2: Execute second query (bind first's context if second has operators)
        has_second = len(self.second.operators) > 0
        if has_second:
            if first_ctx.nodes:
                ctx.nodes = list(first_ctx.nodes)
            if first_ctx.root_causes:
                ctx.root_causes = list(first_ctx.root_causes)
            if first_ctx.depth_map:
                ctx.depth_map = dict(first_ctx.depth_map)
            if first_ctx.metadata:
                ctx.metadata.update(first_ctx.metadata)

            second_ctx = self.second.execute(pdg, facts, engine, trace)

            # Phase 3: Merge — second is primary, attach first's extras
            ctx.nodes = second_ctx.nodes or first_ctx.nodes
            ctx.edges = second_ctx.edges or first_ctx.edges
            ctx.facts = second_ctx.facts or first_ctx.facts
            ctx.history = second_ctx.history or first_ctx.history
            ctx.narrative = second_ctx.narrative or first_ctx.narrative
            ctx.diffs = second_ctx.diffs or first_ctx.diffs
            ctx.stats = second_ctx.stats or first_ctx.stats
            ctx.root_causes = second_ctx.root_causes or first_ctx.root_causes
            ctx.depth_map = second_ctx.depth_map or first_ctx.depth_map

            merged_meta = dict(first_ctx.metadata)
            merged_meta.update(second_ctx.metadata)
            ctx.metadata = merged_meta
        else:
            # No second query — first is the only result
            ctx = first_ctx

        # Phase 4: Apply WHERE filter on the final result
        if self.where_field:
            ctx = self._apply_where(ctx, trace)

        # Phase 5: Apply ORDER BY sort on the final result dict
        if self.order_by:
            ctx = self._apply_order(ctx, trace)

        trace.add('compose', f'Composed: {self.first.query_kind} → {self.second.query_kind}',
                   duration_ms=(time.time() - t0) * 1000)
        return ctx

    def _apply_where(self, ctx: OpResult, trace: QueryTrace) -> OpResult:
        """Filter the composed result by WHERE clause."""
        t0 = time.time()
        field = self.where_field
        op = self.where_op
        value = self.where_value

        # Filter facts if present
        if ctx.facts:
            filtered = []
            for fact in ctx.facts:
                d = fact.to_dict() if hasattr(fact, 'to_dict') else fact
                val = d.get(field) or d.get('metadata', {}).get(field)
                if val is None and field == 'evidence':
                    val = len(d.get('evidence', []))
                if val is not None and FilterFacts._cmp(val, op, value):
                    filtered.append(fact)
            ctx.facts = filtered

        # Filter nodes by depth_map if field matches
        if ctx.nodes and field in ('depth', 'depth_map'):
            ctx.nodes = [n for n in ctx.nodes if FilterFacts._cmp(ctx.depth_map.get(n, 0), op, value)]

        # Filter history if field matches
        if ctx.history and field in ('version', 'step'):
            filtered_h = []
            for sid, vv in ctx.history:
                val = getattr(vv, field, sid) if field == 'version' else sid
                if FilterFacts._cmp(val, op, value):
                    filtered_h.append((sid, vv))
            ctx.history = filtered_h

        trace.add('filter', f'WHERE {field} {op} {value}',
                   duration_ms=(time.time() - t0) * 1000)
        return ctx

    def _apply_order(self, ctx: OpResult, trace: QueryTrace) -> OpResult:
        """Sort the composed result by ORDER BY clause."""
        t0 = time.time()
        field = self.order_by
        desc = self.order_desc

        if ctx.facts:
            ctx.facts.sort(
                key=lambda f: (f.to_dict() if hasattr(f, 'to_dict') else f).get(field, 0),
                reverse=desc,
            )
        if ctx.history:
            ctx.history.sort(
                key=lambda h: getattr(h[1], field, 0) if hasattr(h[1], field) else 0,
                reverse=desc,
            )
        if ctx.nodes and field == 'depth':
            ctx.nodes.sort(key=lambda n: ctx.depth_map.get(n, 0), reverse=desc)

        trace.add('sort', f'ORDER BY {field} {"DESC" if desc else "ASC"}',
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
        parts = []
        for op in self.operators:
            if isinstance(op, ComposePlan):
                w = f' WHERE {op.where_field}{op.where_op}{op.where_value}' if op.where_field else ''
                o = f' ORDER BY {op.order_by}{" DESC" if op.order_desc else ""}' if op.order_by else ''
                parts.append(f'compose({op.first.query_kind}->{op.second.query_kind}{w}{o})')
            else:
                attrs = ', '.join(f'{k}={v}' for k, v in op.__dict__.items() if v and k != 'name')
                parts.append(f'{op.name}({attrs})')
        return parts


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

        ops = [
            ComposePlan(
                first=plan1,
                second=plan2,
                where_field=q.where_field,
                where_op=q.where_op,
                where_value=q.where_value,
                order_by=q.order_by,
                order_desc=q.order_desc,
            ),
        ]
        return LogicalPlan(ops, query_kind=f'composed({plan1.query_kind}→{plan2.query_kind})')
