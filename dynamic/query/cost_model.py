"""Cost Model — estimate execution cost for plan trees.

Uses statistics from StatisticsCatalog to estimate the cost of each
operator in a plan tree. Enables cost-based plan reordering.

Cost factors:
    cpu  — computation per row
    io   — data scanned / transferred
    mem  — memory for materialization
    rows — expected output cardinality

Usage:
    from dynamic.query.cost_model import CostEstimator
    estimator = CostEstimator(catalog)
    cost = estimator.estimate(tree)
    best = estimator.pick_cheaper(plan_a, plan_b)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from .plan_tree import (
    PlanNode, SelectNodesNode, SelectFactsNode, TraverseNode,
    CollectHistoryNode, FilterNodesNode, FilterFactsNode,
    SortNode, LimitNode, CompareNode, StatsNode, NarrateNode,
    ProjectNode, ComposeNode, TreeWalker,
)
from .statistics import StatisticsCatalog


@dataclass
class PlanCost:
    """Estimated cost of executing a plan."""
    cpu: float = 0.0       # computation units
    io: float = 0.0        # data scanned units
    mem: float = 0.0       # memory units
    rows: float = 0.0      # expected output rows
    total: float = -1.0    # weighted sum (-1 = auto-calculate)

    def __post_init__(self):
        if self.total < 0:
            self.total = (self.cpu * _CPU_WEIGHT +
                          self.io * _IO_WEIGHT +
                          self.mem * _MEM_WEIGHT)

    def __lt__(self, other: 'PlanCost') -> bool:
        return self.total < other.total

    def __le__(self, other: 'PlanCost') -> bool:
        return self.total <= other.total

    def to_dict(self) -> dict:
        return {
            'cpu': round(self.cpu, 2),
            'io': round(self.io, 2),
            'mem': round(self.mem, 2),
            'rows': round(self.rows, 2),
            'total': round(self.total, 2),
        }


# Cost weights (relative importance)
_CPU_WEIGHT = 1.0
_IO_WEIGHT = 5.0    # IO is 5x more expensive than CPU
_MEM_WEIGHT = 0.5


class CostEstimator:
    """Estimates execution cost for plan trees.

    Uses statistics catalog for cardinality/selectivity estimates.
    Walks the tree bottom-up, accumulating cost.
    """

    def __init__(self, catalog: StatisticsCatalog):
        self.catalog = catalog
        self.walker = TreeWalker()

    def estimate(self, root: PlanNode) -> PlanCost:
        """Estimate total cost of a plan tree (bottom-up)."""
        costs: dict[int, PlanCost] = {}

        def estimate_node(node: PlanNode) -> Optional[PlanNode]:
            cost = self._estimate_single(node, costs)
            costs[id(node)] = cost
            return None  # don't transform

        self.walker.walk(root, post_visit=estimate_node)

        root_cost = costs.get(id(root), PlanCost())
        return root_cost

    def pick_cheaper(self, a: PlanNode, b: PlanNode) -> PlanNode:
        """Return the plan with lower estimated cost."""
        cost_a = self.estimate(a)
        cost_b = self.estimate(b)
        return a if cost_a <= cost_b else b

    def compare(self, a: PlanNode, b: PlanNode) -> dict:
        """Compare two plans' costs."""
        cost_a = self.estimate(a)
        cost_b = self.estimate(b)
        return {
            'plan_a': cost_a.to_dict(),
            'plan_b': cost_b.to_dict(),
            'cheaper': 'a' if cost_a <= cost_b else 'b',
            'savings': abs(cost_a.total - cost_b.total),
        }

    def _estimate_single(self, node: PlanNode, costs: dict) -> PlanCost:
        """Estimate cost for a single node, given children's costs."""
        # Get children's total cost and output rows
        child_rows = 0.0
        child_cost = PlanCost()
        for child in node.children:
            cc = costs.get(id(child), PlanCost())
            child_rows += cc.rows
            child_cost.cpu += cc.cpu
            child_cost.io += cc.io
            child_cost.mem += cc.mem

        # ComposeNode's first/second
        if isinstance(node, ComposeNode):
            for sub in (node.first, node.second):
                if sub:
                    cc = costs.get(id(sub), PlanCost())
                    child_rows += cc.rows
                    child_cost.cpu += cc.cpu
                    child_cost.io += cc.io
                    child_cost.mem += cc.mem

        if isinstance(node, SelectNodesNode):
            return self._cost_select_nodes(node, child_rows)
        elif isinstance(node, SelectFactsNode):
            return self._cost_select_facts(node, child_rows)
        elif isinstance(node, TraverseNode):
            return self._cost_traverse(node, child_rows)
        elif isinstance(node, CollectHistoryNode):
            return self._cost_collect_history(node, child_rows)
        elif isinstance(node, FilterNodesNode):
            return self._cost_filter_nodes(node, child_rows)
        elif isinstance(node, FilterFactsNode):
            return self._cost_filter_facts(node, child_rows)
        elif isinstance(node, SortNode):
            return self._cost_sort(node, child_rows)
        elif isinstance(node, LimitNode):
            return self._cost_limit(node, child_rows)
        elif isinstance(node, CompareNode):
            return self._cost_compare(node, child_rows)
        elif isinstance(node, StatsNode):
            return self._cost_stats(node)
        elif isinstance(node, NarrateNode):
            return self._cost_narrate(node, child_rows, child_cost)
        elif isinstance(node, ProjectNode):
            return self._cost_project(node, child_rows, child_cost)
        elif isinstance(node, ComposeNode):
            return self._cost_compose(node, child_rows, child_cost)
        else:
            return PlanCost(rows=child_rows, total=child_cost.total)

    def _cost_select_nodes(self, node: SelectNodesNode, child_rows: float) -> PlanCost:
        # SelectNodes scans all nodes to find matches
        scanned = self.catalog.stats.graph.node_count or 10
        cpu = scanned * 0.1  # linear scan
        io = scanned * 0.01
        rows = 1 if node.step >= 0 else min(scanned, 10)
        return PlanCost(cpu=cpu, io=io, mem=0, rows=rows,
                        total=cpu * _CPU_WEIGHT + io * _IO_WEIGHT)

    def _cost_select_facts(self, node: SelectFactsNode, child_rows: float) -> PlanCost:
        # SelectFacts scans all facts
        scanned = self.catalog.stats.total_facts or 10
        cpu = scanned * 0.1
        io = scanned * 0.02
        # With predicate pushdown, effective rows are fewer
        if node.filter_field:
            selectivity = self.catalog.field_selectivity(node.filter_field)
            rows = min(scanned * selectivity, node.limit)
        else:
            rows = min(scanned, node.limit)
        mem = rows * 0.5
        return PlanCost(cpu=cpu, io=io, mem=mem, rows=rows,
                        total=cpu * _CPU_WEIGHT + io * _IO_WEIGHT + mem * _MEM_WEIGHT)

    def _cost_traverse(self, node: TraverseNode, child_rows: float) -> PlanCost:
        # Traversal cost depends on fanout
        if node.direction == 'backward':
            fanout = self.catalog.stats.graph.avg_backward_fanout or 5
        else:
            fanout = self.catalog.stats.graph.avg_forward_fanout or 5
        rows = child_rows * fanout
        cpu = rows * 0.2  # graph walking
        io = rows * 0.1
        return PlanCost(cpu=cpu, io=io, mem=0, rows=rows,
                        total=cpu * _CPU_WEIGHT + io * _IO_WEIGHT)

    def _cost_collect_history(self, node: CollectHistoryNode, child_rows: float) -> PlanCost:
        # History collection scans all nodes for variable versions
        scanned = self.catalog.stats.graph.node_count or 10
        avg_versions = self.catalog.stats.version_count / max(self.catalog.stats.variable_count, 1)
        rows = avg_versions
        cpu = scanned * 0.1
        io = scanned * 0.05
        return PlanCost(cpu=cpu, io=io, mem=rows * 0.2, rows=rows,
                        total=cpu * _CPU_WEIGHT + io * _IO_WEIGHT + rows * 0.2 * _MEM_WEIGHT)

    def _cost_filter_nodes(self, node: FilterNodesNode, child_rows: float) -> PlanCost:
        # Filter is cheap — just predicate evaluation
        cpu = child_rows * 0.01
        rows = child_rows * 0.3  # assume 30% selectivity
        return PlanCost(cpu=cpu, io=0, mem=0, rows=rows,
                        total=cpu * _CPU_WEIGHT)

    def _cost_filter_facts(self, node: FilterFactsNode, child_rows: float) -> PlanCost:
        cpu = child_rows * 0.02
        selectivity = self.catalog.field_selectivity(node.field) if node.field else 0.5
        rows = child_rows * selectivity
        return PlanCost(cpu=cpu, io=0, mem=0, rows=rows,
                        total=cpu * _CPU_WEIGHT)

    def _cost_sort(self, node: SortNode, child_rows: float) -> PlanCost:
        # Sort is O(n log n)
        cpu = child_rows * max(1, math.log2(max(child_rows, 2)))
        mem = child_rows * 0.5
        return PlanCost(cpu=cpu, io=0, mem=mem, rows=child_rows,
                        total=cpu * _CPU_WEIGHT + mem * _MEM_WEIGHT)

    def _cost_limit(self, node: LimitNode, child_rows: float) -> PlanCost:
        rows = min(child_rows, node.n)
        cpu = rows * 0.001  # trivial
        return PlanCost(cpu=cpu, io=0, mem=0, rows=rows,
                        total=cpu * _CPU_WEIGHT)

    def _cost_compare(self, node: CompareNode, child_rows: float) -> PlanCost:
        cpu = 2 * 0.5  # two node lookups
        return PlanCost(cpu=cpu, io=0, mem=0, rows=1,
                        total=cpu * _CPU_WEIGHT)

    def _cost_stats(self, node: StatsNode) -> PlanCost:
        cpu = self.catalog.stats.graph.node_count * 0.1
        io = 0
        return PlanCost(cpu=cpu, io=io, mem=0, rows=1,
                        total=cpu * _CPU_WEIGHT)

    def _cost_narrate(self, node: NarrateNode, child_rows: float, child_cost: PlanCost) -> PlanCost:
        cpu = child_rows * 0.5  # narrative generation
        mem = child_rows * 1.0  # narrative objects
        return PlanCost(cpu=cpu, io=0, mem=mem, rows=child_rows,
                        total=child_cost.total + cpu * _CPU_WEIGHT + mem * _MEM_WEIGHT)

    def _cost_project(self, node: ProjectNode, child_rows: float, child_cost: PlanCost) -> PlanCost:
        # Projection reduces serialization cost
        reduction = len(node.fields) / 10.0 if node.fields else 1.0
        cpu = child_cost.cpu * reduction
        mem = child_cost.mem * reduction
        return PlanCost(cpu=cpu, io=child_cost.io, mem=mem, rows=child_rows,
                        total=cpu * _CPU_WEIGHT + child_cost.io * _IO_WEIGHT + mem * _MEM_WEIGHT)

    def _cost_compose(self, node: ComposeNode, child_rows: float, child_cost: PlanCost) -> PlanCost:
        # Compose runs both plans
        first_cost = PlanCost()
        second_cost = PlanCost()
        if node.first:
            first_cost = self.estimate(node.first)
        if node.second:
            second_cost = self.estimate(node.second)
        total_rows = first_cost.rows + second_cost.rows
        total_cpu = first_cost.cpu + second_cost.cpu
        total_io = first_cost.io + second_cost.io
        total_mem = first_cost.mem + second_cost.mem
        return PlanCost(cpu=total_cpu, io=total_io, mem=total_mem, rows=total_rows,
                        total=total_cpu * _CPU_WEIGHT + total_io * _IO_WEIGHT + total_mem * _MEM_WEIGHT)


import math  # needed for log2 in _cost_sort
