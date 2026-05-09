"""Semantic Query Result — typed, graph-free containers for query output.

These sit between the PDG layer and the Evidence layer.
They carry pre-resolved data (code snippets, line numbers) so downstream
consumers never need to touch the runtime graph.

Duck-typed to be compatible with PDG's SliceResult/VarVersion
so existing code continues to work during migration.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


# ── Lightweight replacements for runtime types ───────────────────

@dataclass
class QueryEdge:
    """A dependency edge — replaces RuntimeEdge at the semantic level."""
    source: int
    target: int
    kind: str           # 'data' | 'control'
    var: str = ''
    source_version: int = 0
    target_version: int = 0


@dataclass
class QueryVarVersion:
    """A variable snapshot — replaces VarVersion at the semantic level."""
    name: str
    version: int
    value: str
    type: str
    memory_id: int = 0
    is_changed: bool = False
    is_new: bool = False


# ── Query result types ───────────────────────────────────────────

@dataclass
class ResolvedStepInfo:
    """Pre-resolved step data — code snippet and line number."""
    code: str
    line: int


@dataclass
class BackwardSliceResult:
    """Result of a backward slice query — graph-free."""
    target_step: int
    target_var: str
    steps: List[int]
    edges: List[QueryEdge]
    root_causes: List[int]
    depth_map: Dict[int, int]
    explanation: List[str] = field(default_factory=list)
    resolved_steps: Dict[int, ResolvedStepInfo] = field(default_factory=dict)


@dataclass
class ForwardImpactResult:
    """Result of a forward impact query — graph-free."""
    target_step: int
    target_var: str
    steps: List[int]
    edges: List[QueryEdge]
    root_causes: List[int]          # leaf nodes in forward direction
    depth_map: Dict[int, int]
    explanation: List[str] = field(default_factory=list)
    resolved_steps: Dict[int, ResolvedStepInfo] = field(default_factory=dict)


@dataclass
class VariableTraceResult:
    """Result of a variable trace query — graph-free."""
    variable: str
    history: List[Tuple[int, QueryVarVersion]]
    version_chain: List[Tuple[int, int, int, int]]  # (src, tgt, src_ver, tgt_ver)
