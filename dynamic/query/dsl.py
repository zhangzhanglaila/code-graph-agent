"""Semantic Query DSL — Natural Language → Structured Query → PDG Execution.

Query types (the vocabulary):
    WHY <target>              — backward slice + explanation
    TRACE <var>               — variable evolution story
    IMPACT <source>           — forward impact analysis
    SHOW <pattern>            — find semantic facts matching pattern
    COMPARE <a> <b>           — compare two execution points
    ROOTS <target>            — find root causes only
    STATS                     — graph statistics

Composable operators:
    <query> THEN <query>      — chain queries (pipe output)
    <query> WHERE <filter>    — filter results
    <query> ORDER BY <field>  — sort results

Examples:
    WHY result
    TRACE memo THEN SHOW mutations
    SHOW loop.accumulation WHERE evidence > 5
    WHY result ORDER BY depth
"""

from __future__ import annotations
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any


# ─── Query Trace ──────────────────────────────────────────────────

@dataclass
class TraceStep:
    """One step in query execution trace."""
    phase: str          # 'parse' | 'plan' | 'traverse' | 'select' | 'narrate' | 'filter'
    description: str    # what happened
    duration_ms: float = 0
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'phase': self.phase,
            'description': self.description,
            'duration_ms': round(self.duration_ms, 2),
            'detail': self.detail,
        }


@dataclass
class QueryTrace:
    """Full execution trace for a query — shows HOW the system reasoned."""
    steps: List[TraceStep] = field(default_factory=list)
    total_ms: float = 0

    def add(self, phase: str, description: str, duration_ms: float = 0,
             detail: Optional[dict] = None, **kwargs) -> None:
        merged = detail or {}
        merged.update(kwargs)
        self.steps.append(TraceStep(
            phase=phase,
            description=description,
            duration_ms=duration_ms,
            detail=merged,
        ))

    def to_dict(self) -> dict:
        return {
            'steps': [s.to_dict() for s in self.steps],
            'total_ms': round(self.total_ms, 2),
            'phase_summary': self._phase_summary(),
        }

    def _phase_summary(self) -> dict:
        summary: Dict[str, float] = {}
        for s in self.steps:
            summary[s.phase] = summary.get(s.phase, 0) + s.duration_ms
        return {k: round(v, 2) for k, v in summary.items()}

    def to_text(self) -> str:
        lines = ['Query Execution Trace', '─' * 40]
        for s in self.steps:
            ms = f' ({s.duration_ms:.1f}ms)' if s.duration_ms > 0 else ''
            lines.append(f'  [{s.phase:8s}] {s.description}{ms}')
        lines.append('─' * 40)
        lines.append(f'  Total: {self.total_ms:.1f}ms')
        return '\n'.join(lines)


# ─── Query AST ────────────────────────────────────────────────────

@dataclass
class SemanticQuery:
    """Base class for all semantic queries."""
    kind: str
    raw: str = ''


@dataclass
class WhyQuery(SemanticQuery):
    """WHY <target> — backward slice + explanation."""
    kind: str = 'why'
    target: str = ''
    target_step: int = -1


@dataclass
class TraceQuery(SemanticQuery):
    """TRACE <var> — variable evolution story."""
    kind: str = 'trace'
    variable: str = ''


@dataclass
class ImpactQuery(SemanticQuery):
    """IMPACT <source> — forward impact analysis."""
    kind: str = 'impact'
    source: str = ''
    source_step: int = -1


@dataclass
class ShowQuery(SemanticQuery):
    """SHOW <pattern> — find matching semantic facts."""
    kind: str = 'show'
    pattern: str = ''
    limit: int = 20


@dataclass
class RootsQuery(SemanticQuery):
    """ROOTS <target> — find root causes only."""
    kind: str = 'roots'
    target: str = ''
    target_step: int = -1


@dataclass
class CompareQuery(SemanticQuery):
    """COMPARE <a> <b> — compare two execution points."""
    kind: str = 'compare'
    step_a: int = -1
    step_b: int = -1
    var: str = ''


@dataclass
class StatsQuery(SemanticQuery):
    """STATS — graph statistics."""
    kind: str = 'stats'


@dataclass
class HelpQuery(SemanticQuery):
    """HELP — show available queries."""
    kind: str = 'help'


@dataclass
class ComposedQuery(SemanticQuery):
    """Composed query: <first> THEN <second> [WHERE <filter>] [ORDER BY <field>]."""
    kind: str = 'composed'
    first: SemanticQuery = field(default_factory=lambda: SemanticQuery(kind='help'))
    second: SemanticQuery = field(default_factory=lambda: SemanticQuery(kind='help'))
    where_field: str = ''
    where_op: str = ''        # '>', '<', '>=', '<=', '==', 'contains'
    where_value: Any = None
    order_by: str = ''
    order_desc: bool = False


# ─── Parser ───────────────────────────────────────────────────────

_QUERY_PATTERNS = [
    (r'^why\s+(.+)$', 'why'),
    (r'^trace\s+(\w+)$', 'trace'),
    (r'^impact\s+(.+)$', 'impact'),
    (r'^show\s+(.+)$', 'show'),
    (r'^roots?\s+(.+)$', 'roots'),
    (r'^compare\s+(\d+)\s+(?:vs?\s+)?(\d+)(?:\s+(\w+))?$', 'compare'),
    (r'^stats?$', 'stats'),
    (r'^help$', 'help'),
]


def _parse_single(text: str) -> SemanticQuery:
    """Parse a single (non-composed) query."""
    text = text.strip()
    for pattern, kind in _QUERY_PATTERNS:
        m = re.match(pattern, text, re.IGNORECASE)
        if not m:
            continue
        if kind == 'why':
            target = m.group(1).strip()
            if target.isdigit():
                return WhyQuery(kind='why', target='', target_step=int(target), raw=text)
            return WhyQuery(kind='why', target=target, raw=text)
        elif kind == 'trace':
            return TraceQuery(kind='trace', variable=m.group(1).strip(), raw=text)
        elif kind == 'impact':
            source = m.group(1).strip()
            if source.isdigit():
                return ImpactQuery(kind='impact', source='', source_step=int(source), raw=text)
            return ImpactQuery(kind='impact', source=source, raw=text)
        elif kind == 'show':
            return ShowQuery(kind='show', pattern=m.group(1).strip(), raw=text)
        elif kind == 'roots':
            target = m.group(1).strip()
            if target.isdigit():
                return RootsQuery(kind='roots', target='', target_step=int(target), raw=text)
            return RootsQuery(kind='roots', target=target, raw=text)
        elif kind == 'compare':
            return CompareQuery(kind='compare', step_a=int(m.group(1)), step_b=int(m.group(2)), var=m.group(3) or '', raw=text)
        elif kind == 'stats':
            return StatsQuery(kind='stats', raw=text)
        elif kind == 'help':
            return HelpQuery(kind='help', raw=text)
    return WhyQuery(kind='why', target=text, raw=text)


def parse_query(text: str) -> SemanticQuery:
    """Parse a natural language query into a SemanticQuery AST.

    Supports composition:
        "TRACE memo THEN SHOW mutations"
        "SHOW loop.accumulation WHERE evidence > 5"
        "WHY result ORDER BY depth"
    """
    text = text.strip()
    raw = text

    # Check for THEN composition
    then_match = re.split(r'\s+then\s+', text, flags=re.IGNORECASE)
    if len(then_match) == 2:
        first = _parse_single(then_match[0])
        # Check for WHERE/ORDER BY on the second part
        second_text = then_match[1]
        where_match = re.search(r'\s+where\s+(\w+)\s*(>=|<=|!=|>|<|==|contains)\s*(.+?)(?:\s+order\s+by\s+|$)', second_text, re.IGNORECASE)
        order_match = re.search(r'\s+order\s+by\s+(\w+)(?:\s+(desc|asc))?\s*$', second_text, re.IGNORECASE)

        second_clean = second_text
        if where_match:
            second_clean = second_text[:where_match.start()].strip()
        if order_match:
            second_clean = second_clean[:order_match.start()].strip()

        second = _parse_single(second_clean)

        composed = ComposedQuery(kind='composed', first=first, second=second, raw=raw)

        if where_match:
            composed.where_field = where_match.group(1)
            composed.where_op = where_match.group(2)
            val_str = where_match.group(3).strip()
            try:
                composed.where_value = int(val_str)
            except ValueError:
                try:
                    composed.where_value = float(val_str)
                except ValueError:
                    composed.where_value = val_str

        if order_match:
            composed.order_by = order_match.group(1)
            composed.order_desc = (order_match.group(2) or '').lower() == 'desc'

        return composed

    # Check for WHERE on single query
    where_match = re.search(r'\s+where\s+(\w+)\s*(>=|<=|!=|>|<|==|contains)\s*(.+?)(?:\s+order\s+by\s+|$)', text, re.IGNORECASE)
    order_match = re.search(r'\s+order\s+by\s+(\w+)(?:\s+(desc|asc))?\s*$', text, re.IGNORECASE)

    clean_text = text
    if where_match:
        clean_text = text[:where_match.start()].strip()
    if order_match:
        clean_text = clean_text[:order_match.start()].strip()

    query = _parse_single(clean_text)

    if where_match or order_match:
        composed = ComposedQuery(kind='composed', first=query, second=HelpQuery(kind='help'), raw=raw)
        if where_match:
            composed.where_field = where_match.group(1)
            composed.where_op = where_match.group(2)
            val_str = where_match.group(3).strip()
            try:
                composed.where_value = int(val_str)
            except ValueError:
                try:
                    composed.where_value = float(val_str)
                except ValueError:
                    composed.where_value = val_str
        if order_match:
            composed.order_by = order_match.group(1)
            composed.order_desc = (order_match.group(2) or '').lower() == 'desc'
        return composed

    return query


# ─── Executor ─────────────────────────────────────────────────────

class QueryExecutor:
    """Executes SemanticQuery against a RuntimePDG + FactExtractor + NarrativeEngine.

    Uses the QueryPlanner + SemanticAlgebra pipeline internally.
    Records a QueryTrace showing HOW the query was executed.
    """

    def __init__(self, pdg, facts, narrative_engine):
        self.pdg = pdg
        self.facts = facts
        self.engine = narrative_engine
        from .algebra import QueryPlanner
        self._planner = QueryPlanner()

    def execute(self, query: SemanticQuery) -> dict:
        """Execute a query and return a structured result with trace."""
        t0 = time.time()
        trace = QueryTrace()
        trace.add('parse', f'Parsed query: {query.kind}', detail={'raw': query.raw})

        # Check for temporal query
        temporal = None
        if hasattr(query, 'temporal') and query.temporal:
            temporal = query.temporal
            inner = query.inner if hasattr(query, 'inner') and query.inner else query
        else:
            inner = query

        # Plan: SemanticQuery AST → LogicalPlan (operator pipeline)
        t_plan = time.time()
        if temporal:
            from .temporal import TemporalQueryPlanner
            tp = TemporalQueryPlanner()
            plan = tp.plan_with_temporal(inner, temporal)
        else:
            plan = self._planner.plan(inner)
        trace.add('plan', f'Planned: {plan.describe()[:120]}',
                   duration_ms=(time.time() - t_plan) * 1000,
                   detail={'pipeline': plan.describe()})

        # Execute the plan
        op_result = plan.execute(self.pdg, self.facts, self.engine, trace)

        # Handle HELP specially (empty plan)
        if query.kind == 'help':
            result = self._exec_help(query, trace)
        else:
            result = op_result.to_dict()

        trace.total_ms = (time.time() - t0) * 1000
        result['_trace'] = trace.to_dict()
        return result

    def _exec_help(self, query: HelpQuery, trace: QueryTrace) -> dict:
        return {
            'success': True, 'query': 'help',
            'commands': [
                {'syntax': 'WHY <target>', 'description': 'Backward slice + explanation'},
                {'syntax': 'TRACE <var>', 'description': 'Variable evolution story'},
                {'syntax': 'IMPACT <source>', 'description': 'Forward impact analysis'},
                {'syntax': 'SHOW <pattern>', 'description': 'Find semantic facts'},
                {'syntax': 'ROOTS <target>', 'description': 'Find root causes'},
                {'syntax': 'COMPARE <a> <b>', 'description': 'Compare two steps'},
                {'syntax': 'STATS', 'description': 'Graph statistics'},
                {'syntax': '<q> THEN <q>', 'description': 'Chain queries'},
                {'syntax': '<q> WHERE <f> > <v>', 'description': 'Filter results'},
                {'syntax': '<q> ORDER BY <f>', 'description': 'Sort results'},
            ],
        }
