"""Explanation IR — the contract between semantic layer and narrative rendering.

NarrativePlanner produces ExplanationIR from semantic data.
NarrativeRenderer consumes ExplanationIR to produce Narrative objects.

This module has ZERO dependencies on runtime or semantic internals.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EvidenceUnit:
    """One unit of resolved evidence — the atomic building block of an explanation.

    All code references are pre-resolved to strings.
    No graph/model access needed by consumers.
    """
    id: str                          # unique identifier
    kind: str                        # 'target'|'root_cause'|'data_flow'|'loop'|'branch'|'result'|'variable_origin'|'variable_evolution'|'variable_final'|'source'|'impact_flow'|'affected_output'
    heading: str                     # short heading
    description: str                 # pre-rendered description text
    step_ids: List[int] = field(default_factory=list)     # related step IDs
    variables: List[str] = field(default_factory=list)     # related variable names
    evidence_facts: List[int] = field(default_factory=list)  # fact indices
    priority: int = 0                # sort priority (lower = more important)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExplanationIR:
    """Complete explanation plan — pure data, zero graph references.

    This is what NarrativePlanner produces and NarrativeRenderer consumes.
    """
    title: str
    summary: str
    units: List[EvidenceUnit] = field(default_factory=list)
    variable_stories: List[dict] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
