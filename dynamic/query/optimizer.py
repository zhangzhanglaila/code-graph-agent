"""Query Optimizer — rule-based plan rewriting.

Applies transformation rules to a PlanNode tree to produce
a more efficient plan before execution.

Rules:
    - Predicate pushdown: move filters closer to data sources
    - Filter fusion: merge adjacent filters
    - Sort pushdown: move sort after filter (filter first, sort less)
    - Limit pushdown: propagate limit to source operators
    - Dead branch elimination: remove unused composition branches

Usage:
    from dynamic.query.optimizer import QueryOptimizer
    optimizer = QueryOptimizer()
    optimized_tree = optimizer.optimize(tree)
"""

from __future__ import annotations
from typing import List, Optional

from .plan_tree import (
    PlanNode, SelectNodesNode, SelectFactsNode, TraverseNode,
    CollectHistoryNode, FilterNodesNode, FilterFactsNode,
    SortNode, LimitNode, CompareNode, StatsNode, NarrateNode,
    ProjectNode, ComposeNode, TreeWalker,
)
from .cost_model import CostEstimator, PlanCost
from .statistics import StatisticsCatalog


class RewriteRule:
    """Base class for rewrite rules."""
    name: str = 'base_rule'

    def matches(self, node: PlanNode) -> bool:
        """Does this rule apply to this node?"""
        raise NotImplementedError

    def apply(self, node: PlanNode) -> Optional[PlanNode]:
        """Transform the node. Return new node or None (no change)."""
        raise NotImplementedError


# ─── Predicate Pushdown ──────────────────────────────────────────

class PushFilterIntoSelectFacts(RewriteRule):
    """Push FilterFacts into SelectFacts.

    Before:  FilterFacts(field=evidence, op='>', value=3)
                 └── SelectFacts(pattern=loop)

    After:   SelectFacts(pattern=loop, filter=(evidence, >, 3))

    This avoids materializing all facts then filtering.
    """
    name = 'push_filter_into_select_facts'

    def matches(self, node: PlanNode) -> bool:
        if not isinstance(node, FilterFactsNode):
            return False
        if len(node.children) != 1:
            return False
        return isinstance(node.children[0], SelectFactsNode)

    def apply(self, node: PlanNode) -> Optional[PlanNode]:
        if not self.matches(node):
            return None
        filter_node: FilterFactsNode = node
        select_node: SelectFactsNode = node.children[0]

        # Push filter predicate directly into SelectFacts
        select_node.filter_field = filter_node.field
        select_node.filter_op = filter_node.op
        select_node.filter_value = filter_node.value
        return select_node


class PushSortAfterFilter(RewriteRule):
    """Ensure Sort runs after Filter (sort less data).

    Before:  Sort(field=X)
                 └── FilterFacts(field=Y, op='>', value=Z)
    After:   (no change — already correct)

    Before:  FilterFacts(field=Y, op='>', value=Z)
                 └── Sort(field=X)
    After:   Sort(field=X)
                 └── FilterFacts(field=Y, op='>', value=Z)

    The second case is wrong — filter should come first.
    """
    name = 'push_sort_after_filter'

    def matches(self, node: PlanNode) -> bool:
        if not isinstance(node, FilterFactsNode):
            return False
        if len(node.children) != 1:
            return False
        return isinstance(node.children[0], (SortNode, LimitNode))

    def apply(self, node: PlanNode) -> Optional[PlanNode]:
        if not self.matches(node):
            return None
        # Swap: filter becomes child, sort/limit becomes parent
        inner = node.children[0]  # Sort or Limit
        node.children = inner.children
        inner.children = [node]
        return inner


# ─── Filter Fusion ───────────────────────────────────────────────

class FuseAdjacentFilters(RewriteRule):
    """Merge adjacent FilterFacts into a single multi-predicate filter.

    Before:  FilterFacts(a > 1)
                 └── FilterFacts(b < 5)
                         └── SelectFacts(...)
    After:   FilterFacts(a > 1 AND b < 5)
                 └── SelectFacts(...)

    Reduces iteration passes over facts.
    """
    name = 'fuse_adjacent_filters'

    def matches(self, node: PlanNode) -> bool:
        if not isinstance(node, FilterFactsNode):
            return False
        if len(node.children) != 1:
            return False
        return isinstance(node.children[0], FilterFactsNode)

    def apply(self, node: PlanNode) -> Optional[PlanNode]:
        if not self.matches(node):
            return None
        # Store combined predicates in metadata
        outer: FilterFactsNode = node
        inner: FilterFactsNode = node.children[0]

        # Keep outer, merge inner's predicate into metadata
        predicates = outer.metadata.get('predicates', [])
        predicates.append({'field': outer.field, 'op': outer.op, 'value': outer.value})
        # Add inner's existing predicates
        inner_preds = inner.metadata.get('predicates', [])
        if inner_preds:
            predicates.extend(inner_preds)
        else:
            predicates.append({'field': inner.field, 'op': inner.op, 'value': inner.value})

        outer.metadata['predicates'] = predicates
        outer.children = inner.children
        return outer


# ─── Limit Pushdown ──────────────────────────────────────────────

class PushLimitIntoSelectFacts(RewriteRule):
    """Push Limit into SelectFacts to reduce materialization.

    Before:  Limit(n=5)
                 └── SelectFacts(pattern=loop, limit=20)
    After:   SelectFacts(pattern=loop, limit=5)

    The tighter limit wins.
    """
    name = 'push_limit_into_select_facts'

    def matches(self, node: PlanNode) -> bool:
        if not isinstance(node, LimitNode):
            return False
        if len(node.children) != 1:
            return False
        child = node.children[0]
        if isinstance(child, SelectFactsNode):
            return node.n < child.limit
        return False

    def apply(self, node: PlanNode) -> Optional[PlanNode]:
        if not self.matches(node):
            return None
        limit_node: LimitNode = node
        select_node: SelectFactsNode = node.children[0]
        select_node.limit = min(select_node.limit, limit_node.n)
        return select_node


# ─── Dead Branch Elimination ─────────────────────────────────────

class EliminateEmptyCompose(RewriteRule):
    """Remove empty second branch from ComposeNode.

    Before:  Compose(first=..., second=empty)
    After:   first (unwrap)
    """
    name = 'eliminate_empty_compose'

    def matches(self, node: PlanNode) -> bool:
        if not isinstance(node, ComposeNode):
            return False
        if node.second is None:
            return True
        if isinstance(node.second, PlanNode) and not node.second.children and not node.second.__dict__.get('var'):
            # Generic empty PlanNode
            return type(node.second) == PlanNode
        return False

    def apply(self, node: PlanNode) -> Optional[PlanNode]:
        if not self.matches(node):
            return None
        compose: ComposeNode = node
        # If there's no WHERE/ORDER BY, just unwrap
        if not compose.where_field and not compose.order_by:
            return compose.first
        # Keep compose but with second=None
        compose.second = None
        return compose


# ─── Compose Filter Pushdown ─────────────────────────────────────

class PushComposeFilterIntoBranches(RewriteRule):
    """Push ComposeNode's WHERE filter into its branches when possible.

    Before:  Compose(first=ShowFacts, second=..., where=evidence>3)
    After:   Compose(first=FilterFacts(evidence>3)->ShowFacts, second=...)

    Moves filtering earlier in the pipeline.
    """
    name = 'push_compose_filter_into_branches'

    def matches(self, node: PlanNode) -> bool:
        if not isinstance(node, ComposeNode):
            return False
        return bool(node.where_field) and node.first is not None

    def apply(self, node: PlanNode) -> Optional[PlanNode]:
        if not self.matches(node):
            return None
        compose: ComposeNode = node

        # Create a FilterFactsNode and push it into first branch
        filter_node = FilterFactsNode(
            field=compose.where_field,
            op=compose.where_op,
            value=compose.where_value,
        )

        # If first branch's root is a leaf, wrap it
        if not compose.first.children:
            filter_node.children = [compose.first]
            compose.first = filter_node
        else:
            # Insert filter between root and its first child
            root = compose.first
            filter_node.children = [root.children[0]] if root.children else []
            root.children = [filter_node]

        # Clear WHERE from compose (already pushed down)
        compose.where_field = ''
        compose.where_op = ''
        compose.where_value = None

        return compose


# ─── Projection Pruning ──────────────────────────────────────────

class InferProjection(RewriteRule):
    """Infer minimum required fields from the plan tree and insert a ProjectNode.

    Analyzes what each operator in the tree actually needs:
        - SHOW/facts query → only needs 'facts', 'count'
        - WHY/roots query → needs 'steps', 'root_causes', 'depth_map', 'narrative'
        - TRACE query → needs 'history', 'versions'
        - IMPACT query → needs 'steps', 'narrative'
        - COMPARE query → needs 'diffs'
        - STATS query → needs 'stats'

    Inserts a ProjectNode at the root to prune unused fields.
    """
    name = 'infer_projection'

    # Fields each operator type produces/needs
    _NEEDS = {
        'selectNodes': {'steps'},
        'selectFacts': {'facts', 'count'},
        'traverse': {'steps', 'root_causes', 'depth_map'},
        'collectHistory': {'history', 'versions'},
        'filterNodes': {'steps'},
        'filterFacts': {'facts', 'count'},
        'sort': set(),  # transparent
        'limit': set(),  # transparent
        'compare': {'diffs'},
        'stats': {'stats'},
        'narrate': {'narrative', 'text'},
        'project': set(),  # itself
    }

    def matches(self, node: PlanNode) -> bool:
        # Only apply to root nodes that don't already have projection
        if isinstance(node, ProjectNode):
            return False
        if node.metadata.get('project_fields'):
            return False
        if node.metadata.get('_projection_applied'):
            return False
        return True

    def apply(self, node: PlanNode) -> Optional[PlanNode]:
        # Collect all fields needed by the tree
        needed = set()
        self._collect_needs(node, needed)
        if not needed:
            return None
        # Insert ProjectNode as new root
        project = ProjectNode(fields=sorted(needed))
        # Move original tree under project
        if isinstance(node, ComposeNode):
            # Don't wrap compose — store projection in metadata
            node.metadata['project_fields'] = sorted(needed)
            node.metadata['_projection_applied'] = True
            return None
        project.children = [node]
        # Mark children so they don't re-trigger
        node.metadata['_projection_applied'] = True
        return project

    def _collect_needs(self, node: PlanNode, needed: set):
        """Recursively collect fields needed by all operators in tree."""
        name = node.name
        if name in self._NEEDS:
            needed.update(self._NEEDS[name])
        # ComposeNode needs everything from both branches
        if isinstance(node, ComposeNode):
            needed.update(['facts', 'count', 'steps', 'narrative', 'text',
                           'history', 'versions', 'root_causes', 'depth_map'])
        for child in node.children:
            self._collect_needs(child, needed)
        # Also check compose's first/second
        if isinstance(node, ComposeNode):
            if node.first:
                self._collect_needs(node.first, needed)
            if node.second:
                self._collect_needs(node.second, needed)


# ─── Cost-Based Reordering ───────────────────────────────────────

class ReorderFilterBeforeSort(RewriteRule):
    """Reorder: Filter before Sort (filter first = sort less data).

    Compare costs:
        Sort(Filter(x))  vs  Filter(Sort(x))
    First is almost always cheaper.
    """
    name = 'reorder_filter_before_sort'

    def matches(self, node: PlanNode) -> bool:
        if not isinstance(node, SortNode):
            return False
        if len(node.children) != 1:
            return False
        return isinstance(node.children[0], (FilterFactsNode, FilterNodesNode))

    def apply(self, node: PlanNode) -> Optional[PlanNode]:
        if not self.matches(node):
            return None
        # Swap: filter becomes parent, sort becomes child
        sort_node: SortNode = node
        filter_node = node.children[0]
        sort_node.children = filter_node.children
        filter_node.children = [sort_node]
        return filter_node


class ReorderLimitBeforeSort(RewriteRule):
    """Push Limit before Sort when possible.

    Sort(Limit(x)) is cheaper than Limit(Sort(x)) because
    we sort fewer elements.
    """
    name = 'reorder_limit_before_sort'

    def matches(self, node: PlanNode) -> bool:
        if not isinstance(node, SortNode):
            return False
        if len(node.children) != 1:
            return False
        return isinstance(node.children[0], LimitNode)

    def apply(self, node: PlanNode) -> Optional[PlanNode]:
        if not self.matches(node):
            return None
        sort_node: SortNode = node
        limit_node: LimitNode = node.children[0]
        sort_node.children = limit_node.children
        limit_node.children = [sort_node]
        return limit_node


# ─── Optimizer ───────────────────────────────────────────────────

class QueryOptimizer:
    """Applies rewrite rules to optimize a plan tree.

    Runs rules in multiple passes until no more transformations apply
    (fixpoint). Maximum 10 passes to prevent infinite loops.
    """

    DEFAULT_RULES = [
        PushFilterIntoSelectFacts(),
        PushSortAfterFilter(),
        FuseAdjacentFilters(),
        PushLimitIntoSelectFacts(),
        EliminateEmptyCompose(),
        PushComposeFilterIntoBranches(),
        ReorderFilterBeforeSort(),
        ReorderLimitBeforeSort(),
    ]
    # Projection runs once at the end, not in the iterative loop
    PROJECTION_RULE = InferProjection()

    def __init__(self, rules: Optional[List[RewriteRule]] = None,
                 catalog: Optional[StatisticsCatalog] = None):
        self.rules = rules or self.DEFAULT_RULES
        self.walker = TreeWalker()
        self._transform_count = 0
        self._catalog = catalog
        self._estimator = CostEstimator(catalog) if catalog else None
        self._cost_before: Optional[PlanCost] = None
        self._cost_after: Optional[PlanCost] = None

    def optimize(self, root: PlanNode, max_passes: int = 10) -> PlanNode:
        """Optimize a plan tree by applying rewrite rules to fixpoint,
        then apply projection pruning once at the end."""
        self._transform_count = 0

        # Record cost before optimization
        if self._estimator:
            self._cost_before = self._estimator.estimate(root)

        for pass_num in range(max_passes):
            changed = False

            for rule in self.rules:
                def apply_rule(node, _rule=rule):
                    nonlocal changed
                    if _rule.matches(node):
                        result = _rule.apply(node)
                        if result is not None:
                            changed = True
                            self._transform_count += 1
                            return result
                    return None

                root = self.walker.walk(root, pre_visit=apply_rule)

            if not changed:
                break

        # Apply projection pruning once at the end (root level only)
        proj_result = self.PROJECTION_RULE.apply(root)
        if proj_result is not None:
            root = proj_result
            self._transform_count += 1

        # Record cost after optimization
        if self._estimator:
            self._cost_after = self._estimator.estimate(root)

        return root

    @property
    def transform_count(self) -> int:
        return self._transform_count

    def stats(self) -> dict:
        result = {
            'rules': [r.name for r in self.rules],
            'transforms_applied': self._transform_count,
        }
        if self._cost_before and self._cost_after:
            result['cost_before'] = self._cost_before.to_dict()
            result['cost_after'] = self._cost_after.to_dict()
            result['cost_reduction'] = round(
                self._cost_before.total - self._cost_after.total, 2
            )
            result['cost_reduction_pct'] = round(
                (1 - self._cost_after.total / max(self._cost_before.total, 0.01)) * 100, 1
            )
        return result
