"""Optimize schemas — Request models for feedback loop/consolidation endpoints."""

from typing import List, Optional
from pydantic import BaseModel


class ActionOutcomeRequest(BaseModel):
    execution_id: str
    action_type: str
    action_title: str
    step_count_before: int = 0
    step_count_after: int = 0
    time_complexity_before: str = ''
    time_complexity_after: str = ''
    invariant_violations_before: int = 0
    invariant_violations_after: int = 0
    total_calls_before: int = 0
    total_calls_after: int = 0
    code_before: str = ''
    code_after: str = ''
    user_feedback: Optional[str] = None
    notes: str = ''


class PrepareExecutionRequest(BaseModel):
    action_type: str
    action_title: str
    step_count: int = 0
    time_complexity: str = ''
    invariant_violations: int = 0
    total_calls: int = 0
    code_before: str = ''


class ConceptQueryRequest(BaseModel):
    action_type: str = ''
    tags: List[str] = []
    top_k: int = 10
