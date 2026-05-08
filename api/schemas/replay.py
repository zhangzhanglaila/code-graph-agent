"""Replay schemas — Request models for failure attribution/causal chain endpoints."""

from pydantic import BaseModel


class ReplayInsightRequest(BaseModel):
    code: str
    func_name: str = ""
    language: str = "python"
