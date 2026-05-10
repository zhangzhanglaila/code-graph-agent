"""Tests for SemanticQueryEngine — ComposedQuery, CompareQuery, ShowQuery."""

import pytest
from dynamic.semantic.query_engine import SemanticQueryEngine
from dynamic.query.dsl import (
    WhyQuery, TraceQuery, ShowQuery, CompareQuery, StatsQuery,
    ComposedQuery, ImpactQuery, RootsQuery, HelpQuery,
)


class TestWhyQuery:
    def test_backward_slice_returns_result(self, loop_query_engine):
        result = loop_query_engine.execute(WhyQuery(kind='why', target='total'))
        assert result is not None

    def test_backward_slice_has_steps(self, loop_query_engine):
        result = loop_query_engine.backward_slice(0, 'total')
        assert hasattr(result, 'steps')
        assert hasattr(result, 'edges')
        assert hasattr(result, 'root_causes')


class TestTraceQuery:
    def test_variable_trace(self, loop_query_engine):
        result = loop_query_engine.execute(TraceQuery(kind='trace', variable='total'))
        assert result is not None

    def test_variable_trace_returns_chain(self, loop_query_engine):
        result = loop_query_engine.variable_trace('total')
        assert hasattr(result, 'variable')
        assert result.variable == 'total'


class TestShowQuery:
    def test_show_facts(self, loop_query_engine):
        query = ShowQuery(kind='show', pattern='loop')
        result = loop_query_engine.execute(query)
        assert isinstance(result, dict)

    def test_show_matches_pattern(self, loop_query_engine, loop_facts):
        query = ShowQuery(kind='show', pattern='all', limit=5)
        result = loop_query_engine._execute_show(query)
        assert isinstance(result, dict)
        assert 'facts' in result


class TestCompareQuery:
    def test_compare_two_steps(self, loop_query_engine, loop_pdg):
        nodes = list(loop_pdg.nodes.keys())
        if len(nodes) >= 2:
            query = CompareQuery(kind='compare', step_a=nodes[0], step_b=nodes[1])
            result = loop_query_engine.execute(query)
            assert isinstance(result, dict)
            assert 'diffs' in result or 'error' in result


class TestStatsQuery:
    def test_stats(self, loop_query_engine):
        result = loop_query_engine.execute(StatsQuery(kind='stats'))
        assert isinstance(result, dict)


class TestComposedQuery:
    def test_composed_stats_then_show(self, loop_query_engine):
        first = StatsQuery(kind='stats')
        second = ShowQuery(kind='show', pattern='all', limit=2)
        composed = ComposedQuery(kind='composed', first=first, second=second)
        result = loop_query_engine.execute(composed)
        assert isinstance(result, dict)

    def test_composed_show_then_show(self, loop_query_engine):
        first = ShowQuery(kind='show', pattern='loop', limit=3)
        second = ShowQuery(kind='show', pattern='all', limit=2)
        composed = ComposedQuery(kind='composed', first=first, second=second)
        result = loop_query_engine.execute(composed)
        assert isinstance(result, dict)


class TestRootsQuery:
    def test_roots(self, loop_query_engine):
        query = RootsQuery(kind='roots', target='total')
        result = loop_query_engine.execute(query)
        assert isinstance(result, dict)


class TestImpactQuery:
    def test_forward_impact(self, loop_query_engine):
        query = ImpactQuery(kind='impact', source='i')
        result = loop_query_engine.execute(query)
        assert result is not None
