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


# ─── Query AST (frozen = immutable + hashable) ───────────────────

@dataclass(frozen=True)
class SemanticQuery:
    """Base class for all semantic queries. Immutable and hashable."""
    kind: str
    raw: str = ''

    def to_dict(self) -> dict:
        """Serialize to dict — stable, deterministic."""
        d = {'kind': self.kind}
        for k, v in self.__dict__.items():
            if k in ('kind', 'raw'):
                continue
            if isinstance(v, SemanticQuery):
                d[k] = v.to_dict()
            elif v is not None and v != '' and v != -1 and v != False and v != 20:
                d[k] = v
        return d

    def to_json(self) -> str:
        """Serialize to JSON string."""
        import json
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)

    def query_hash(self) -> str:
        """Deterministic hash for caching. Semantic-equivalent queries → same hash."""
        import hashlib, json
        canonical = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class WhyQuery(SemanticQuery):
    """WHY <target> — backward slice + explanation."""
    kind: str = 'why'
    target: str = ''
    target_step: int = -1


@dataclass(frozen=True)
class TraceQuery(SemanticQuery):
    """TRACE <var> — variable evolution story."""
    kind: str = 'trace'
    variable: str = ''


@dataclass(frozen=True)
class ImpactQuery(SemanticQuery):
    """IMPACT <source> — forward impact analysis."""
    kind: str = 'impact'
    source: str = ''
    source_step: int = -1


@dataclass(frozen=True)
class ShowQuery(SemanticQuery):
    """SHOW <pattern> — find matching semantic facts."""
    kind: str = 'show'
    pattern: str = ''
    limit: int = 20


@dataclass(frozen=True)
class RootsQuery(SemanticQuery):
    """ROOTS <target> — find root causes only."""
    kind: str = 'roots'
    target: str = ''
    target_step: int = -1


@dataclass(frozen=True)
class CompareQuery(SemanticQuery):
    """COMPARE <a> <b> — compare two execution points."""
    kind: str = 'compare'
    step_a: int = -1
    step_b: int = -1
    var: str = ''


@dataclass(frozen=True)
class StatsQuery(SemanticQuery):
    """STATS — graph statistics."""
    kind: str = 'stats'


@dataclass(frozen=True)
class HelpQuery(SemanticQuery):
    """HELP — show available queries."""
    kind: str = 'help'


@dataclass(frozen=True)
class ComposedQuery(SemanticQuery):
    """Composed query: <first> THEN <second> [WHERE <filter>] [ORDER BY <field>]."""
    kind: str = 'composed'
    first: SemanticQuery = field(default_factory=lambda: HelpQuery(kind='help'))
    second: SemanticQuery = field(default_factory=lambda: HelpQuery(kind='help'))
    where_field: str = ''
    where_op: str = ''        # '>', '<', '>=', '<=', '==', 'contains'
    where_value: Any = None
    order_by: str = ''
    order_desc: bool = False


# ─── Validation ──────────────────────────────────────────────────

class QueryValidationError(Exception):
    """Raised when a query fails validation."""
    pass


def validate_query(query: SemanticQuery, pdg=None) -> List[str]:
    """Validate a query. Returns list of warnings (empty = valid).

    Checks:
    - Shape: required fields are present
    - Semantic: step/variable exist in PDG (if pdg provided)
    """
    warnings = []

    if isinstance(query, WhyQuery):
        if query.target_step < 0 and not query.target:
            warnings.append('WHY query needs a target_step or target variable')
        if pdg and query.target_step >= 0 and query.target_step not in pdg.nodes:
            warnings.append(f'Step {query.target_step} not found in execution')

    elif isinstance(query, TraceQuery):
        if not query.variable:
            warnings.append('TRACE query needs a variable name')
        if pdg and query.variable:
            all_vars = set()
            for n in pdg.nodes.values():
                all_vars.update((n.vars or {}).keys())
            if query.variable not in all_vars:
                warnings.append(f'Variable "{query.variable}" not found in execution')

    elif isinstance(query, ImpactQuery):
        if query.source_step < 0 and not query.source:
            warnings.append('IMPACT query needs a source_step or source variable')

    elif isinstance(query, RootsQuery):
        if query.target_step < 0 and not query.target:
            warnings.append('ROOTS query needs a target_step or target variable')

    elif isinstance(query, CompareQuery):
        if query.step_a < 0 or query.step_b < 0:
            warnings.append('COMPARE query needs two step IDs')

    elif isinstance(query, ComposedQuery):
        w1 = validate_query(query.first, pdg)
        w2 = validate_query(query.second, pdg)
        warnings.extend([f'first.{w}' for w in w1])
        warnings.extend([f'second.{w}' for w in w2])

    return warnings


def validate_query_or_raise(query: SemanticQuery, pdg=None) -> None:
    """Validate a query, raising on errors."""
    warnings = validate_query(query, pdg)
    if warnings:
        raise QueryValidationError('; '.join(warnings))


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


def _parse_where_value(val_str: str) -> Any:
    """Parse a WHERE value string to int/float/str."""
    try:
        return int(val_str)
    except ValueError:
        try:
            return float(val_str)
        except ValueError:
            return val_str


def _extract_where_order(text: str):
    """Extract WHERE and ORDER BY clauses from text. Returns (clean_text, where_match, order_match)."""
    where_match = re.search(r'\s+where\s+(\w+)\s*(>=|<=|!=|>|<|==|contains)\s*(.+?)(?:\s+order\s+by\s+|$)', text, re.IGNORECASE)
    order_match = re.search(r'\s+order\s+by\s+(\w+)(?:\s+(desc|asc))?\s*$', text, re.IGNORECASE)
    clean = text
    if where_match:
        clean = clean[:where_match.start()].strip()
    if order_match:
        clean = clean[:order_match.start()].strip()
    return clean, where_match, order_match


def _build_composed(first, second, raw, where_match=None, order_match=None) -> ComposedQuery:
    """Build a ComposedQuery with all values at construction time (frozen-safe)."""
    wf = where_match.group(1) if where_match else ''
    wo = where_match.group(2) if where_match else ''
    wv = _parse_where_value(where_match.group(3).strip()) if where_match else None
    ob = order_match.group(1) if order_match else ''
    od = (order_match.group(2) or '').lower() == 'desc' if order_match else False
    return ComposedQuery(
        kind='composed', first=first, second=second, raw=raw,
        where_field=wf, where_op=wo, where_value=wv,
        order_by=ob, order_desc=od,
    )


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
        second_text = then_match[1]
        second_clean, where_match, order_match = _extract_where_order(second_text)
        second = _parse_single(second_clean)
        return _build_composed(first, second, raw, where_match, order_match)

    # Check for WHERE/ORDER BY on single query
    clean_text, where_match, order_match = _extract_where_order(text)
    query = _parse_single(clean_text)

    if where_match or order_match:
        return _build_composed(query, HelpQuery(kind='help'), raw, where_match, order_match)

    return query


# ─── Executor ─────────────────────────────────────────────────────

class QueryExecutor:
    """Executes SemanticQuery against a RuntimePDG + FactExtractor + NarrativeEngine.

    Uses the QueryPlanner + SemanticAlgebra pipeline internally.
    Records a QueryTrace showing HOW the query was executed.
    Caches results by query.query_hash() for deterministic replay.
    """

    def __init__(self, pdg, facts, narrative_engine, cache_size: int = 128,
                 cache_ttl: float = 600, timeout_seconds: float = 30.0):
        self.pdg = pdg
        self.facts = facts
        self.engine = narrative_engine
        self._timeout = timeout_seconds
        from .algebra import QueryPlanner
        self._planner = QueryPlanner()
        from .cache import QueryResultCache
        self._cache = QueryResultCache(max_size=cache_size, ttl_seconds=cache_ttl)

    def execute(self, query: SemanticQuery) -> dict:
        """Execute a query and return a structured result with trace."""
        from .metrics import query_metrics

        # Cache check — skip planning + execution entirely
        cached = self._cache.get(query)
        if cached is not None:
            cached['_cache'] = {'hit': True, 'key': query.query_hash()}
            query_metrics.record(query.kind, duration_ms=0, cached=True)
            return cached

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

        # Timeout check
        elapsed = (time.time() - t0) * 1000
        if elapsed > self._timeout * 1000:
            trace.add('timeout', f'Query timed out after {elapsed:.0f}ms')
            result = {'success': False, 'error': f'Query timed out after {elapsed:.0f}ms'}
            query_metrics.record(query.kind, duration_ms=elapsed, error=True)
            return result

        # Handle HELP specially (empty plan)
        if query.kind == 'help':
            result = self._exec_help(query, trace)
        else:
            result = op_result.to_dict()

        trace.total_ms = (time.time() - t0) * 1000
        result['_trace'] = trace.to_dict()
        result['_cache'] = {'stored': True, 'key': query.query_hash()}
        self._cache.put(query, result)
        query_metrics.record(query.kind, duration_ms=trace.total_ms, cached=False)
        return result

    def cache_stats(self) -> dict:
        """Return cache performance stats."""
        return self._cache.stats()

    def cache_clear(self) -> None:
        """Clear the query result cache."""
        self._cache.clear()

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
