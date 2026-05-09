"""Remote Query Executor — server-side handler + client SDK.

Server: receives QueryEnvelope, runs through Planner → Optimizer → Executor.
Client: sends QueryEnvelope, receives QueryResponse.

Usage:
    # Server-side (in API route):
    from dynamic.query.remote import RemoteQueryHandler
    handler = RemoteQueryHandler(pdg, facts, engine)
    response = handler.handle(envelope)

    # Client-side:
    from dynamic.query.remote import RemoteQueryClient
    client = RemoteQueryClient("http://localhost:8000")
    response = client.execute("WHY result")
"""

from __future__ import annotations
import time
from typing import Any, Dict, Optional

from .protocol import QueryEnvelope, QueryResponse, ExecutionHints
from .dsl import parse_query, QueryExecutor
from .algebra import QueryPlanner, LogicalPlan
from .plan_tree import flat_plan_to_tree, tree_to_flat_plan
from .optimizer import QueryOptimizer
from .statistics import StatisticsCatalog
from .cost_model import CostEstimator


class RemoteQueryHandler:
    """Server-side handler for remote query execution.

    Pipeline: parse → plan → optimize → execute → response
    """

    def __init__(self, pdg: Any, facts: list, engine: Any,
                 catalog: Optional[StatisticsCatalog] = None):
        self.pdg = pdg
        self.facts = facts
        self.engine = engine
        self.executor = QueryExecutor(pdg, facts, engine)
        self.catalog = catalog or StatisticsCatalog()
        self.catalog.collect(pdg, facts)
        self.optimizer = QueryOptimizer(catalog=self.catalog)
        self.planner = QueryPlanner()

    def handle(self, envelope: QueryEnvelope) -> QueryResponse:
        """Execute a query envelope and return a response."""
        t0 = time.time()

        try:
            # Parse
            query = envelope.parse_query()

            # Plan
            plan = self.planner.plan(query)

            # Optimize (if requested)
            plan_info = None
            if envelope.hints.optimize:
                tree = flat_plan_to_tree(plan)
                optimized_tree = self.optimizer.optimize(tree)
                plan = tree_to_flat_plan(optimized_tree, plan.query_kind)
                plan_info = {
                    'description': plan.describe(),
                    'optimizer_stats': self.optimizer.stats(),
                }

            # Cost check
            if envelope.hints.max_cost < 1000.0:
                tree = flat_plan_to_tree(plan)
                estimator = CostEstimator(self.catalog)
                cost = estimator.estimate(tree)
                if cost.total > envelope.hints.max_cost:
                    return QueryResponse.error_response(
                        f'Estimated cost {cost.total:.1f} exceeds limit {envelope.hints.max_cost:.1f}'
                    )

            # Execute
            result = self.executor.execute(query)

            # Build response
            response = QueryResponse(
                success=True,
                result=result,
                plan=plan_info,
                statistics=self.catalog.to_dict() if envelope.hints.trace else None,
                trace=result.get('_trace') if envelope.hints.trace else None,
                execution_ms=(time.time() - t0) * 1000,
                cached=result.get('_cache', {}).get('hit', False),
            )

            return response

        except Exception as e:
            return QueryResponse(
                success=False,
                error=str(e),
                execution_ms=(time.time() - t0) * 1000,
            )


class RemoteQueryClient:
    """Client SDK for remote query execution.

    Wraps HTTP calls to a remote query server.
    Falls back to local execution if remote is unavailable.
    """

    def __init__(self, base_url: str = '', timeout: float = 30.0):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self._local_handler: Optional[RemoteQueryHandler] = None

    def set_local_fallback(self, handler: RemoteQueryHandler):
        """Set a local handler for fallback when remote is unavailable."""
        self._local_handler = handler

    def execute(self, query_text: str, **hints) -> QueryResponse:
        """Execute a query, optionally via remote server.

        Args:
            query_text: DSL query string (e.g., "WHY result")
            **hints: ExecutionHints overrides (cache, optimize, trace, etc.)
        """
        envelope = QueryEnvelope(
            query=query_text,
            hints=ExecutionHints(**hints) if hints else ExecutionHints(),
        )

        if self.base_url:
            return self._execute_remote(envelope)
        elif self._local_handler:
            return self._local_handler.handle(envelope)
        else:
            return QueryResponse.error_response('No remote URL or local handler configured')

    def execute_envelope(self, envelope: QueryEnvelope) -> QueryResponse:
        """Execute a pre-built envelope."""
        if self.base_url:
            return self._execute_remote(envelope)
        elif self._local_handler:
            return self._local_handler.handle(envelope)
        else:
            return QueryResponse.error_response('No remote URL or local handler configured')

    def _execute_remote(self, envelope: QueryEnvelope) -> QueryResponse:
        """Send query to remote server via HTTP."""
        try:
            import urllib.request
            import urllib.error

            url = f'{self.base_url}/api/query/remote'
            data = envelope.to_json().encode('utf-8')
            req = urllib.request.Request(
                url,
                data=data,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )

            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode('utf-8')
                return QueryResponse.from_json(body)

        except urllib.error.URLError as e:
            # Fallback to local if configured
            if self._local_handler:
                return self._local_handler.handle(envelope)
            return QueryResponse.error_response(f'Remote unavailable: {e}')
        except Exception as e:
            return QueryResponse.error_response(str(e))
