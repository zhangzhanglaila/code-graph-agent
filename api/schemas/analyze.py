"""Analyze schemas — Request models for analysis endpoints."""

from typing import Optional
from pydantic import BaseModel


class AnalyzeRequest(BaseModel):
    code: str
    language: str = "python"
    error_line: Optional[int] = None
    config: Optional[str] = None


class InsightRequest(BaseModel):
    code: str
    func_name: str = ""
    language: str = "python"


class DSVizRequest(BaseModel):
    code: str
    func_name: str = ""
    language: str = "python"


class RunRequest(BaseModel):
    code: str
    func_name: str = ""
    timeout: int = 10


class ExplainRequest(BaseModel):
    code: str
    func_name: str = ""
    language: str = "python"
    provider: str = "mock"
    api_key: str = ""


class ExplainStepsRequest(BaseModel):
    code: str = ""
    func_name: str = ""
    language: str = "python"
    provider: str = "mock"
    api_key: str = ""
    session_id: str = ""


class ExplainStepFocusRequest(BaseModel):
    code: str = ""
    func_name: str = ""
    language: str = "python"
    step_index: int = 0
    window_before: int = 2
    window_after: int = 2
    provider: str = "mock"
    api_key: str = ""
    session_id: str = ""


class PatternNarrativeRequest(BaseModel):
    code: str
    func_name: str = ""
    language: str = "python"
    session_id: str = ""


class SubproblemGraphRequest(BaseModel):
    code: str
    func_name: str = ""
    language: str = "python"


class AnalyzeFullRequest(BaseModel):
    code: str
    func_name: str = ""
    language: str = "python"
