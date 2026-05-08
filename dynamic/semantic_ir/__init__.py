"""Semantic IR — language-agnostic execution model.

The SemanticExecutionModel is the contract between runtime and semantic layers.
Runtime adapters (Python, JS, WASM) lower into this model.
Semantic modules consume only this model — never runtime structures directly.
"""

from dynamic.semantic_ir.model import (
    SemanticExecutionModel, SemanticNode, SemanticEdge, SemanticVariable,
    SemanticEdgeKind, build_from_pdg,
)
