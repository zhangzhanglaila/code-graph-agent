"""Identity schemas — Request models for identity/fingerprint/similarity endpoints."""

from pydantic import BaseModel


class IdentityRequest(BaseModel):
    code: str
    func_name: str = ""
    language: str = "python"


class SimilarityRequest(BaseModel):
    code_a: str
    code_b: str
    func_name: str = ""
    language: str = "python"


class SemanticDiffRequest(BaseModel):
    code_a: str
    code_b: str
    func_name: str = ""
    language: str = "python"
