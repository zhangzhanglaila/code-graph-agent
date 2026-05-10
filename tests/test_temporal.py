"""Tests for temporal operators — SnapshotOperator, WindowOperator."""

import pytest
from dynamic.query.temporal import (
    TemporalPredicate, TemporalFilter, SnapshotOperator, WindowOperator,
    parse_temporal_query, TemporalQueryPlanner,
)
from dynamic.query.algebra import OpResult


def _loop_fn(n=6):
    total = 0
    for i in range(n):
        total += i
    return total


@pytest.fixture
def pdg_and_facts():
    from dynamic.runtime.recorder import record_function
    from dynamic.runtime.pdg import RuntimePDG
    from dynamic.semantic.facts import FactExtractor
    _, timeline = record_function(_loop_fn, 6)
    pdg = RuntimePDG.from_timeline(timeline)
    facts = FactExtractor(pdg).extract_all()
    return pdg, facts


class TestTemporalPredicate:
    def test_describe_at(self):
        p = TemporalPredicate(mode='at', step=15)
        assert 'AT step 15' in p.describe()

    def test_describe_before(self):
        p = TemporalPredicate(mode='before', marker='return')
        assert 'BEFORE return' in p.describe()

    def test_describe_between(self):
        p = TemporalPredicate(mode='between', step_a=5, step_b=20)
        assert '5..20' in p.describe()


class TestSnapshotOperator:
    def test_snapshot_captures_state(self, pdg_and_facts):
        pdg, facts = pdg_and_facts
        nodes = list(pdg.nodes.keys())
        if not nodes:
            pytest.skip("No PDG nodes")

        op = SnapshotOperator(step=nodes[0])
        ctx = OpResult(nodes=list(nodes), facts=facts)

        class FakeTrace:
            def add(self, *a, **kw): pass

        result = op.execute(ctx, pdg, facts, None, FakeTrace())
        assert nodes[0] in result.nodes
        assert 'snapshot_step' in result.metadata


class TestWindowOperator:
    def test_window_filters_nodes(self, pdg_and_facts):
        pdg, facts = pdg_and_facts
        nodes = sorted(pdg.nodes.keys())
        if len(nodes) < 3:
            pytest.skip("Need at least 3 nodes")

        op = WindowOperator(start=nodes[0], end=nodes[2])
        all_nodes = list(nodes)
        ctx = OpResult(nodes=all_nodes, facts=facts)

        class FakeTrace:
            def add(self, *a, **kw): pass

        result = op.execute(ctx, pdg, facts, None, FakeTrace())
        for n in result.nodes:
            assert nodes[0] <= n <= nodes[2]

    def test_window_filters_facts(self, pdg_and_facts):
        pdg, facts = pdg_and_facts
        nodes = sorted(pdg.nodes.keys())
        if len(nodes) < 2:
            pytest.skip("Need at least 2 nodes")

        mid = nodes[len(nodes) // 2]
        op = WindowOperator(start=nodes[0], end=mid)
        ctx = OpResult(nodes=list(nodes), facts=facts)

        class FakeTrace:
            def add(self, *a, **kw): pass

        result = op.execute(ctx, pdg, facts, None, FakeTrace())
        assert 'window_start' in result.metadata
        assert 'window_end' in result.metadata


class TestTemporalParser:
    def test_parse_snapshot_at(self):
        query, pred = parse_temporal_query("SNAPSHOT AT 15")
        assert pred is not None
        assert pred.mode == 'at'
        assert pred.step == 15

    def test_parse_at_step(self):
        query, pred = parse_temporal_query("WHY memo AT step 15")
        assert pred is not None
        assert pred.mode == 'at'
        assert pred.step == 15

    def test_parse_between(self):
        query, pred = parse_temporal_query("TRACE a BETWEEN 5..20")
        assert pred is not None
        assert pred.mode == 'between'
        assert pred.step_a == 5
        assert pred.step_b == 20

    def test_parse_before(self):
        query, pred = parse_temporal_query("SHOW mutations BEFORE return")
        assert pred is not None
        assert pred.mode == 'before'
        assert pred.marker == 'return'

    def test_parse_after_step(self):
        query, pred = parse_temporal_query("SHOW loops AFTER step 10")
        assert pred is not None
        assert pred.mode == 'after'
        assert pred.step == 10

    def test_parse_window(self):
        query, pred = parse_temporal_query("WINDOW 5..20")
        assert pred is not None
        assert pred.mode == 'between'
        assert pred.step_a == 5
        assert pred.step_b == 20

    def test_parse_no_temporal(self):
        query, pred = parse_temporal_query("WHY result")
        assert pred is None
        assert query.kind == 'why'


class TestTemporalQueryPlanner:
    def test_plan_with_temporal(self, pdg_and_facts):
        pdg, facts = pdg_and_facts
        from dynamic.query.dsl import WhyQuery
        from dynamic.semantic.narrative import NarrativeEngine
        engine = NarrativeEngine(pdg, facts)

        planner = TemporalQueryPlanner()
        query = WhyQuery(kind='why', target='total')
        pred = TemporalPredicate(mode='at', step=0)
        plan = planner.plan_with_temporal(query, pred)
        assert plan is not None
        assert len(plan.operators) > 0
