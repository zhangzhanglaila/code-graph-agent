"""Query schemas — Request models for query endpoints."""

from pydantic import BaseModel


class QueryRequest(BaseModel):
    code: str
    query: dict = {}
    text: str = ""
    func_name: str = ""
    language: str = "python"
