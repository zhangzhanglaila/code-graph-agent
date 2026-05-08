"""Semantic Evidence IR — graph-free evidence objects for narrative planning.

These types sit between the query layer and the narrative planner.
They contain NO references to graph nodes, edges, or runtime structures.
Only pre-resolved semantic content: code snippets, variable values, relationships.

The evidence lowering layer (build_*_evidence) is the ONLY place that
converts model/graph data into evidence objects.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


# ── Core evidence types ──────────────────────────────────────────

@dataclass
class ResolvedStep:
    """A single execution step, fully resolved to strings."""
    id: int
    code: str
    line: int


@dataclass
class DataFlowChain:
    """A chain of data flow for one variable."""
    variable: str
    steps: List[ResolvedStep] = field(default_factory=list)


@dataclass
class ControlCondition:
    """A condition that controls execution flow."""
    condition_step: ResolvedStep
    description: str = ""


@dataclass
class VariableEvolution:
    """A variable's evolution through versions."""
    variable: str
    versions: List[Dict[str, Any]] = field(default_factory=list)
    # Each version: {'step_id': int, 'value': str, 'version': int}


@dataclass
class FactEvidence:
    """A semantic fact with resolved description."""
    index: int
    kind: str
    subject: str
    description: str
    evidence_steps: List[int] = field(default_factory=list)


# ── Evidence collection — what the Planner consumes ──────────────

@dataclass
class EvidenceCollection:
    """A complete set of pre-resolved evidence for narrative planning.

    This is the Planner's input contract. Zero graph references.
    Built by the evidence lowering layer from model + query results.
    """
    kind: str  # 'backward_slice' | 'variable' | 'impact'

    # Target/source info
    target: Optional[ResolvedStep] = None
    target_var: str = ""

    # Structural evidence
    root_causes: List[ResolvedStep] = field(default_factory=list)
    data_flows: List[DataFlowChain] = field(default_factory=list)
    control_conditions: List[ControlCondition] = field(default_factory=list)
    variable_evolutions: List[VariableEvolution] = field(default_factory=list)

    # Facts
    loop_facts: List[FactEvidence] = field(default_factory=list)
    accumulation_facts: List[FactEvidence] = field(default_factory=list)

    # Impact-specific
    impact_flows: List[DataFlowChain] = field(default_factory=list)
    affected_outputs: List[ResolvedStep] = field(default_factory=list)

    # Summary metadata
    step_count: int = 0
    root_cause_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
