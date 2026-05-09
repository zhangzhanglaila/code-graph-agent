"""FastAPI backend — connects Python analysis engine to Vue frontend.

Modular router architecture. Each domain has its own route module.
"""

from __future__ import annotations
import os
import sys
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

app = FastAPI(title="Why-Code-Agent API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Records endpoint latency for all API requests."""

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith('/api/'):
            return await call_next(request)
        t0 = time.time()
        error = False
        try:
            response = await call_next(request)
            if response.status_code >= 400:
                error = True
            return response
        except Exception:
            error = True
            raise
        finally:
            from dynamic.query.execution_metrics import execution_metrics
            elapsed = (time.time() - t0) * 1000
            execution_metrics.record_endpoint(request.url.path, elapsed, error)


app.add_middleware(MetricsMiddleware)

# Serve output directory for generated HTML files
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")

# ── Register Route Modules ───────────────────────────────────────

from api.routes.analyze import router as analyze_router
from api.routes.replay import router as replay_router
from api.routes.identity import router as identity_router
from api.routes.query import router as query_router
from api.routes.session import router as session_router
from api.routes.optimize import router as optimize_router
from api.routes.github import router as github_router
from api.routes.agent import router as agent_router
from api.routes.metrics import router as metrics_router

app.include_router(analyze_router)
app.include_router(replay_router)
app.include_router(identity_router)
app.include_router(query_router)
app.include_router(session_router)
app.include_router(optimize_router)
app.include_router(github_router)
app.include_router(agent_router)
app.include_router(metrics_router)
