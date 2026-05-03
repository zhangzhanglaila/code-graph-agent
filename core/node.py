"""Graph node representation for code lines and config items."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CodeNode:
    """A node in the causal graph."""

    node_id: str                          # "file:line" or "config:key"
    file_path: str
    line_number: int
    code_content: str = ""
    node_type: str = "CODE"               # CODE | CONFIG | ERROR | ENTRY
    semantic_label: str = ""              # human-readable purpose
    existence_reason: Optional[str] = None  # why this line exists

    # LLM reasoning results
    root_cause_info: Optional[dict] = field(default=None)

    def __hash__(self):
        return hash(self.node_id)

    def __eq__(self, other):
        if not isinstance(other, CodeNode):
            return NotImplemented
        return self.node_id == other.node_id

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "code_content": self.code_content,
            "node_type": self.node_type,
            "semantic_label": self.semantic_label,
            "existence_reason": self.existence_reason,
            "root_cause_info": self.root_cause_info,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CodeNode:
        return cls(**data)

    @staticmethod
    def make_id(file_path: str, line_number: int) -> str:
        return f"{file_path}:{line_number}"

    @staticmethod
    def config_id(key: str) -> str:
        return f"config:{key}"
