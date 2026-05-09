"""Agent Execution IR — observe, reason, act on code execution.

Pipeline:
    Timeline → ObservationStream → AgentState → ReasoningChain → ActionPlan → ActionResult

Usage:
    from dynamic.agent import AgentEngine
    engine = AgentEngine()
    result = engine.run(timeline, question="Why does result change?")
"""

from .observation import Observation, ObservationStream
from .state import AgentState, KnowledgeBase
from .reasoning import Hypothesis, Evidence, ReasoningChain, AgentQuery
from .action import Action, ActionPlan, ActionResult
from .agent_engine import AgentEngine

__all__ = [
    'Observation', 'ObservationStream',
    'AgentState', 'KnowledgeBase',
    'Hypothesis', 'Evidence', 'ReasoningChain', 'AgentQuery',
    'Action', 'ActionPlan', 'ActionResult',
    'AgentEngine',
]
