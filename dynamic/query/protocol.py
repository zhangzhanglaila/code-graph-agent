"""Remote Query Protocol — wire format for distributed query execution.

Defines the request/response envelope for remote query execution.
Supports HTTP, WebSocket, and future binary protocols.

Wire format:
    Request:  QueryEnvelope (query + params + hints)
    Response: QueryResponse (result + plan + stats + trace)

Usage:
    from dynamic.query.protocol import QueryEnvelope, QueryResponse
    envelope = QueryEnvelope(query="WHY result", client_id="agent01")
    response = executor.execute_remote(envelope)
"""

from __future__ import annotations
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .dsl import SemanticQuery, parse_query


# ─── Request Envelope ────────────────────────────────────────────

@dataclass
class ExecutionHints:
    """Hints for remote execution optimization."""
    cache: bool = True              # use result cache
    optimize: bool = True           # run optimizer
    max_cost: float = 1000.0        # abort if estimated cost exceeds this
    timeout_ms: float = 30000.0     # execution timeout
    trace: bool = False             # include execution trace
    projection: List[str] = field(default_factory=list)  # requested fields

    def to_dict(self) -> dict:
        d = {}
        if not self.cache: d['cache'] = False
        if not self.optimize: d['optimize'] = False
        if self.max_cost != 1000.0: d['max_cost'] = self.max_cost
        if self.timeout_ms != 30000.0: d['timeout_ms'] = self.timeout_ms
        if self.trace: d['trace'] = True
        if self.projection: d['projection'] = self.projection
        return d

    @classmethod
    def from_dict(cls, d: dict) -> 'ExecutionHints':
        return cls(
            cache=d.get('cache', True),
            optimize=d.get('optimize', True),
            max_cost=d.get('max_cost', 1000.0),
            timeout_ms=d.get('timeout_ms', 30000.0),
            trace=d.get('trace', False),
            projection=d.get('projection', []),
        )


@dataclass
class QueryEnvelope:
    """Wire-format request for remote query execution."""
    query: str                          # query text (DSL string)
    client_id: str = ''                 # originating client
    session_id: str = ''                # session context
    params: Dict[str, Any] = field(default_factory=dict)
    hints: ExecutionHints = field(default_factory=ExecutionHints)
    schema_version: str = '1.0.0'
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        d = {
            'query': self.query,
            'schema_version': self.schema_version,
            'timestamp': self.timestamp,
        }
        if self.client_id: d['client_id'] = self.client_id
        if self.session_id: d['session_id'] = self.session_id
        if self.params: d['params'] = self.params
        hints_dict = self.hints.to_dict()
        if hints_dict: d['hints'] = hints_dict
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> 'QueryEnvelope':
        return cls(
            query=d.get('query', ''),
            client_id=d.get('client_id', ''),
            session_id=d.get('session_id', ''),
            params=d.get('params', {}),
            hints=ExecutionHints.from_dict(d.get('hints', {})),
            schema_version=d.get('schema_version', '1.0.0'),
            timestamp=d.get('timestamp', time.time()),
        )

    @classmethod
    def from_json(cls, text: str) -> 'QueryEnvelope':
        return cls.from_dict(json.loads(text))

    def parse_query(self) -> SemanticQuery:
        """Parse the query text into a SemanticQuery AST."""
        return parse_query(self.query)


# ─── Response Envelope ───────────────────────────────────────────

@dataclass
class QueryResponse:
    """Wire-format response from remote query execution."""
    success: bool
    result: Dict[str, Any] = field(default_factory=dict)
    plan: Optional[Dict[str, Any]] = None
    statistics: Optional[Dict[str, Any]] = None
    trace: Optional[Dict[str, Any]] = None
    error: str = ''
    schema_version: str = '1.0.0'
    execution_ms: float = 0.0
    cached: bool = False

    def to_dict(self) -> dict:
        d = {
            'success': self.success,
            'schema_version': self.schema_version,
            'execution_ms': round(self.execution_ms, 2),
        }
        if self.result: d['result'] = self.result
        if self.plan: d['plan'] = self.plan
        if self.statistics: d['statistics'] = self.statistics
        if self.trace: d['trace'] = self.trace
        if self.error: d['error'] = self.error
        if self.cached: d['cached'] = True
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    @classmethod
    def from_dict(cls, d: dict) -> 'QueryResponse':
        return cls(
            success=d.get('success', False),
            result=d.get('result', {}),
            plan=d.get('plan'),
            statistics=d.get('statistics'),
            trace=d.get('trace'),
            error=d.get('error', ''),
            schema_version=d.get('schema_version', '1.0.0'),
            execution_ms=d.get('execution_ms', 0.0),
            cached=d.get('cached', False),
        )

    @classmethod
    def from_json(cls, text: str) -> 'QueryResponse':
        return cls.from_dict(json.loads(text))

    @classmethod
    def error_response(cls, error: str) -> 'QueryResponse':
        return cls(success=False, error=error)
