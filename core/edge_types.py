"""Causal edge types for code causality graph."""

from enum import Enum


class EdgeType(str, Enum):
    """Six core causal edge types."""

    # Static edges
    DATA_DEPENDENCY = "DATA_DEPENDENCY"      # variable/parameter flow
    CALL_RELATION = "CALL_RELATION"          # function call chain
    CONFIG_INFLUENCE = "CONFIG_INFLUENCE"    # config item -> code line

    # Dynamic edges
    RUNTIME_TRACE = "RUNTIME_TRACE"          # actual execution path
    THROWS = "THROWS"                        # exception propagation

    # Structural
    CONTROL_FLOW = "CONTROL_FLOW"            # if/for/while branching


EDGE_STYLES = {
    EdgeType.DATA_DEPENDENCY: {"color": "#2196F3", "dashes": False, "title": "Data Dependency"},
    EdgeType.CALL_RELATION: {"color": "#4CAF50", "dashes": False, "title": "Call Relation"},
    EdgeType.CONFIG_INFLUENCE: {"color": "#FF9800", "dashes": True, "title": "Config Influence"},
    EdgeType.RUNTIME_TRACE: {"color": "#E91E63", "dashes": False, "title": "Runtime Trace"},
    EdgeType.THROWS: {"color": "#F44336", "dashes": True, "title": "Throws Exception"},
    EdgeType.CONTROL_FLOW: {"color": "#9C27B0", "dashes": False, "title": "Control Flow"},
}
