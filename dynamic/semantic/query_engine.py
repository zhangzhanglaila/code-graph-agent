"""Semantic Query Engine — unified public API for semantic queries.

Wraps the PDG layer and produces typed, graph-free QueryResult objects.
All downstream consumers (EvidenceBuilder, Planner, Renderer) go through this.

Usage:
    engine = SemanticQueryEngine(pdg, model, facts)
    result = engine.backward_slice(step=11, variable='b')
    result = engine.variable_trace('b')
    result = engine.forward_impact(step=0, variable='a')
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

from dynamic.semantic.query_result import (
    BackwardSliceResult, ForwardImpactResult, VariableTraceResult,
    QueryEdge, QueryVarVersion, ResolvedStepInfo,
)


class SemanticQueryEngine:
    """Unified semantic query interface — the public API for all queries.

    Produces typed, graph-free result objects.
    PDG operations happen internally and are never exposed.
    """

    def __init__(self, pdg, model=None, facts=None):
        self._pdg = pdg
        self._model = model
        self._facts = facts

    # ── Main query methods ────────────────────────────────────────

    def backward_slice(self, step: int, variable: str = '') -> BackwardSliceResult:
        """Execute a backward slice query."""
        sr = self._pdg.backward_slice(step, variable)
        step_ids = list(sr.steps) if isinstance(sr.steps, set) else sr.steps
        # Collect all referenced step IDs for resolution
        all_ids = set(step_ids) | set(sr.root_causes or [])
        all_ids.add(sr.target_step)
        for e in sr.edges:
            all_ids.add(getattr(e, 'source', 0))
            all_ids.add(getattr(e, 'target', 0))
        return BackwardSliceResult(
            target_step=sr.target_step,
            target_var=sr.target_var,
            steps=step_ids,
            edges=[self._edge_to_query(e) for e in sr.edges],
            root_causes=sr.root_causes,
            depth_map=sr.depth_map,
            explanation=getattr(sr, 'explanation', []),
            resolved_steps=self._resolve_steps(all_ids),
        )

    def forward_impact(self, step: int, variable: str = '') -> ForwardImpactResult:
        """Execute a forward impact query."""
        sr = self._pdg.forward_impact(step, variable)
        step_ids = list(sr.steps) if isinstance(sr.steps, set) else sr.steps
        all_ids = set(step_ids) | set(sr.root_causes or [])
        all_ids.add(sr.target_step)
        for e in sr.edges:
            all_ids.add(getattr(e, 'source', 0))
            all_ids.add(getattr(e, 'target', 0))
        return ForwardImpactResult(
            target_step=sr.target_step,
            target_var=sr.target_var,
            steps=step_ids,
            edges=[self._edge_to_query(e) for e in sr.edges],
            root_causes=sr.root_causes,
            depth_map=sr.depth_map,
            explanation=getattr(sr, 'explanation', []),
            resolved_steps=self._resolve_steps(all_ids),
        )

    def variable_trace(self, variable: str) -> VariableTraceResult:
        """Execute a variable trace query."""
        history = self._pdg.get_variable_history(variable)
        chain = self._pdg.get_version_chain(variable)

        q_history = []
        for step_id, vv in history:
            q_history.append((step_id, QueryVarVersion(
                name=getattr(vv, 'name', variable),
                version=getattr(vv, 'version', 0),
                value=str(getattr(vv, 'value', '')),
                type=str(getattr(vv, 'type', '')),
                memory_id=getattr(vv, 'memory_id', 0),
                is_changed=getattr(vv, 'is_changed', False),
                is_new=getattr(vv, 'is_new', False),
            )))

        q_chain = []
        for e in chain:
            q_chain.append((
                getattr(e, 'source', 0),
                getattr(e, 'target', 0),
                getattr(e, 'source_version', 0),
                getattr(e, 'target_version', 0),
            ))

        return VariableTraceResult(
            variable=variable,
            history=q_history,
            version_chain=q_chain,
        )

    # ── Declarative query execution ──────────────────────────────

    def execute(self, query) -> Any:
        """Execute a SemanticQuery AST and return typed result.

        Usage:
            from dynamic.query.builder import Query
            result = engine.execute(Query.step(11).depends_on("b"))
            result = engine.execute(Query.variable("x").history())
        """
        from dynamic.query.dsl import (
            WhyQuery, TraceQuery, ImpactQuery, RootsQuery,
            ShowQuery, CompareQuery, StatsQuery, ComposedQuery,
        )

        if isinstance(query, WhyQuery):
            step = query.target_step if query.target_step >= 0 else 0
            return self.backward_slice(step, query.target)

        elif isinstance(query, ImpactQuery):
            step = query.source_step if query.source_step >= 0 else 0
            return self.forward_impact(step, query.source)

        elif isinstance(query, TraceQuery):
            return self.variable_trace(query.variable)

        elif isinstance(query, RootsQuery):
            step = query.target_step if query.target_step >= 0 else 0
            result = self.backward_slice(step, query.target)
            # Return only root causes
            return {
                'root_causes': result.root_causes,
                'resolved_steps': result.resolved_steps,
            }

        elif isinstance(query, CompareQuery):
            return self._execute_compare(query)

        elif isinstance(query, StatsQuery):
            return self._pdg.stats() if hasattr(self._pdg, 'stats') else {}

        elif isinstance(query, ShowQuery):
            return self._execute_show(query)

        elif isinstance(query, ComposedQuery):
            return self._execute_composed(query)

        else:
            return {'error': f'Unknown query type: {type(query).__name__}'}

    # ── Batch queries ─────────────────────────────────────────────

    def full_analysis(self, step: int, variable: str = '') -> Dict[str, Any]:
        """Run all queries for a target step. Returns a dict of results."""
        return {
            'backward_slice': self.backward_slice(step, variable),
            'forward_impact': self.forward_impact(step, variable),
            'variable_trace': self.variable_trace(variable) if variable else None,
        }

    # ── Query handlers ────────────────────────────────────────────

    def _execute_show(self, query) -> dict:
        """Execute a SHOW query — find facts matching pattern."""
        pattern = query.pattern.lower()
        limit = query.limit
        matched = []
        for fact in self._facts:
            if pattern in fact.kind or pattern in fact.description.lower() or pattern in fact.subject.lower():
                matched.append(fact)
            if len(matched) >= limit:
                break
        return {
            'facts': [f.to_dict() if hasattr(f, 'to_dict') else f for f in matched],
            'count': len(matched),
            'pattern': query.pattern,
        }

    def _execute_compare(self, query) -> dict:
        """Execute a COMPARE query — compare two execution points."""
        node_a = self._pdg.nodes.get(query.step_a)
        node_b = self._pdg.nodes.get(query.step_b)
        if not node_a or not node_b:
            return {'error': f'Step {query.step_a} or {query.step_b} not found'}

        diffs = []
        all_vars = set(node_a.vars.keys()) | set(node_b.vars.keys())
        if query.var:
            all_vars = {query.var} if query.var in all_vars else set()

        for var in sorted(all_vars):
            va, vb = node_a.vars.get(var), node_b.vars.get(var)
            if va and vb:
                if va.value != vb.value or va.version != vb.version:
                    diffs.append({
                        'var': var, 'a_value': va.value, 'b_value': vb.value,
                        'a_version': va.version, 'b_version': vb.version, 'type': 'changed',
                    })
            elif va:
                diffs.append({'var': var, 'a_value': va.value, 'b_value': None, 'type': 'removed'})
            elif vb:
                diffs.append({'var': var, 'a_value': None, 'b_value': vb.value, 'type': 'added'})

        return {
            'step_a': query.step_a,
            'step_b': query.step_b,
            'code_a': node_a.code,
            'code_b': node_b.code,
            'diffs': diffs,
            'diff_count': len(diffs),
        }

    def _execute_composed(self, query):
        """Execute a composed query: first THEN second [WHERE ...] [ORDER BY ...]."""
        from .query_result import ComposedResult

        first_result = self.execute(query.first)

        # If no second query, just apply WHERE/ORDER BY on first
        from dynamic.query.dsl import HelpQuery
        if isinstance(query.second, HelpQuery) or query.second.kind == 'help':
            result = first_result
            second_result = None
        else:
            second_result = self.execute(query.second)
            # Merge: second is primary, first's extras attached
            # Convert typed results to dicts for merging
            first_dict = self._to_dict(first_result)
            second_dict = self._to_dict(second_result)
            result = dict(second_dict)
            for key, val in first_dict.items():
                if key not in result or result[key] is None:
                    result[key] = val

        # Apply WHERE filter
        where_applied = None
        if query.where_field:
            result = self._apply_where(result, query.where_field, query.where_op, query.where_value)
            where_applied = f'{query.where_field} {query.where_op} {query.where_value}'

        # Apply ORDER BY
        order_applied = None
        if query.order_by:
            result = self._apply_order(result, query.order_by, query.order_desc)
            order_applied = query.order_by

        composed = ComposedResult(
            first=first_result,
            second=second_result,
            merged=result,
            where_applied=where_applied,
            order_by=order_applied,
            where_field=query.where_field or '',
            where_op=query.where_op or '',
            where_value=query.where_value,
            order_desc=query.order_desc if hasattr(query, 'order_desc') else False,
        )

        # Attach typed result to metadata, return merged dict for backward compat
        result['_composed'] = {
            'first_keys': list(first_result.keys()) if isinstance(first_result, dict) else [],
            'second_keys': list(second_result.keys()) if isinstance(second_result, dict) else [],
            'where_applied': where_applied,
            'order_by': order_applied,
        }
        return result

    @staticmethod
    def _apply_where(result: dict, field: str, op: str, value) -> dict:
        """Filter result dict by WHERE clause."""
        def cmp(a, o, b):
            try:
                if o == '>': return a > b
                if o == '<': return a < b
                if o == '>=': return a >= b
                if o == '<=': return a <= b
                if o == '==': return a == b
                if o == '!=': return a != b
                if o == 'contains': return str(b).lower() in str(a).lower()
            except TypeError:
                return False
            return False

        # Filter facts list
        if 'facts' in result and isinstance(result['facts'], list):
            filtered = []
            for f in result['facts']:
                d = f.to_dict() if hasattr(f, 'to_dict') else f
                val = d.get(field) or d.get('metadata', {}).get(field)
                if val is None and field == 'evidence':
                    val = len(d.get('evidence', []))
                if val is not None and cmp(val, op, value):
                    filtered.append(f)
            result['facts'] = filtered
            result['count'] = len(filtered)

        # Filter history list
        if 'history' in result and isinstance(result['history'], list):
            filtered = []
            for entry in result['history']:
                val = entry.get(field) if isinstance(entry, dict) else None
                if val is not None and cmp(val, op, value):
                    filtered.append(entry)
            result['history'] = filtered

        return result

    @staticmethod
    def _apply_order(result: dict, field: str, desc: bool) -> dict:
        """Sort result dict by ORDER BY clause."""
        if 'facts' in result and isinstance(result['facts'], list):
            result['facts'].sort(
                key=lambda f: (f.to_dict() if hasattr(f, 'to_dict') else f).get(field, 0),
                reverse=desc,
            )
        if 'history' in result and isinstance(result['history'], list):
            result['history'].sort(
                key=lambda h: h.get(field, 0) if isinstance(h, dict) else 0,
                reverse=desc,
            )
        return result

    @staticmethod
    def _to_dict(result) -> dict:
        """Convert a typed result (dataclass or dict) to dict."""
        if isinstance(result, dict):
            return result
        if hasattr(result, '__dataclass_fields__'):
            d = {}
            for fname in result.__dataclass_fields__:
                val = getattr(result, fname)
                if hasattr(val, '__dataclass_fields__'):
                    d[fname] = SemanticQueryEngine._to_dict(val)
                elif isinstance(val, list):
                    d[fname] = [
                        SemanticQueryEngine._to_dict(v) if hasattr(v, '__dataclass_fields__') else v
                        for v in val
                    ]
                elif isinstance(val, dict):
                    d[fname] = {
                        k: SemanticQueryEngine._to_dict(v) if hasattr(v, '__dataclass_fields__') else v
                        for k, v in val.items()
                    }
                elif isinstance(val, tuple):
                    d[fname] = list(val)
                else:
                    d[fname] = val
            return d
        return {'value': result}

    # ── Internal ──────────────────────────────────────────────────

    def _resolve_steps(self, step_ids: set) -> Dict[int, ResolvedStepInfo]:
        """Pre-resolve step IDs to code/line info from the PDG."""
        resolved = {}
        for sid in step_ids:
            node = self._pdg.nodes.get(sid)
            if node:
                resolved[sid] = ResolvedStepInfo(
                    code=getattr(node, 'code', ''),
                    line=getattr(node, 'line', 0),
                )
        return resolved

    def _edge_to_query(self, edge) -> QueryEdge:
        """Convert a RuntimeEdge to a QueryEdge."""
        return QueryEdge(
            source=getattr(edge, 'source', 0),
            target=getattr(edge, 'target', 0),
            kind=getattr(edge, 'kind', ''),
            var=getattr(edge, 'var', ''),
            source_version=getattr(edge, 'source_version', 0),
            target_version=getattr(edge, 'target_version', 0),
        )
