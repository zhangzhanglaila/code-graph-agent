"""Statistics Catalog — data source statistics for cost-based optimization.

Collects and maintains statistics about PDG nodes, facts, and edges
to enable cost estimation for plan optimization.

Statistics:
    - fact cardinality (how many facts of each kind)
    - field selectivity (how selective each filter field is)
    - graph degree (avg edges per node)
    - traversal fanout (expected nodes from backward/forward traversal)
    - cache hit ratio (from QueryResultCache)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
import math


@dataclass
class FactStats:
    """Statistics for a fact kind."""
    kind: str
    count: int = 0
    field_selectivity: Dict[str, float] = field(default_factory=dict)
    avg_evidence_count: float = 0.0


@dataclass
class GraphStats:
    """Statistics for the PDG graph."""
    node_count: int = 0
    edge_count: int = 0
    avg_degree: float = 0.0
    max_degree: int = 0
    avg_backward_fanout: float = 0.0
    avg_forward_fanout: float = 0.0


@dataclass
class CatalogStats:
    """Full statistics catalog."""
    facts: Dict[str, FactStats] = field(default_factory=dict)
    graph: GraphStats = field(default_factory=GraphStats)
    total_facts: int = 0
    variable_count: int = 0
    version_count: int = 0


class StatisticsCatalog:
    """Collects and maintains statistics for cost-based optimization.

    Usage:
        catalog = StatisticsCatalog()
        catalog.collect(pdg, facts)
        stats = catalog.stats
        cost = estimate_cost(plan, stats)
    """

    def __init__(self):
        self.stats = CatalogStats()

    def collect(self, pdg: Any, facts: list) -> CatalogStats:
        """Collect statistics from PDG and facts."""
        self._collect_graph_stats(pdg)
        self._collect_fact_stats(facts)
        self._collect_variable_stats(pdg)
        return self.stats

    def _collect_graph_stats(self, pdg: Any):
        """Collect PDG graph statistics."""
        gs = self.stats.graph
        gs.node_count = len(pdg.nodes) if hasattr(pdg, 'nodes') else 0

        # Count edges
        if hasattr(pdg, 'edges'):
            gs.edge_count = len(pdg.edges)
            # Compute degree
            degree_map: Dict[int, int] = {}
            for e in pdg.edges:
                src = getattr(e, 'source', 0)
                tgt = getattr(e, 'target', 0)
                degree_map[src] = degree_map.get(src, 0) + 1
                degree_map[tgt] = degree_map.get(tgt, 0) + 1
            if degree_map:
                gs.avg_degree = sum(degree_map.values()) / len(degree_map)
                gs.max_degree = max(degree_map.values())

        # Estimate traversal fanout
        if hasattr(pdg, 'backward_slice') and gs.node_count > 0:
            sample_nodes = list(pdg.nodes.keys())[:min(5, gs.node_count)]
            backward_sizes = []
            forward_sizes = []
            for nid in sample_nodes:
                try:
                    sr = pdg.backward_slice(nid)
                    backward_sizes.append(len(sr.steps) if hasattr(sr, 'steps') else 0)
                except Exception:
                    pass
                try:
                    impact = pdg.forward_impact(nid)
                    forward_sizes.append(len(impact.steps) if hasattr(impact, 'steps') else 0)
                except Exception:
                    pass
            if backward_sizes:
                gs.avg_backward_fanout = sum(backward_sizes) / len(backward_sizes)
            if forward_sizes:
                gs.avg_forward_fanout = sum(forward_sizes) / len(forward_sizes)

    def _collect_fact_stats(self, facts: list):
        """Collect fact statistics by kind."""
        kind_counts: Dict[str, int] = {}
        kind_evidence: Dict[str, List[int]] = {}
        field_freq: Dict[str, Dict[str, int]] = {}

        for fact in facts:
            kind = getattr(fact, 'kind', 'unknown')
            kind_counts[kind] = kind_counts.get(kind, 0) + 1

            # Evidence count
            evidence = getattr(fact, 'evidence', [])
            if kind not in kind_evidence:
                kind_evidence[kind] = []
            kind_evidence[kind].append(len(evidence))

            # Field frequency for selectivity
            d = fact.to_dict() if hasattr(fact, 'to_dict') else {}
            for key, val in d.items():
                if key not in field_freq:
                    field_freq[key] = {}
                str_val = str(val)
                field_freq[key][str_val] = field_freq[key].get(str_val, 0) + 1

        # Build FactStats per kind
        for kind, count in kind_counts.items():
            fs = FactStats(kind=kind, count=count)
            # Selectivity = distinct_values / total_count
            for field_name, val_counts in field_freq.items():
                if field_name in ('kind', 'description', 'subject', 'evidence'):
                    fs.field_selectivity[field_name] = len(val_counts) / max(count, 1)
            # Average evidence count
            ev_counts = kind_evidence.get(kind, [])
            if ev_counts:
                fs.avg_evidence_count = sum(ev_counts) / len(ev_counts)
            self.stats.facts[kind] = fs

        self.stats.total_facts = len(facts)

    def _collect_variable_stats(self, pdg: Any):
        """Collect variable and version statistics."""
        if not hasattr(pdg, 'nodes'):
            return
        variables: Set[str] = set()
        total_versions = 0
        for node in pdg.nodes.values():
            vars_dict = getattr(node, 'vars', {})
            for var_name, vv in vars_dict.items():
                variables.add(var_name)
                total_versions += getattr(vv, 'version', 0) + 1
        self.stats.variable_count = len(variables)
        self.stats.version_count = total_versions

    def fact_count(self, kind: str = '') -> int:
        """Get fact count, optionally filtered by kind."""
        if kind and kind in self.stats.facts:
            return self.stats.facts[kind].count
        return self.stats.total_facts

    def field_selectivity(self, field: str, kind: str = '') -> float:
        """Get field selectivity (0.0 = all same, 1.0 = all unique)."""
        if kind and kind in self.stats.facts:
            return self.stats.facts[kind].field_selectivity.get(field, 0.5)
        # Average across all kinds
        vals = [fs.field_selectivity.get(field, 0.5) for fs in self.stats.facts.values()]
        return sum(vals) / len(vals) if vals else 0.5

    def to_dict(self) -> dict:
        return {
            'total_facts': self.stats.total_facts,
            'fact_kinds': {k: {'count': v.count, 'selectivity': v.field_selectivity}
                          for k, v in self.stats.facts.items()},
            'graph': {
                'nodes': self.stats.graph.node_count,
                'edges': self.stats.graph.edge_count,
                'avg_degree': round(self.stats.graph.avg_degree, 2),
                'avg_backward_fanout': round(self.stats.graph.avg_backward_fanout, 2),
                'avg_forward_fanout': round(self.stats.graph.avg_forward_fanout, 2),
            },
            'variables': self.stats.variable_count,
            'versions': self.stats.version_count,
        }
