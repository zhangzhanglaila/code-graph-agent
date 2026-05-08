"""Session schemas — Request models for semantic investigation sessions."""

from pydantic import BaseModel


class SessionCreateRequest(BaseModel):
    code: str = ''
    description: str = ''


class SessionQueryRequest(BaseModel):
    code: str
    query_text: str
    func_name: str = ''
    language: str = 'python'


class SessionNoteRequest(BaseModel):
    query_id: int
    note: str
