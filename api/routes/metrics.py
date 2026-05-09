"""Metrics routes — system observability endpoints."""

from __future__ import annotations
import os
import sys

from fastapi import APIRouter

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from dynamic.query.metrics import query_metrics
from dynamic.query.execution_metrics import execution_metrics
from dynamic.agent.metrics import agent_metrics

router = APIRouter()


@router.get("/api/metrics")
async def all_metrics():
    """Get all system metrics: query, execution, and agent."""
    return {
        'query': query_metrics.snapshot(),
        'execution': execution_metrics.snapshot(),
        'agent': agent_metrics.snapshot(),
    }


@router.get("/api/metrics/query")
async def query_metrics_endpoint():
    """Get query-specific metrics."""
    return query_metrics.snapshot()


@router.get("/api/metrics/execution")
async def execution_metrics_endpoint():
    """Get execution pipeline metrics."""
    return execution_metrics.snapshot()


@router.get("/api/metrics/agent")
async def agent_metrics_endpoint():
    """Get agent reasoning metrics."""
    return agent_metrics.snapshot()


@router.post("/api/metrics/reset")
async def reset_metrics():
    """Reset all metrics counters."""
    query_metrics.reset()
    execution_metrics.reset()
    agent_metrics.reset()
    return {'success': True, 'message': 'All metrics reset'}
