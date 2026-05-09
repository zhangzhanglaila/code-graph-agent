"""Plan Tree — Tree-structured logical plan for optimization.

Converts the flat operator pipeline into a tree where the root is the
final output and children are data sources. This enables:

    - Tree visitors for rewrite rules
    - Predicate pushdown (filter closer to source)
    - Projection pruning (remove unused outputs)
    - Cost estimation (bottom-up aggregation)

Tree structure:
    Narrate
    └── Traverse
        └── SelectNodes

Instead of flat: [SelectNodes, Traverse, Narrate]

Usage:
    from dynamic.query.plan_tree import PlanNode, TreeWalker, tree_to_plan
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from .algebra import (
    Operator, SelectNodes, SelectFacts, Traverse, CollectHistory,
    FilterNodes, FilterFacts, Sort, Limit, CompareNodes, ComputeStats,
    Narrate, Project, ComposePlan, LogicalPlan,
)


# ─── Plan Node (tree structure) ──────────────────────────────────

@dataclass
class PlanNode:
    """Base class for tree-structured plan nodes.

    Tree convention: root = final output, children = data sources.
    Leaf nodes have no children (they are data sources).
    """
    children: List['PlanNode'] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        n = self.__class__.__name__
        if n.endswith('Node'):
            n = n[:-4]
        return n[0].lower() + n[1:]

    def add_child(self, child: 'PlanNode') -> 'PlanNode':
        self.children.append(child)
        return self

    def clone(self) -> 'PlanNode':
        """Deep clone this node and all children."""
        return PlanNode(
            children=[c.clone() for c in self.children],
            metadata=dict(self.metadata),
        )

    def describe(self, indent: int = 0) -> str:
        """Human-readable tree representation."""
        prefix = '  ' * indent
        lines = [f'{prefix}{self.name}({self._params()})']
        for child in self.children:
            lines.append(child.describe(indent + 1))
        return '\n'.join(lines)

    def _params(self) -> str:
        return ''

    def __repr__(self):
        return f'{self.name}({self._params()})'


# ─── Concrete Node Types ─────────────────────────────────────────

class SelectNodesNode(PlanNode):
    """Select starting nodes from PDG."""
    def __init__(self, var: str = '', step: int = -1, code_pattern: str = '', **kwargs):
        super().__init__(**kwargs)
        self.var = var
        self.step = step
        self.code_pattern = code_pattern

    def _params(self):
        parts = []
        if self.var: parts.append(f'var={self.var!r}')
        if self.step >= 0: parts.append(f'step={self.step}')
        return ', '.join(parts)

    def to_operator(self) -> SelectNodes:
        return SelectNodes(var=self.var, step=self.step, code_pattern=self.code_pattern)


class SelectFactsNode(PlanNode):
    """Select facts matching pattern, with optional predicate pushdown."""
    def __init__(self, pattern: str = 'all', limit: int = 20,
                 filter_field: str = '', filter_op: str = '', filter_value: Any = None, **kwargs):
        super().__init__(**kwargs)
        self.pattern = pattern
        self.limit = limit
        self.filter_field = filter_field
        self.filter_op = filter_op
        self.filter_value = filter_value

    def _params(self):
        parts = [f'pattern={self.pattern!r}, limit={self.limit}']
        if self.filter_field:
            parts.append(f'filter={self.filter_field}{self.filter_op}{self.filter_value}')
        return ', '.join(parts)

    def to_operator(self) -> SelectFacts:
        return SelectFacts(
            pattern=self.pattern, limit=self.limit,
            filter_field=self.filter_field, filter_op=self.filter_op, filter_value=self.filter_value,
        )


class TraverseNode(PlanNode):
    """Walk PDG graph."""
    def __init__(self, direction: str = 'backward', edge_kind: str = 'data', **kwargs):
        super().__init__(**kwargs)
        self.direction = direction
        self.edge_kind = edge_kind

    def _params(self):
        return f'direction={self.direction!r}'

    def to_operator(self) -> Traverse:
        return Traverse(direction=self.direction, edge_kind=self.edge_kind)


class CollectHistoryNode(PlanNode):
    """Collect variable version history."""
    def __init__(self, var: str = '', **kwargs):
        super().__init__(**kwargs)
        self.var = var

    def _params(self):
        return f'var={self.var!r}'

    def to_operator(self) -> CollectHistory:
        return CollectHistory(var=self.var)


class FilterNodesNode(PlanNode):
    """Filter nodes by predicate."""
    def __init__(self, predicate: str = 'is_root', value: Any = None, **kwargs):
        super().__init__(**kwargs)
        self.predicate = predicate
        self.value = value

    def _params(self):
        return f'predicate={self.predicate!r}, value={self.value}'

    def to_operator(self) -> FilterNodes:
        return FilterNodes(predicate=self.predicate, value=self.value)


class FilterFactsNode(PlanNode):
    """Filter facts by field predicate."""
    def __init__(self, field: str = '', op: str = '>', value: Any = None, **kwargs):
        super().__init__(**kwargs)
        self.field = field
        self.op = op
        self.value = value

    def _params(self):
        return f'{self.field} {self.op} {self.value}'

    def to_operator(self) -> FilterFacts:
        return FilterFacts(field=self.field, op=self.op, value=self.value)


class SortNode(PlanNode):
    """Sort results by field."""
    def __init__(self, field: str = '', desc: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.field = field
        self.desc = desc

    def _params(self):
        return f'{self.field} {"DESC" if self.desc else "ASC"}'

    def to_operator(self) -> Sort:
        return Sort(field=self.field, desc=self.desc)


class LimitNode(PlanNode):
    """Limit result count."""
    def __init__(self, n: int = 20, **kwargs):
        super().__init__(**kwargs)
        self.n = n

    def _params(self):
        return f'n={self.n}'

    def to_operator(self) -> Limit:
        return Limit(n=self.n)


class CompareNode(PlanNode):
    """Compare two execution points."""
    def __init__(self, step_a: int = -1, step_b: int = -1, var: str = '', **kwargs):
        super().__init__(**kwargs)
        self.step_a = step_a
        self.step_b = step_b
        self.var = var

    def _params(self):
        return f'{self.step_a} vs {self.step_b}'

    def to_operator(self) -> CompareNodes:
        return CompareNodes(step_a=self.step_a, step_b=self.step_b, var=self.var)


class StatsNode(PlanNode):
    """Compute graph statistics."""
    def _params(self):
        return ''

    def to_operator(self) -> ComputeStats:
        return ComputeStats()


class NarrateNode(PlanNode):
    """Generate narrative."""
    def __init__(self, mode: str = 'slice', **kwargs):
        super().__init__(**kwargs)
        self.mode = mode

    def _params(self):
        return f'mode={self.mode!r}'

    def to_operator(self) -> Narrate:
        return Narrate(mode=self.mode)


class ProjectNode(PlanNode):
    """Project (prune) result fields."""
    def __init__(self, fields: List[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.fields = fields or []

    def _params(self):
        return f'fields={self.fields}'

    def to_operator(self) -> Project:
        return Project(fields=self.fields)


class ComposeNode(PlanNode):
    """Composition of two plans with optional WHERE/ORDER BY."""
    def __init__(self, first: PlanNode, second: Optional[PlanNode] = None,
                 where_field: str = '', where_op: str = '', where_value: Any = None,
                 order_by: str = '', order_desc: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.first = first
        self.second = second
        self.where_field = where_field
        self.where_op = where_op
        self.where_value = where_value
        self.order_by = order_by
        self.order_desc = order_desc

    def _params(self):
        parts = [self.first.name]
        if self.second:
            parts.append(f'-> {self.second.name}')
        if self.where_field:
            parts.append(f'WHERE {self.where_field} {self.where_op} {self.where_value}')
        if self.order_by:
            parts.append(f'ORDER BY {self.order_by} {"DESC" if self.order_desc else ""}')
        return ' '.join(parts)

    def describe(self, indent: int = 0) -> str:
        prefix = '  ' * indent
        lines = [f'{prefix}compose({self._params()})']
        if self.first:
            lines.append(f'{prefix}  first:')
            lines.append(self.first.describe(indent + 2))
        if self.second:
            lines.append(f'{prefix}  second:')
            lines.append(self.second.describe(indent + 2))
        return '\n'.join(lines)


# ─── Tree Walker ─────────────────────────────────────────────────

class TreeWalker:
    """Walk a plan tree, applying visitor functions.

    Supports pre-order and post-order traversal.

    Usage:
        walker = TreeWalker()
        walker.walk(root, pre_visit=..., post_visit=...)
    """

    def walk(self, node: PlanNode,
             pre_visit: Optional[Callable[[PlanNode], Optional[PlanNode]]] = None,
             post_visit: Optional[Callable[[PlanNode], Optional[PlanNode]]] = None) -> PlanNode:
        """Walk tree, optionally transforming nodes.

        pre_visit: called before children. Return new node to replace.
        post_visit: called after children. Return new node to replace.
        """
        if pre_visit:
            replacement = pre_visit(node)
            if replacement is not None:
                node = replacement

        # Walk children (handle ComposeNode's first/second specially)
        if isinstance(node, ComposeNode):
            if node.first:
                node.first = self.walk(node.first, pre_visit, post_visit)
            if node.second:
                node.second = self.walk(node.second, pre_visit, post_visit)
        else:
            node.children = [self.walk(c, pre_visit, post_visit) for c in node.children]

        if post_visit:
            replacement = post_visit(node)
            if replacement is not None:
                node = replacement

        return node

    def collect(self, node: PlanNode, predicate: Callable[[PlanNode], bool]) -> List[PlanNode]:
        """Collect all nodes matching predicate."""
        results = []
        def visitor(n):
            if predicate(n):
                results.append(n)
            return None
        self.walk(node, pre_visit=visitor)
        return results

    def count_nodes(self, node: PlanNode) -> int:
        """Count total nodes in tree."""
        count = [0]
        def visitor(n):
            count[0] += 1
            return None
        self.walk(node, pre_visit=visitor)
        return count[0]

    def height(self, node: PlanNode) -> int:
        """Compute tree height."""
        if isinstance(node, ComposeNode):
            h1 = self.height(node.first) if node.first else 0
            h2 = self.height(node.second) if node.second else 0
            return 1 + max(h1, h2)
        if not node.children:
            return 1
        return 1 + max(self.height(c) for c in node.children)


# ─── Conversion: flat LogicalPlan ↔ PlanNode tree ────────────────

def flat_plan_to_tree(plan: LogicalPlan) -> PlanNode:
    """Convert a flat operator-list LogicalPlan to a PlanNode tree.

    The flat list [A, B, C] becomes:
        C
        └── B
            └── A
    (last operator is root, first is leaf)

    ComposePlan operators are handled specially — their nested plans
    are recursively converted.
    """
    ops = plan.operators
    if not ops:
        return PlanNode()  # empty plan

    # Convert each operator to its tree node
    nodes: List[PlanNode] = []
    for op in ops:
        if isinstance(op, ComposePlan):
            first_tree = flat_plan_to_tree(op.first)
            second_tree = flat_plan_to_tree(op.second) if op.second.operators else None
            nodes.append(ComposeNode(
                first=first_tree,
                second=second_tree,
                where_field=op.where_field,
                where_op=op.where_op,
                where_value=op.where_value,
                order_by=op.order_by,
                order_desc=op.order_desc,
            ))
        else:
            nodes.append(_op_to_node(op))

    # Chain: last is root, each previous becomes child of next
    if len(nodes) == 1:
        return nodes[0]

    root = nodes[-1]
    current = root
    for i in range(len(nodes) - 2, -1, -1):
        current.children = [nodes[i]]
        current = nodes[i]

    return root


def tree_to_flat_plan(root: PlanNode, query_kind: str = '') -> LogicalPlan:
    """Convert a PlanNode tree back to a flat operator-list LogicalPlan.

    Walks the tree depth-first, collecting operators in execution order.
    """
    ops = _collect_ops(root)
    return LogicalPlan(ops, query_kind=query_kind)


def _collect_ops(node: PlanNode) -> List[Operator]:
    """Collect operators from tree in execution order (leaf-first)."""
    if isinstance(node, ComposeNode):
        # ComposePlan wraps entire sub-plans
        first_plan = tree_to_flat_plan(node.first) if node.first else LogicalPlan([])
        second_plan = tree_to_flat_plan(node.second) if node.second else LogicalPlan([])
        return [ComposePlan(
            first=first_plan,
            second=second_plan,
            where_field=node.where_field,
            where_op=node.where_op,
            where_value=node.where_value,
            order_by=node.order_by,
            order_desc=node.order_desc,
        )]

    ops = []
    # Children first (data sources)
    for child in node.children:
        ops.extend(_collect_ops(child))
    # Then this node's operator
    op = node.to_operator()
    if op:
        ops.append(op)
    return ops


def _op_to_node(op: Operator) -> PlanNode:
    """Convert an Operator to its corresponding PlanNode."""
    mapping = {
        SelectNodes: SelectNodesNode,
        SelectFacts: SelectFactsNode,
        Traverse: TraverseNode,
        CollectHistory: CollectHistoryNode,
        FilterNodes: FilterNodesNode,
        FilterFacts: FilterFactsNode,
        Sort: SortNode,
        Limit: LimitNode,
        CompareNodes: CompareNode,
        ComputeStats: StatsNode,
        Narrate: NarrateNode,
        Project: ProjectNode,
    }
    node_cls = mapping.get(type(op))
    if node_cls is None:
        # Unknown operator — wrap as generic node
        return PlanNode(metadata={'operator': op})
    # Copy all operator attributes to the node
    params = {k: v for k, v in op.__dict__.items() if not k.startswith('_')}
    return node_cls(**params)
