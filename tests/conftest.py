"""Shared fixtures for all tests."""

import sys
import os
import pytest

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def _loop_accum(n=6):
    """Simple loop accumulator for testing."""
    total = 0
    for i in range(n):
        total = total + i
    return total


def _branch_example(x=5):
    """Branching code for testing."""
    if x > 3:
        result = "big"
    else:
        result = "small"
    return result


def _mutation_example():
    """Mutation-heavy code for testing."""
    arr = [1, 2, 3]
    arr.append(4)
    arr[0] = 99
    return arr


@pytest.fixture
def loop_timeline():
    """Timeline from loop accumulator execution."""
    from dynamic.runtime.recorder import record_function
    result, timeline = record_function(_loop_accum, 6)
    return timeline, result


@pytest.fixture
def branch_timeline():
    """Timeline from branch example execution."""
    from dynamic.runtime.recorder import record_function
    result, timeline = record_function(_branch_example, 5)
    return timeline, result


@pytest.fixture
def mutation_timeline():
    """Timeline from mutation example execution."""
    from dynamic.runtime.recorder import record_function
    result, timeline = record_function(_mutation_example)
    return timeline, result


@pytest.fixture
def loop_pdg(loop_timeline):
    """PDG from loop execution."""
    from dynamic.runtime.pdg import RuntimePDG
    timeline, _ = loop_timeline
    return RuntimePDG.from_timeline(timeline)


@pytest.fixture
def loop_facts(loop_pdg):
    """Facts from loop execution."""
    from dynamic.semantic.facts import FactExtractor
    return FactExtractor(loop_pdg).extract_all()


@pytest.fixture
def loop_engine(loop_pdg, loop_facts):
    """NarrativeEngine from loop execution."""
    from dynamic.semantic.narrative import NarrativeEngine
    return NarrativeEngine(loop_pdg, loop_facts)


@pytest.fixture
def loop_query_engine(loop_pdg, loop_facts):
    """SemanticQueryEngine from loop execution."""
    from dynamic.semantic.query_engine import SemanticQueryEngine
    return SemanticQueryEngine(loop_pdg, facts=loop_facts)
