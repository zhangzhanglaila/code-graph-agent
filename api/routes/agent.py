"""Agent routes — intelligent code analysis via observe → reason → act pipeline."""

from __future__ import annotations
import os
import sys

from fastapi import APIRouter, Depends

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from api.services.analysis import prepare_execution
from api.container import get_container, AppContainer

router = APIRouter()


@router.post("/api/agent/analyze")
async def agent_analyze(req: dict, container: AppContainer = Depends(get_container)):
    """Full agent analysis: observe → reason → act.

    Request body:
        code: str — source code to analyze
        func_name: str — function to execute
        language: str — 'python' (default)
        question: str — optional question to guide reasoning
    """
    func_file = None
    try:
        code = req.get('code', '')
        func_name = req.get('func_name', '')
        language = req.get('language', 'python')
        question = req.get('question', '')

        module, func, timeline, result, func_file = prepare_execution(
            code, func_name, language,
        )

        AgentEngine = container.agent_engine_class
        engine = AgentEngine()
        agent_result = engine.run(timeline, question=question)

        return {
            'success': True,
            'agent': agent_result,
            'execution_result': repr(result),
        }
    except Exception as e:
        import traceback
        return {'success': False, 'error': str(e), 'traceback': traceback.format_exc()}
    finally:
        if func_file and os.path.exists(func_file):
            try:
                os.unlink(func_file)
            except OSError:
                pass


@router.post("/api/agent/observe")
async def agent_observe(req: dict, container: AppContainer = Depends(get_container)):
    """Observe and reason without executing actions.

    Returns observations, state, and reasoning chain only.
    """
    func_file = None
    try:
        code = req.get('code', '')
        func_name = req.get('func_name', '')
        language = req.get('language', 'python')
        question = req.get('question', '')

        module, func, timeline, result, func_file = prepare_execution(
            code, func_name, language,
        )

        AgentEngine = container.agent_engine_class
        engine = AgentEngine()
        agent_result = engine.observe_and_reason(timeline, question=question)

        return {
            'success': True,
            'agent': agent_result,
        }
    except Exception as e:
        import traceback
        return {'success': False, 'error': str(e), 'traceback': traceback.format_exc()}
    finally:
        if func_file and os.path.exists(func_file):
            try:
                os.unlink(func_file)
            except OSError:
                pass
