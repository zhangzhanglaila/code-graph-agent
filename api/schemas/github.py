"""GitHub schemas — Request models for GitHub analysis endpoints."""

from pydantic import BaseModel


class GitHubAnalyzeRequest(BaseModel):
    repo_url: str
    file_path: str = ''
    func_name: str = ''
    max_files: int = 10


class ImportGraphRequest(BaseModel):
    repo_url: str
    max_files: int = 50
