"""Session routes — semantic investigation sessions."""

from __future__ import annotations
import os
import sys

from fastapi import APIRouter, Depends

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from dynamic.semantic_session import SemanticSession
from dynamic.query.dsl import parse_query

from api.services.analysis import prepare_execution
from api.schemas.session import SessionCreateRequest, SessionQueryRequest, SessionNoteRequest
from api.container import get_container, AppContainer

router = APIRouter()
SESSION_DIR = os.path.join(PROJECT_ROOT, '.semantic-session')


@router.post("/api/session/create")
async def session_create(req: SessionCreateRequest):
    """Create a new semantic investigation session."""
    try:
        session = SemanticSession.create(SESSION_DIR, code=req.code, description=req.description)
        return {"success": True, "session": session.meta.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/session/query")
async def session_query(req: SessionQueryRequest, container: AppContainer = Depends(get_container)):
    """Execute a query within a session."""
    func_file = None
    try:
        module, func, timeline, result, func_file = prepare_execution(
            req.code, req.func_name, req.language,
        )

        pipeline = container.build_pipeline(timeline)
        parsed = parse_query(req.query_text)
        query_result = pipeline.executor.execute(parsed)

        session = SemanticSession.load_latest(SESSION_DIR)
        if session:
            session.save_query(req.query_text, query_result, pipeline.pdg, pipeline.facts)

        return {"success": True, "result": query_result, "session_id": session.meta.session_id if session else None}
    except Exception as e:
        import traceback
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
    finally:
        if func_file:
            try:
                os.unlink(func_file)
            except OSError:
                pass


@router.get("/api/session/queries")
async def session_queries():
    """List all queries in the current session."""
    try:
        session = SemanticSession.load_latest(SESSION_DIR)
        if not session:
            return {"success": True, "queries": []}
        return {"success": True, "queries": session.list_queries()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/session/note")
async def session_note(req: SessionNoteRequest):
    """Add a note to a query in the session."""
    try:
        session = SemanticSession.load_latest(SESSION_DIR)
        if not session:
            return {"success": False, "error": "No active session"}
        session.add_note(req.query_id, req.note)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/api/session/export")
async def session_export():
    """Export session as markdown report."""
    try:
        session = SemanticSession.load_latest(SESSION_DIR)
        if not session:
            return {"success": False, "error": "No active session"}
        report = session.export_report()
        return {"success": True, "report": report, "json": session.export_json()}
    except Exception as e:
        return {"success": False, "error": str(e)}
