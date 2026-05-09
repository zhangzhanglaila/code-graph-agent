"""Fluent Query Builder — programmatic API for semantic queries.

Instead of text parsing:
    parse_query("WHY result")

Use the fluent API:
    Query.step(11).depends_on("b")
    Query.variable("x").history()
    Query.step(4).impacts()

Each builder method returns a SemanticQuery AST that can be executed:
    engine.execute(Query.step(11).depends_on("b"))
"""

from __future__ import annotations
from typing import Optional

from dynamic.query.dsl import (
    SemanticQuery, WhyQuery, TraceQuery, ImpactQuery,
    ShowQuery, RootsQuery, CompareQuery, StatsQuery,
)


class _StepBuilder:
    """Builder for step-oriented queries."""

    def __init__(self, step: int):
        self._step = step

    def depends_on(self, variable: str = '') -> WhyQuery:
        """Backward slice: what does this step depend on?"""
        return WhyQuery(
            kind='why',
            target=variable,
            target_step=self._step,
            raw=f'WHY step {self._step}' + (f' var {variable}' if variable else ''),
        )

    def impacts(self, variable: str = '') -> ImpactQuery:
        """Forward impact: what does this step affect?"""
        return ImpactQuery(
            kind='impact',
            source=variable,
            source_step=self._step,
            raw=f'IMPACT step {self._step}' + (f' var {variable}' if variable else ''),
        )

    def roots(self, variable: str = '') -> RootsQuery:
        """Root causes: where does this step's value originate?"""
        return RootsQuery(
            kind='roots',
            target=variable,
            target_step=self._step,
            raw=f'ROOTS step {self._step}' + (f' var {variable}' if variable else ''),
        )

    def compare_to(self, other_step: int, variable: str = '') -> CompareQuery:
        """Compare two execution points."""
        return CompareQuery(
            kind='compare',
            step_a=self._step,
            step_b=other_step,
            var=variable,
            raw=f'COMPARE {self._step} vs {other_step}',
        )


class _VariableBuilder:
    """Builder for variable-oriented queries."""

    def __init__(self, name: str):
        self._name = name

    def history(self) -> TraceQuery:
        """Variable evolution story."""
        return TraceQuery(
            kind='trace',
            variable=self._name,
            raw=f'TRACE {self._name}',
        )

    def why(self, step: int = -1) -> WhyQuery:
        """Why does this variable have its value?"""
        return WhyQuery(
            kind='why',
            target=self._name,
            target_step=step,
            raw=f'WHY {self._name}',
        )


class _QueryBuilder:
    """Builder for pattern/fact queries."""

    @staticmethod
    def show(pattern: str, limit: int = 20) -> ShowQuery:
        """Find semantic facts matching a pattern."""
        return ShowQuery(
            kind='show',
            pattern=pattern,
            limit=limit,
            raw=f'SHOW {pattern}',
        )

    @staticmethod
    def stats() -> StatsQuery:
        """Graph statistics."""
        return StatsQuery(kind='stats', raw='STATS')


class Query:
    """Entry point for the fluent query API.

    Usage:
        Query.step(11).depends_on("b")       # backward slice
        Query.step(4).impacts()               # forward impact
        Query.variable("x").history()         # variable trace
        Query.step(11).roots("b")             # root causes only
        Query.step(5).compare_to(10, "x")     # compare two points
        Query.show("loop.*")                  # find facts
        Query.stats()                         # graph statistics
    """

    @staticmethod
    def step(step_id: int) -> _StepBuilder:
        """Start a step-oriented query."""
        return _StepBuilder(step_id)

    @staticmethod
    def variable(name: str) -> _VariableBuilder:
        """Start a variable-oriented query."""
        return _VariableBuilder(name)

    @staticmethod
    def show(pattern: str, limit: int = 20) -> ShowQuery:
        """Find semantic facts matching a pattern."""
        return _QueryBuilder.show(pattern, limit)

    @staticmethod
    def stats() -> StatsQuery:
        """Graph statistics."""
        return _QueryBuilder.stats()
