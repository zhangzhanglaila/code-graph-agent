"""Tests for variable evolutions and backward slice evidence."""

import pytest
from dynamic.semantic.evidence_builder import (
    build_backward_slice_evidence, build_variable_evidence, build_impact_evidence,
)
from dynamic.semantic.query_engine import SemanticQueryEngine


def _loop_fn(n=6):
    total = 0
    for i in range(n):
        total += i
    return total


@pytest.fixture
def loop_setup():
    from dynamic.runtime.recorder import record_function
    from dynamic.runtime.pdg import RuntimePDG
    from dynamic.semantic.facts import FactExtractor
    _, timeline = record_function(_loop_fn, 6)
    pdg = RuntimePDG.from_timeline(timeline)
    facts = FactExtractor(pdg).extract_all()
    return pdg, facts, timeline


class TestVariableEvolutions:
    def test_backward_slice_result_has_edges(self, loop_setup):
        pdg, facts, timeline = loop_setup
        nodes = list(pdg.nodes.keys())
        if len(nodes) < 2:
            pytest.skip("Need at least 2 nodes")

        engine = SemanticQueryEngine(pdg, facts=facts)
        last_step = nodes[-1]
        target_var = 'total'

        slice_result = engine.backward_slice(last_step, target_var)
        assert slice_result is not None
        assert hasattr(slice_result, 'edges')

    def test_build_backward_slice_evidence(self, loop_setup):
        pdg, facts, timeline = loop_setup
        nodes = list(pdg.nodes.keys())
        if len(nodes) < 2:
            pytest.skip("Need at least 2 nodes")

        engine = SemanticQueryEngine(pdg, facts=facts)
        slice_result = engine.backward_slice(nodes[-1], 'total')
        evidence = build_backward_slice_evidence(slice_result, facts)
        assert evidence is not None
        assert hasattr(evidence, 'kind')  # EvidenceCollection has 'kind'
        assert hasattr(evidence, 'target')


class TestBackwardSlice:
    def test_backward_slice_returns_steps(self, loop_setup):
        pdg, facts, timeline = loop_setup
        nodes = list(pdg.nodes.keys())
        if not nodes:
            pytest.skip("No nodes")

        engine = SemanticQueryEngine(pdg, facts=facts)
        result = engine.backward_slice(nodes[-1], 'total')
        assert hasattr(result, 'steps')
        assert hasattr(result, 'root_causes')
        assert hasattr(result, 'depth_map')

    def test_backward_slice_has_edges(self, loop_setup):
        pdg, facts, timeline = loop_setup
        nodes = list(pdg.nodes.keys())
        if not nodes:
            pytest.skip("No nodes")

        engine = SemanticQueryEngine(pdg, facts=facts)
        result = engine.backward_slice(nodes[-1], 'total')
        assert hasattr(result, 'edges')
