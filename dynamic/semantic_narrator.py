"""
AST-based Semantic Narrator — Rule-based plugin architecture.

Each semantic rule handles one AST node type.
The RuleRegistry dispatches to the first matching rule.

Architecture:
    RuleRegistry
    ├── AssignRule
    ├── AugAssignRule
    ├── ConditionRule
    ├── ReturnRule
    ├── LoopRule
    ├── RecursiveCallRule
    ├── PointerMoveRule
    ├── ListOpRule
    ├── ClassDefRule
    └── FallbackRule
"""

from __future__ import annotations
import ast
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ─── IR Types ───────────────────────────────────────────────────

@dataclass
class PointerMove:
    pointer: str
    from_object: Optional[str] = None
    to_object: Optional[str] = None
    via: str = ''  # 'next', 'left', 'right', etc.

@dataclass
class HeapMutation:
    object_id: str
    field: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None

@dataclass
class ExecutionEvent:
    """Unified execution event IR — the core data model."""
    step: int = 0
    event_type: str = 'unknown'
    narration: str = ''
    semantic_tags: List[str] = field(default_factory=list)
    depth: int = 0
    call_id: int = 0
    depth_delta: int = 0
    pointer_move: Optional[PointerMove] = None
    heap_mutations: List[HeapMutation] = field(default_factory=list)
    target_var: Optional[str] = None
    visual_priority: int = 0  # Higher = more important for visualization


# ─── Rule Base ──────────────────────────────────────────────────

class SemanticRule(ABC):
    """Base class for semantic analysis rules."""

    @abstractmethod
    def match(self, stmt: ast.AST, code: str, vars_: Dict[str, Any], depth: int) -> bool:
        """Return True if this rule handles this statement."""
        ...

    @abstractmethod
    def narrate(self, stmt: ast.AST, code: str, vars_: Dict[str, Any],
                depth: int, depth_delta: int, func_names: set, class_names: set) -> ExecutionEvent:
        """Generate semantic event for this statement."""
        ...

    def _get_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f'{self._get_name(node.value)}.{node.attr}'
        if isinstance(node, ast.Subscript):
            return f'{self._get_name(node.value)}[{self._expr_to_str(node.slice)}]'
        return '?'

    def _expr_to_str(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Constant):
            return repr(node.value)
        if isinstance(node, ast.Attribute):
            return f'{self._expr_to_str(node.value)}.{node.attr}'
        if isinstance(node, ast.Call):
            name = self._call_name(node)
            args = ', '.join(self._expr_to_str(a) for a in node.args)
            return f'{name}({args})'
        if isinstance(node, ast.BinOp):
            return f'{self._expr_to_str(node.left)} {_op_str(type(node.op))} {self._expr_to_str(node.right)}'
        if isinstance(node, ast.Compare):
            return f'{self._expr_to_str(node.left)} ...'
        if isinstance(node, ast.Subscript):
            return f'{self._expr_to_str(node.value)}[{self._expr_to_str(node.slice)}]'
        if isinstance(node, ast.List):
            return '[...]'
        if isinstance(node, ast.Dict):
            return '{...}'
        if isinstance(node, ast.Tuple):
            elts = ', '.join(self._expr_to_str(e) for e in node.elts)
            return f'({elts})'
        if isinstance(node, ast.ListComp):
            return '[... for ...]'
        if isinstance(node, ast.UnaryOp):
            return f'{_op_str(type(node.op))}{self._expr_to_str(node.operand)}'
        if isinstance(node, ast.BoolOp):
            op = 'and' if isinstance(node.op, ast.And) else 'or'
            return f' {op} '.join(self._expr_to_str(v) for v in node.values)
        return '...'

    def _call_name(self, node: ast.Call) -> str:
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
        return '?'

    def _find_primary_var(self, node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return self._find_primary_var(node.value)
        if isinstance(node, ast.UnaryOp):
            return self._find_primary_var(node.operand)
        if isinstance(node, ast.Compare):
            return self._find_primary_var(node.left)
        if isinstance(node, ast.BoolOp):
            for v in node.values:
                found = self._find_primary_var(v)
                if found:
                    return found
        return None

    def _is_none(self, node: ast.AST) -> bool:
        return isinstance(node, ast.Constant) and node.value is None

    def _var_val(self, vars_: Dict[str, Any], name: str) -> str:
        if not name or name == '?':
            return '?'
        v = vars_.get(name)
        if v is None:
            return '?'
        if isinstance(v, dict):
            return str(v.get('value', '?'))[:40]
        return str(v)[:40]


# ─── Concrete Rules ─────────────────────────────────────────────

class AssignRule(SemanticRule):
    """Handles: x = expr"""

    def match(self, stmt, code, vars_, depth):
        return isinstance(stmt, ast.Assign)

    def narrate(self, stmt, code, vars_, depth, depth_delta, func_names, class_names):
        targets = stmt.targets
        value = stmt.value

        # Tuple assignment: a, b = expr
        if len(targets) == 1 and isinstance(targets[0], ast.Tuple):
            names = [self._get_name(t) for t in targets[0].elts]
            vals = [self._var_val(vars_, n) for n in names]
            pairs = ', '.join(f'{n}={v}' for n, v in zip(names, vals))
            return ExecutionEvent(
                event_type='assignment', narration=f'更新 {pairs}',
                semantic_tags=['tuple_unpack'], target_var=names[0],
                depth_delta=depth_delta,
            )

        target_name = self._get_name(targets[0])

        # x = Constructor() → node creation
        if isinstance(value, ast.Call):
            call_name = self._call_name(value)
            if call_name in class_names or call_name in ('Node', 'TreeNode', 'ListNode'):
                val = self._var_val(vars_, target_name)
                return ExecutionEvent(
                    event_type='assignment', narration=f'创建节点 {target_name} = {val}',
                    semantic_tags=['node_creation', 'heap_alloc'],
                    target_var=target_name, depth_delta=depth_delta, visual_priority=2,
                )
            if call_name in func_names:
                args_str = ', '.join(self._expr_to_str(a) for a in value.args)
                return ExecutionEvent(
                    event_type='recursive_call', narration=f'调用 {call_name}({args_str})',
                    semantic_tags=['recursion', 'function_call'],
                    target_var=target_name, depth_delta=depth_delta, visual_priority=5,
                )
            val = self._var_val(vars_, target_name)
            return ExecutionEvent(
                event_type='assignment', narration=f'{target_name} = {call_name}() → {val}',
                semantic_tags=['function_call'], target_var=target_name, depth_delta=depth_delta,
            )

        # x = literal
        val = self._var_val(vars_, target_name)
        tags = ['initialization'] if val in ('0', '1', 'None', 'True', 'False', '{}', '[]') else []
        return ExecutionEvent(
            event_type='assignment', narration=f'{target_name} = {val}',
            semantic_tags=tags, target_var=target_name, depth_delta=depth_delta,
        )


class AugAssignRule(SemanticRule):
    """Handles: x += expr, x.next = y"""

    def match(self, stmt, code, vars_, depth):
        return isinstance(stmt, ast.AugAssign)

    def narrate(self, stmt, code, vars_, depth, depth_delta, func_names, class_names):
        target_name = self._get_name(stmt.target)
        op = _op_str(stmt.op)
        val = self._var_val(vars_, target_name)

        if isinstance(stmt.target, ast.Attribute):
            obj = self._get_name(stmt.target.value)
            attr = stmt.target.attr
            return ExecutionEvent(
                event_type='pointer_update',
                narration=f'{obj}.{attr} {op}= {self._expr_to_str(stmt.value)}',
                semantic_tags=['pointer', 'mutation'], target_var=f'{obj}.{attr}',
                depth_delta=depth_delta,
            )

        return ExecutionEvent(
            event_type='assignment', narration=f'{target_name} {op}= {self._expr_to_str(stmt.value)} → {val}',
            semantic_tags=['accumulation'], target_var=target_name, depth_delta=depth_delta,
        )


class ConditionRule(SemanticRule):
    """Handles: if x:, if not x:, if x is None:, while x:"""

    def match(self, stmt, code, vars_, depth):
        return isinstance(stmt, (ast.If, ast.While))

    def narrate(self, stmt, code, vars_, depth, depth_delta, func_names, class_names):
        test = stmt.test if isinstance(stmt, ast.If) else stmt.test
        is_while = isinstance(stmt, ast.While)

        # if not x
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            if isinstance(test.operand, ast.Name):
                var = test.operand.id
                val = self._var_val(vars_, var)
                return ExecutionEvent(
                    event_type='condition', narration=f'检查 {var} 是否为空 → {val}',
                    semantic_tags=['null_check', 'base_case'], target_var=var,
                    depth_delta=depth_delta, visual_priority=3,
                )

        # Compare with None
        if isinstance(test, ast.Compare):
            left_name = self._find_primary_var(test.left)
            for op, comparator in zip(test.ops, test.comparators):
                if self._is_none(comparator):
                    val = self._var_val(vars_, left_name)
                    if isinstance(op, ast.Is):
                        return ExecutionEvent(
                            event_type='condition', narration=f'检查 {left_name} 是否为 None → {val}',
                            semantic_tags=['null_check', 'base_case'], target_var=left_name,
                            depth_delta=depth_delta, visual_priority=3,
                        )
                    if isinstance(op, ast.IsNot):
                        return ExecutionEvent(
                            event_type='condition', narration=f'检查 {left_name} 是否有值 → {val}',
                            semantic_tags=['null_check'], target_var=left_name,
                            depth_delta=depth_delta, visual_priority=3,
                        )

        # Generic condition
        cond_str = self._expr_to_str(test)
        primary_var = self._find_primary_var(test)
        val = self._var_val(vars_, primary_var) if primary_var else '?'
        prefix = '循环条件' if is_while else '判断'
        return ExecutionEvent(
            event_type='condition', narration=f'{prefix}: {cond_str} (={val})',
            semantic_tags=['branch'], target_var=primary_var, depth_delta=depth_delta,
        )


class ReturnRule(SemanticRule):
    """Handles: return expr"""

    def match(self, stmt, code, vars_, depth):
        return isinstance(stmt, ast.Return)

    def narrate(self, stmt, code, vars_, depth, depth_delta, func_names, class_names):
        if stmt.value is None:
            return ExecutionEvent(
                event_type='return', narration='返回 (无值)',
                semantic_tags=['return'], depth_delta=depth_delta, visual_priority=4,
            )

        expr_str = self._expr_to_str(stmt.value)

        if isinstance(stmt.value, ast.Call):
            call_name = self._call_name(stmt.value)
            if call_name in func_names:
                return ExecutionEvent(
                    event_type='return', narration=f'返回递归结果',
                    semantic_tags=['return', 'recursion'], depth_delta=depth_delta, visual_priority=4,
                )

        val = self._var_val(vars_, expr_str.split('.')[0].split('[')[0])
        return ExecutionEvent(
            event_type='return', narration=f'返回 {val if val != "?" else expr_str}',
            semantic_tags=['return'], depth_delta=depth_delta, visual_priority=4,
        )


class LoopRule(SemanticRule):
    """Handles: for x in iter:"""

    def match(self, stmt, code, vars_, depth):
        return isinstance(stmt, ast.For)

    def narrate(self, stmt, code, vars_, depth, depth_delta, func_names, class_names):
        var_name = self._get_name(stmt.target)
        iter_str = self._expr_to_str(stmt.iter)
        val = self._var_val(vars_, var_name)
        return ExecutionEvent(
            event_type='loop', narration=f'循环: {var_name} = {val} (遍历 {iter_str})',
            semantic_tags=['loop', 'iteration'], target_var=var_name, depth_delta=depth_delta,
        )


class PointerMoveRule(SemanticRule):
    """Handles: x = x.next, x = x.left, current = current.next"""

    def match(self, stmt, code, vars_, depth):
        if not isinstance(stmt, ast.Assign):
            return False
        if len(stmt.targets) != 1:
            return False
        value = stmt.value
        return (isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.attr in ('next', 'prev', 'left', 'right', 'children', 'child', 'parent'))

    def narrate(self, stmt, code, vars_, depth, depth_delta, func_names, class_names):
        target = self._get_name(stmt.targets[0])
        obj_name = stmt.value.value.id
        attr = stmt.value.attr
        val = self._var_val(vars_, target)
        old_val = self._var_val(vars_, obj_name)

        return ExecutionEvent(
            event_type='pointer_move',
            narration=f'{target} 移动到 .{attr} → {val}',
            semantic_tags=['pointer', 'traversal'],
            target_var=target,
            pointer_move=PointerMove(pointer=target, from_object=old_val, to_object=val, via=attr),
            depth_delta=depth_delta, visual_priority=6,
        )


class RecursiveCallRule(SemanticRule):
    """Handles: dfs(x.left), traverse(head.next) as standalone statements — only known functions."""

    def match(self, stmt, code, vars_, depth):
        if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)):
            return False
        call = stmt.value
        name = self._call_name(call)
        # Only match direct function calls, not method calls (x.method())
        if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name):
            return False  # Let ListOpRule handle method calls
        return True

    def narrate(self, stmt, code, vars_, depth, depth_delta, func_names, class_names):
        call = stmt.value
        call_name = self._call_name(call)
        args_str = ', '.join(self._expr_to_str(a) for a in call.args)

        if call_name in func_names:
            return ExecutionEvent(
                event_type='recursive_call', narration=f'递归调用 {call_name}({args_str})',
                semantic_tags=['recursion'], depth_delta=depth_delta, visual_priority=5,
            )
        return ExecutionEvent(
            event_type='function_call', narration=f'调用 {call_name}({args_str})',
            semantic_tags=['function_call'], depth_delta=depth_delta,
        )


class ListOpRule(SemanticRule):
    """Handles: x.append(y), x.extend(y)"""

    def match(self, stmt, code, vars_, depth):
        if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)):
            return False
        call = stmt.value
        return (isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.attr in ('append', 'extend', 'insert', 'remove', 'pop', 'sort', 'reverse'))

    def narrate(self, stmt, code, vars_, depth, depth_delta, func_names, class_names):
        call = stmt.value
        obj = call.func.value.id
        method = call.func.attr
        val = self._var_val(vars_, obj)

        if method == 'append' and call.args:
            arg = self._expr_to_str(call.args[0])
            return ExecutionEvent(
                event_type='list_op', narration=f'{obj}.append({arg})',
                semantic_tags=['list_mutation', 'append'], target_var=obj,
                depth_delta=depth_delta,
            )
        return ExecutionEvent(
            event_type='list_op', narration=f'{obj}.{method}(...)',
            semantic_tags=['list_mutation'], target_var=obj, depth_delta=depth_delta,
        )


class ClassDefRule(SemanticRule):
    """Handles: class X:"""

    def match(self, stmt, code, vars_, depth):
        return isinstance(stmt, ast.ClassDef)

    def narrate(self, stmt, code, vars_, depth, depth_delta, func_names, class_names):
        return ExecutionEvent(
            event_type='class_def', narration=f'定义类 {stmt.name}',
            semantic_tags=['class_definition'], depth_delta=depth_delta,
        )


class FunctionDefRule(SemanticRule):
    """Handles: def x():"""

    def match(self, stmt, code, vars_, depth):
        return isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))

    def narrate(self, stmt, code, vars_, depth, depth_delta, func_names, class_names):
        return ExecutionEvent(
            event_type='function_def', narration=f'定义函数 {stmt.name}',
            semantic_tags=['function_definition'], depth_delta=depth_delta,
        )


class FallbackRule(SemanticRule):
    """Catch-all for unrecognized statements."""

    def match(self, stmt, code, vars_, depth):
        return True

    def narrate(self, stmt, code, vars_, depth, depth_delta, func_names, class_names):
        code = code.strip()
        if code == 'pass':
            return ExecutionEvent(event_type='pass', narration='跳过', semantic_tags=[])
        if code == 'break':
            return ExecutionEvent(event_type='break', narration='跳出循环', semantic_tags=['loop_control'])
        if code == 'continue':
            return ExecutionEvent(event_type='continue', narration='继续下一次循环', semantic_tags=['loop_control'])
        if code.startswith('#'):
            return ExecutionEvent(event_type='comment', narration=code, semantic_tags=[])
        if code.startswith('import ') or code.startswith('from '):
            return ExecutionEvent(event_type='import', narration=code, semantic_tags=[])
        return ExecutionEvent(event_type='unknown', narration=code, semantic_tags=[])


# ─── Registry ───────────────────────────────────────────────────

class RuleRegistry:
    """Ordered rule dispatcher — first match wins."""

    def __init__(self):
        self.rules: List[SemanticRule] = [
            PointerMoveRule(),    # Must be before AssignRule (x = x.next is an Assign)
            ListOpRule(),         # Must be before RecursiveCallRule (method calls first)
            RecursiveCallRule(),  # Direct function calls only
            AugAssignRule(),
            AssignRule(),
            ConditionRule(),
            ReturnRule(),
            LoopRule(),
            ClassDefRule(),
            FunctionDefRule(),
            FallbackRule(),      # Must be last
        ]

    def dispatch(self, stmt: ast.AST, code: str, vars_: Dict[str, Any],
                 depth: int, depth_delta: int, func_names: set, class_names: set) -> ExecutionEvent:
        for rule in self.rules:
            if rule.match(stmt, code, vars_, depth):
                return rule.narrate(stmt, code, vars_, depth, depth_delta, func_names, class_names)
        return ExecutionEvent(event_type='unknown', narration=code)


# ─── Main Narrator ──────────────────────────────────────────────

class SemanticNarrator:
    """AST-based semantic analyzer — entry point."""

    def __init__(self, code: str):
        self.code = code
        self._func_names: set = set()
        self._class_names: set = set()
        self._registry = RuleRegistry()
        self._parse()

    def _parse(self):
        try:
            tree = ast.parse(self.code)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    self._func_names.add(node.name)
                elif isinstance(node, ast.ClassDef):
                    self._class_names.add(node.name)
        except SyntaxError:
            pass

    def analyze_step(self, code_line: str, vars_snapshot: Dict[str, Any],
                     depth: int = 0, prev_depth: int = 0,
                     step_index: int = 0, call_id: int = 0) -> ExecutionEvent:
        """Analyze a single execution step and return unified IR."""
        code = (code_line or '').strip()
        depth_delta = depth - prev_depth

        stmt = self._parse_stmt(code)
        if stmt is None:
            return ExecutionEvent(
                step=step_index, event_type='unknown', narration=code,
                depth=depth, call_id=call_id, depth_delta=depth_delta,
            )

        event = self._registry.dispatch(
            stmt, code, vars_snapshot, depth, depth_delta,
            self._func_names, self._class_names,
        )
        event.step = step_index
        event.depth = depth
        event.call_id = call_id
        return event

    def detect_patterns(self, events: List[ExecutionEvent]) -> List[PatternMatch]:
        """Detect algorithmic patterns from a sequence of execution events."""
        combinator = PatternCombinator()
        return combinator.detect(events)

    def understand(self, events: List[ExecutionEvent]) -> List[IntentGraph]:
        """Full cognition pipeline: detect patterns → classify → temporal analyze → narrate."""
        matches = self.detect_patterns(events)
        engine = CognitionEngine()
        return engine.understand(matches, events)

    def _parse_stmt(self, code: str) -> Optional[ast.AST]:
        try:
            return ast.parse(code).body[0] if code else None
        except SyntaxError:
            try:
                return ast.parse(code + '\n    pass').body[0]
            except SyntaxError:
                return None


# ─── Pattern Combinators v2: Graph-based + Hierarchical ─────────

@dataclass
class SemanticOperation:
    """Canonical semantic meaning of a matched pattern.
    This is the 'intent recovery' layer — what the algorithm is DOING."""
    op: str                  # 'traverse' | 'divide' | 'accumulate' | 'search' | 'transform'
    structure: str           # 'linked_list' | 'tree' | 'array' | 'graph' | 'state_machine'
    actors: List[str]        # variable roles: ['pointer', 'accumulator', 'cache']
    direction: str = ''      # 'forward' | 'backward' | 'bidirectional' | 'depth_first' | 'breadth_first'
    combines: str = ''       # 'add' | 'merge' | 'max' | 'min' | 'concat'
    terminates: str = ''     # 'null_check' | 'bounds_check' | 'convergence' | 'exhaustion'


@dataclass
class PatternMatch:
    """A detected algorithmic pattern spanning multiple steps."""
    pattern_name: str
    display_name: str
    description: str
    start_step: int
    end_step: int
    confidence: float  # 0.0–1.0
    key_steps: List[int] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    semantic: Optional[SemanticOperation] = None
    sub_patterns: List[str] = field(default_factory=list)  # hierarchical: which sub-patterns composed this


# ─── Pattern Graph Node ─────────────────────────────────────────

@dataclass
class PatternNode:
    """A single node in a PatternGraph — matches one or more event specs."""
    id: str
    specs: List[Dict[str, Any]]  # ANY of these specs can match (OR within node)
    role: str = ''                # semantic role: 'pointer_move', 'base_case', 'accumulate', etc.
    weight: float = 1.0           # importance weight for scoring
    optional: bool = False        # if True, missing this node doesn't kill the match


@dataclass
class PatternEdge:
    """Edge between PatternNodes — defines temporal/structural relationship."""
    from_id: str
    to_id: str
    edge_type: str = 'sequential'  # 'sequential' | 'parallel' | 'branch' | 'dataflow'
    max_gap: int = 5               # max steps between from and to


class PatternGraph:
    """Graph-based pattern definition — supports branches, parallel paths, dataflow.

    Replaces linear sequence=[...] with a DAG of PatternNodes connected by PatternEdges.
    Matching decomposes the graph into linear paths and scores each independently,
    then combines with structural weights.
    """

    def __init__(self, name: str, display_name: str, description: str,
                 nodes: List[PatternNode], edges: List[PatternEdge],
                 min_confidence: float = 0.5,
                 semantic: Optional[SemanticOperation] = None):
        self.name = name
        self.display_name = display_name
        self.description = description
        self.nodes = {n.id: n for n in nodes}
        self.edges = edges
        self.min_confidence = min_confidence
        self.semantic = semantic
        # Build adjacency for path decomposition
        self._adj: Dict[str, List[str]] = {n.id: [] for n in nodes}
        self._edge_map: Dict[Tuple[str, str], PatternEdge] = {}
        for e in edges:
            self._adj.setdefault(e.from_id, []).append(e.to_id)
            self._edge_map[(e.from_id, e.to_id)] = e
        # Topological paths (all root-to-leaf paths)
        self._paths = self._compute_paths()

    def _compute_paths(self) -> List[List[str]]:
        """Find all root-to-leaf paths in the DAG (handles backedges safely)."""
        targets = set(e.to_id for e in self.edges)
        roots = [n_id for n_id in self.nodes if n_id not in targets]
        if not roots and self.nodes:
            roots = [list(self.nodes.keys())[0]]

        paths: List[List[str]] = []

        def dfs(node_id: str, path: List[str], visited: set):
            children = self._adj.get(node_id, [])
            # Filter out backedges (already visited) and find forward children
            forward = [c for c in children if c not in visited]
            if not forward:
                paths.append(path[:])
                return
            for child_id in forward:
                path.append(child_id)
                visited.add(child_id)
                dfs(child_id, path, visited)
                path.pop()
                visited.discard(child_id)

        for r in roots:
            dfs(r, [r], {r})

        return paths if paths else [[n_id for n_id in self.nodes]]

    def match(self, events: List[ExecutionEvent], window: int = 30) -> List[PatternMatch]:
        """Match this graph pattern against a sequence of events.

        Strategy: decompose graph into linear paths, match each path independently,
        then combine scores with structural weights.
        """
        if not self._paths or not events:
            return []

        all_matches: List[PatternMatch] = []
        total_node_weight = sum(n.weight for n in self.nodes.values())

        for start in range(len(events)):
            for end in range(start + 1, min(start + window, len(events) + 1)):
                window_events = events[start:end]
                score, key_steps, matched_roles = self._score_graph(window_events)

                if score >= self.min_confidence:
                    # Boost score for structural completeness
                    structural_bonus = len(matched_roles) / len(self.nodes) * 0.15
                    final_score = min(score + structural_bonus, 1.0)

                    all_matches.append(PatternMatch(
                        pattern_name=self.name,
                        display_name=self.display_name,
                        description=self.description,
                        start_step=start,
                        end_step=end - 1,
                        confidence=final_score,
                        key_steps=key_steps,
                        tags=[self.name],
                        semantic=self.semantic,
                    ))

        return self._dedupe(all_matches)

    def _score_graph(self, events: List[ExecutionEvent]) -> Tuple[float, List[int], set]:
        """Score events against all paths, return best composite score."""
        best_score = 0.0
        best_steps: List[int] = []
        best_roles: set = set()

        for path in self._paths:
            score, steps, roles = self._score_path(events, path)
            if score > best_score:
                best_score = score
                best_steps = steps
                best_roles = roles

        # Check parallel edges: both from_id and to_id must appear
        for e in self.edges:
            if e.edge_type == 'parallel':
                from_found = any(self._matches_spec(ev, self.nodes[e.from_id].specs[0])
                                 for ev in events)
                to_found = any(self._matches_spec(ev, self.nodes[e.to_id].specs[0])
                               for ev in events)
                if from_found and to_found:
                    best_score = min(best_score + 0.1, 1.0)

        return best_score, best_steps, best_roles

    def _score_path(self, events: List[ExecutionEvent], path: List[str]) -> Tuple[float, List[int], set]:
        """Score events against a single linear path through the graph."""
        matched = 0
        total_weight = 0.0
        matched_weight = 0.0
        key_steps: List[int] = []
        matched_roles: set = set()
        ei = 0

        for node_id in path:
            node = self.nodes[node_id]
            total_weight += node.weight

            found = False
            while ei < len(events):
                ev = events[ei]
                if any(self._matches_spec(ev, spec) for spec in node.specs):
                    matched += 1
                    matched_weight += node.weight
                    key_steps.append(ev.step)
                    if node.role:
                        matched_roles.add(node.role)
                    ei += 1
                    found = True
                    break
                ei += 1

            if not found and not node.optional:
                # Non-optional node not found — penalize but don't zero
                pass

        score = matched_weight / total_weight if total_weight > 0 else 0.0
        return score, key_steps, matched_roles

    def _matches_spec(self, ev: ExecutionEvent, spec: Dict[str, Any]) -> bool:
        if 'event_type' in spec and ev.event_type != spec['event_type']:
            return False
        if 'tags' in spec:
            if not all(t in ev.semantic_tags for t in spec['tags']):
                return False
        if 'target_var' in spec:
            if ev.target_var != spec['target_var']:
                if spec['target_var'].endswith('*'):
                    prefix = spec['target_var'][:-1]
                    if not (ev.target_var or '').startswith(prefix):
                        return False
                else:
                    return False
        return True

    def _dedupe(self, matches: List[PatternMatch]) -> List[PatternMatch]:
        if len(matches) <= 1:
            return matches
        matches.sort(key=lambda m: -m.confidence)
        kept: List[PatternMatch] = []
        for m in matches:
            if not any(self._overlaps(m, k) for k in kept):
                kept.append(m)
        return sorted(kept, key=lambda m: m.start_step)

    @staticmethod
    def _overlaps(a: PatternMatch, b: PatternMatch) -> bool:
        return a.start_step <= b.end_step and b.start_step <= a.end_step


# ─── Hierarchical Pattern Composer ──────────────────────────────

class HierarchicalComposer:
    """Pattern-of-patterns: compose atomic patterns into higher-order algorithmic motifs.

    E.g., pointer_traversal + cycle_detection = floyd_cycle_finder
    """

    def __init__(self):
        self.compositions: List[Dict[str, Any]] = []

    def add_composition(self, name: str, display_name: str, description: str,
                        components: List[str], semantic: SemanticOperation):
        """Register a composition rule.

        Args:
            components: list of pattern_names that must ALL be present
        """
        self.compositions.append({
            'name': name,
            'display_name': display_name,
            'description': description,
            'components': components,
            'semantic': semantic,
        })

    def compose(self, matches: List[PatternMatch]) -> List[PatternMatch]:
        """Given atomic pattern matches, detect higher-order compositions."""
        atomic_names = {m.pattern_name for m in matches}
        composed: List[PatternMatch] = []

        for rule in self.compositions:
            components = rule['components']
            if not all(c in atomic_names for c in components):
                continue

            # Find the step range that covers all component patterns
            component_matches = [m for m in matches if m.pattern_name in components]
            if not component_matches:
                continue

            start = min(m.start_step for m in component_matches)
            end = max(m.end_step for m in component_matches)
            avg_conf = sum(m.confidence for m in component_matches) / len(component_matches)

            composed.append(PatternMatch(
                pattern_name=rule['name'],
                display_name=rule['display_name'],
                description=rule['description'],
                start_step=start,
                end_step=end,
                confidence=avg_conf,
                key_steps=[s for m in component_matches for s in m.key_steps],
                tags=[rule['name']],
                semantic=rule.get('semantic'),
                sub_patterns=components,
            ))

        return composed


# ─── Scoring Engine: Semantic Weighted Confidence ────────────────

class SemanticScorer:
    """Multi-signal confidence scoring — replaces simple matched/len(seq).

    Signals:
    - structural:  did the expected event types appear?
    - temporal:    are they in the right order, close together?
    - dataflow:    do variables flow consistently between steps?
    - topology:    does the execution structure match (depth changes, recursion)?
    """

    @staticmethod
    def score(match: PatternMatch, events: List[ExecutionEvent]) -> float:
        """Re-score a pattern match with multi-signal weighting."""
        if not match.key_steps or not events:
            return match.confidence

        relevant = [e for e in events if e.step in match.key_steps]
        if not relevant:
            return match.confidence

        scores = {
            'structural': SemanticScorer._structural_score(relevant),
            'temporal': SemanticScorer._temporal_score(relevant, events),
            'dataflow': SemanticScorer._dataflow_score(relevant),
            'topology': SemanticScorer._topology_score(relevant),
        }

        # Weighted combination
        weights = {'structural': 0.35, 'temporal': 0.20, 'dataflow': 0.25, 'topology': 0.20}
        final = sum(scores[k] * weights[k] for k in scores)

        # Blend with original confidence
        return 0.6 * match.confidence + 0.4 * final

    @staticmethod
    def _structural_score(events: List[ExecutionEvent]) -> float:
        """Do the expected event types appear? (0-1)"""
        types = [e.event_type for e in events]
        # Diversity bonus: more distinct types = richer pattern
        distinct = len(set(types))
        return min(distinct / max(len(types), 1) + 0.3, 1.0)

    @staticmethod
    def _temporal_score(events: List[ExecutionEvent], all_events: List[ExecutionEvent]) -> float:
        """Are events in the right order, close together? (0-1)"""
        if len(events) < 2:
            return 0.5

        # Order: are key steps monotonically increasing?
        steps = [e.step for e in events]
        ordered = all(steps[i] <= steps[i+1] for i in range(len(steps)-1))
        order_score = 1.0 if ordered else 0.3

        # Proximity: are they close together?
        span = steps[-1] - steps[0] + 1
        proximity = min(len(events) / span, 1.0) if span > 0 else 1.0

        return 0.5 * order_score + 0.5 * proximity

    @staticmethod
    def _dataflow_score(events: List[ExecutionEvent]) -> float:
        """Do variables flow consistently between steps? (0-1)"""
        if len(events) < 2:
            return 0.5

        # Check: do target_vars from earlier events appear in later events?
        targets = set()
        references = 0
        for e in events:
            if e.target_var:
                # Check if this var was a target in a previous event
                if e.target_var in targets:
                    references += 1
                targets.add(e.target_var)

        # Also check pointer_move consistency
        pointer_vars = set()
        for e in events:
            if e.pointer_move:
                pointer_vars.add(e.pointer_move.pointer)

        flow_score = min(references / max(len(events) - 1, 1) + 0.2, 1.0)
        pointer_bonus = 0.2 if len(pointer_vars) > 0 else 0.0

        return min(flow_score + pointer_bonus, 1.0)

    @staticmethod
    def _topology_score(events: List[ExecutionEvent]) -> float:
        """Does execution structure match? (depth changes, recursion) (0-1)"""
        if not events:
            return 0.5

        # Recursion evidence: depth changes
        depths = [e.depth for e in events]
        has_depth_change = any(d != depths[0] for d in depths)

        # Loop evidence: same event_type repeating
        types = [e.event_type for e in events]
        has_repeat = len(types) != len(set(types))

        score = 0.5
        if has_depth_change:
            score += 0.3
        if has_repeat:
            score += 0.2

        return min(score, 1.0)


# ─── Built-in Pattern Graphs ────────────────────────────────────

def _build_builtin_patterns() -> List[PatternGraph]:
    """Construct the built-in pattern library as PatternGraphs."""

    patterns = []

    # 1. Linked List Traversal
    patterns.append(PatternGraph(
        name='linked_list_traversal',
        display_name='链表遍历',
        description='沿链表 .next 指针逐节点遍历，含空值检查',
        nodes=[
            PatternNode('entry', [{'event_type': 'pointer_move'}], role='start_traversal', weight=1.0),
            PatternNode('guard', [{'event_type': 'condition', 'tags': ['null_check']},
                                  {'event_type': 'condition'}], role='guard', weight=0.8),
            PatternNode('advance', [{'event_type': 'pointer_move'}], role='advance_pointer', weight=1.0),
        ],
        edges=[
            PatternEdge('entry', 'guard', 'sequential'),
            PatternEdge('guard', 'advance', 'sequential'),
        ],
        min_confidence=0.55,
        semantic=SemanticOperation(
            op='traverse', structure='linked_list',
            actors=['pointer'], direction='forward', terminates='null_check',
        ),
    ))

    # 2. Tree DFS
    patterns.append(PatternGraph(
        name='tree_dfs',
        display_name='树 DFS 遍历',
        description='先检查空节点，再递归左右子树，最后返回结果',
        nodes=[
            PatternNode('base', [{'event_type': 'condition', 'tags': ['null_check']}],
                        role='base_case', weight=1.0),
            PatternNode('left', [{'event_type': 'recursive_call'}], role='recurse_left', weight=0.9),
            PatternNode('right', [{'event_type': 'recursive_call'}], role='recurse_right', weight=0.9),
            PatternNode('ret', [{'event_type': 'return'}], role='combine', weight=0.7, optional=True),
        ],
        edges=[
            PatternEdge('base', 'left', 'sequential'),
            PatternEdge('left', 'right', 'sequential'),
            PatternEdge('right', 'ret', 'sequential'),
        ],
        min_confidence=0.5,
        semantic=SemanticOperation(
            op='divide', structure='tree',
            actors=['left_subtree', 'right_subtree'],
            direction='depth_first', terminates='null_check',
        ),
    ))

    # 3. Accumulator / Iterative Aggregation
    patterns.append(PatternGraph(
        name='accumulator',
        display_name='累加器模式',
        description='初始化变量，循环中逐步累加，最后返回结果',
        nodes=[
            PatternNode('init', [{'event_type': 'assignment', 'tags': ['initialization']}],
                        role='init', weight=1.0),
            PatternNode('loop', [{'event_type': 'loop'}], role='iterate', weight=0.8),
            PatternNode('acc', [{'event_type': 'assignment', 'tags': ['accumulation']}],
                        role='accumulate', weight=1.0),
            PatternNode('ret', [{'event_type': 'return'}], role='result', weight=0.6, optional=True),
        ],
        edges=[
            PatternEdge('init', 'loop', 'sequential'),
            PatternEdge('loop', 'acc', 'sequential'),
            PatternEdge('acc', 'ret', 'sequential'),
        ],
        min_confidence=0.4,
        semantic=SemanticOperation(
            op='accumulate', structure='array',
            actors=['accumulator', 'element'],
            direction='forward', terminates='exhaustion',
        ),
    ))

    # 4. Memoization / Cache Lookup
    patterns.append(PatternGraph(
        name='memoization',
        display_name='记忆化缓存',
        description='先查缓存，未命中则计算并存储，避免重复计算',
        nodes=[
            PatternNode('check', [{'event_type': 'condition'}], role='cache_lookup', weight=1.0),
            PatternNode('compute', [{'event_type': 'assignment'}], role='compute', weight=0.9),
            PatternNode('store', [{'event_type': 'assignment', 'tags': ['accumulation']},
                                  {'event_type': 'list_op'}], role='cache_store', weight=0.8, optional=True),
            PatternNode('ret', [{'event_type': 'return'}], role='return_cached', weight=0.7),
        ],
        edges=[
            PatternEdge('check', 'compute', 'branch'),    # if miss → compute
            PatternEdge('compute', 'store', 'sequential'),
            PatternEdge('check', 'ret', 'branch'),         # if hit → return
        ],
        min_confidence=0.35,
        semantic=SemanticOperation(
            op='transform', structure='state_machine',
            actors=['cache', 'input', 'result'],
            terminates='convergence',
        ),
    ))

    # 5. Fast-Slow Pointer (Floyd's)
    patterns.append(PatternGraph(
        name='fast_slow_pointer',
        display_name='快慢指针',
        description='两个指针以不同速度遍历，常用于检测环或找中点',
        nodes=[
            PatternNode('slow', [{'event_type': 'pointer_move'}], role='slow_pointer', weight=1.0),
            PatternNode('fast', [{'event_type': 'pointer_move'}], role='fast_pointer', weight=1.0),
        ],
        edges=[
            PatternEdge('slow', 'fast', 'parallel'),  # both must appear, order flexible
        ],
        min_confidence=0.45,
        semantic=SemanticOperation(
            op='traverse', structure='linked_list',
            actors=['slow', 'fast'],
            direction='bidirectional', terminates='convergence',
        ),
    ))

    # 6. Binary Search
    patterns.append(PatternGraph(
        name='binary_search',
        display_name='二分搜索',
        description='每次将搜索空间减半，直到找到目标或空间耗尽',
        nodes=[
            PatternNode('bounds', [{'event_type': 'assignment'}], role='init_bounds', weight=0.7, optional=True),
            PatternNode('compare', [{'event_type': 'condition'}], role='compare', weight=1.0),
            PatternNode('narrow', [{'event_type': 'assignment'}], role='narrow_bounds', weight=1.0),
            PatternNode('ret', [{'event_type': 'return'}], role='found', weight=0.6, optional=True),
        ],
        edges=[
            PatternEdge('bounds', 'compare', 'sequential'),
            PatternEdge('compare', 'narrow', 'sequential'),
            PatternEdge('narrow', 'compare', 'sequential'),  # backedge: loop
        ],
        min_confidence=0.4,
        semantic=SemanticOperation(
            op='search', structure='array',
            actors=['left', 'right', 'mid'],
            direction='bidirectional', terminates='bounds_check',
        ),
    ))

    # 7. Sliding Window
    patterns.append(PatternGraph(
        name='sliding_window',
        display_name='滑动窗口',
        description='维护一个窗口，逐步扩展右边界、收缩左边界',
        nodes=[
            PatternNode('expand', [{'event_type': 'loop'}], role='expand_right', weight=1.0),
            PatternNode('update', [{'event_type': 'assignment'}], role='update_window', weight=0.9),
            PatternNode('shrink', [{'event_type': 'assignment'}], role='shrink_left', weight=0.8, optional=True),
            PatternNode('ret', [{'event_type': 'return'}], role='result', weight=0.6, optional=True),
        ],
        edges=[
            PatternEdge('expand', 'update', 'sequential'),
            PatternEdge('update', 'shrink', 'branch'),
            PatternEdge('shrink', 'expand', 'sequential'),
        ],
        min_confidence=0.35,
        semantic=SemanticOperation(
            op='traverse', structure='array',
            actors=['left', 'right', 'window_state'],
            direction='forward', terminates='exhaustion',
        ),
    ))

    # 8. State Machine / DP Transition
    patterns.append(PatternGraph(
        name='state_transition',
        display_name='状态转移',
        description='变量通过连续赋值逐步变换状态，最终收敛到结果',
        nodes=[
            PatternNode('init', [{'event_type': 'assignment', 'tags': ['initialization']}],
                        role='init_state', weight=0.8),
            PatternNode('transition', [{'event_type': 'assignment'}], role='transition', weight=1.0),
            PatternNode('transition2', [{'event_type': 'assignment'}], role='transition', weight=0.8, optional=True),
            PatternNode('ret', [{'event_type': 'return'}], role='final_state', weight=0.7),
        ],
        edges=[
            PatternEdge('init', 'transition', 'sequential'),
            PatternEdge('transition', 'transition2', 'sequential'),
            PatternEdge('transition2', 'ret', 'sequential'),
        ],
        min_confidence=0.4,
        semantic=SemanticOperation(
            op='transform', structure='state_machine',
            actors=['state'],
            direction='forward', terminates='convergence',
        ),
    ))

    return patterns


BUILTIN_PATTERN_GRAPHS = _build_builtin_patterns()


# ─── Hierarchical Composition Rules ─────────────────────────────

def _build_composer() -> HierarchicalComposer:
    """Build the default hierarchical composer with known algorithm compositions."""
    composer = HierarchicalComposer()

    composer.add_composition(
        name='floyd_cycle_finder',
        display_name='Floyd 环检测',
        description='快慢指针遍历链表，若两指针相遇则存在环',
        components=['fast_slow_pointer', 'linked_list_traversal'],
        semantic=SemanticOperation(
            op='traverse', structure='linked_list',
            actors=['slow', 'fast'],
            direction='bidirectional', terminates='convergence',
        ),
    )

    composer.add_composition(
        name='recursive_divide_and_conquer',
        display_name='分治递归',
        description='将问题分解为子问题，递归求解后合并',
        components=['tree_dfs', 'accumulator'],
        semantic=SemanticOperation(
            op='divide', structure='tree',
            actors=['left_subtree', 'right_subtree', 'result'],
            direction='depth_first', combines='merge',
        ),
    )

    composer.add_composition(
        name='memoized_recursion',
        display_name='记忆化递归',
        description='递归求解 + 缓存结果，避免重复计算',
        components=['tree_dfs', 'memoization'],
        semantic=SemanticOperation(
            op='divide', structure='tree',
            actors=['cache', 'subproblem'],
            direction='depth_first', terminates='convergence',
        ),
    )

    composer.add_composition(
        name='iterative_state_evolution',
        display_name='迭代状态演化',
        description='循环中通过赋值逐步变换状态变量',
        components=['accumulator', 'state_transition'],
        semantic=SemanticOperation(
            op='transform', structure='state_machine',
            actors=['state', 'accumulator'],
            direction='forward', terminates='exhaustion',
        ),
    )

    return composer


# ─── Pattern Combinator v2 (Graph + Hierarchical + Scoring) ─────

class PatternCombinator:
    """Detects algorithmic patterns from sequences of ExecutionEvents.

    v2 upgrades:
    - PatternGraph: graph-based patterns (branches, parallel, dataflow)
    - HierarchicalComposer: pattern-of-patterns
    - SemanticScorer: multi-signal confidence scoring
    """

    def __init__(self, patterns: Optional[List[PatternGraph]] = None):
        self.patterns = patterns or BUILTIN_PATTERN_GRAPHS
        self.scorer = SemanticScorer()
        self.composer = _build_composer()

    def detect(self, events: List[ExecutionEvent]) -> List[PatternMatch]:
        """Run all pattern graphs, compose hierarchically, re-score."""
        # Phase 1: atomic pattern matching
        all_matches: List[PatternMatch] = []
        for pattern in self.patterns:
            all_matches.extend(pattern.match(events))

        # Phase 2: hierarchical composition
        composed = self.composer.compose(all_matches)
        all_matches.extend(composed)

        # Phase 3: re-score with semantic scorer
        for m in all_matches:
            m.confidence = self.scorer.score(m, events)

        # Phase 4: global deduplication
        return self._global_dedupe(all_matches)

    def _global_dedupe(self, matches: List[PatternMatch]) -> List[PatternMatch]:
        if len(matches) <= 1:
            return matches
        matches.sort(key=lambda m: (m.start_step, -m.confidence))
        kept: List[PatternMatch] = []
        for m in matches:
            if not any(self._overlaps(m, k) and k.confidence >= m.confidence for k in kept):
                kept.append(m)
        return kept

    @staticmethod
    def _overlaps(a: PatternMatch, b: PatternMatch) -> bool:
        return a.start_step <= b.end_step and b.start_step <= a.end_step


# ─── L5: Semantic Lattice ───────────────────────────────────────
#
# Hierarchical classification of computational operations.
# Each node has: name, parent, description, narrative templates.
# Enables semantic inheritance: "binary search" IS-A "bounded search" IS-A "search".
#
# This is the ontological backbone of the cognition engine.

@dataclass
class LatticeNode:
    """A node in the semantic lattice — represents a computational concept."""
    name: str
    parent: Optional[str]         # parent concept name (None for root)
    description: str              # what this concept means
    templates: List[str]          # narrative templates (with {placeholders})
    properties: Dict[str, Any] = field(default_factory=dict)  # default properties


class SemanticLattice:
    """Semantic hierarchy of computational operations.

    Provides:
    - Concept inheritance (binary_search → bounded_search → search → computation)
    - Narrative templates at each level
    - Property resolution (child overrides parent)
    """

    def __init__(self):
        self.nodes: Dict[str, LatticeNode] = {}
        self._build_default_lattice()

    def _add(self, name: str, parent: Optional[str], description: str,
             templates: List[str], properties: Dict[str, Any] = None):
        self.nodes[name] = LatticeNode(
            name=name, parent=parent, description=description,
            templates=templates, properties=properties or {},
        )

    def _build_default_lattice(self):
        # ── Root ──
        self._add('computation', None,
                  'A process that transforms inputs to outputs',
                  ['This algorithm computes a result through a sequence of operations.'])

        # ── Traversal ──
        self._add('traversal', 'computation',
                  'Systematic exploration of a data structure',
                  ['The algorithm systematically visits elements of a {structure}.'])

        self._add('linear_traversal', 'traversal',
                  'Sequential visit of elements along a path',
                  ['Elements are visited one by one along a {direction} path.'])

        self._add('cyclic_traversal', 'traversal',
                  'Traversal that may revisit elements (cycle detection)',
                  ['The traversal detects cycles by comparing paths of two iterators.'])

        self._add('depth_first_traversal', 'traversal',
                  'Exploration that goes deep before going wide',
                  ['The algorithm explores as deep as possible before backtracking.'])

        self._add('breadth_first_traversal', 'traversal',
                  'Exploration that goes wide before going deep',
                  ['The algorithm explores all neighbors before moving deeper.'])

        # ── Search ──
        self._add('search', 'computation',
                  'Finding a target value or condition within a space',
                  ['The algorithm searches for a target within a {structure}.'])

        self._add('exhaustive_search', 'search',
                  'Search that examines every candidate',
                  ['Every candidate is examined until the target is found.'])

        self._add('bounded_search', 'search',
                  'Search that maintains and narrows a search region',
                  [
                      'The algorithm maintains a bounded search region.',
                      'Each step {narrows} the region, progressively reducing uncertainty.',
                      'The search terminates when the region {terminates}.',
                  ])

        self._add('heuristic_search', 'search',
                  'Search guided by an evaluation function',
                  ['The search is guided by a heuristic that estimates proximity to the goal.'])

        # ── Divide ──
        self._add('divide', 'computation',
                  'Breaking a problem into smaller subproblems',
                  ['The problem is decomposed into smaller subproblems.'])

        self._add('divide_and_conquer', 'divide',
                  'Divide, solve independently, then combine',
                  [
                      'The problem is split into {branching} independent subproblems.',
                      'Each subproblem is solved recursively.',
                      'Partial solutions are combined through {combines} into the final result.',
                  ])

        self._add('decrease_and_conquer', 'divide',
                  'Reduce to a single smaller subproblem',
                  [
                      'Each step reduces the problem to a single smaller instance.',
                      'The reduction continues until a base case is reached.',
                  ])

        # ── Accumulate ──
        self._add('accumulate', 'computation',
                  'Building a result incrementally through iteration',
                  [
                      'The algorithm iterates through {structure},',
                      'building a result incrementally through {combines}.',
                  ])

        self._add('filter_accumulate', 'accumulate',
                  'Selective accumulation based on a predicate',
                  [
                      'Elements are selectively added to the result',
                      'when they satisfy a condition.',
                  ])

        self._add('reduce', 'accumulate',
                  'Reducing a collection to a single value',
                  [
                      'The collection is reduced to a single value',
                      'through repeated {combines} operations.',
                  ])

        # ── Transform ──
        self._add('transform', 'computation',
                  'Converting state from one form to another',
                  ['The algorithm transforms {actors} from one state to another.'])

        self._add('state_evolution', 'transform',
                  'State that evolves monotonically toward convergence',
                  [
                      'State evolves monotonically toward convergence.',
                      'Each step advances the state through {combines},',
                      'compressing previous states into a rolling frontier.',
                  ])

        self._add('projection', 'transform',
                  'Mapping from one representation to another',
                  ['The algorithm projects {structure} into a different representation.'])

        # ── Merge ──
        self._add('merge', 'computation',
                  'Combining multiple sorted/structured inputs',
                  ['Multiple inputs are merged into a unified result.'])

        self._add('sorted_merge', 'merge',
                  'Merge of sorted sequences maintaining order',
                  ['Sorted sequences are merged while maintaining order.'])

    def resolve(self, op_name: str) -> List[str]:
        """Walk from op_name to root, returning the full inheritance chain."""
        chain = []
        current = op_name
        while current and current in self.nodes:
            chain.append(current)
            current = self.nodes[current].parent
        return chain

    def get_templates(self, op_name: str) -> List[str]:
        """Get all narrative templates from op_name up to root (most specific first)."""
        chain = self.resolve(op_name)
        templates = []
        for name in chain:
            node = self.nodes[name]
            templates.extend(node.templates)
        return templates

    def classify(self, semantic: SemanticOperation) -> str:
        """Given a SemanticOperation, find the most specific lattice node.

        Uses semantic properties to navigate the lattice:
        - op → top-level category
        - structure, direction, terminates → refine to subcategory
        """
        op = semantic.op

        if op == 'traverse':
            if semantic.terminates == 'convergence':
                return 'cyclic_traversal'
            if semantic.direction == 'depth_first':
                return 'depth_first_traversal'
            if semantic.direction == 'breadth_first':
                return 'breadth_first_traversal'
            return 'linear_traversal'

        if op == 'search':
            if semantic.terminates == 'bounds_check':
                return 'bounded_search'
            if semantic.terminates == 'exhaustion':
                return 'exhaustive_search'
            return 'search'

        if op == 'divide':
            if semantic.combines:
                return 'divide_and_conquer'
            return 'decrease_and_conquer'

        if op == 'accumulate':
            return 'accumulate'

        if op == 'transform':
            if semantic.terminates == 'convergence':
                return 'state_evolution'
            return 'transform'

        return op if op in self.nodes else 'computation'


# ─── L6: Temporal Logic ─────────────────────────────────────────
#
# Temporal predicates over event sequences.
# Replaces simple "did X happen" with "X always holds" / "X eventually happens"
# / "X holds until Y" / "X converges toward Z".
#
# This is what separates pattern matching from execution semantics.

@dataclass
class TemporalFact:
    """A temporal fact extracted from the event sequence."""
    predicate: str       # 'always' | 'eventually' | 'until' | 'converges' | 'repeats'
    subject: str         # what the predicate is about
    evidence: List[int]  # step indices that support this fact
    confidence: float    # 0.0–1.0
    description: str     # human-readable


class TemporalLogicEngine:
    """Extracts temporal facts from event sequences.

    Temporal predicates:
    - always(P):      P holds at every step in a range
    - eventually(P):  P holds at least once
    - until(P, Q):    P holds until Q happens
    - converges(P):   P's value monotonically approaches a limit
    - repeats(P):     P occurs multiple times
    """

    def __init__(self):
        pass

    def analyze(self, events: List[ExecutionEvent],
                match: PatternMatch) -> List[TemporalFact]:
        """Extract temporal facts relevant to a pattern match."""
        facts: List[TemporalFact] = []
        relevant = [e for e in events if match.start_step <= e.step <= match.end_step]
        if not relevant:
            return facts

        # 1. always: certain properties hold throughout the pattern
        always_facts = self._check_always(relevant, match)
        facts.extend(always_facts)

        # 2. eventually: certain events must occur
        eventually_facts = self._check_eventually(relevant, match)
        facts.extend(eventually_facts)

        # 3. until: one property holds until another
        until_facts = self._check_until(relevant, match)
        facts.extend(until_facts)

        # 4. converges: state narrows toward a limit
        converge_facts = self._check_converges(relevant, match)
        facts.extend(converge_facts)

        # 5. repeats: certain patterns repeat
        repeat_facts = self._check_repeats(relevant, match)
        facts.extend(repeat_facts)

        return facts

    def _check_always(self, events: List[ExecutionEvent],
                      match: PatternMatch) -> List[TemporalFact]:
        """Check what holds at every step."""
        facts = []

        # Always making progress (depth doesn't stay stuck)
        depths = [e.depth for e in events]
        if len(depths) >= 3:
            # Check: depth is bounded (not monotonically increasing = not infinite recursion)
            max_depth = max(depths)
            min_depth = min(depths)
            if max_depth - min_depth <= 3:
                facts.append(TemporalFact(
                    predicate='always',
                    subject='bounded_depth',
                    evidence=[e.step for e in events],
                    confidence=0.8,
                    description=f'Execution depth stays bounded (range: {min_depth}–{max_depth})',
                ))

        # Always operating on same structure (target_var consistency)
        target_vars = [e.target_var for e in events if e.target_var]
        if target_vars:
            most_common = max(set(target_vars), key=target_vars.count)
            ratio = target_vars.count(most_common) / len(target_vars)
            if ratio >= 0.5:
                facts.append(TemporalFact(
                    predicate='always',
                    subject=f'focuses_{most_common}',
                    evidence=[e.step for e in events if e.target_var == most_common],
                    confidence=ratio,
                    description=f'The algorithm consistently operates on `{most_common}`',
                ))

        return facts

    def _check_eventually(self, events: List[ExecutionEvent],
                          match: PatternMatch) -> List[TemporalFact]:
        """Check what must eventually happen."""
        facts = []

        # Eventually returns
        returns = [e for e in events if e.event_type == 'return']
        if returns:
            facts.append(TemporalFact(
                predicate='eventually',
                subject='returns',
                evidence=[e.step for e in returns],
                confidence=0.9,
                description='The computation eventually produces a result',
            ))

        # Eventually reaches base case (null check, bounds check)
        base_cases = [e for e in events if 'base_case' in e.semantic_tags
                      or 'null_check' in e.semantic_tags]
        if base_cases:
            facts.append(TemporalFact(
                predicate='eventually',
                subject='base_case',
                evidence=[e.step for e in base_cases],
                confidence=0.85,
                description='A base case is reached, terminating the recursion/traversal',
            ))

        return facts

    def _check_until(self, events: List[ExecutionEvent],
                     match: PatternMatch) -> List[TemporalFact]:
        """Check what holds until what."""
        facts = []

        # Traversal until null/termination
        if match.semantic and match.semantic.op == 'traverse':
            pointer_moves = [e for e in events if e.event_type == 'pointer_move']
            terminations = [e for e in events if 'null_check' in e.semantic_tags]
            if pointer_moves and terminations:
                facts.append(TemporalFact(
                    predicate='until',
                    subject='traversal_termination',
                    evidence=[pointer_moves[0].step, terminations[-1].step],
                    confidence=0.85,
                    description='Traversal continues until a null/termination condition is met',
                ))

        # Search until found
        if match.semantic and match.semantic.op == 'search':
            narrows = [e for e in events if e.event_type == 'assignment']
            returns = [e for e in events if e.event_type == 'return']
            if narrows and returns:
                facts.append(TemporalFact(
                    predicate='until',
                    subject='search_convergence',
                    evidence=[narrows[0].step, returns[-1].step],
                    confidence=0.8,
                    description='The search region narrows until the target is found',
                ))

        return facts

    def _check_converges(self, events: List[ExecutionEvent],
                         match: PatternMatch) -> List[TemporalFact]:
        """Check if state converges (monotonically approaches a limit)."""
        facts = []

        # Check pointer_move convergence: pointer eventually reaches end
        if match.semantic and match.semantic.terminates in ('null_check', 'convergence'):
            pointer_events = [e for e in events if e.event_type == 'pointer_move']
            if len(pointer_events) >= 2:
                facts.append(TemporalFact(
                    predicate='converges',
                    subject='pointer_position',
                    evidence=[e.step for e in pointer_events],
                    confidence=0.75,
                    description='The pointer position converges toward the structure boundary',
                ))

        # Check bounds convergence (binary search pattern)
        assignments = [e for e in events if e.event_type == 'assignment']
        if match.semantic and match.semantic.op == 'search' and len(assignments) >= 2:
            facts.append(TemporalFact(
                predicate='converges',
                subject='search_bounds',
                evidence=[e.step for e in assignments],
                confidence=0.7,
                description='Search bounds converge monotonically toward the target',
            ))

        return facts

    def _check_repeats(self, events: List[ExecutionEvent],
                       match: PatternMatch) -> List[TemporalFact]:
        """Check for repeated structures."""
        facts = []

        # Same event type repeating = iteration/recursion
        type_counts: Dict[str, int] = {}
        for e in events:
            type_counts[e.event_type] = type_counts.get(e.event_type, 0) + 1

        for etype, count in type_counts.items():
            if count >= 3 and etype in ('pointer_move', 'assignment', 'recursive_call'):
                facts.append(TemporalFact(
                    predicate='repeats',
                    subject=etype,
                    evidence=[e.step for e in events if e.event_type == etype],
                    confidence=min(0.5 + count * 0.1, 0.9),
                    description=f'{etype} repeats {count} times, indicating iterative structure',
                ))

        return facts


# ─── L6: Cognitive Narrative Generator ──────────────────────────
#
# The core of the cognition engine: transforms SemanticOperation + TemporalFacts
# into human-readable "why" explanations.
#
# Pipeline:
#   PatternMatch → SemanticLattice.classify() → LatticeNode.templates
#                 → TemporalLogicEngine.analyze() → TemporalFacts
#                 → NarrativeComposer → CognitiveNarrative

@dataclass
class CognitiveNarrative:
    """A human-readable explanation of what an algorithm is doing and WHY."""
    headline: str                  # one-line: "Binary search narrows uncertainty"
    mechanism: str                 # how it works: "Each step halves the search space"
    strategy: str                  # why this strategy: "Because the array is sorted"
    temporal_facts: List[str]      # temporal logic observations
    analogies: List[str]           # computational analogies
    lattice_path: List[str]        # semantic inheritance chain
    confidence: float


class CognitiveNarrativeGenerator:
    """Generates CognitiveNarratives from PatternMatches.

    This is the "understanding" layer — it doesn't just detect patterns,
    it explains WHY the algorithm works the way it does.
    """

    def __init__(self):
        self.lattice = SemanticLattice()
        self.temporal = TemporalLogicEngine()

    def generate(self, match: PatternMatch, events: List[ExecutionEvent]) -> CognitiveNarrative:
        """Generate a cognitive narrative for a pattern match."""
        # Step 1: Classify into semantic lattice
        semantic = match.semantic or SemanticOperation(op='computation', structure='unknown', actors=[])
        lattice_name = self.lattice.classify(semantic)
        lattice_path = self.lattice.resolve(lattice_name)

        # Step 2: Extract temporal facts
        temporal_facts = self.temporal.analyze(events, match)

        # Step 3: Generate narrative from templates + temporal facts
        headline = self._generate_headline(lattice_name, semantic)
        mechanism = self._generate_mechanism(lattice_name, semantic, temporal_facts)
        strategy = self._generate_strategy(lattice_name, semantic)
        fact_descriptions = [f.description for f in temporal_facts]
        analogies = self._generate_analogies(lattice_name, semantic)

        # Step 4: Compute confidence
        conf = match.confidence
        if temporal_facts:
            avg_fact_conf = sum(f.confidence for f in temporal_facts) / len(temporal_facts)
            conf = 0.6 * conf + 0.4 * avg_fact_conf

        return CognitiveNarrative(
            headline=headline,
            mechanism=mechanism,
            strategy=strategy,
            temporal_facts=fact_descriptions,
            analogies=analogies,
            lattice_path=lattice_path,
            confidence=round(conf, 3),
        )

    def _generate_headline(self, lattice_name: str, semantic: SemanticOperation) -> str:
        """Generate a one-line headline from the lattice classification."""
        headlines = {
            'linear_traversal': 'Sequential exploration of structure',
            'cyclic_traversal': 'Cycle-aware traversal with convergence detection',
            'depth_first_traversal': 'Deep exploration before backtracking',
            'breadth_first_traversal': 'Level-by-level exploration',
            'bounded_search': 'Progressive uncertainty reduction',
            'exhaustive_search': 'Systematic candidate examination',
            'heuristic_search': 'Goal-directed search with estimation',
            'divide_and_conquer': 'Recursive decomposition and recombination',
            'decrease_and_conquer': 'Progressive problem reduction',
            'accumulate': 'Incremental result construction',
            'filter_accumulate': 'Selective element aggregation',
            'reduce': 'Collection reduction to single value',
            'state_evolution': 'Monotonic state convergence',
            'projection': 'Representation transformation',
            'sorted_merge': 'Ordered sequence combination',
        }
        return headlines.get(lattice_name, f'Computational {semantic.op}')

    def _generate_mechanism(self, lattice_name: str, semantic: SemanticOperation,
                            facts: List[TemporalFact]) -> str:
        """Generate "how it works" from templates + temporal facts."""
        templates = self.lattice.get_templates(lattice_name)

        # Fill templates with semantic properties
        filled = []
        for t in templates:
            text = t
            text = text.replace('{structure}', semantic.structure or 'data')
            text = text.replace('{direction}', semantic.direction or 'systematic')
            text = text.replace('{combines}', semantic.combines or 'combines')
            text = text.replace('{terminates}', semantic.terminates or 'completion')
            text = text.replace('{narrows}', 'narrows' if semantic.op == 'search' else 'advances through')
            text = text.replace('{branching}', 'two' if 'tree' in semantic.structure else 'multiple')
            if '{' not in text:
                filled.append(text)

        mechanism = ' '.join(filled) if filled else f'The algorithm performs {semantic.op} on {semantic.structure}.'

        # Enrich with temporal facts
        converge_facts = [f for f in facts if f.predicate == 'converges']
        if converge_facts:
            mechanism += f' {converge_facts[0].description}.'

        return mechanism

    def _generate_strategy(self, lattice_name: str, semantic: SemanticOperation) -> str:
        """Generate "why this strategy" — the deeper reasoning."""
        strategies = {
            'bounded_search': (
                'Because the search space has monotonic structure (sorted, ordered), '
                'each comparison eliminates half the remaining candidates. '
                'This transforms O(n) exhaustive search into O(log n) bounded search.'
            ),
            'linear_traversal': (
                'Because the structure is sequential and each element must be visited, '
                'the algorithm follows the chain of references until exhaustion.'
            ),
            'depth_first_traversal': (
                'Because the problem has recursive substructure, '
                'depth-first exploration naturally follows the call stack, '
                'using implicit memory rather than an explicit queue.'
            ),
            'divide_and_conquer': (
                'Because the problem can be decomposed into independent subproblems, '
                'each subproblem is solved separately and the results combined. '
                'This enables parallelism and reduces total work through the Master Theorem.'
            ),
            'state_evolution': (
                'Because the result depends only on the current state and the next input, '
                'the algorithm maintains a compact rolling state, '
                'discarding history that no longer affects the outcome.'
            ),
            'accumulate': (
                'Because each element contributes independently to the result, '
                'the algorithm processes them in sequence, '
                'building the answer incrementally without backtracking.'
            ),
        }
        return strategies.get(lattice_name, f'The {semantic.op} strategy is appropriate for {semantic.structure} structures.')

    def _generate_analogies(self, lattice_name: str, semantic: SemanticOperation) -> List[str]:
        """Generate computational analogies — algorithms that share the same essence."""
        analogy_map = {
            'bounded_search': [
                'Binary search on sorted arrays',
                'Newton-Raphson root finding (iterative convergence)',
                'Alpha-beta pruning in game trees',
                'Gradient descent (bounded uncertainty reduction)',
            ],
            'linear_traversal': [
                'Linked list iteration',
                'String scanning',
                'Array linear search',
            ],
            'depth_first_traversal': [
                'Tree DFS',
                'Graph DFS with visited set',
                'Backtracking search',
                'Recursive descent parsing',
            ],
            'divide_and_conquer': [
                'Merge sort',
                'Quick sort',
                'Closest pair of points',
                'Strassen matrix multiplication',
            ],
            'state_evolution': [
                'Fibonacci iteration (rolling state)',
                'Running average (streaming computation)',
                'Dynamic programming state transition',
                'Finite state machine execution',
            ],
            'accumulate': [
                'Sum/product reduction',
                'Filter + map pipeline',
                'Histogram construction',
            ],
        }
        return analogy_map.get(lattice_name, [])


# ─── P1: Invariant Engine ───────────────────────────────────────
#
# Extracts algorithmic invariants from execution traces.
# Invariants are properties that MUST hold for the algorithm to be correct.
#
# Example: binary search requires:
#   - lo <= hi (loop guard)
#   - sorted(input) (precondition)
#   - interval shrinks each step (progress)
#
# This is the bridge from "what happened" to "why it's correct."

@dataclass
class Invariant:
    """An algorithmic invariant — a property that must hold for correctness."""
    name: str                     # 'loop_guard' | 'monotonic_progress' | 'bounded_depth' | ...
    predicate: str                # human-readable: 'lo <= hi'
    holds_on: List[int]           # step indices where invariant holds
    violated_by: List[int]        # step indices where invariant is violated (if any)
    confidence: float             # 0.0–1.0
    category: str                 # 'precondition' | 'loop_invariant' | 'progress' | 'termination' | 'postcondition'
    description: str              # why this invariant matters
    depends_on: List[str] = field(default_factory=list)  # other invariant names this depends on


class InvariantEngine:
    """Extracts algorithmic invariants from execution traces.

    Invariant categories:
    - precondition: must hold before algorithm starts
    - loop_invariant: must hold at every iteration
    - progress: must advance toward termination
    - termination: must eventually stop
    - postcondition: must hold after algorithm completes
    """

    def __init__(self):
        pass

    def extract(self, events: List[ExecutionEvent],
                match: PatternMatch) -> List[Invariant]:
        """Extract invariants relevant to a pattern match."""
        invariants: List[Invariant] = []
        relevant = [e for e in events if match.start_step <= e.step <= match.end_step]
        if not relevant:
            return invariants

        # 1. Loop guard invariants
        invariants.extend(self._check_loop_guards(relevant, match))

        # 2. Monotonic progress
        invariants.extend(self._check_progress(relevant, match))

        # 3. Bounded depth (termination)
        invariants.extend(self._check_bounded_depth(relevant, match))

        # 4. State consistency
        invariants.extend(self._check_state_consistency(relevant, match))

        # 5. Reachability (eventual return)
        invariants.extend(self._check_reachability(relevant, match))

        return invariants

    def _check_loop_guards(self, events: List[ExecutionEvent],
                           match: PatternMatch) -> List[Invariant]:
        """Check that loop/condition guards are maintained."""
        invariants = []

        # Loop conditions that always evaluate
        conditions = [e for e in events if e.event_type == 'condition']
        if conditions and match.semantic and match.semantic.op in ('search', 'traverse'):
            # The guard condition should appear at every iteration
            guard_steps = [e.step for e in conditions]
            invariants.append(Invariant(
                name='loop_guard',
                predicate='loop condition is evaluated at each iteration',
                holds_on=guard_steps,
                violated_by=[],
                confidence=0.85,
                category='loop_invariant',
                description='The loop guard is checked at each iteration, ensuring the algorithm '
                            'terminates when the condition becomes false.',
            ))

        return invariants

    def _check_progress(self, events: List[ExecutionEvent],
                        match: PatternMatch) -> List[Invariant]:
        """Check that the algorithm makes progress toward termination."""
        invariants = []

        if match.semantic and match.semantic.op == 'search':
            # Bounds should narrow (progress toward termination)
            assignments = [e for e in events if e.event_type == 'assignment']
            if len(assignments) >= 2:
                invariants.append(Invariant(
                    name='monotonic_progress',
                    predicate='search interval shrinks each iteration',
                    holds_on=[e.step for e in assignments],
                    violated_by=[],
                    confidence=0.75,
                    category='progress',
                    description='The search interval narrows monotonically. Each iteration '
                                'eliminates at least one candidate, guaranteeing termination.',
                    depends_on=['loop_guard'],
                ))

        if match.semantic and match.semantic.op == 'traverse':
            # Pointer should advance (not stay stuck)
            pointer_moves = [e for e in events if e.event_type == 'pointer_move']
            if len(pointer_moves) >= 2:
                invariants.append(Invariant(
                    name='pointer_advance',
                    predicate='pointer moves forward each iteration',
                    holds_on=[e.step for e in pointer_moves],
                    violated_by=[],
                    confidence=0.8,
                    category='progress',
                    description='The pointer advances through the structure each iteration, '
                                'ensuring the traversal makes progress toward completion.',
                ))

        if match.semantic and match.semantic.op == 'accumulate':
            # Accumulator should grow
            accum_events = [e for e in events if 'accumulation' in e.semantic_tags]
            if accum_events:
                invariants.append(Invariant(
                    name='accumulator_growth',
                    predicate='accumulator state grows with each element',
                    holds_on=[e.step for e in accum_events],
                    violated_by=[],
                    confidence=0.7,
                    category='progress',
                    description='The accumulator incorporates each element, '
                                'progressively building toward the final result.',
                ))

        return invariants

    def _check_bounded_depth(self, events: List[ExecutionEvent],
                             match: PatternMatch) -> List[Invariant]:
        """Check that recursion depth is bounded (termination guarantee)."""
        invariants = []

        depths = [e.depth for e in events]
        if depths:
            max_depth = max(depths)
            min_depth = min(depths)
            depth_range = max_depth - min_depth

            if depth_range <= 5:
                invariants.append(Invariant(
                    name='bounded_depth',
                    predicate=f'execution depth bounded in [{min_depth}, {max_depth}]',
                    holds_on=[e.step for e in events],
                    violated_by=[],
                    confidence=0.9,
                    category='termination',
                    description=f'Execution depth stays bounded (range: {min_depth}–{max_depth}). '
                                'This guarantees the algorithm terminates without stack overflow.',
                ))
            else:
                # Deep recursion — potential termination risk
                deep_steps = [e.step for e in events if e.depth > min_depth + 3]
                invariants.append(Invariant(
                    name='bounded_depth',
                    predicate=f'execution depth bounded in [{min_depth}, {max_depth}]',
                    holds_on=[e.step for e in events if e.depth <= min_depth + 3],
                    violated_by=deep_steps,
                    confidence=0.6,
                    category='termination',
                    description=f'Execution depth reaches {max_depth} (range: {min_depth}–{max_depth}). '
                                'Deep recursion detected — termination depends on base case reachability.',
                ))

        return invariants

    def _check_state_consistency(self, events: List[ExecutionEvent],
                                 match: PatternMatch) -> List[Invariant]:
        """Check that variables maintain consistent relationships."""
        invariants = []

        # Pointer consistency: pointer always references valid structure
        if match.semantic and match.semantic.op == 'traverse':
            pointer_vars = set()
            for e in events:
                if e.pointer_move:
                    pointer_vars.add(e.pointer_move.pointer)
            if pointer_vars:
                invariants.append(Invariant(
                    name='pointer_validity',
                    predicate=f'pointer(s) {", ".join(pointer_vars)} reference valid nodes',
                    holds_on=[e.step for e in events if e.event_type == 'pointer_move'],
                    violated_by=[],
                    confidence=0.7,
                    category='loop_invariant',
                    description='Pointers consistently reference valid structure nodes. '
                                'This is maintained by the null check guard.',
                ))

        # Search bounds consistency: lo <= hi
        if match.semantic and match.semantic.op == 'search':
            invariants.append(Invariant(
                name='bounds_ordering',
                predicate='lo <= hi',
                holds_on=[e.step for e in events if e.event_type == 'condition'],
                violated_by=[],
                confidence=0.8,
                category='loop_invariant',
                description='Lower bound never exceeds upper bound. '
                            'When this invariant is violated, the search terminates.',
            ))

        return invariants

    def _check_reachability(self, events: List[ExecutionEvent],
                            match: PatternMatch) -> List[Invariant]:
        """Check that the algorithm reaches a result."""
        invariants = []

        returns = [e for e in events if e.event_type == 'return']
        if returns:
            invariants.append(Invariant(
                name='result_reachability',
                predicate='a return statement is eventually executed',
                holds_on=[returns[-1].step],
                violated_by=[],
                confidence=0.95,
                category='postcondition',
                description='The algorithm eventually produces a result. '
                            'This confirms the execution path reaches a terminal state.',
            ))

        base_cases = [e for e in events if 'base_case' in e.semantic_tags]
        if base_cases:
            invariants.append(Invariant(
                name='base_case_reachability',
                predicate='base case is reachable',
                holds_on=[e.step for e in base_cases],
                violated_by=[],
                confidence=0.85,
                category='termination',
                description='The base case is reached, providing a termination point '
                            'for recursion or iteration.',
            ))

        return invariants


# ─── P2: Causal Graph ───────────────────────────────────────────
#
# Transforms temporal sequence into causal dependencies.
#
# Instead of: "A happened, then B happened"
# We get:     "A CAUSED B" / "B DEPENDS ON A"
#
# This is the bridge from "what happened" to "why it happened."

@dataclass
class CausalEdge:
    """A causal relationship between two execution events."""
    cause_step: int
    effect_step: int
    cause_type: str          # 'data_dependency' | 'control_dependency' | 'state_change' | 'recursive_invocation'
    variable: Optional[str]  # the variable that links cause to effect
    confidence: float
    description: str


@dataclass
class CausalNode:
    """A node in the causal graph — an execution event with its causal context."""
    step: int
    event_type: str
    code: str
    caused_by: List[int]     # steps that caused this
    causes: List[int]        # steps this causes
    role: str                # 'trigger' | 'propagation' | 'convergence' | 'result'


class CausalGraph:
    """Execution causality graph — transforms temporal sequence into causal structure.

    Causal relationships:
    - data_dependency: A writes var X, B reads var X → A causes B
    - control_dependency: A's condition determines whether B executes
    - state_change: A mutates state that B depends on
    - recursive_invocation: A calls the function that produces B
    """

    def __init__(self):
        pass

    def build(self, events: List[ExecutionEvent],
              match: PatternMatch) -> Tuple[List[CausalNode], List[CausalEdge]]:
        """Build causal graph for events within a pattern match."""
        relevant = [e for e in events if match.start_step <= e.step <= match.end_step]
        if not relevant:
            return [], []

        nodes: List[CausalNode] = []
        edges: List[CausalEdge] = []

        # Build data dependency edges
        data_edges = self._find_data_dependencies(relevant)
        edges.extend(data_edges)

        # Build control dependency edges
        control_edges = self._find_control_dependencies(relevant)
        edges.extend(control_edges)

        # Build state change edges
        state_edges = self._find_state_changes(relevant)
        edges.extend(state_edges)

        # Build recursive invocation edges
        recursion_edges = self._find_recursive_invocations(relevant)
        edges.extend(recursion_edges)

        # Build nodes with causal context
        caused_by: Dict[int, List[int]] = {}
        causes: Dict[int, List[int]] = {}
        for e in edges:
            caused_by.setdefault(e.effect_step, []).append(e.cause_step)
            causes.setdefault(e.cause_step, []).append(e.effect_step)

        for ev in relevant:
            role = self._classify_causal_role(ev, caused_by, causes)
            nodes.append(CausalNode(
                step=ev.step,
                event_type=ev.event_type,
                code='',  # not available here
                caused_by=caused_by.get(ev.step, []),
                causes=causes.get(ev.step, []),
                role=role,
            ))

        return nodes, edges

    def _find_data_dependencies(self, events: List[ExecutionEvent]) -> List[CausalEdge]:
        """A writes var X, B reads var X → A causes B."""
        edges = []
        last_writer: Dict[str, int] = {}

        for ev in events:
            # Reads: check if target_var of a previous event appears in this event's context
            if ev.target_var and ev.target_var in last_writer:
                writer_step = last_writer[ev.target_var]
                if writer_step != ev.step:
                    edges.append(CausalEdge(
                        cause_step=writer_step,
                        effect_step=ev.step,
                        cause_type='data_dependency',
                        variable=ev.target_var,
                        confidence=0.9,
                        description=f'`{ev.target_var}` written at step {writer_step} is read at step {ev.step}',
                    ))

            # Writes: update last writer
            if ev.target_var:
                last_writer[ev.target_var] = ev.step

            # Pointer moves: the pointer variable is both read and written
            if ev.pointer_move:
                ptr = ev.pointer_move.pointer
                if ptr in last_writer and last_writer[ptr] != ev.step:
                    edges.append(CausalEdge(
                        cause_step=last_writer[ptr],
                        effect_step=ev.step,
                        cause_type='data_dependency',
                        variable=ptr,
                        confidence=0.85,
                        description=f'pointer `{ptr}` state from step {last_writer[ptr]} enables step {ev.step}',
                    ))
                last_writer[ptr] = ev.step

        return edges

    def _find_control_dependencies(self, events: List[ExecutionEvent]) -> List[CausalEdge]:
        """A's condition determines whether B executes."""
        edges = []
        conditions = [e for e in events if e.event_type == 'condition']

        for cond in conditions:
            # The next event after a condition is control-dependent on it
            next_events = [e for e in events if e.step > cond.step]
            if next_events:
                next_ev = next_events[0]
                edges.append(CausalEdge(
                    cause_step=cond.step,
                    effect_step=next_ev.step,
                    cause_type='control_dependency',
                    variable=cond.target_var,
                    confidence=0.8,
                    description=f'condition at step {cond.step} controls execution of step {next_ev.step}',
                ))

        return edges

    def _find_state_changes(self, events: List[ExecutionEvent]) -> List[CausalEdge]:
        """A mutates state that B depends on."""
        edges = []
        mutations: Dict[str, int] = {}

        for ev in events:
            # Track state mutations via assignment
            if ev.event_type == 'assignment' and ev.target_var:
                if ev.target_var in mutations:
                    edges.append(CausalEdge(
                        cause_step=mutations[ev.target_var],
                        effect_step=ev.step,
                        cause_type='state_change',
                        variable=ev.target_var,
                        confidence=0.75,
                        description=f'`{ev.target_var}` state change at step {mutations[ev.target_var]} '
                                    f'leads to update at step {ev.step}',
                    ))
                mutations[ev.target_var] = ev.step

            # Pointer updates
            if ev.event_type == 'pointer_move' and ev.pointer_move:
                ptr = ev.pointer_move.pointer
                if ptr in mutations:
                    edges.append(CausalEdge(
                        cause_step=mutations[ptr],
                        effect_step=ev.step,
                        cause_type='state_change',
                        variable=ptr,
                        confidence=0.8,
                        description=f'pointer `{ptr}` mutation at step {mutations[ptr]} '
                                    f'enables traversal at step {ev.step}',
                    ))
                mutations[ptr] = ev.step

        return edges

    def _find_recursive_invocations(self, events: List[ExecutionEvent]) -> List[CausalEdge]:
        """A calls the function that produces B."""
        edges = []
        calls = [e for e in events if e.event_type == 'recursive_call']
        returns = [e for e in events if e.event_type == 'return']

        for call in calls:
            # The closest return after this call is its result
            future_returns = [r for r in returns if r.step > call.step]
            if future_returns:
                edges.append(CausalEdge(
                    cause_step=call.step,
                    effect_step=future_returns[0].step,
                    cause_type='recursive_invocation',
                    variable=None,
                    confidence=0.85,
                    description=f'recursive call at step {call.step} produces result at step {future_returns[0].step}',
                ))

        return edges

    def _classify_causal_role(self, event: ExecutionEvent,
                              caused_by: Dict[int, List[int]],
                              causes: Dict[int, List[int]]) -> str:
        """Classify an event's role in the causal chain."""
        has_causes = event.step in caused_by
        has_effects = event.step in causes

        if event.event_type == 'return':
            return 'result'
        if not has_causes and has_effects:
            return 'trigger'
        if has_causes and has_effects:
            return 'propagation'
        if has_causes and not has_effects:
            return 'convergence'
        return 'isolated'


# ─── P3: Goal Inference Engine ─────────────────────────────────
#
# Recovers optimization objectives from execution traces.
# The system knows "what strategy" but not "what objective."
# Goal types: minimize, maximize, preserve, converge, compress
#
# Without this layer, the system cannot distinguish between:
#   - binary_search (minimize uncertainty in search space)
#   - fibonacci (accumulate values bottom-up)
#   - merge_sort (preserve ordering while dividing)

@dataclass
class Goal:
    """An inferred optimization objective."""
    goal_type: str              # 'minimize' | 'maximize' | 'preserve' | 'converge' | 'compress'
    target: str                 # what's being optimized: 'search_space', 'value', 'ordering', 'state_size', ...
    variable: Optional[str]     # the variable that tracks progress toward the goal
    evidence: List[str]         # human-readable evidence for this goal
    confidence: float           # 0.0–1.0
    start_step: int
    end_step: int
    description: str            # narrative: "minimize search interval [lo, hi] until lo > hi"


class GoalInferenceEngine:
    """Infers optimization objectives from execution traces.

    Analyzes variable trajectories, operation patterns, and termination
    conditions to recover what the algorithm is trying to achieve.

    Goal types:
    - minimize: quantity decreases monotonically (search space, distance, cost)
    - maximize: quantity increases monotonically (coverage, value, score)
    - preserve: ordering/structure maintained throughout (sorted, balanced)
    - converge: system reaches a fixed point (stable state, equilibrium)
    - compress: state dimensionality reduces (memoization, deduplication)
    """

    def infer(self, events: List[ExecutionEvent],
              match: PatternMatch) -> List[Goal]:
        """Infer goals from execution events within a pattern match."""
        goals: List[Goal] = []
        pattern_events = [e for e in events
                          if match.start_step <= e.step <= match.end_step]

        if len(pattern_events) < 2:
            return goals

        # Analyze variable trajectories
        goals.extend(self._detect_minimization(pattern_events, match))
        goals.extend(self._detect_maximization(pattern_events, match))
        goals.extend(self._detect_convergence(pattern_events, match))
        goals.extend(self._detect_preservation(pattern_events, match))
        goals.extend(self._detect_compression(pattern_events, match))

        # Rank by confidence
        goals.sort(key=lambda g: g.confidence, reverse=True)
        return goals

    def _detect_minimization(self, events: List[ExecutionEvent],
                             match: PatternMatch) -> List[Goal]:
        """Detect variables that decrease monotonically (search space shrinking)."""
        goals = []

        # Look for interval narrowing patterns: lo/hi, left/right, start/end
        narrowing_pairs = [
            ('lo', 'hi'), ('left', 'right'), ('start', 'end'),
            ('low', 'high'), ('begin', 'end'), ('min_idx', 'max_idx'),
        ]

        # Track variable value changes across events
        var_values: Dict[str, List[Tuple[int, Any]]] = {}
        for e in events:
            # Extract variable assignments from narration
            for tag in e.semantic_tags:
                if '=' in tag:
                    name, val = tag.split('=', 1)
                    name, val = name.strip(), val.strip()
                    try:
                        val_num = float(val)
                        if name not in var_values:
                            var_values[name] = []
                        var_values[name].append((e.step, val_num))
                    except ValueError:
                        pass

        # Check for narrowing pairs
        for lo_name, hi_name in narrowing_pairs:
            lo_vals = var_values.get(lo_name, [])
            hi_vals = var_values.get(hi_name, [])
            if lo_vals and hi_vals:
                # Check if interval [lo, hi] is shrinking
                lo_increasing = self._is_monotonic(lo_vals, direction='increasing')
                hi_decreasing = self._is_monotonic(hi_vals, direction='decreasing')
                if lo_increasing or hi_decreasing:
                    conf = 0.85 if (lo_increasing and hi_decreasing) else 0.65
                    goals.append(Goal(
                        goal_type='minimize',
                        target='search_space',
                        variable=f'[{lo_name}, {hi_name}]',
                        evidence=[f'{lo_name} 单调递增' if lo_increasing else f'{hi_name} 单调递减',
                                  f'区间 [{lo_name}, {hi_name}] 收缩'],
                        confidence=conf,
                        start_step=match.start_step,
                        end_step=match.end_step,
                        description=f'最小化搜索区间 [{lo_name}, {hi_name}]，直到收敛',
                    ))

        # Generic decreasing variable detection
        for name, vals in var_values.items():
            if len(vals) >= 3 and name not in ('i', 'j', 'k', 'n'):
                if self._is_monotonic(vals, direction='decreasing'):
                    goals.append(Goal(
                        goal_type='minimize',
                        target=name,
                        variable=name,
                        evidence=[f'{name} 单调递减: {vals[0][1]} → {vals[-1][1]}'],
                        confidence=0.6,
                        start_step=match.start_step,
                        end_step=match.end_step,
                        description=f'最小化 {name}: {vals[0][1]} → {vals[-1][1]}',
                    ))

        return goals

    def _detect_maximization(self, events: List[ExecutionEvent],
                             match: PatternMatch) -> List[Goal]:
        """Detect variables that increase monotonically (accumulation)."""
        goals = []

        # Track variable trajectories
        var_values: Dict[str, List[Tuple[int, Any]]] = {}
        for e in events:
            for tag in e.semantic_tags:
                if '=' in tag:
                    name, val = tag.split('=', 1)
                    name, val = name.strip(), val.strip()
                    try:
                        val_num = float(val)
                        if name not in var_values:
                            var_values[name] = []
                        var_values[name].append((e.step, val_num))
                    except ValueError:
                        pass

        # Accumulation patterns: sum, count, total, result
        accumulation_names = {'sum', 'total', 'count', 'result', 'acc', 'score', 'max_val', 'profit'}

        for name, vals in var_values.items():
            if len(vals) >= 3:
                if self._is_monotonic(vals, direction='increasing'):
                    is_accumulator = name.lower() in accumulation_names
                    conf = 0.8 if is_accumulator else 0.55
                    goals.append(Goal(
                        goal_type='maximize',
                        target=name,
                        variable=name,
                        evidence=[f'{name} 单调递增: {vals[0][1]} → {vals[-1][1]}'],
                        confidence=conf,
                        start_step=match.start_step,
                        end_step=match.end_step,
                        description=f'最大化 {name}: {vals[0][1]} → {vals[-1][1]}',
                    ))

        return goals

    def _detect_convergence(self, events: List[ExecutionEvent],
                            match: PatternMatch) -> List[Goal]:
        """Detect convergence to fixed point (two-pointer meeting, binary search termination)."""
        goals = []

        # Track variable trajectories
        var_values: Dict[str, List[Tuple[int, Any]]] = {}
        for e in events:
            for tag in e.semantic_tags:
                if '=' in tag:
                    name, val = tag.split('=', 1)
                    name, val = name.strip(), val.strip()
                    try:
                        val_num = float(val)
                        if name not in var_values:
                            var_values[name] = []
                        var_values[name].append((e.step, val_num))
                    except ValueError:
                        pass

        # Convergence: two variables meeting (slow/fast pointers, lo/hi meeting)
        converging_pairs = [
            ('slow', 'fast'), ('lo', 'hi'), ('left', 'right'),
            ('tortoise', 'hare'), ('i', 'j'),
        ]

        for a_name, b_name in converging_pairs:
            a_vals = var_values.get(a_name, [])
            b_vals = var_values.get(b_name, [])
            if a_vals and b_vals:
                # Check if they converge (difference → 0)
                if len(a_vals) >= 2 and len(b_vals) >= 2:
                    initial_diff = abs(a_vals[0][1] - b_vals[0][1])
                    final_diff = abs(a_vals[-1][1] - b_vals[-1][1])
                    if initial_diff > 0 and final_diff < initial_diff * 0.3:
                        goals.append(Goal(
                            goal_type='converge',
                            target=f'{a_name}={b_name}',
                            variable=f'{a_name}, {b_name}',
                            evidence=[f'{a_name} 和 {b_name} 从距离 {initial_diff:.1f} 收敛到 {final_diff:.1f}'],
                            confidence=0.85,
                            start_step=match.start_step,
                            end_step=match.end_step,
                            description=f'{a_name} 和 {b_name} 收敛到同一位置',
                        ))

        # Fixed-point: variable stops changing
        for name, vals in var_values.items():
            if len(vals) >= 4:
                # Check if last few values are identical
                last_vals = [v for _, v in vals[-3:]]
                if len(set(last_vals)) == 1 and vals[0][1] != vals[-1][1]:
                    goals.append(Goal(
                        goal_type='converge',
                        target=f'{name}_fixed_point',
                        variable=name,
                        evidence=[f'{name} 收敛到固定值 {vals[-1][1]}'],
                        confidence=0.7,
                        start_step=match.start_step,
                        end_step=match.end_step,
                        description=f'{name} 收敛到不动点 {vals[-1][1]}',
                    ))

        return goals

    def _detect_preservation(self, events: List[ExecutionEvent],
                             match: PatternMatch) -> List[Goal]:
        """Detect ordering/structure preservation (merge sort, heap operations)."""
        goals = []

        # Look for sort/merge/heap operations in semantic tags
        sort_indicators = {'sort', 'merge', 'heap', 'partition', 'ordered', 'sorted'}
        structure_indicators = {'balanced', 'bst', 'heap_property', 'invariant'}

        all_tags = set()
        for e in events:
            all_tags.update(e.semantic_tags)

        has_sort = bool(all_tags & sort_indicators)
        has_structure = bool(all_tags & structure_indicators)

        if has_sort:
            goals.append(Goal(
                goal_type='preserve',
                target='ordering',
                variable=None,
                evidence=['检测到排序/归并操作语义标签'],
                confidence=0.75,
                start_step=match.start_step,
                end_step=match.end_step,
                description='保持元素有序性（排序/归并目标）',
            ))

        if has_structure:
            goals.append(Goal(
                goal_type='preserve',
                target='structural_invariant',
                variable=None,
                evidence=['检测到结构不变量语义标签'],
                confidence=0.7,
                start_step=match.start_step,
                end_step=match.end_step,
                description='维护数据结构不变量（平衡性/堆性质）',
            ))

        return goals

    def _detect_compression(self, events: List[ExecutionEvent],
                            match: PatternMatch) -> List[Goal]:
        """Detect state compression (memoization, caching, deduplication)."""
        goals = []

        # Look for memo/cache patterns
        memo_indicators = {'memo', 'cache', 'dp', 'memoize', 'lookup', 'table'}
        all_tags = set()
        for e in events:
            all_tags.update(e.semantic_tags)

        # Check semantic tags for memoization
        has_memo = bool(all_tags & memo_indicators)

        # Check pattern name for DP/memo patterns
        pattern_name = match.pattern_name.lower()
        is_dp = any(kw in pattern_name for kw in ['dynamic', 'memo', 'dp', 'cache'])

        if has_memo or is_dp:
            goals.append(Goal(
                goal_type='compress',
                target='state_space',
                variable=None,
                evidence=['检测到记忆化/缓存语义标签' if has_memo else '模式名称包含DP/memo关键词'],
                confidence=0.8 if (has_memo and is_dp) else 0.6,
                start_step=match.start_step,
                end_step=match.end_step,
                description='通过缓存压缩状态空间，避免重复计算',
            ))

        return goals

    @staticmethod
    def _is_monotonic(vals: List[Tuple[int, Any]],
                      direction: str = 'increasing') -> bool:
        """Check if values are monotonically increasing or decreasing."""
        if len(vals) < 2:
            return False
        nums = [v for _, v in vals]
        if direction == 'increasing':
            return all(nums[i] <= nums[i + 1] for i in range(len(nums) - 1))
        else:
            return all(nums[i] >= nums[i + 1] for i in range(len(nums) - 1))


# ─── P4: Counterfactual Reasoning Engine ───────────────────────
#
# Answers "what would break if X changed?"
#
# For each critical operation in the trace:
#   1. Identify the operation's role (progress, guard, accumulator, base case)
#   2. Simulate removal: what invariant would be violated?
#   3. Generate counterfactual narrative
#
# Example: "If lo were not updated, the search interval would not shrink,
#           and the algorithm would loop forever."

@dataclass
class Counterfactual:
    """A counterfactual: what would happen if something changed."""
    condition: str          # what we're hypothetically changing
    consequence: str        # what would break
    severity: str           # 'critical' | 'major' | 'minor'
    confidence: float       # 0.0–1.0
    affected_invariant: str # which invariant would be violated
    category: str           # 'progress_loss' | 'termination_loss' | 'correctness_loss' | 'efficiency_loss'


class CounterfactualEngine:
    """Reasons about what would break if key operations were removed.

    Uses invariants as the backbone: each invariant has dependencies,
    and removing a dependency breaks the invariant.
    """

    def reason(self, events: List[ExecutionEvent],
               match: PatternMatch,
               invariants: List[Invariant],
               goals: List[Goal]) -> List[Counterfactual]:
        """Generate counterfactuals from invariants and goals."""
        counterfactuals: List[Counterfactual] = []

        # Reason about invariant dependencies
        counterfactuals.extend(self._reason_from_invariants(invariants, events, match))

        # Reason about goal dependencies
        counterfactuals.extend(self._reason_from_goals(goals, events, match))

        # Deduplicate and rank
        seen = set()
        unique = []
        for cf in counterfactuals:
            key = (cf.condition, cf.consequence)
            if key not in seen:
                seen.add(key)
                unique.append(cf)
        unique.sort(key=lambda c: c.confidence, reverse=True)
        return unique

    def _reason_from_invariants(self, invariants: List[Invariant],
                                events: List[ExecutionEvent],
                                match: PatternMatch) -> List[Counterfactual]:
        """For each invariant, ask: what if its dependencies were violated?"""
        cfs = []

        for inv in invariants:
            if not inv.depends_on:
                continue

            for dep_name in inv.depends_on:
                severity = 'critical' if inv.category in ('termination', 'loop_invariant') else 'major'
                cfs.append(Counterfactual(
                    condition=f'如果 {dep_name} 不成立',
                    consequence=f'{inv.name} 将被违反: {inv.description}',
                    severity=severity,
                    confidence=inv.confidence * 0.8,
                    affected_invariant=inv.name,
                    category=self._invariant_to_category(inv.category),
                ))

        # Progress-specific counterfactuals
        progress_invariants = [i for i in invariants if i.category == 'progress']
        for inv in progress_invariants:
            cfs.append(Counterfactual(
                condition=f'如果进展条件 {inv.predicate} 不被维护',
                consequence='算法将无法终止，陷入无限循环',
                severity='critical',
                confidence=inv.confidence * 0.9,
                affected_invariant=inv.name,
                category='termination_loss',
            ))

        return cfs

    def _reason_from_goals(self, goals: List[Goal],
                           events: List[ExecutionEvent],
                           match: PatternMatch) -> List[Counterfactual]:
        """For each goal, reason about what would happen without it."""
        cfs = []

        for goal in goals:
            if goal.goal_type == 'minimize':
                cfs.append(Counterfactual(
                    condition=f'如果 {goal.variable or goal.target} 不被缩小',
                    consequence=f'搜索空间不会收缩，算法效率退化为线性或无限',
                    severity='major',
                    confidence=goal.confidence * 0.7,
                    affected_invariant=f'progress_{goal.target}',
                    category='efficiency_loss',
                ))
            elif goal.goal_type == 'converge':
                cfs.append(Counterfactual(
                    condition=f'如果 {goal.variable or goal.target} 不收敛',
                    consequence='算法将无法找到终止条件，可能无限循环',
                    severity='critical',
                    confidence=goal.confidence * 0.8,
                    affected_invariant=f'convergence_{goal.target}',
                    category='termination_loss',
                ))
            elif goal.goal_type == 'compress':
                cfs.append(Counterfactual(
                    condition='如果缓存/记忆化被移除',
                    consequence='相同子问题将被重复计算，时间复杂度指数级增长',
                    severity='major',
                    confidence=goal.confidence * 0.85,
                    affected_invariant='memoization_efficiency',
                    category='efficiency_loss',
                ))
            elif goal.goal_type == 'preserve':
                cfs.append(Counterfactual(
                    condition=f'如果 {goal.target} 有序性被破坏',
                    consequence='后续操作可能产生错误结果，正确性无法保证',
                    severity='critical',
                    confidence=goal.confidence * 0.75,
                    affected_invariant=f'ordering_{goal.target}',
                    category='correctness_loss',
                ))

        return cfs

    @staticmethod
    def _invariant_to_category(inv_category: str) -> str:
        mapping = {
            'precondition': 'correctness_loss',
            'loop_invariant': 'correctness_loss',
            'progress': 'progress_loss',
            'termination': 'termination_loss',
            'postcondition': 'correctness_loss',
        }
        return mapping.get(inv_category, 'correctness_loss')


# ─── P5: Semantic Compression Engine ──────────────────────────
#
# Extracts latent computational motifs — the deep structural patterns
# that underlie multiple surface-level operations.
#
# Example: binary search and fibonacci both involve "uncertainty reduction,"
# but through different mechanisms. Semantic compression identifies these
# shared motifs.

@dataclass
class ComputationalMotif:
    """A latent computational motif shared across algorithms."""
    motif: str              # 'uncertainty_reduction' | 'state_compression' | 'frontier_expansion' | ...
    description: str        # human-readable
    evidence: List[str]     # what operations map to this motif
    confidence: float
    depth: int              # 0 = surface, 1 = structural, 2 = deep


class SemanticCompressor:
    """Extracts deep computational motifs from execution traces.

    Motif types:
    - uncertainty_reduction: search, binary search, decision trees
    - state_compression: DP, memoization, caching
    - frontier_expansion: BFS, Dijkstra, exploration
    - constraint_propagation: backtracking, CSP, SAT
    - fixed_point_convergence: iterative algorithms, relaxation
    """

    # Maps operation patterns → motifs
    MOTIF_SIGNATURES = {
        'uncertainty_reduction': {
            'ops': {'search', 'binary_search', 'narrow', 'partition'},
            'patterns': ['binary_search', 'ternary_search', 'bisect'],
            'description': '通过每次操作减少不确定性空间',
        },
        'state_compression': {
            'ops': {'memo', 'cache', 'dp', 'lookup', 'store'},
            'patterns': ['dynamic_programming', 'memoization', 'dp'],
            'description': '通过缓存中间结果压缩状态空间',
        },
        'frontier_expansion': {
            'ops': {'enqueue', 'dequeue', 'expand', 'visit', 'bfs', 'dfs'},
            'patterns': ['bfs', 'dfs', 'dijkstra', 'graph_traversal'],
            'description': '系统性扩展搜索前沿直到覆盖目标',
        },
        'constraint_propagation': {
            'ops': {'backtrack', 'prune', 'try', 'undo', 'constraint'},
            'patterns': ['backtracking', 'n_queens', 'sudoku', 'permutation'],
            'description': '通过约束传播和回溯探索解空间',
        },
        'fixed_point_convergence': {
            'ops': {'iterate', 'relax', 'update', 'converge', 'stable'},
            'patterns': ['bellman_ford', 'floyd_warshall', 'page_rank', 'iterative'],
            'description': '反复迭代直到系统达到不动点',
        },
    }

    def compress(self, events: List[ExecutionEvent],
                 match: PatternMatch,
                 goals: List[Goal]) -> List[ComputationalMotif]:
        """Extract computational motifs from execution trace."""
        motifs: List[ComputationalMotif] = []

        # Collect all semantic tags
        all_tags: set = set()
        for e in events:
            if match.start_step <= e.step <= match.end_step:
                all_tags.update(e.semantic_tags)

        pattern_name = match.pattern_name.lower()

        # Match against motif signatures
        for motif_name, sig in self.MOTIF_SIGNATURES.items():
            score = 0.0
            evidence = []

            # Check operation overlap
            op_overlap = all_tags & sig['ops']
            if op_overlap:
                score += min(len(op_overlap) * 0.2, 0.5)
                evidence.append(f'操作语义: {", ".join(op_overlap)}')

            # Check pattern name
            for pat in sig['patterns']:
                if pat in pattern_name:
                    score += 0.3
                    evidence.append(f'模式名匹配: {pat}')

            # Check goals alignment
            for goal in goals:
                if motif_name == 'uncertainty_reduction' and goal.goal_type == 'minimize':
                    score += 0.15
                    evidence.append(f'目标对齐: 最小化 {goal.target}')
                elif motif_name == 'state_compression' and goal.goal_type == 'compress':
                    score += 0.2
                    evidence.append(f'目标对齐: 压缩状态')
                elif motif_name == 'frontier_expansion' and goal.goal_type == 'maximize':
                    score += 0.1
                    evidence.append(f'目标对齐: 最大化覆盖')
                elif motif_name == 'fixed_point_convergence' and goal.goal_type == 'converge':
                    score += 0.15
                    evidence.append(f'目标对齐: 收敛到不动点')

            if score >= 0.25:
                depth = 0 if score < 0.4 else (1 if score < 0.6 else 2)
                motifs.append(ComputationalMotif(
                    motif=motif_name,
                    description=sig['description'],
                    evidence=evidence,
                    confidence=min(score, 1.0),
                    depth=depth,
                ))

        motifs.sort(key=lambda m: (m.depth, m.confidence), reverse=True)
        return motifs


# ─── P6: Constraint IR (Semantic Intermediate Representation) ──
#
# THE critical upgrade. Replaces heuristic pattern matching with
# declarative constraint reasoning.
#
# Architecture:
#   ExecutionEvent → SemanticFact[] → ConstraintGraph → fixed-point → cognition
#
# Instead of:
#   if "lo" and "hi": infer binary_search_minimization
#
# We write:
#   Fact: Monotonic(lo, increasing, step_2..step_5)
#   Fact: Monotonic(hi, decreasing, step_2..step_5)
#   Fact: Paired(lo, hi, "interval")
#   Rule: Paired(a,b,"interval") ∧ Monotonic(a,increasing) ∧ Monotonic(b,decreasing)
#         → DerivedFact(Shrinks, Interval(a,b))
#   Rule: Shrinks(Interval(a,b)) ∧ Bounded(Interval(a,b))
#         → Invariant(progress, interval_shrinks)
#         → Goal(minimize, search_space)
#
# This is declarative, composable, and doesn't explode.

from enum import Enum


class FactKind(str, Enum):
    """Primitive fact types in the Constraint IR."""
    # Variable properties
    MONOTONIC = 'monotonic'         # Monotonic(var, direction, steps)
    CONSTANT = 'constant'           # Constant(var, value, steps)
    BOUNDED = 'bounded'             # Bounded(var, lower, upper)
    PAIRED = 'paired'               # Paired(var1, var2, relationship)
    CONVERGES = 'converges'         # Converges(var1, var2, steps)
    CHANGES = 'changes'             # Changes(var, step)
    ACCUMULATES = 'accumulates'     # Accumulates(var, operation)

    # Structural properties
    RECURSIVE = 'recursive'         # Recursive(func, depth)
    BRANCHING = 'branching'         # Branching(step, condition)
    LOOPING = 'looping'             # Looping(step, guard)
    BASE_CASE = 'base_case'         # BaseCase(step, condition)
    MEMOIZED = 'memoized'           # Memoized(func, cache_var)

    # Derived properties
    SHRINKS = 'shrinks'             # Shrinks(interval) — derived
    REACHABLE = 'reachable'         # Reachable(target, from) — derived
    STABLE = 'stable'               # Stable(state, step) — derived
    DOMINATES = 'dominates'         # Dominates(step1, step2) — derived

    # Goal-level
    OBJECTIVE = 'objective'         # Objective(type, target) — derived
    INVARIANT = 'invariant'         # Invariant(category, predicate) — derived
    COUNTERFACTUAL = 'counterfactual'  # Counterfactual(condition, consequence) — derived


@dataclass
class SemanticFact:
    """A primitive fact in the Constraint IR.

    This is the atomic unit of semantic knowledge.
    All cognition (goals, invariants, counterfactuals, motifs)
    is derived from facts through constraint rules.

    P7: Use typed constructors (MonotonicFact, PairedFact, etc.)
    for type-safe fact creation instead of raw SemanticFact.
    """
    kind: FactKind
    subject: str                    # primary entity (variable name, step, etc.)
    relation: str = ''              # secondary qualifier (direction, relationship, etc.)
    value: Any = None               # optional value (bound, constant, etc.)
    steps: Tuple[int, ...] = ()     # step range where this fact holds
    confidence: float = 1.0
    source: str = ''                # 'observed' | 'derived'
    evidence: str = ''              # human-readable evidence
    depends_on: Tuple[str, ...] = ()  # fact IDs this was derived from

    # P8: Provenance tracking
    derived_from_rule: str = ''     # name of the rule that derived this fact
    derived_from_facts: Tuple[str, ...] = ()  # fact IDs used to derive this

    @property
    def id(self) -> str:
        """Unique identifier for this fact."""
        return f'{self.kind.value}:{self.subject}:{self.relation}:{self.value}'

    def to_dict(self) -> Dict[str, Any]:
        return {
            'kind': self.kind.value,
            'subject': self.subject,
            'relation': self.relation,
            'value': self.value,
            'steps': list(self.steps),
            'confidence': self.confidence,
            'source': self.source,
            'evidence': self.evidence,
            'derived_from_rule': self.derived_from_rule,
            'derived_from_facts': list(self.derived_from_facts),
        }


# ─── P7: Typed Fact Constructors ──────────────────────────────
#
# Type-safe constructors for SemanticFact.
# Instead of: SemanticFact(FactKind.MONOTONIC, 'lo', 'increasing')
# Write:      MonotonicFact('lo', 'increasing')
#
# Each constructor encodes the semantic structure of its fact type,
# making the code self-documenting and preventing string soup.

def MonotonicFact(var: str, direction: str, steps: Tuple[int, ...] = (),
                  confidence: float = 1.0, source: str = '',
                  evidence: str = '') -> SemanticFact:
    """Variable `var` is monotonically `direction` (increasing/decreasing)."""
    return SemanticFact(
        kind=FactKind.MONOTONIC, subject=var, relation=direction,
        steps=steps, confidence=confidence, source=source,
        evidence=evidence or f'{var} 单调{direction}',
    )

def PairedFact(var1: str, var2: str, relationship: str = 'interval',
               steps: Tuple[int, ...] = (), confidence: float = 1.0,
               source: str = '', evidence: str = '') -> SemanticFact:
    """Two variables form a structural pair (interval, sorted, etc.)."""
    return SemanticFact(
        kind=FactKind.PAIRED, subject=var1, relation=relationship,
        value=var2, steps=steps, confidence=confidence, source=source,
        evidence=evidence or f'{var1} 和 {var2} 形成 {relationship}',
    )

def ConvergesFact(var1: str, var2: str, steps: Tuple[int, ...] = (),
                  confidence: float = 1.0, source: str = '',
                  evidence: str = '') -> SemanticFact:
    """Two variables are converging toward each other."""
    return SemanticFact(
        kind=FactKind.CONVERGES, subject=var1, relation='converges_with',
        value=var2, steps=steps, confidence=confidence, source=source,
        evidence=evidence or f'{var1} 和 {var2} 正在收敛',
    )

def LoopingFact(step: int, steps: Tuple[int, ...] = (),
                confidence: float = 1.0, source: str = '',
                evidence: str = '') -> SemanticFact:
    """A loop guard exists at this step."""
    return SemanticFact(
        kind=FactKind.LOOPING, subject=str(step),
        steps=(step,) if not steps else steps,
        confidence=confidence, source=source,
        evidence=evidence or f'步骤 {step}: 循环守卫',
    )

def RecursiveFact(func: str, steps: Tuple[int, ...] = (),
                  confidence: float = 1.0, source: str = '',
                  evidence: str = '') -> SemanticFact:
    """Function `func` has a recursive call."""
    return SemanticFact(
        kind=FactKind.RECURSIVE, subject=func,
        steps=steps, confidence=confidence, source=source,
        evidence=evidence or f'{func} 是递归函数',
    )

def MemoizedFact(var: str, steps: Tuple[int, ...] = (),
                 confidence: float = 1.0, source: str = '',
                 evidence: str = '') -> SemanticFact:
    """Variable `var` is used for memoization/caching."""
    return SemanticFact(
        kind=FactKind.MEMOIZED, subject=var,
        steps=steps, confidence=confidence, source=source,
        evidence=evidence or f'{var} 用于缓存',
    )

def AccumulatesFact(var: str, steps: Tuple[int, ...] = (),
                    confidence: float = 1.0, source: str = '',
                    evidence: str = '') -> SemanticFact:
    """Variable `var` accumulates a value (sum, count, etc.)."""
    return SemanticFact(
        kind=FactKind.ACCUMULATES, subject=var,
        steps=steps, confidence=confidence, source=source,
        evidence=evidence or f'{var} 是累积变量',
    )

def ShrinksFact(interval: str, steps: Tuple[int, ...] = (),
                confidence: float = 1.0, source: str = 'derived',
                evidence: str = '') -> SemanticFact:
    """An interval or quantity is shrinking (derived from monotonic pair)."""
    return SemanticFact(
        kind=FactKind.SHRINKS, subject=interval,
        steps=steps, confidence=confidence, source=source,
        evidence=evidence or f'{interval} 单调收缩',
    )

def ObjectiveFact(goal_type: str, target: str, steps: Tuple[int, ...] = (),
                  confidence: float = 1.0, source: str = 'derived',
                  evidence: str = '') -> SemanticFact:
    """An optimization objective (minimize, maximize, converge, etc.)."""
    return SemanticFact(
        kind=FactKind.OBJECTIVE, subject=goal_type, relation=target,
        steps=steps, confidence=confidence, source=source,
        evidence=evidence or f'目标: {goal_type} {target}',
    )

def InvariantFact(category: str, predicate: str, steps: Tuple[int, ...] = (),
                  confidence: float = 1.0, source: str = 'derived',
                  evidence: str = '') -> SemanticFact:
    """A correctness invariant (progress, termination, loop_invariant, etc.)."""
    return SemanticFact(
        kind=FactKind.INVARIANT, subject=category, relation=predicate,
        steps=steps, confidence=confidence, source=source,
        evidence=evidence or f'{category}: {predicate}',
    )

def CounterfactualFact(condition: str, consequence: str, steps: Tuple[int, ...] = (),
                       confidence: float = 1.0, source: str = 'derived',
                       evidence: str = '') -> SemanticFact:
    """A counterfactual: if condition, then consequence."""
    return SemanticFact(
        kind=FactKind.COUNTERFACTUAL, subject=condition, relation=consequence,
        steps=steps, confidence=confidence, source=source,
        evidence=evidence or f'如果 {condition} → {consequence}',
    )


@dataclass
class ConstraintRule:
    """A declarative rule that derives new facts from existing ones.

    Format:
        name: human-readable rule name
        requires: list of fact patterns that must all match
        produces: list of fact templates to create when matched
        description: why this rule exists

    A fact pattern is a SemanticFact with optional wildcards (None = any).
    Matching is structural: kind, subject, relation must match (if non-None).
    """
    name: str
    requires: List[SemanticFact]
    produces: List[SemanticFact]
    description: str = ''


class ConstraintGraph:
    """The Semantic Intermediate Representation.

    Stores facts and derives higher-level cognition through
    fixed-point iteration over constraint rules.

    This is the backbone that replaces all heuristic engines.
    """

    def __init__(self):
        self.facts: Dict[str, SemanticFact] = {}  # id → fact
        self.derivation_chain: Dict[str, List[str]] = {}  # fact_id → [source_fact_ids]
        self._rules: List[ConstraintRule] = self._build_rules()
        self._stratified: List[StratifiedRule] = stratify_rules(self._rules)
        self._stratum_stats: Dict[int, int] = {}  # stratum → facts derived
        self._conflicts: List[Dict[str, Any]] = []  # P12: detected contradictions

        # P11: Build fact-kind → rule index for incremental propagation
        self._kind_to_rules: Dict[FactKind, List[ConstraintRule]] = {}
        for rule in self._rules:
            for req in rule.requires:
                if req.kind not in self._kind_to_rules:
                    self._kind_to_rules[req.kind] = []
                if rule not in self._kind_to_rules[req.kind]:
                    self._kind_to_rules[req.kind].append(rule)

    def add_fact(self, fact: SemanticFact) -> str:
        """Add a fact to the graph. Canonicalizes first (P9). Returns the fact's ID.

        P12: Also checks for conflicts (contradictory facts).
        """
        fact = canonicalize(fact)  # P9: normalize
        fid = fact.id
        if fid not in self.facts:
            self.facts[fid] = fact
            # P12: Conflict detection
            self._detect_conflicts(fact)
        else:
            # Merge: keep higher confidence, union steps
            existing = self.facts[fid]
            existing.confidence = max(existing.confidence, fact.confidence)
            existing.steps = tuple(sorted(set(existing.steps) | set(fact.steps)))
        return fid

    def add_facts(self, facts: List[SemanticFact]) -> None:
        for f in facts:
            self.add_fact(f)

    def query(self, kind: Optional[FactKind] = None,
              subject: Optional[str] = None,
              relation: Optional[str] = None) -> List[SemanticFact]:
        """Query facts by pattern. None = wildcard."""
        results = []
        for f in self.facts.values():
            if kind and f.kind != kind:
                continue
            if subject and f.subject != subject:
                continue
            if relation and f.relation != relation:
                continue
            results.append(f)
        return results

    def fixed_point(self, max_iterations: int = 10) -> int:
        """Run stratified fixed-point iteration (P10).

        Rules fire in stratum order (L0 → L6), ensuring prerequisites
        are available before higher-level rules run.
        Returns total number of new facts derived.
        """
        total_new = 0
        for _ in range(max_iterations):
            round_new = 0
            # P10: Execute strata in order
            for stratum in range(7):
                stratum_rules = [sr.rule for sr in self._stratified if sr.stratum == stratum]
                if not stratum_rules:
                    continue
                new_facts = self._apply_rules_subset(stratum_rules)
                round_new += len(new_facts)
                self._stratum_stats[stratum] = self._stratum_stats.get(stratum, 0) + len(new_facts)
            if round_new == 0:
                break
            total_new += round_new
        return total_new

    def _apply_rules(self) -> List[SemanticFact]:
        """Apply all rules once. Return newly derived facts with provenance."""
        return self._apply_rules_subset(self._rules)

    def _apply_rules_subset(self, rules: List[ConstraintRule]) -> List[SemanticFact]:
        """Apply a subset of rules once. Return newly derived facts with provenance."""
        new_facts = []
        existing_ids = set(self.facts.keys())

        for rule in rules:
            matches = self._match_rule(rule)
            for match_bindings in matches:
                for prod_template in rule.produces:
                    derived = self._instantiate(prod_template, match_bindings)
                    if derived.id not in existing_ids:
                        derived.source = 'derived'
                        # P8: Provenance tracking
                        derived.derived_from_rule = rule.name
                        derived.derived_from_facts = tuple(
                            b.id for b in match_bindings.values()
                        )
                        self.add_fact(derived)
                        self.derivation_chain[derived.id] = list(derived.derived_from_facts)
                        new_facts.append(derived)
        return new_facts

    # ─── P11: Incremental Fixpoint (Delta Propagation) ─────────

    def incremental_fixed_point(self, initial_facts: List[SemanticFact],
                                max_iterations: int = 10) -> int:
        """Incremental fixpoint: only re-evaluate rules affected by new facts.

        Instead of batch re-computation (O(rules × facts)), this uses
        delta propagation: new facts → affected rules → new derived facts → repeat.

        This is the scalable version of fixed_point().
        """
        # Seed: add initial facts and collect the delta
        delta: List[SemanticFact] = []
        for f in initial_facts:
            fid = self.add_fact(f)
            if fid in self.facts:
                delta.append(self.facts[fid])

        total_new = 0
        for _ in range(max_iterations):
            if not delta:
                break

            # Find rules affected by delta facts
            affected_rules = self._find_affected_rules(delta)

            # Apply only affected rules (per stratum)
            next_delta: List[SemanticFact] = []
            for stratum in range(7):
                stratum_rules = [
                    r for r in affected_rules
                    if any(sr.rule is r and sr.stratum == stratum
                           for sr in self._stratified)
                ]
                if not stratum_rules:
                    continue
                new_facts = self._apply_rules_subset(stratum_rules)
                next_delta.extend(new_facts)
                self._stratum_stats[stratum] = self._stratum_stats.get(stratum, 0) + len(new_facts)

            total_new += len(next_delta)
            delta = next_delta

        return total_new

    def _find_affected_rules(self, delta: List[SemanticFact]) -> List[ConstraintRule]:
        """Find rules whose requirements overlap with the delta facts.

        Uses the kind → rules index for O(1) lookup per fact kind.
        """
        affected = set()
        for fact in delta:
            for rule in self._kind_to_rules.get(fact.kind, []):
                affected.add(id(rule))
        return [r for r in self._rules if id(r) in affected]

    # ─── P12: Conflict Detection (Contradiction Lattice) ───────

    def _detect_conflicts(self, new_fact: SemanticFact) -> None:
        """Check if a new fact contradicts existing facts.

        Detected conflicts:
        - Same variable, same kind, opposite direction (increasing vs decreasing)
        - Same variable, incompatible kinds (MONOTONIC vs CONSTANT)
        """
        if new_fact.kind == FactKind.MONOTONIC:
            # Check for opposite monotonicity on same variable
            opposite = 'decreasing' if new_fact.relation == 'increasing' else 'increasing'
            opposite_id = f'monotonic:{new_fact.subject}:{opposite}:None'
            if opposite_id in self.facts:
                self._conflicts.append({
                    'type': 'contradictory_monotonicity',
                    'subject': new_fact.subject,
                    'fact_a': new_fact.id,
                    'fact_b': opposite_id,
                    'description': f'{new_fact.subject} 同时被标记为递增和递减',
                    'severity': 'critical',
                })

        if new_fact.kind == FactKind.CONSTANT:
            # Check if variable is also monotonic (contradiction)
            for direction in ('increasing', 'decreasing'):
                mono_id = f'monotonic:{new_fact.subject}:{direction}:None'
                if mono_id in self.facts:
                    self._conflicts.append({
                        'type': 'constant_vs_monotonic',
                        'subject': new_fact.subject,
                        'fact_a': new_fact.id,
                        'fact_b': mono_id,
                        'description': f'{new_fact.subject} 同时被标记为常量和单调变化',
                        'severity': 'warning',
                    })

    @property
    def conflicts(self) -> List[Dict[str, Any]]:
        """Return detected conflicts."""
        return self._conflicts

    # ─── P8: Provenance & Explainability ───────────────────────

    def explain(self, fact_id: str, depth: int = 0, max_depth: int = 10) -> List[Dict[str, Any]]:
        """Explain the derivation chain for a fact.

        Returns a list of reasoning steps, each containing:
        - fact: the fact at this step
        - rule: the rule that derived it (if any)
        - inputs: the facts that were used as inputs
        - depth: nesting level

        This is the "proof tree" for a derived fact.
        """
        if depth > max_depth:
            return []

        fact = self.facts.get(fact_id)
        if not fact:
            return []

        chain = []
        source_facts = self.derivation_chain.get(fact_id, [])

        # Recurse into source facts first (bottom-up)
        for src_id in source_facts:
            chain.extend(self.explain(src_id, depth + 1, max_depth))

        # Then add this fact
        chain.append({
            'fact': fact.to_dict(),
            'rule': fact.derived_from_rule or '',
            'source_facts': source_facts,
            'depth': depth,
        })

        return chain

    def explain_dag(self) -> Dict[str, Any]:
        """Export the full reasoning DAG for visualization (P10: includes stratum).

        Returns nodes (facts) and edges (derivation relationships).
        """
        # Build rule → stratum mapping
        rule_stratum = {}
        for sr in self._stratified:
            rule_stratum[sr.rule.name] = int(sr.stratum)

        nodes = []
        edges = []
        for fid, fact in self.facts.items():
            # Determine stratum: observed facts are L0, derived facts inherit from rule
            if fact.source == 'observed':
                stratum = 0
            else:
                stratum = rule_stratum.get(fact.derived_from_rule, 1)

            nodes.append({
                'id': fid,
                'kind': fact.kind.value,
                'subject': fact.subject,
                'relation': fact.relation,
                'value': fact.value,
                'source': fact.source,
                'confidence': fact.confidence,
                'evidence': fact.evidence,
                'rule': fact.derived_from_rule,
                'stratum': stratum,
                'stratum_name': STRATUM_NAMES.get(stratum, f'L{stratum}'),
            })
            for src_id in self.derivation_chain.get(fid, []):
                edges.append({
                    'from': src_id,
                    'to': fid,
                    'rule': fact.derived_from_rule,
                })
        return {'nodes': nodes, 'edges': edges}

    def _match_rule(self, rule: ConstraintRule) -> List[Dict[str, SemanticFact]]:
        """Find all ways to satisfy a rule's requirements.

        Returns list of binding maps: {template_subject → matched_fact}.
        Enforces that different named wildcards bind to DIFFERENT subjects.
        """
        if not rule.requires:
            return [{}]

        bindings_list: List[Dict[str, SemanticFact]] = [{}]

        for req in rule.requires:
            new_bindings = []
            for bindings in bindings_list:
                candidates = self._find_matching(req, bindings)
                for candidate in candidates:
                    new_b = dict(bindings)
                    # Bind the template subject to the matched fact
                    if req.subject not in new_b:
                        new_b[req.subject] = candidate
                    # Enforce: different wildcards must bind to different subjects
                    if self._bindings_valid(new_b):
                        new_bindings.append(new_b)
            bindings_list = new_bindings
            if not bindings_list:
                break

        return bindings_list

    @staticmethod
    def _bindings_valid(bindings: Dict[str, SemanticFact]) -> bool:
        """Check that different named wildcards don't bind to the same fact."""
        seen_ids: set = set()
        for key, fact in bindings.items():
            if key.startswith('*'):
                if fact.id in seen_ids:
                    return False  # Two wildcards bound to same fact
                seen_ids.add(fact.id)
        return True

    def _find_matching(self, template: SemanticFact,
                       bindings: Dict[str, SemanticFact]) -> List[SemanticFact]:
        """Find facts matching a template, respecting existing bindings.

        Named wildcards (subjects starting with '*') are bindable placeholders.
        Each unique wildcard name binds to exactly one FACT (by id, not just subject).
        Different fact kinds with the same subject can bind to different wildcards.
        """
        results = []
        is_wildcard = template.subject.startswith('*')

        # Build set of already-bound fact IDs (to prevent double-binding same fact)
        bound_fact_ids = {f.id for f in bindings.values()}

        for fact in self.facts.values():
            # Kind must match
            if template.kind != fact.kind:
                continue
            # Subject matching
            if is_wildcard:
                # If this wildcard is already bound, the fact's subject must match
                if template.subject in bindings:
                    if bindings[template.subject].subject != fact.subject:
                        continue
                # Don't bind the same fact to two different wildcards
                if fact.id in bound_fact_ids:
                    continue
            else:
                if template.subject != fact.subject:
                    continue
            # Relation: must match if specified
            if template.relation and template.relation != '*' and template.relation != fact.relation:
                continue
            results.append(fact)
        return results

    def _instantiate(self, template: SemanticFact,
                     bindings: Dict[str, SemanticFact]) -> SemanticFact:
        """Create a concrete fact from a template + bindings.

        Named wildcards (e.g. '*pair', '*lo') are resolved from bindings.
        Literal subjects pass through unchanged.
        """
        subject = template.subject
        if subject.startswith('*') and subject in bindings:
            subject = bindings[subject].subject

        # Also resolve value if it's a named wildcard
        value = template.value
        if isinstance(value, str) and value.startswith('*') and value in bindings:
            value = bindings[value].subject

        # Collect steps from all bindings
        all_steps = set(template.steps)
        for b in bindings.values():
            all_steps.update(b.steps)

        return SemanticFact(
            kind=template.kind,
            subject=subject,
            relation=template.relation,
            value=value,
            steps=tuple(sorted(all_steps)),
            confidence=min(b.confidence for b in bindings.values()) if bindings else template.confidence,
            evidence=template.evidence,
        )

    # ─── Declarative Rule Definitions ─────────────────────────

    def _build_rules(self) -> List[ConstraintRule]:
        """Build the constraint rule set.

        These are DECLARATIVE — they describe WHAT to derive, not HOW to detect.
        This is the core difference from heuristic engines.
        """
        return [
            # ── Interval Shrinking ──
            ConstraintRule(
                name='interval_shrinks',
                description='If two variables form an interval and one increases while the other decreases, the interval shrinks.',
                requires=[
                    SemanticFact(FactKind.PAIRED, '*pair', 'interval'),
                    SemanticFact(FactKind.MONOTONIC, '*lo', 'increasing'),
                    SemanticFact(FactKind.MONOTONIC, '*hi', 'decreasing'),
                ],
                produces=[
                    SemanticFact(FactKind.SHRINKS, '*pair', '',
                                 evidence='区间单调收缩', confidence=0.9),
                ],
            ),

            # ── Progress Guarantee ──
            ConstraintRule(
                name='shrinking_interval_progress',
                description='A shrinking interval guarantees progress toward termination.',
                requires=[
                    SemanticFact(FactKind.SHRINKS, '*interval'),
                    SemanticFact(FactKind.LOOPING, '*loop'),
                ],
                produces=[
                    SemanticFact(FactKind.INVARIANT, 'progress', 'interval_shrinks',
                                 evidence='区间收缩保证进展', confidence=0.9),
                    SemanticFact(FactKind.OBJECTIVE, 'minimize', 'search_space',
                                 evidence='目标: 最小化搜索空间', confidence=0.85),
                ],
            ),

            # ── Convergence → Termination ──
            ConstraintRule(
                name='convergence_termination',
                description='If interval shrinks to a point, termination is guaranteed.',
                requires=[
                    SemanticFact(FactKind.SHRINKS, '*s'),
                    SemanticFact(FactKind.CONVERGES, '*c'),
                ],
                produces=[
                    SemanticFact(FactKind.INVARIANT, 'termination', 'convergence',
                                 evidence='收敛保证终止', confidence=0.9),
                    SemanticFact(FactKind.OBJECTIVE, 'converge', '*c',
                                 evidence='目标: 收敛到不动点', confidence=0.85),
                ],
            ),

            # ── Accumulation → Maximization ──
            ConstraintRule(
                name='accumulation_maximization',
                description='A variable that accumulates (sum, count) is being maximized.',
                requires=[
                    SemanticFact(FactKind.ACCUMULATES, '*acc'),
                    SemanticFact(FactKind.MONOTONIC, '*acc', 'increasing'),
                ],
                produces=[
                    SemanticFact(FactKind.OBJECTIVE, 'maximize', '*acc',
                                 evidence='目标: 最大化累积值', confidence=0.8),
                ],
            ),

            # ── Memoization → Compression ──
            ConstraintRule(
                name='memoization_compression',
                description='Memoization compresses the state space by caching subproblem results.',
                requires=[
                    SemanticFact(FactKind.MEMOIZED, '*memo'),
                ],
                produces=[
                    SemanticFact(FactKind.OBJECTIVE, 'compress', 'state_space',
                                 evidence='目标: 通过缓存压缩状态空间', confidence=0.85),
                    SemanticFact(FactKind.INVARIANT, 'progress', 'subproblems_cached',
                                 evidence='子问题被缓存避免重复计算', confidence=0.8),
                ],
            ),

            # ── Recursion + Base Case → Termination ──
            ConstraintRule(
                name='recursion_base_case_termination',
                description='Recursion with a base case guarantees termination if the problem shrinks.',
                requires=[
                    SemanticFact(FactKind.RECURSIVE, '*func'),
                    SemanticFact(FactKind.BASE_CASE, '*case'),
                ],
                produces=[
                    SemanticFact(FactKind.INVARIANT, 'termination', 'base_case_reached',
                                 evidence='基例保证递归终止', confidence=0.85),
                ],
            ),

            # ── Loop Guard → Loop Invariant ──
            ConstraintRule(
                name='loop_guard_invariant',
                description='A loop guard is a loop invariant that must hold for the loop to continue.',
                requires=[
                    SemanticFact(FactKind.LOOPING, '*loop'),
                ],
                produces=[
                    SemanticFact(FactKind.INVARIANT, 'loop_invariant', 'guard_holds',
                                 evidence='循环守卫在每次迭代中成立', confidence=0.8),
                ],
            ),

            # ── Ordering Preservation ──
            ConstraintRule(
                name='ordering_preservation',
                description='Sort/merge operations preserve ordering as an invariant.',
                requires=[
                    SemanticFact(FactKind.PAIRED, '*pair', 'sorted'),
                ],
                produces=[
                    SemanticFact(FactKind.OBJECTIVE, 'preserve', 'ordering',
                                 evidence='目标: 保持有序性', confidence=0.8),
                    SemanticFact(FactKind.INVARIANT, 'postcondition', 'sorted_output',
                                 evidence='输出保持有序', confidence=0.75),
                ],
            ),

            # ── Shrinking + Looping → Counterfactual ──
            ConstraintRule(
                name='no_progress_counterfactual',
                description='If progress condition were violated, the loop would not terminate.',
                requires=[
                    SemanticFact(FactKind.INVARIANT, 'progress', '*inv'),
                    SemanticFact(FactKind.LOOPING, '*loop'),
                ],
                produces=[
                    SemanticFact(FactKind.COUNTERFACTUAL, 'progress_violated', 'infinite_loop',
                                 evidence='如果进展条件不成立 → 无限循环', confidence=0.85),
                ],
            ),

            # ── Memoization Removal Counterfactual ──
            ConstraintRule(
                name='no_memo_counterfactual',
                description='If memoization were removed, complexity would explode.',
                requires=[
                    SemanticFact(FactKind.MEMOIZED, '*memo'),
                    SemanticFact(FactKind.RECURSIVE, '*func'),
                ],
                produces=[
                    SemanticFact(FactKind.COUNTERFACTUAL, 'memo_removed', 'exponential_blowup',
                                 evidence='如果移除缓存 → 指数级时间复杂度', confidence=0.9),
                ],
            ),
        ]

    # ─── Fact Extraction from Execution Events ────────────────

    @staticmethod
    def extract_facts(events: List[ExecutionEvent],
                      match: PatternMatch) -> List[SemanticFact]:
        """Extract primitive semantic facts from execution events.

        This is the ONLY place where observation meets interpretation.
        Everything above this is pure derivation.
        """
        facts: List[SemanticFact] = []
        pattern_events = [e for e in events
                          if match.start_step <= e.step <= match.end_step]

        if len(pattern_events) < 2:
            return facts

        step_range = (match.start_step, match.end_step)

        # ── Track variable trajectories ──
        var_steps: Dict[str, List[Tuple[int, str]]] = {}  # var → [(step, value_str)]
        for e in pattern_events:
            for tag in e.semantic_tags:
                if '=' in tag:
                    name, val = tag.split('=', 1)
                    name, val = name.strip(), val.strip()
                    if name not in var_steps:
                        var_steps[name] = []
                    var_steps[name].append((e.step, val))

        # ── Observe monotonicity (P7: typed constructors) ──
        for var, vals in var_steps.items():
            nums = []
            for step, v in vals:
                try:
                    nums.append((step, float(v)))
                except ValueError:
                    pass

            if len(nums) >= 2:
                is_inc = all(nums[i][1] <= nums[i+1][1] for i in range(len(nums)-1))
                is_dec = all(nums[i][1] >= nums[i+1][1] for i in range(len(nums)-1))
                steps = tuple(range(nums[0][0], nums[-1][0]+1))

                if is_inc:
                    facts.append(MonotonicFact(var, 'increasing', steps=steps, source='observed',
                        evidence=f'{var} 单调递增: {nums[0][1]} → {nums[-1][1]}'))
                elif is_dec:
                    facts.append(MonotonicFact(var, 'decreasing', steps=steps, source='observed',
                        evidence=f'{var} 单调递减: {nums[0][1]} → {nums[-1][1]}'))

        # ── Observe changes ──
        for var in var_steps:
            if len(var_steps[var]) >= 2:
                facts.append(SemanticFact(
                    kind=FactKind.CHANGES, subject=var,
                    steps=(var_steps[var][0][0], var_steps[var][-1][0]),
                    source='observed', evidence=f'{var} 在执行过程中发生变化',
                ))

        # ── Observe pairs (interval, sorted, etc.) ──
        interval_pairs = [
            ('lo', 'hi'), ('left', 'right'), ('start', 'end'),
            ('low', 'high'), ('begin', 'end'), ('min_idx', 'max_idx'),
        ]
        for a, b in interval_pairs:
            if a in var_steps and b in var_steps:
                facts.append(PairedFact(a, b, 'interval', steps=step_range, source='observed'))

        # ── Observe convergence ──
        converging_pairs = [
            ('slow', 'fast'), ('lo', 'hi'), ('left', 'right'),
            ('tortoise', 'hare'), ('i', 'j'),
        ]
        for a, b in converging_pairs:
            a_vals = [(s, float(v)) for s, v in var_steps.get(a, []) if _try_float(v) is not None]
            b_vals = [(s, float(v)) for s, v in var_steps.get(b, []) if _try_float(v) is not None]
            if len(a_vals) >= 2 and len(b_vals) >= 2:
                init_diff = abs(a_vals[0][1] - b_vals[0][1])
                final_diff = abs(a_vals[-1][1] - b_vals[-1][1])
                if init_diff > 0 and final_diff < init_diff * 0.3:
                    facts.append(ConvergesFact(a, b, steps=(a_vals[0][0], a_vals[-1][0]),
                        source='observed',
                        evidence=f'{a} 和 {b} 收敛: 距离 {init_diff:.1f} → {final_diff:.1f}'))

        # ── Observe looping ──
        for e in pattern_events:
            if e.event_type in ('loop_guard', 'condition', 'loop'):
                facts.append(LoopingFact(e.step, source='observed'))

        # ── Observe recursion ──
        for e in pattern_events:
            if e.event_type == 'recursive_call' or 'recursive' in e.semantic_tags:
                func = e.narration.split('(')[0] if '(' in e.narration else '?'
                facts.append(RecursiveFact(func, steps=(e.step,), source='observed',
                    evidence=f'步骤 {e.step}: 递归调用 {func}'))
            if e.event_type == 'base_case' or 'base_case' in e.semantic_tags:
                facts.append(SemanticFact(
                    kind=FactKind.BASE_CASE, subject=str(e.step),
                    steps=(e.step,), source='observed',
                    evidence=f'步骤 {e.step}: 基例',
                ))

        # ── Observe memoization ──
        memo_tags = {'memo', 'cache', 'dp', 'memoize', 'lookup', 'table'}
        for e in pattern_events:
            tags = e.semantic_tags if isinstance(e.semantic_tags, set) else set(e.semantic_tags)
            if tags & memo_tags:
                var_name = e.narration.split('=')[0].strip() if '=' in e.narration else 'memo'
                facts.append(MemoizedFact(var_name, steps=(e.step,), source='observed',
                    evidence=f'步骤 {e.step}: 缓存/记忆化操作'))

        # ── Observe accumulation ──
        acc_names = {'sum', 'total', 'count', 'result', 'acc', 'score'}
        for var in var_steps:
            if var.lower() in acc_names:
                facts.append(AccumulatesFact(var, steps=step_range, source='observed'))

        return facts

    # ─── Cognition Extraction ─────────────────────────────────

    def extract_goals(self) -> List[Goal]:
        """Extract goals from derived OBJECTIVE facts."""
        goals = []
        for f in self.query(kind=FactKind.OBJECTIVE):
            goals.append(Goal(
                goal_type=f.subject,  # 'minimize', 'maximize', etc.
                target=f.relation or f.subject,
                variable=f.value if isinstance(f.value, str) else None,
                evidence=[f.evidence] if f.evidence else [],
                confidence=f.confidence,
                start_step=f.steps[0] if f.steps else 0,
                end_step=f.steps[-1] if f.steps else 0,
                description=f.evidence,
            ))
        return goals

    def extract_invariants(self) -> List[Invariant]:
        """Extract invariants from derived INVARIANT facts."""
        invariants = []
        for f in self.query(kind=FactKind.INVARIANT):
            invariants.append(Invariant(
                name=f'{f.subject}_{f.relation}',
                predicate=f.evidence or f'{f.subject}({f.relation})',
                holds_on=list(f.steps),
                violated_by=[],
                confidence=f.confidence,
                category=f.subject,  # 'progress', 'termination', etc.
                description=f.evidence,
                depends_on=list(f.depends_on),
            ))
        return invariants

    def extract_counterfactuals(self) -> List[Counterfactual]:
        """Extract counterfactuals from derived COUNTERFACTUAL facts."""
        counterfactuals = []
        for f in self.query(kind=FactKind.COUNTERFACTUAL):
            category_map = {
                'infinite_loop': 'termination_loss',
                'exponential_blowup': 'efficiency_loss',
                'correctness_violated': 'correctness_loss',
            }
            counterfactuals.append(Counterfactual(
                condition=f.subject.replace('_', ' '),
                consequence=f.relation.replace('_', ' '),
                severity='critical' if 'termination' in (f.relation or '') else 'major',
                confidence=f.confidence,
                affected_invariant=f.value if isinstance(f.value, str) else '',
                category=category_map.get(f.relation, 'correctness_loss'),
            ))
        return counterfactuals

    def summary(self) -> Dict[str, Any]:
        """Human-readable summary of the constraint graph."""
        by_kind: Dict[str, int] = {}
        for f in self.facts.values():
            by_kind[f.kind.value] = by_kind.get(f.kind.value, 0) + 1

        observed = sum(1 for f in self.facts.values() if f.source == 'observed')
        derived = sum(1 for f in self.facts.values() if f.source == 'derived')

        # P10: Stratum breakdown
        strata = {}
        for s, count in self._stratum_stats.items():
            strata[STRATUM_NAMES.get(s, f'L{s}')] = count

        return {
            'total_facts': len(self.facts),
            'observed': observed,
            'derived': derived,
            'by_kind': by_kind,
            'rules_applied': len(self.derivation_chain),
            'strata': strata,
            'conflicts': len(self._conflicts),
        }


def _try_float(v: str) -> Optional[float]:
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


# ─── P9: Canonical Fact Normalization ─────────────────────────
#
# Prevents semantic duplication in the DAG.
#
# Problem:
#   MonotonicFact('lo', 'increasing')  and  TrendFact('lo', 'positive')
#   represent the same truth but have different IDs.
#
# Solution: canonicalize() maps every fact to a unique normal form.
# This ensures the DAG has no redundant nodes and derivation is deterministic.

# Canonical aliases: variant → canonical (kind, relation)
_CANONICAL_ALIASES: Dict[Tuple[str, str], Tuple[FactKind, str]] = {
    # Monotonicity
    ('monotonic', 'positive'): (FactKind.MONOTONIC, 'increasing'),
    ('monotonic', 'up'): (FactKind.MONOTONIC, 'increasing'),
    ('monotonic', 'growing'): (FactKind.MONOTONIC, 'increasing'),
    ('monotonic', 'negative'): (FactKind.MONOTONIC, 'decreasing'),
    ('monotonic', 'down'): (FactKind.MONOTONIC, 'decreasing'),
    ('monotonic', 'shrinking'): (FactKind.MONOTONIC, 'decreasing'),

    # Pairs
    ('paired', 'range'): (FactKind.PAIRED, 'interval'),
    ('paired', 'bounds'): (FactKind.PAIRED, 'interval'),
    ('paired', 'ordered'): (FactKind.PAIRED, 'sorted'),

    # Convergence
    ('converges', 'meets'): (FactKind.CONVERGES, 'converges_with'),
    ('converges', 'approaches'): (FactKind.CONVERGES, 'converges_with'),

    # Objectives
    ('objective', 'reduce'): (FactKind.OBJECTIVE, 'minimize'),
    ('objective', 'shrink'): (FactKind.OBJECTIVE, 'minimize'),
    ('objective', 'grow'): (FactKind.OBJECTIVE, 'maximize'),
    ('objective', 'expand'): (FactKind.OBJECTIVE, 'maximize'),
    ('objective', 'reach'): (FactKind.OBJECTIVE, 'converge'),
    ('objective', 'stabilize'): (FactKind.OBJECTIVE, 'converge'),
    ('objective', 'maintain'): (FactKind.OBJECTIVE, 'preserve'),
    ('objective', 'keep'): (FactKind.OBJECTIVE, 'preserve'),
}


def canonicalize(fact: SemanticFact) -> SemanticFact:
    """Map a fact to its canonical normal form.

    This is the semantic equivalent of type normalization in compilers.
    Ensures that semantically equivalent facts have the same ID.
    """
    key = (fact.kind.value, fact.relation)
    if key in _CANONICAL_ALIASES:
        canon_kind, canon_relation = _CANONICAL_ALIASES[key]
        return SemanticFact(
            kind=canon_kind,
            subject=fact.subject,
            relation=canon_relation,
            value=fact.value,
            steps=fact.steps,
            confidence=fact.confidence,
            source=fact.source,
            evidence=fact.evidence,
            derived_from_rule=fact.derived_from_rule,
            derived_from_facts=fact.derived_from_facts,
        )
    return fact


# ─── P10: Rule Stratification ─────────────────────────────────
#
# Organizes rules into layers (strata) to prevent rule explosion
# and ensure correct derivation ordering.
#
# Without stratification, all rules fire in arbitrary order, which
# can cause: missed derivations, redundant work, non-deterministic results.
#
# Strata (bottom to top):
#   L0: Observations      — raw facts from execution events
#   L1: Structural facts  — pairs, monotonicity, convergence
#   L2: Behavioral facts  — shrinking, accumulation, memoization
#   L3: Objectives        — goals derived from behavior
#   L4: Correctness       — invariants, termination guarantees
#   L5: Counterfactuals   — failure modes derived from invariants
#   L6: Motifs            — deep computational archetypes
#
# Rules in lower strata fire first, ensuring all prerequisites
# are available before higher strata rules run.

class RuleStratum(int):
    """A rule stratum (layer) in the constraint system."""
    pass

# Stratum constants
STRATUM_OBSERVATION = RuleStratum(0)
STRATUM_STRUCTURAL = RuleStratum(1)
STRATUM_BEHAVIORAL = RuleStratum(2)
STRATUM_OBJECTIVE = RuleStratum(3)
STRATUM_CORRECTNESS = RuleStratum(4)
STRATUM_COUNTERFACTUAL = RuleStratum(5)
STRATUM_MOTIF = RuleStratum(6)

STRATUM_NAMES = {
    0: '观测', 1: '结构', 2: '行为', 3: '目标', 4: '正确性', 5: '反事实', 6: '原语',
}


@dataclass
class StratifiedRule:
    """A constraint rule with a stratum (layer) assignment.

    The stratum determines WHEN the rule fires relative to other rules.
    Lower strata fire first.
    """
    rule: ConstraintRule
    stratum: RuleStratum
    description: str = ''


def stratify_rules(rules: List[ConstraintRule]) -> List[StratifiedRule]:
    """Automatically assign strata to rules based on their produces/consumes.

    Heuristic:
    - Rules producing OBJECTIVE/INVARIANT → stratum 3-4
    - Rules producing COUNTERFACTUAL → stratum 5
    - Rules producing SHRINKS/STABLE → stratum 2
    - Everything else → stratum 1
    """
    stratified = []
    for rule in rules:
        # Determine stratum from what the rule produces
        max_produce_stratum = STRATUM_STRUCTURAL  # default
        for prod in rule.produces:
            if prod.kind == FactKind.OBJECTIVE:
                max_produce_stratum = max(max_produce_stratum, STRATUM_OBJECTIVE)
            elif prod.kind == FactKind.INVARIANT:
                max_produce_stratum = max(max_produce_stratum, STRATUM_CORRECTNESS)
            elif prod.kind == FactKind.COUNTERFACTUAL:
                max_produce_stratum = max(max_produce_stratum, STRATUM_COUNTERFACTUAL)
            elif prod.kind in (FactKind.SHRINKS, FactKind.STABLE, FactKind.REACHABLE):
                max_produce_stratum = max(max_produce_stratum, STRATUM_BEHAVIORAL)

        stratified.append(StratifiedRule(
            rule=rule,
            stratum=max_produce_stratum,
            description=rule.description,
        ))

    # Sort by stratum (lower fires first)
    stratified.sort(key=lambda s: s.stratum)
    return stratified


# ─── ConstraintEngine: The New Cognition Pipeline ──────────────

class ConstraintEngine:
    """The declarative cognition pipeline.

    Replaces heuristic-based GoalInferenceEngine, InvariantEngine (partially),
    and CounterfactualEngine with a single declarative system.

    Pipeline:
        ExecutionEvent[] → extract_facts() → ConstraintGraph
        → fixed_point() → extract_goals/invariants/counterfactuals

    This is the "semantic compiler" that transforms execution into cognition.
    """

    def __init__(self):
        self.graph = ConstraintGraph()

    def compile(self, events: List[ExecutionEvent],
                match: PatternMatch) -> Dict[str, Any]:
        """Full compilation: events → cognition.

        P11: Uses incremental fixed-point (delta propagation) for scalability.

        Returns dict with goals, invariants, counterfactuals, and graph summary.
        """
        # Phase 1: Extract primitive facts from observations
        observed_facts = ConstraintGraph.extract_facts(events, match)

        # Phase 2: P11 incremental fixpoint — only re-evaluate affected rules
        self.graph.incremental_fixed_point(observed_facts, max_iterations=10)

        # Phase 3: Extract cognition from derived facts
        return {
            'goals': self.graph.extract_goals(),
            'invariants': self.graph.extract_invariants(),
            'counterfactuals': self.graph.extract_counterfactuals(),
            'summary': self.graph.summary(),
            'conflicts': self.graph.conflicts,
        }


# ─── Updated IntentGraph with Full Cognition Stack ─────────────

@dataclass
class IntentGraph:
    """The complete cognitive output for a pattern match.

    Combines:
    - What: PatternMatch (detected pattern)
    - How: SemanticOperation (canonical semantics)
    - Why: CognitiveNarrative (reasoning)
    - When: TemporalFacts (temporal logic)
    - Correctness: Invariants (what must hold)
    - Causality: CausalGraph (why things happened)
    - Goals: GoalInference (what it's trying to achieve)
    - Counterfactuals: CounterfactualEngine (what would break)
    - Motifs: SemanticCompressor (deep computational patterns)
    """
    pattern: PatternMatch
    narrative: CognitiveNarrative
    temporal_facts: List[TemporalFact]
    invariants: List[Invariant] = field(default_factory=list)
    causal_edges: List[CausalEdge] = field(default_factory=list)
    goals: List[Goal] = field(default_factory=list)
    counterfactuals: List[Counterfactual] = field(default_factory=list)
    motifs: List[ComputationalMotif] = field(default_factory=list)
    constraint_summary: Dict[str, Any] = field(default_factory=dict)
    reasoning_dag: Dict[str, Any] = field(default_factory=dict)  # P8: provenance DAG
    conflicts: List[Dict[str, Any]] = field(default_factory=list)  # P12: contradictions

    def to_dict(self) -> Dict[str, Any]:
        return {
            'pattern_name': self.pattern.pattern_name,
            'display_name': self.pattern.display_name,
            'description': self.pattern.description,
            'start_step': self.pattern.start_step,
            'end_step': self.pattern.end_step,
            'confidence': self.pattern.confidence,
            'key_steps': self.pattern.key_steps,
            'sub_patterns': self.pattern.sub_patterns,
            'semantic': {
                'op': self.pattern.semantic.op,
                'structure': self.pattern.semantic.structure,
                'actors': self.pattern.semantic.actors,
                'direction': self.pattern.semantic.direction,
                'combines': self.pattern.semantic.combines,
                'terminates': self.pattern.semantic.terminates,
            } if self.pattern.semantic else None,
            'narrative': {
                'headline': self.narrative.headline,
                'mechanism': self.narrative.mechanism,
                'strategy': self.narrative.strategy,
                'temporal_facts': self.narrative.temporal_facts,
                'analogies': self.narrative.analogies,
                'lattice_path': self.narrative.lattice_path,
                'confidence': self.narrative.confidence,
            },
            'temporal': [
                {
                    'predicate': f.predicate,
                    'subject': f.subject,
                    'confidence': f.confidence,
                    'description': f.description,
                }
                for f in self.temporal_facts
            ],
            'invariants': [
                {
                    'name': inv.name,
                    'predicate': inv.predicate,
                    'category': inv.category,
                    'confidence': inv.confidence,
                    'description': inv.description,
                    'holds': len(inv.holds_on),
                    'violations': len(inv.violated_by),
                    'depends_on': inv.depends_on,
                }
                for inv in self.invariants
            ],
            'causal_edges': [
                {
                    'cause': e.cause_step,
                    'effect': e.effect_step,
                    'type': e.cause_type,
                    'variable': e.variable,
                    'confidence': e.confidence,
                    'description': e.description,
                }
                for e in self.causal_edges
            ],
            'goals': [
                {
                    'type': g.goal_type,
                    'target': g.target,
                    'variable': g.variable,
                    'evidence': g.evidence,
                    'confidence': g.confidence,
                    'description': g.description,
                }
                for g in self.goals
            ],
            'counterfactuals': [
                {
                    'condition': cf.condition,
                    'consequence': cf.consequence,
                    'severity': cf.severity,
                    'confidence': cf.confidence,
                    'affected_invariant': cf.affected_invariant,
                    'category': cf.category,
                }
                for cf in self.counterfactuals
            ],
            'motifs': [
                {
                    'motif': m.motif,
                    'description': m.description,
                    'evidence': m.evidence,
                    'confidence': m.confidence,
                    'depth': m.depth,
                }
                for m in self.motifs
            ],
            'constraint_summary': self.constraint_summary,
            'reasoning_dag': self.reasoning_dag,
            'conflicts': self.conflicts,
        }


# ─── CognitionEngine v3 (Full Cognition Stack) ──────────────────

class CognitionEngine:
    """Top-level orchestrator: PatternMatch → IntentGraph.

    v4 pipeline (hybrid declarative + heuristic):
    1. Pattern detection (PatternCombinator)
    2. Semantic classification (SemanticLattice)
    3. Temporal analysis (TemporalLogicEngine)
    4. Constraint IR compilation (ConstraintEngine) — PRIMARY
    5. Causal graph construction (CausalGraph)
    6. Semantic compression (SemanticCompressor)
    7. Narrative generation (CognitiveNarrativeGenerator)

    The ConstraintEngine replaces GoalInferenceEngine, InvariantEngine,
    and CounterfactualEngine with a single declarative system.
    Heuristic engines are kept as fallback/enrichment.
    """

    def __init__(self):
        self.narrative_gen = CognitiveNarrativeGenerator()
        self.temporal = TemporalLogicEngine()
        self.causal_graph = CausalGraph()
        self.compressor = SemanticCompressor()
        # Heuristic engines (fallback / enrichment)
        self.invariant_engine = InvariantEngine()
        self.goal_engine = GoalInferenceEngine()
        self.counterfactual_engine = CounterfactualEngine()

    def understand(self, matches: List[PatternMatch],
                   events: List[ExecutionEvent]) -> List[IntentGraph]:
        """Convert pattern matches into full cognitive understanding."""
        intent_graphs = []

        for match in matches:
            # ── Phase 1: Constraint IR (declarative) ──
            constraint_engine = ConstraintEngine()
            constraint_result = constraint_engine.compile(events, match)
            reasoning_dag = constraint_engine.graph.explain_dag()

            goals_c = constraint_result['goals']
            invariants_c = constraint_result['invariants']
            counterfactuals_c = constraint_result['counterfactuals']
            constraint_summary = constraint_result['summary']
            conflicts = constraint_result.get('conflicts', [])

            # ── Phase 2: Heuristic enrichment (merge, don't replace) ──
            # Heuristics may find things the constraint rules don't cover yet
            goals_h = self.goal_engine.infer(events, match)
            invariants_h = self.invariant_engine.extract(events, match)
            counterfactuals_h = self.counterfactual_engine.reason(
                events, match, invariants_h, goals_h)

            # Merge: constraint-derived takes priority, heuristics fill gaps
            goals = self._merge_goals(goals_c, goals_h)
            invariants = self._merge_invariants(invariants_c, invariants_h)
            counterfactuals = self._merge_counterfactuals(counterfactuals_c, counterfactuals_h)

            # ── Phase 3: Causal graph (independent) ──
            _, causal_edges = self.causal_graph.build(events, match)

            # ── Phase 4: Semantic compression (uses merged goals) ──
            motifs = self.compressor.compress(events, match, goals)

            # ── Phase 5: Narrative + Temporal ──
            narrative = self.narrative_gen.generate(match, events)
            temporal_facts = self.temporal.analyze(events, match)

            intent_graphs.append(IntentGraph(
                pattern=match,
                narrative=narrative,
                temporal_facts=temporal_facts,
                invariants=invariants,
                causal_edges=causal_edges,
                goals=goals,
                counterfactuals=counterfactuals,
                motifs=motifs,
                constraint_summary=constraint_summary,
                reasoning_dag=reasoning_dag,
                conflicts=conflicts,
            ))

        return intent_graphs

    @staticmethod
    def _merge_goals(constraint: List[Goal], heuristic: List[Goal]) -> List[Goal]:
        """Merge constraint-derived and heuristic goals. Constraint takes priority."""
        seen_targets = {(g.goal_type, g.target) for g in constraint}
        merged = list(constraint)
        for g in heuristic:
            if (g.goal_type, g.target) not in seen_targets:
                merged.append(g)
                seen_targets.add((g.goal_type, g.target))
        return sorted(merged, key=lambda g: g.confidence, reverse=True)

    @staticmethod
    def _merge_invariants(constraint: List[Invariant],
                          heuristic: List[Invariant]) -> List[Invariant]:
        """Merge constraint-derived and heuristic invariants."""
        seen_names = {inv.name for inv in constraint}
        merged = list(constraint)
        for inv in heuristic:
            if inv.name not in seen_names:
                merged.append(inv)
                seen_names.add(inv.name)
        return sorted(merged, key=lambda i: i.confidence, reverse=True)

    @staticmethod
    def _merge_counterfactuals(constraint: List[Counterfactual],
                               heuristic: List[Counterfactual]) -> List[Counterfactual]:
        """Merge constraint-derived and heuristic counterfactuals."""
        seen = {(cf.condition, cf.consequence) for cf in constraint}
        merged = list(constraint)
        for cf in heuristic:
            if (cf.condition, cf.consequence) not in seen:
                merged.append(cf)
                seen.add((cf.condition, cf.consequence))
        return sorted(merged, key=lambda c: c.confidence, reverse=True)


# ─── Helpers ────────────────────────────────────────────────────

def _op_str(op: Any) -> str:
    op_map = {
        ast.Add: '+', ast.Sub: '-', ast.Mult: '*', ast.Div: '/',
        ast.Mod: '%', ast.Pow: '**', ast.FloorDiv: '//',
        ast.USub: '-', ast.UAdd: '+', ast.Not: 'not',
        ast.And: 'and', ast.Or: 'or',
    }
    return op_map.get(op, '?')


# ─── P13: Goal-Action Layer (Agentization) ───────────────────────

class ActionType:
    """Categories of actionable suggestions."""
    OPTIMIZE = 'optimize'       # Performance improvement
    DEBUG = 'debug'             # Investigate potential bug
    REFACTOR = 'refactor'       # Code structure improvement
    VERIFY = 'verify'           # Correctness verification
    ADD_MEMO = 'add_memo'       # Add memoization/caching
    ADD_GUARD = 'add_guard'     # Add boundary/safety check
    SIMPLIFY = 'simplify'       # Simplify logic
    EXTRACT = 'extract'         # Extract pattern into helper


ACTION_TYPE_LABELS = {
    ActionType.OPTIMIZE: '优化',
    ActionType.DEBUG: '调试',
    ActionType.REFACTOR: '重构',
    ActionType.VERIFY: '验证',
    ActionType.ADD_MEMO: '缓存',
    ActionType.ADD_GUARD: '防护',
    ActionType.SIMPLIFY: '简化',
    ActionType.EXTRACT: '提取',
}


@dataclass
class Action:
    """A concrete, actionable suggestion derived from cognitive analysis.

    P13: This bridges the gap between "understanding" and "doing."
    Each action is a specific, implementable recommendation with
    preconditions, expected outcomes, and priority scoring.
    """
    action_type: str                     # ActionType constant
    title: str                           # Short, imperative title
    description: str                     # Detailed explanation
    priority: float = 0.5                # 0-1, higher = more urgent
    confidence: float = 0.8              # 0-1, how sure we are
    target_line: Optional[int] = None    # Code line to modify
    target_variable: Optional[str] = None  # Variable involved
    evidence: List[str] = field(default_factory=list)
    preconditions: List[str] = field(default_factory=list)
    expected_outcome: str = ''
    effort: str = 'medium'               # 'low', 'medium', 'high'
    impact: str = 'medium'               # 'low', 'medium', 'high'
    from_goal: Optional[str] = None      # Source goal type
    from_invariant: Optional[str] = None  # Source invariant
    from_counterfactual: Optional[str] = None  # Source counterfactual


class ActionSynthesizer:
    """P13: Converts cognitive analysis into actionable suggestions.

    This is the "decision layer" that bridges reasoning → action.
    It takes the IntentGraph (goals, invariants, counterfactuals, motifs,
    conflicts) and produces a prioritized list of concrete actions.

    Architecture:
        IntentGraph → ActionSynthesizer.synthesize() → Action[]

    Each action has:
    - type: what kind of action
    - priority: how urgent (derived from confidence × impact)
    - preconditions: what must be true
    - expected_outcome: what will improve
    - evidence: why we recommend this
    """

    def synthesize(self, intent: IntentGraph,
                   events: List[ExecutionEvent]) -> List[Action]:
        """Full action synthesis pipeline.

        Returns actions sorted by priority (highest first).
        """
        actions: List[Action] = []

        # Phase 1: Goal-driven actions
        actions.extend(self._actions_from_goals(intent.goals, events))

        # Phase 2: Invariant-driven actions
        actions.extend(self._actions_from_invariants(intent.invariants, events))

        # Phase 3: Counterfactual-driven actions
        actions.extend(self._actions_from_counterfactuals(
            intent.counterfactuals, intent.invariants))

        # Phase 4: Motif-driven actions
        actions.extend(self._actions_from_motifs(intent.motifs, events))

        # Phase 5: Conflict-driven actions
        actions.extend(self._actions_from_conflicts(intent.conflicts))

        # Phase 6: Pattern-specific actions
        actions.extend(self._actions_from_pattern(intent.pattern, events))

        # Deduplicate and sort by priority
        actions = self._deduplicate(actions)
        actions.sort(key=lambda a: a.priority, reverse=True)

        return actions

    def _actions_from_goals(self, goals: List[Goal],
                            events: List[ExecutionEvent]) -> List[Action]:
        """Convert optimization goals into concrete actions."""
        actions = []

        for goal in goals:
            if goal.goal_type == 'minimize':
                # Minimization goal → optimization opportunity
                actions.append(Action(
                    action_type=ActionType.OPTIMIZE,
                    title=f'优化 {goal.target} 的计算',
                    description=f'检测到最小化目标: {goal.description}。考虑使用记忆化或动态规划减少重复计算。',
                    priority=goal.confidence * 0.8,
                    confidence=goal.confidence,
                    target_variable=goal.target,
                    evidence=goal.evidence,
                    preconditions=[f'{goal.target} 存在重复计算'],
                    expected_outcome=f'减少 {goal.target} 的时间复杂度',
                    effort='medium',
                    impact='high',
                    from_goal=goal.goal_type,
                ))

            elif goal.goal_type == 'maximize':
                # Maximization goal → accumulation optimization
                actions.append(Action(
                    action_type=ActionType.OPTIMIZE,
                    title=f'优化 {goal.target} 的累积过程',
                    description=f'检测到最大化目标: {goal.description}。'
                                f'考虑使用更高效的累积策略。',
                    priority=goal.confidence * 0.7,
                    confidence=goal.confidence,
                    target_variable=goal.target,
                    evidence=goal.evidence,
                    preconditions=[f'{goal.target} 存在累积操作'],
                    expected_outcome=f'提升 {goal.target} 的计算效率',
                    effort='medium',
                    impact='medium',
                    from_goal=goal.goal_type,
                ))

            elif goal.goal_type == 'converge':
                # Convergence goal → termination verification
                actions.append(Action(
                    action_type=ActionType.VERIFY,
                    title=f'验证 {goal.target} 的收敛性',
                    description=f'检测到收敛目标: {goal.description}。'
                                f'建议验证终止条件是否正确。',
                    priority=goal.confidence * 0.6,
                    confidence=goal.confidence,
                    target_variable=goal.target,
                    evidence=goal.evidence,
                    preconditions=[f'{goal.target} 存在收敛行为'],
                    expected_outcome=f'确保 {goal.target} 正确终止',
                    effort='low',
                    impact='high',
                    from_goal=goal.goal_type,
                ))

            elif goal.goal_type == 'preserve':
                # Preservation goal → invariant check
                actions.append(Action(
                    action_type=ActionType.VERIFY,
                    title=f'验证 {goal.target} 的不变性',
                    description=f'检测到保持目标: {goal.description}。'
                                f'建议添加断言验证不变量。',
                    priority=goal.confidence * 0.7,
                    confidence=goal.confidence,
                    target_variable=goal.target,
                    evidence=goal.evidence,
                    preconditions=[f'{goal.target} 应保持不变'],
                    expected_outcome=f'确保 {goal.target} 不被意外修改',
                    effort='low',
                    impact='medium',
                    from_goal=goal.goal_type,
                ))

        return actions

    def _actions_from_invariants(self, invariants: List[Invariant],
                                 events: List[ExecutionEvent]) -> List[Action]:
        """Convert invariants into verification/guard actions."""
        actions = []

        for inv in invariants:
            if inv.violated_by:
                # Violated invariant → debug action
                actions.append(Action(
                    action_type=ActionType.DEBUG,
                    title=f'修复不变量违反: {inv.name}',
                    description=f'不变量 {inv.predicate} 在步骤 {inv.violated_by} 被违反。'
                                f'{inv.description}',
                    priority=inv.confidence * 0.9,  # High priority for violations
                    confidence=inv.confidence,
                    evidence=[inv.description],
                    preconditions=[f'不变量 {inv.name} 应成立'],
                    expected_outcome=f'修复 {inv.name} 的违反',
                    effort='medium',
                    impact='high',
                    from_invariant=inv.name,
                ))
            else:
                # Holding invariant → add guard
                if inv.category in ('loop', 'bound'):
                    actions.append(Action(
                        action_type=ActionType.ADD_GUARD,
                        title=f'添加断言: {inv.name}',
                        description=f'不变量 {inv.predicate} 始终成立。'
                                    f'建议添加断言以确保未来修改不会破坏它。',
                        priority=inv.confidence * 0.4,  # Lower priority for guards
                        confidence=inv.confidence,
                        evidence=[inv.description],
                        preconditions=[f'不变量 {inv.name} 当前成立'],
                        expected_outcome=f'防止 {inv.name} 被意外破坏',
                        effort='low',
                        impact='medium',
                        from_invariant=inv.name,
                    ))

        return actions

    def _actions_from_counterfactuals(
            self, counterfactuals: List[Counterfactual],
            invariants: List[Invariant]) -> List[Action]:
        """Convert counterfactuals into preventive actions."""
        actions = []

        for cf in counterfactuals:
            if cf.severity == 'high':
                # High severity → add guard
                actions.append(Action(
                    action_type=ActionType.ADD_GUARD,
                    title=f'防护: {cf.condition}',
                    description=f'如果 {cf.condition}，则 {cf.consequence}。'
                                f'建议添加防护措施。',
                    priority=cf.confidence * 0.8,
                    confidence=cf.confidence,
                    evidence=[f'反事实分析: {cf.description}'],
                    preconditions=[cf.condition],
                    expected_outcome=f'防止 {cf.consequence}',
                    effort='low',
                    impact='high',
                    from_counterfactual=cf.condition,
                ))

            elif cf.severity == 'medium':
                # Medium severity → verify
                actions.append(Action(
                    action_type=ActionType.VERIFY,
                    title=f'验证: {cf.condition}',
                    description=f'如果 {cf.condition}，则 {cf.consequence}。'
                                f'建议验证此场景是否可能发生。',
                    priority=cf.confidence * 0.5,
                    confidence=cf.confidence,
                    evidence=[f'反事实分析: {cf.description}'],
                    preconditions=[cf.condition],
                    expected_outcome=f'确认 {cf.condition} 不会发生',
                    effort='low',
                    impact='medium',
                    from_counterfactual=cf.condition,
                ))

        return actions

    def _actions_from_motifs(self, motifs: List[ComputationalMotif],
                             events: List[ExecutionEvent]) -> List[Action]:
        """Convert computational motifs into refactoring actions."""
        actions = []

        for motif in motifs:
            if motif.motif == 'divide_and_conquer':
                # D&C → suggest memoization if not already cached
                actions.append(Action(
                    action_type=ActionType.ADD_MEMO,
                    title='添加记忆化',
                    description=f'检测到分治模式: {motif.description}。'
                                f'考虑添加记忆化以避免重复计算。',
                    priority=motif.confidence * 0.8,
                    confidence=motif.confidence,
                    evidence=motif.evidence,
                    preconditions=['存在分治递归', '存在重叠子问题'],
                    expected_outcome='将指数复杂度降为多项式',
                    effort='low',
                    impact='high',
                ))

            elif motif.motif == 'greedy_choice':
                # Greedy → verify correctness
                actions.append(Action(
                    action_type=ActionType.VERIFY,
                    title='验证贪心选择性质',
                    description=f'检测到贪心模式: {motif.description}。'
                                f'建议验证贪心选择的正确性。',
                    priority=motif.confidence * 0.6,
                    confidence=motif.confidence,
                    evidence=motif.evidence,
                    preconditions=['存在贪心选择'],
                    expected_outcome='确认贪心策略的正确性',
                    effort='low',
                    impact='high',
                ))

            elif motif.motif == 'dynamic_programming':
                # DP → suggest space optimization
                actions.append(Action(
                    action_type=ActionType.OPTIMIZE,
                    title='优化 DP 空间复杂度',
                    description=f'检测到动态规划模式: {motif.description}。'
                                f'考虑使用滚动数组优化空间。',
                    priority=motif.confidence * 0.5,
                    confidence=motif.confidence,
                    evidence=motif.evidence,
                    preconditions=['存在 DP 表'],
                    expected_outcome='减少空间复杂度',
                    effort='medium',
                    impact='medium',
                ))

            elif motif.motif == 'backtracking':
                # Backtracking → suggest pruning
                actions.append(Action(
                    action_type=ActionType.OPTIMIZE,
                    title='添加回溯剪枝',
                    description=f'检测到回溯模式: {motif.description}。'
                                f'考虑添加剪枝条件减少搜索空间。',
                    priority=motif.confidence * 0.7,
                    confidence=motif.confidence,
                    evidence=motif.evidence,
                    preconditions=['存在回溯搜索'],
                    expected_outcome='减少搜索空间，提升性能',
                    effort='medium',
                    impact='high',
                ))

        return actions

    def _actions_from_conflicts(self, conflicts: List[Dict[str, Any]]) -> List[Action]:
        """Convert conflicts into debug actions."""
        actions = []

        for conflict in conflicts:
            actions.append(Action(
                action_type=ActionType.DEBUG,
                title=f'解决冲突: {conflict.get("subject", "未知")}',
                description=f'检测到矛盾: {conflict.get("relation_a", "?")} '
                            f'与 {conflict.get("relation_b", "?")} '
                            f'关于 {conflict.get("subject", "未知")}。',
                priority=0.9,  # Conflicts are always high priority
                confidence=0.95,
                evidence=[f'冲突类型: {conflict.get("kind", "未知")}'],
                preconditions=['存在语义矛盾'],
                expected_outcome='解决逻辑矛盾',
                effort='high',
                impact='high',
            ))

        return actions

    def _actions_from_pattern(self, pattern: PatternMatch,
                              events: List[ExecutionEvent]) -> List[Action]:
        """Generate pattern-specific actions."""
        actions = []

        if pattern.pattern_name == 'recursive_fibonacci':
            # Fibonacci-specific: suggest matrix exponentiation
            actions.append(Action(
                action_type=ActionType.OPTIMIZE,
                title='使用矩阵快速幂优化',
                description='斐波那契递归可以使用矩阵快速幂将 O(2^n) 优化到 O(log n)。',
                priority=0.7,
                confidence=0.9,
                evidence=['检测到斐波那契递归模式'],
                preconditions=['递归斐波那契'],
                expected_outcome='时间复杂度从 O(2^n) 降至 O(log n)',
                effort='medium',
                impact='high',
            ))

        elif pattern.pattern_name == 'bubble_sort':
            # Bubble sort → suggest better algorithm
            actions.append(Action(
                action_type=ActionType.REFACTOR,
                title='替换为更高效的排序算法',
                description='冒泡排序 O(n²) 可以替换为归并排序或快速排序 O(n log n)。',
                priority=0.8,
                confidence=0.95,
                evidence=['检测到冒泡排序模式'],
                preconditions=['使用冒泡排序'],
                expected_outcome='时间复杂度从 O(n²) 降至 O(n log n)',
                effort='medium',
                impact='high',
            ))

        elif pattern.pattern_name == 'linear_search':
            # Linear search → suggest hash map
            actions.append(Action(
                action_type=ActionType.OPTIMIZE,
                title='使用哈希表优化查找',
                description='线性查找 O(n) 可以使用哈希表优化到 O(1)。',
                priority=0.6,
                confidence=0.8,
                evidence=['检测到线性查找模式'],
                preconditions=['存在重复查找'],
                expected_outcome='查找复杂度从 O(n) 降至 O(1)',
                effort='low',
                impact='high',
            ))

        return actions

    def _deduplicate(self, actions: List[Action]) -> List[Action]:
        """Remove duplicate actions, keeping highest priority."""
        seen: Dict[Tuple[str, str], Action] = {}

        for action in actions:
            key = (action.action_type, action.title)
            if key not in seen or action.priority > seen[key].priority:
                seen[key] = action

        return list(seen.values())


# ─── Updated IntentGraph with P13 Actions ────────────────────────

# Re-open IntentGraph to add actions field (dataclass allows this pattern)
# We'll add it via __post_init__ or by modifying the class

# Monkey-patch: add actions field to IntentGraph
IntentGraph.__dataclass_fields__['actions'] = field(
    default_factory=list,
    metadata={'type': List[Action]}
)
IntentGraph.actions = field(default_factory=list)

# Update to_dict to include actions
_original_to_dict = IntentGraph.to_dict

def _to_dict_with_actions(self) -> Dict[str, Any]:
    result = _original_to_dict(self)
    result['actions'] = [
        {
            'action_type': a.action_type,
            'title': a.title,
            'description': a.description,
            'priority': a.priority,
            'confidence': a.confidence,
            'target_line': a.target_line,
            'target_variable': a.target_variable,
            'evidence': a.evidence,
            'preconditions': a.preconditions,
            'expected_outcome': a.expected_outcome,
            'effort': a.effort,
            'impact': a.impact,
            'from_goal': a.from_goal,
            'from_invariant': a.from_invariant,
            'from_counterfactual': a.from_counterfactual,
        }
        for a in (self.actions if hasattr(self, 'actions') else [])
    ]
    return result

IntentGraph.to_dict = _to_dict_with_actions


# ─── Updated CognitionEngine with P13 Action Synthesis ────────────

# Store original understand method
_original_understand = CognitionEngine.understand

def _understand_with_actions(self, matches: List[PatternMatch],
                              events: List[ExecutionEvent]) -> List[IntentGraph]:
    """Extended understand: adds action synthesis to intent graphs."""
    # Call original understand
    intent_graphs = _original_understand(self, matches, events)

    # P13: Synthesize actions for each intent graph
    action_synthesizer = ActionSynthesizer()
    for intent in intent_graphs:
        intent.actions = action_synthesizer.synthesize(intent, events)

    return intent_graphs

CognitionEngine.understand = _understand_with_actions


# ─── P14: Execution & Feedback Loop Layer ─────────────────────────

import time
import hashlib
import json


@dataclass
class ExecutionMetrics:
    """Metrics captured at a point in time."""
    step_count: int = 0
    time_complexity: str = ''           # e.g., 'O(n^2)'
    space_complexity: str = ''          # e.g., 'O(n)'
    invariant_violations: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    recursive_depth: int = 0
    total_calls: int = 0
    unique_subproblems: int = 0
    execution_time_ms: float = 0.0

    def delta(self, other: 'ExecutionMetrics') -> Dict[str, float]:
        """Compute improvement metrics (positive = better)."""
        return {
            'step_reduction': self.step_count - other.step_count,
            'violation_reduction': self.invariant_violations - other.invariant_violations,
            'cache_improvement': (self.cache_hits - other.cache_hits) if self.cache_hits else 0,
            'depth_reduction': self.recursive_depth - other.recursive_depth,
            'call_reduction': self.total_calls - other.total_calls,
            'time_improvement': self.execution_time_ms - other.execution_time_ms,
        }

    def overall_improvement(self) -> float:
        """Single score: positive = improved, negative = degraded."""
        # Normalize each metric to [-1, 1] range
        scores = []
        if self.step_count > 0:
            scores.append(min(1.0, self.step_reduction / max(1, self.step_count)))
        if self.invariant_violations >= 0:
            scores.append(1.0 if self.violation_reduction > 0 else (-1.0 if self.violation_reduction < 0 else 0))
        if self.total_calls > 0:
            scores.append(min(1.0, self.call_reduction / max(1, self.total_calls)))
        return sum(scores) / len(scores) if scores else 0.0


@dataclass
class ActionExecution:
    """Tracks the outcome of applying an action.

    P14: This is the "observation" in the observe→reason→act→observe loop.
    Each execution records what happened so the system can learn.
    """
    execution_id: str                    # Unique ID
    action_type: str                     # ActionType constant
    action_title: str                    # Human-readable title
    pre_metrics: ExecutionMetrics        # Metrics before action
    post_metrics: ExecutionMetrics       # Metrics after action
    success: bool                        # Did the action help?
    delta_metrics: Dict[str, float]      # Improvement measurements
    confidence_delta: float              # How much confidence changed
    timestamp: float                     # When executed
    code_before: str                     # Code snapshot before
    code_after: str                      # Code snapshot after
    user_feedback: Optional[str] = None  # 'accepted', 'rejected', 'modified'
    notes: str = ''                      # User notes


class ActionOutcomeMemory:
    """P14: Stores action executions and computes success rates.

    This is the "experience" of the system — it remembers what worked
    and what didn't, enabling adaptive policy updates.

    Architecture:
        ActionExecution[] → ActionOutcomeMemory → success_rates
        success_rates → AdaptivePolicy → adjusted priorities
    """

    def __init__(self):
        self.executions: List[ActionExecution] = []
        self._success_rates: Dict[str, float] = {}  # action_type → rate
        self._title_success: Dict[str, float] = {}   # action_title → rate
        self._pattern_success: Dict[str, List[float]] = {}  # pattern → [rates]

    def record(self, execution: ActionExecution):
        """Record an action execution outcome."""
        self.executions.append(execution)
        self._update_rates(execution)

    def _update_rates(self, execution: ActionExecution):
        """Incrementally update success rates."""
        # Update action_type rate
        at = execution.action_type
        type_execs = [e for e in self.executions if e.action_type == at]
        self._success_rates[at] = sum(1 for e in type_execs if e.success) / len(type_execs)

        # Update title rate (more specific)
        title = execution.action_title
        title_execs = [e for e in self.executions if e.action_title == title]
        self._title_success[title] = sum(1 for e in title_execs if e.success) / len(title_execs)

    def success_rate(self, action_type: str) -> float:
        """Get historical success rate for an action type."""
        return self._success_rates.get(action_type, 0.5)  # default: 50%

    def title_success_rate(self, action_title: str) -> float:
        """Get historical success rate for a specific action title."""
        return self._title_success.get(action_title, None)

    def similar_executions(self, action_type: str,
                           action_title: str) -> List[ActionExecution]:
        """Find similar past executions for learning."""
        return [
            e for e in self.executions
            if e.action_type == action_type or e.action_title == action_title
        ]

    def best_actions(self, top_k: int = 5) -> List[Tuple[str, float]]:
        """Get the most successful action types."""
        sorted_rates = sorted(
            self._success_rates.items(),
            key=lambda x: x[1],
            reverse=True
        )
        return sorted_rates[:top_k]

    def worst_actions(self, top_k: int = 5) -> List[Tuple[str, float]]:
        """Get the least successful action types."""
        sorted_rates = sorted(
            self._success_rates.items(),
            key=lambda x: x[1]
        )
        return sorted_rates[:top_k]

    def summary(self) -> Dict[str, Any]:
        """Get memory summary."""
        return {
            'total_executions': len(self.executions),
            'success_rates': dict(self._success_rates),
            'title_success_rates': dict(self._title_success),
            'best_actions': self.best_actions(),
            'worst_actions': self.worst_actions(),
        }


class AdaptivePolicy:
    """P14: Adjusts action priorities based on historical success.

    This is the "learning" component — it transforms static priorities
    into adaptive ones that improve over time.

    Formula:
        adjusted_priority = base_priority * success_weight * recency_weight

    Where:
        success_weight = f(historical_success_rate)
        recency_weight = f(time_since_last_execution)
    """

    def __init__(self, memory: ActionOutcomeMemory):
        self.memory = memory
        self.exploration_rate = 0.1  # ε for ε-greedy exploration

    def adjust_priority(self, action: Action,
                        base_priority: float) -> float:
        """Adjust action priority based on historical success.

        Returns adjusted priority in [0, 1].
        """
        # Get historical success rate
        type_rate = self.memory.success_rate(action.action_type)
        title_rate = self.memory.title_success_rate(action.title)

        # Use title rate if available, otherwise type rate
        success_rate = title_rate if title_rate is not None else type_rate

        # Success weight: scale by historical performance
        # If success_rate = 0.8, weight = 1.6 (boost)
        # If success_rate = 0.2, weight = 0.4 (suppress)
        success_weight = 0.5 + success_rate  # maps [0,1] → [0.5, 1.5]

        # Recency weight: boost recently successful actions
        recency_weight = self._recency_weight(action)

        # Exploration bonus: occasionally boost unexplored actions
        exploration_bonus = self._exploration_bonus(action)

        # Final adjusted priority
        adjusted = base_priority * success_weight * recency_weight + exploration_bonus

        return max(0.0, min(1.0, adjusted))

    def _recency_weight(self, action: Action) -> float:
        """Weight based on how recently this action type was executed."""
        similar = self.memory.similar_executions(action.action_type, action.title)
        if not similar:
            return 1.2  # Boost unexplored actions

        # Time since last execution
        last_exec = max(similar, key=lambda e: e.timestamp)
        hours_since = (time.time() - last_exec.timestamp) / 3600

        # Decay: recent executions get normal weight, old ones get boost
        if hours_since < 1:
            return 1.0  # Recent, normal weight
        elif hours_since < 24:
            return 1.1  # Somewhat old, slight boost
        else:
            return 1.2  # Old, boost to re-explore

    def _exploration_bonus(self, action: Action) -> float:
        """Small bonus for unexplored actions (ε-greedy)."""
        similar = self.memory.similar_executions(action.action_type, action.title)
        if not similar:
            return self.exploration_rate  # Boost unexplored
        return 0.0

    def update_from_outcome(self, execution: ActionExecution):
        """Update policy based on execution outcome."""
        # The memory already tracks success rates
        # This method can be extended for more sophisticated learning
        pass


class ExecutionFeedbackLoop:
    """P14: Orchestrates the observe→reason→act→observe cycle.

    This is the "execution engine" that closes the loop:
    1. Observe: Capture pre-execution metrics
    2. Reason: Generate actions (P13)
    3. Act: User applies action (external)
    4. Observe: Capture post-execution metrics
    5. Learn: Update policy based on outcome

    The system doesn't execute code directly — it tracks what the user
    does and learns from the outcomes.
    """

    def __init__(self):
        self.memory = ActionOutcomeMemory()
        self.policy = AdaptivePolicy(self.memory)
        self._pending_executions: Dict[str, Action] = {}  # action_id → action

    def prepare_execution(self, action: Action,
                          pre_metrics: ExecutionMetrics,
                          code_before: str) -> str:
        """Prepare an action for execution tracking.

        Returns execution_id for tracking.
        """
        execution_id = self._generate_id(action, pre_metrics)
        self._pending_executions[execution_id] = action
        return execution_id

    def record_outcome(self, execution_id: str,
                       post_metrics: ExecutionMetrics,
                       code_after: str,
                       user_feedback: Optional[str] = None,
                       notes: str = '') -> ActionExecution:
        """Record the outcome of an executed action.

        This is called after the user applies the action and re-runs the code.
        """
        action = self._pending_executions.pop(execution_id, None)
        if not action:
            raise ValueError(f'Unknown execution_id: {execution_id}')

        # Compute delta metrics
        pre_metrics = self._get_pre_metrics(execution_id)
        delta = post_metrics.delta(pre_metrics) if pre_metrics else {}
        success = post_metrics.overall_improvement() > 0 if pre_metrics else False

        # Create execution record
        execution = ActionExecution(
            execution_id=execution_id,
            action_type=action.action_type,
            action_title=action.title,
            pre_metrics=pre_metrics or ExecutionMetrics(),
            post_metrics=post_metrics,
            success=success,
            delta_metrics=delta,
            confidence_delta=0.0,  # Will be computed by policy
            timestamp=time.time(),
            code_before='',  # Could be captured
            code_after=code_after,
            user_feedback=user_feedback,
            notes=notes,
        )

        # Record in memory
        self.memory.record(execution)

        # Update policy
        self.policy.update_from_outcome(execution)

        return execution

    def get_adjusted_actions(self, actions: List[Action]) -> List[Action]:
        """Re-rank actions based on learned policy.

        This is the key method: it transforms static P13 actions
        into P14 adaptive actions.
        """
        adjusted = []
        for action in actions:
            # Get base priority from P13
            base_priority = action.priority

            # Adjust based on historical success
            adjusted_priority = self.policy.adjust_priority(action, base_priority)

            # Create adjusted action
            adjusted_action = Action(
                action_type=action.action_type,
                title=action.title,
                description=action.description,
                priority=adjusted_priority,
                confidence=action.confidence,
                target_line=action.target_line,
                target_variable=action.target_variable,
                evidence=action.evidence.copy(),
                preconditions=action.preconditions.copy(),
                expected_outcome=action.expected_outcome,
                effort=action.effort,
                impact=action.impact,
                from_goal=action.from_goal,
                from_invariant=action.from_invariant,
                from_counterfactual=action.from_counterfactual,
            )

            # Add learning context to evidence
            similar = self.memory.similar_executions(action.action_type, action.title)
            if similar:
                success_count = sum(1 for e in similar if e.success)
                adjusted_action.evidence.append(
                    f'历史记录: {len(similar)} 次执行, {success_count} 次成功 '
                    f'({success_count/len(similar)*100:.0f}% 成功率)'
                )

            adjusted.append(adjusted_action)

        # Re-sort by adjusted priority
        adjusted.sort(key=lambda a: a.priority, reverse=True)
        return adjusted

    def _generate_id(self, action: Action,
                     metrics: ExecutionMetrics) -> str:
        """Generate unique execution ID."""
        content = f'{action.action_type}:{action.title}:{time.time()}'
        return hashlib.md5(content.encode()).hexdigest()[:12]

    def _get_pre_metrics(self, execution_id: str) -> Optional[ExecutionMetrics]:
        """Retrieve pre-execution metrics."""
        # In a real system, this would be stored
        # For now, return None (metrics will be computed from delta)
        return None

    def summary(self) -> Dict[str, Any]:
        """Get feedback loop summary."""
        return {
            'memory': self.memory.summary(),
            'pending_executions': len(self._pending_executions),
            'policy': {
                'exploration_rate': self.policy.exploration_rate,
            },
        }


# ─── MetricsExtractor: Derives metrics from execution events ─────

class MetricsExtractor:
    """Extracts ExecutionMetrics from execution events.

    This bridges the gap between "execution events" and "metrics"
    that the feedback loop needs.
    """

    @staticmethod
    def extract(events: List[ExecutionEvent]) -> ExecutionMetrics:
        """Extract metrics from execution events."""
        if not events:
            return ExecutionMetrics()

        return ExecutionMetrics(
            step_count=len(events),
            recursive_depth=max((e.depth or 0) for e in events),
            total_calls=sum(1 for e in events if e.event_type == 'call'),
            invariant_violations=0,  # Would need invariant checking
            cache_hits=0,  # Would need cache tracking
            cache_misses=0,
            unique_subproblems=0,
            execution_time_ms=0.0,
        )

    @staticmethod
    def extract_from_insight(insight_result: Dict[str, Any]) -> ExecutionMetrics:
        """Extract metrics from insight API result."""
        return ExecutionMetrics(
            step_count=insight_result.get('total_steps', 0),
            time_complexity=insight_result.get('insight', {}).get('explanation_levels', {}).get('complexity', ''),
            total_calls=insight_result.get('total_steps', 0),
        )


# ─── Updated CognitionEngine with P14 Feedback Loop ──────────────

# Global feedback loop instance
_feedback_loop = ExecutionFeedbackLoop()

def get_feedback_loop() -> ExecutionFeedbackLoop:
    """Get the global feedback loop instance."""
    return _feedback_loop

def _understand_with_feedback(self, matches: List[PatternMatch],
                               events: List[ExecutionEvent]) -> List[IntentGraph]:
    """Extended understand: adds P14 adaptive action ranking."""
    # Call P13 understand (adds actions)
    intent_graphs = _understand_with_actions(self, matches, events)

    # P14: Re-rank actions based on learned policy
    for intent in intent_graphs:
        if intent.actions:
            intent.actions = _feedback_loop.get_adjusted_actions(intent.actions)

    return intent_graphs

# Apply P14 patch (overwrites P13 patch)
CognitionEngine.understand = _understand_with_feedback


# ─── P15: Memory Consolidation Layer ─────────────────────────────

import threading
from collections import defaultdict
from enum import Enum


class ConceptLifecycle(Enum):
    """Lifecycle states for concepts.

    P16: Concepts move through states as they are validated or invalidated.
    This prevents concept drift and ensures only reliable knowledge persists.

    Transitions:
        EMERGING → VALIDATED (enough evidence, high success rate)
        EMERGING → INVALIDATED (low success rate, counter-examples)
        VALIDATED → DEPRECATED (success rate declining)
        VALIDATED → INVALIDATED (critical counter-example)
        DEPRECATED → INVALIDATED (continued decline)
        ANY → EMERGING (new evidence contradicts state)
    """
    EMERGING = 'emerging'        # New concept, accumulating evidence
    VALIDATED = 'validated'      # Proven reliable, high confidence
    DEPRECATED = 'deprecated'    # Declining performance, being phased out
    INVALIDATED = 'invalidated'  # Proven wrong, should not be used


@dataclass
class Concept:
    """An abstracted rule extracted from experience.

    P15: This is the "knowledge unit" — a generalizable insight
    that transcends individual executions.

    Example:
        pattern: "recursion + overlapping subproblems"
        action: "add memoization"
        confidence: 0.92
        evidence_count: 47
    """
    concept_id: str                      # Unique identifier
    name: str                            # Human-readable name
    description: str                     # What this concept means
    pattern: str                         # When to apply (semantic pattern)
    action_type: str                     # What action to take
    action_template: str                 # Action title template
    confidence: float                    # How reliable (0-1)
    evidence_count: int                  # How many executions support this
    success_rate: float                  # Historical success rate
    examples: List[str] = field(default_factory=list)  # Execution IDs
    tags: List[str] = field(default_factory=list)       # Semantic tags
    created_at: float = 0.0             # When first learned
    last_used: float = 0.0              # When last applied
    use_count: int = 0                  # How many times applied
    lifecycle: ConceptLifecycle = ConceptLifecycle.EMERGING  # P16: lifecycle state


@dataclass
class ConceptCluster:
    """A cluster of related concepts for compression."""
    cluster_id: str
    concepts: List[Concept]
    centroid_pattern: str                # Representative pattern
    centroid_action: str                 # Representative action
    avg_confidence: float
    total_evidence: int


class ExperienceBuffer:
    """Collects raw execution records for pattern extraction.

    P15: This is the "experience memory" — a buffer of raw
    execution records that will be consolidated into concepts.

    Features:
    - Fixed-size FIFO buffer (prevents memory explosion)
    - Indexing by action_type for fast retrieval
    - Clustering preparation
    """

    def __init__(self, max_size: int = 1000):
        self.buffer: List[ActionExecution] = []
        self.max_size = max_size
        self._by_type: Dict[str, List[ActionExecution]] = defaultdict(list)
        self._by_title: Dict[str, List[ActionExecution]] = defaultdict(list)

    def add(self, execution: ActionExecution):
        """Add execution to buffer."""
        self.buffer.append(execution)
        self._by_type[execution.action_type].append(execution)
        self._by_title[execution.action_title].append(execution)

        # Evict oldest if buffer full
        if len(self.buffer) > self.max_size:
            evicted = self.buffer.pop(0)
            self._by_type[evicted.action_type].remove(evicted)
            self._by_title[evicted.action_title].remove(evicted)

    def get_by_type(self, action_type: str) -> List[ActionExecution]:
        """Get executions by action type."""
        return self._by_type.get(action_type, [])

    def get_by_title(self, action_title: str) -> List[ActionExecution]:
        """Get executions by action title."""
        return self._by_title.get(action_title, [])

    def get_successful(self) -> List[ActionExecution]:
        """Get all successful executions."""
        return [e for e in self.buffer if e.success]

    def get_failed(self) -> List[ActionExecution]:
        """Get all failed executions."""
        return [e for e in self.buffer if not e.success]

    def size(self) -> int:
        return len(self.buffer)

    def clear(self):
        self.buffer.clear()
        self._by_type.clear()
        self._by_title.clear()


class PatternExtractor:
    """Extracts abstract patterns from experience buffer.

    P15: This is the "abstraction engine" — it finds common
    patterns across executions and creates concepts.

    Techniques:
    - Frequency analysis (what works often?)
    - Context clustering (when does it work?)
    - Success/failure correlation (what distinguishes success?)
    """

    def __init__(self, min_evidence: int = 3, min_confidence: float = 0.6):
        self.min_evidence = min_evidence
        self.min_confidence = min_confidence

    def extract(self, buffer: ExperienceBuffer) -> List[Concept]:
        """Extract concepts from experience buffer."""
        concepts = []

        # Phase 1: Extract from action types
        concepts.extend(self._extract_from_types(buffer))

        # Phase 2: Extract from action titles (more specific)
        concepts.extend(self._extract_from_titles(buffer))

        # Phase 3: Extract from success patterns
        concepts.extend(self._extract_from_success_patterns(buffer))

        # Deduplicate and filter
        concepts = self._deduplicate(concepts)
        concepts = [c for c in concepts if c.evidence_count >= self.min_evidence]

        return concepts

    def _extract_from_types(self, buffer: ExperienceBuffer) -> List[Concept]:
        """Extract concepts from action type patterns."""
        concepts = []

        for action_type in set(e.action_type for e in buffer.buffer):
            execs = buffer.get_by_type(action_type)
            if len(execs) < self.min_evidence:
                continue

            success_count = sum(1 for e in execs if e.success)
            success_rate = success_count / len(execs)

            if success_rate >= self.min_confidence:
                # This action type works well
                concept = Concept(
                    concept_id=f'type:{action_type}',
                    name=f'{action_type} 策略',
                    description=f'{action_type} 类型的操作成功率 {success_rate:.0%}',
                    pattern=f'action_type == {action_type}',
                    action_type=action_type,
                    action_template=f'{ACTION_TYPE_LABELS.get(action_type, action_type)}: {{title}}',
                    confidence=success_rate,
                    evidence_count=len(execs),
                    success_rate=success_rate,
                    examples=[e.execution_id for e in execs[:5]],
                    tags=[action_type],
                    created_at=time.time(),
                    last_used=max(e.timestamp for e in execs),
                    use_count=0,
                )
                concepts.append(concept)

        return concepts

    def _extract_from_titles(self, buffer: ExperienceBuffer) -> List[Concept]:
        """Extract concepts from action title patterns."""
        concepts = []

        for title in set(e.action_title for e in buffer.buffer):
            execs = buffer.get_by_title(title)
            if len(execs) < self.min_evidence:
                continue

            success_count = sum(1 for e in execs if e.success)
            success_rate = success_count / len(execs)

            if success_rate >= self.min_confidence:
                # This specific action works well
                action_type = execs[0].action_type
                concept = Concept(
                    concept_id=f'title:{hashlib.md5(title.encode()).hexdigest()[:8]}',
                    name=title,
                    description=f'"{title}" 成功率 {success_rate:.0%} ({len(execs)} 次执行)',
                    pattern=f'action_title == "{title}"',
                    action_type=action_type,
                    action_template=title,
                    confidence=success_rate,
                    evidence_count=len(execs),
                    success_rate=success_rate,
                    examples=[e.execution_id for e in execs[:5]],
                    tags=[action_type, 'specific'],
                    created_at=time.time(),
                    last_used=max(e.timestamp for e in execs),
                    use_count=0,
                )
                concepts.append(concept)

        return concepts

    def _extract_from_success_patterns(self, buffer: ExperienceBuffer) -> List[Concept]:
        """Extract concepts from success patterns (what works together)."""
        concepts = []

        # Find pairs of action types that often succeed together
        successful = buffer.get_successful()
        if len(successful) < self.min_evidence:
            return concepts

        # Group by execution context (simplified)
        type_pairs = defaultdict(int)
        for i, e1 in enumerate(successful):
            for e2 in successful[i+1:]:
                if e1.action_type != e2.action_type:
                    pair = tuple(sorted([e1.action_type, e2.action_type]))
                    type_pairs[pair] += 1

        # Create concepts for frequent pairs
        for pair, count in type_pairs.items():
            if count >= self.min_evidence:
                concept = Concept(
                    concept_id=f'pair:{pair[0]}+{pair[1]}',
                    name=f'{pair[0]} + {pair[1]} 组合',
                    description=f'{pair[0]} 和 {pair[1]} 组合成功率高 ({count} 次)',
                    pattern=f'action_type in {list(pair)}',
                    action_type=pair[0],
                    action_template=f'{pair[0]} + {pair[1]} 组合策略',
                    confidence=0.8,  # Default for pairs
                    evidence_count=count,
                    success_rate=0.8,
                    examples=[],
                    tags=list(pair),
                    created_at=time.time(),
                    last_used=time.time(),
                    use_count=0,
                )
                concepts.append(concept)

        return concepts

    def _deduplicate(self, concepts: List[Concept]) -> List[Concept]:
        """Remove duplicate concepts."""
        seen = {}
        for concept in concepts:
            key = concept.concept_id
            if key not in seen or concept.confidence > seen[key].confidence:
                seen[key] = concept
        return list(seen.values())


class ConceptMemory:
    """Stores and manages abstracted concepts.

    P15: This is the "long-term memory" — a knowledge base of
    abstracted rules that persist across executions.

    Features:
    - Concept storage and retrieval
    - Relevance scoring (which concepts apply to current context?)
    - Aging and forgetting (outdated concepts fade)
    - Compression (merge similar concepts)
    """

    def __init__(self, max_concepts: int = 500):
        self.concepts: Dict[str, Concept] = {}
        self.max_concepts = max_concepts
        self._by_type: Dict[str, List[Concept]] = defaultdict(list)
        self._by_tag: Dict[str, List[Concept]] = defaultdict(list)

    def add(self, concept: Concept):
        """Add or update a concept."""
        if concept.concept_id in self.concepts:
            # Update existing concept
            existing = self.concepts[concept.concept_id]
            existing.evidence_count += concept.evidence_count
            existing.success_rate = (
                (existing.success_rate * existing.evidence_count +
                 concept.success_rate * concept.evidence_count) /
                (existing.evidence_count + concept.evidence_count)
            )
            existing.confidence = min(0.95, existing.confidence + 0.01)
            existing.last_used = time.time()
        else:
            # Add new concept
            self.concepts[concept.concept_id] = concept
            self._by_type[concept.action_type].append(concept)
            for tag in concept.tags:
                self._by_tag[tag].append(concept)

        # Evict if full
        if len(self.concepts) > self.max_concepts:
            self._evict_oldest()

    def get_relevant(self, context: Dict[str, Any],
                     top_k: int = 5) -> List[Concept]:
        """Get concepts relevant to current context."""
        scores = []

        for concept in self.concepts.values():
            score = self._relevance_score(concept, context)
            if score > 0:
                scores.append((concept, score))

        # Sort by relevance
        scores.sort(key=lambda x: x[1], reverse=True)
        return [c for c, _ in scores[:top_k]]

    def _relevance_score(self, concept: Concept,
                         context: Dict[str, Any]) -> float:
        """Compute relevance score for a concept in given context."""
        score = concept.confidence

        # Boost if action type matches
        if 'action_type' in context:
            if concept.action_type == context['action_type']:
                score *= 1.5

        # Boost if tags match
        if 'tags' in context:
            matching_tags = set(concept.tags) & set(context['tags'])
            if matching_tags:
                score *= (1 + 0.2 * len(matching_tags))

        # Recency boost
        hours_since_use = (time.time() - concept.last_used) / 3600
        if hours_since_use < 24:
            score *= 1.2
        elif hours_since_use > 168:  # 1 week
            score *= 0.8

        # Evidence boost
        if concept.evidence_count > 10:
            score *= 1.3

        return score

    def _evict_oldest(self):
        """Evict oldest, least-used concepts."""
        if not self.concepts:
            return

        # Sort by last_used (oldest first)
        sorted_concepts = sorted(
            self.concepts.values(),
            key=lambda c: (c.last_used, -c.use_count)
        )

        # Remove oldest 10%
        evict_count = max(1, len(sorted_concepts) // 10)
        for concept in sorted_concepts[:evict_count]:
            del self.concepts[concept.concept_id]
            self._by_type[concept.action_type].remove(concept)
            for tag in concept.tags:
                self._by_tag[tag].remove(concept)

    def get_by_type(self, action_type: str) -> List[Concept]:
        """Get concepts by action type."""
        return self._by_type.get(action_type, [])

    def get_by_tag(self, tag: str) -> List[Concept]:
        """Get concepts by tag."""
        return self._by_tag.get(tag, [])

    def summary(self) -> Dict[str, Any]:
        """Get memory summary."""
        return {
            'total_concepts': len(self.concepts),
            'by_type': {k: len(v) for k, v in self._by_type.items()},
            'avg_confidence': (
                sum(c.confidence for c in self.concepts.values()) /
                len(self.concepts) if self.concepts else 0
            ),
            'avg_evidence': (
                sum(c.evidence_count for c in self.concepts.values()) /
                len(self.concepts) if self.concepts else 0
            ),
        }


class PolicyBiasInjector:
    """Uses concepts to bias action generation.

    P15: This is the "wisdom layer" — it injects learned knowledge
    into the action synthesis process.

    When generating actions, the injector:
    1. Retrieves relevant concepts for current context
    2. Boosts priority of actions matching successful concepts
    3. Suppresses actions matching failed concepts
    4. Suggests new actions based on concept templates
    """

    def __init__(self, concept_memory: ConceptMemory):
        self.memory = concept_memory

    def inject_bias(self, actions: List[Action],
                    context: Dict[str, Any]) -> List[Action]:
        """Inject concept-based bias into action priorities."""
        relevant_concepts = self.memory.get_relevant(context)

        if not relevant_concepts:
            return actions  # No bias to inject

        biased_actions = []
        for action in actions:
            # Find matching concepts
            matching = [
                c for c in relevant_concepts
                if self._matches_concept(action, c)
            ]

            if matching:
                # Compute bias from matching concepts
                bias = self._compute_bias(matching)
                adjusted_priority = action.priority * bias

                # Create biased action
                biased_action = Action(
                    action_type=action.action_type,
                    title=action.title,
                    description=action.description,
                    priority=min(1.0, adjusted_priority),
                    confidence=action.confidence,
                    target_line=action.target_line,
                    target_variable=action.target_variable,
                    evidence=action.evidence.copy(),
                    preconditions=action.preconditions.copy(),
                    expected_outcome=action.expected_outcome,
                    effort=action.effort,
                    impact=action.impact,
                    from_goal=action.from_goal,
                    from_invariant=action.from_invariant,
                    from_counterfactual=action.from_counterfactual,
                )

                # Add concept evidence
                for c in matching:
                    biased_action.evidence.append(
                        f'经验支持: {c.name} ({c.success_rate:.0%} 成功率, '
                        f'{c.evidence_count} 次验证)'
                    )

                biased_actions.append(biased_action)
            else:
                biased_actions.append(action)

        # Sort by biased priority
        biased_actions.sort(key=lambda a: a.priority, reverse=True)
        return biased_actions

    def suggest_from_concepts(self, context: Dict[str, Any]) -> List[Action]:
        """Suggest new actions based on concept templates."""
        suggestions = []
        relevant_concepts = self.memory.get_relevant(context, top_k=10)

        for concept in relevant_concepts:
            if concept.success_rate > 0.7 and concept.evidence_count > 5:
                # High-confidence concept → suggest action
                suggestion = Action(
                    action_type=concept.action_type,
                    title=concept.action_template.format(title=concept.name),
                    description=f'基于历史经验: {concept.description}',
                    priority=concept.confidence * 0.9,
                    confidence=concept.confidence,
                    evidence=[
                        f'经验支持: {concept.evidence_count} 次执行, '
                        f'{concept.success_rate:.0%} 成功率'
                    ],
                    preconditions=[concept.pattern],
                    expected_outcome=f'预期成功率 {concept.success_rate:.0%}',
                    effort='medium',
                    impact='medium',
                )
                suggestions.append(suggestion)

        return suggestions

    def _matches_concept(self, action: Action, concept: Concept) -> bool:
        """Check if an action matches a concept."""
        # Match by action type
        if action.action_type == concept.action_type:
            return True

        # Match by title similarity (simplified)
        if concept.action_template in action.title:
            return True

        # Match by tags
        action_tags = {action.action_type}
        if action.from_goal:
            action_tags.add(action.from_goal)
        if action.from_invariant:
            action_tags.add(action.from_invariant)

        if set(concept.tags) & action_tags:
            return True

        return False

    def _compute_bias(self, concepts: List[Concept]) -> float:
        """Compute priority bias from matching concepts."""
        if not concepts:
            return 1.0

        # Average success rate of matching concepts
        avg_success = sum(c.success_rate for c in concepts) / len(concepts)

        # Bias: >1.0 boosts, <1.0 suppresses
        # If avg_success = 0.8, bias = 1.6 (strong boost)
        # If avg_success = 0.3, bias = 0.6 (suppress)
        return 0.5 + avg_success  # maps [0,1] → [0.5, 1.5]


class MemoryConsolidationEngine:
    """P15: Orchestrates the full memory consolidation pipeline.

    This is the "learning engine" that transforms raw experience
    into abstracted knowledge.

    Pipeline:
        P14 Execution Memory
              ↓
        Experience Buffer
              ↓
        Pattern Extractor
              ↓
        Concept Memory
              ↓
        Policy Bias Injection (P13 + P14 share)
    """

    def __init__(self):
        self.experience_buffer = ExperienceBuffer(max_size=2000)
        self.pattern_extractor = PatternExtractor(min_evidence=3, min_confidence=0.6)
        self.concept_memory = ConceptMemory(max_concepts=500)
        self.bias_injector = PolicyBiasInjector(self.concept_memory)
        self._consolidation_count = 0
        self._last_consolidation = 0.0

    def record_execution(self, execution: ActionExecution):
        """Record an execution in the experience buffer."""
        self.experience_buffer.add(execution)

        # Trigger consolidation if buffer is full enough
        if (self.experience_buffer.size() >= 50 and
                time.time() - self._last_consolidation > 3600):  # 1 hour
            self.consolidate()

    def consolidate(self):
        """Run the full consolidation pipeline."""
        # Phase 1: Extract patterns from buffer
        concepts = self.pattern_extractor.extract(self.experience_buffer)

        # Phase 2: Add to concept memory
        for concept in concepts:
            self.concept_memory.add(concept)

        # Phase 3: Update stats
        self._consolidation_count += 1
        self._last_consolidation = time.time()

    def get_biased_actions(self, actions: List[Action],
                           context: Dict[str, Any]) -> List[Action]:
        """Get actions biased by learned concepts."""
        return self.bias_injector.inject_bias(actions, context)

    def get_concept_suggestions(self, context: Dict[str, Any]) -> List[Action]:
        """Get action suggestions from concepts."""
        return self.bias_injector.suggest_from_concepts(context)

    def summary(self) -> Dict[str, Any]:
        """Get consolidation summary."""
        return {
            'experience_buffer_size': self.experience_buffer.size(),
            'consolidation_count': self._consolidation_count,
            'last_consolidation': self._last_consolidation,
            'concept_memory': self.concept_memory.summary(),
        }


# ─── Global Memory Consolidation Engine ──────────────────────────

_consolidation_engine = MemoryConsolidationEngine()

def get_consolidation_engine() -> MemoryConsolidationEngine:
    """Get the global memory consolidation engine."""
    return _consolidation_engine


# ─── Updated CognitionEngine with P15 Memory Consolidation ───────

def _understand_with_consolidation(self, matches: List[PatternMatch],
                                    events: List[ExecutionEvent]) -> List[IntentGraph]:
    """Extended understand: adds P15 memory consolidation."""
    # Call P14 understand (adds adaptive actions)
    intent_graphs = _understand_with_feedback(self, matches, events)

    # P15: Bias actions based on consolidated concepts
    for intent in intent_graphs:
        if intent.actions:
            # Build context for concept retrieval
            context = {
                'pattern_name': intent.pattern.pattern_name,
                'action_types': [a.action_type for a in intent.actions],
                'tags': [intent.pattern.pattern_name],
            }

            # Get concept-biased actions
            intent.actions = _consolidation_engine.get_biased_actions(
                intent.actions, context
            )

            # Add concept-based suggestions
            suggestions = _consolidation_engine.get_concept_suggestions(context)
            if suggestions:
                # Merge suggestions (avoid duplicates)
                existing_titles = {a.title for a in intent.actions}
                for suggestion in suggestions:
                    if suggestion.title not in existing_titles:
                        intent.actions.append(suggestion)
                        existing_titles.add(suggestion.title)

                # Re-sort
                intent.actions.sort(key=lambda a: a.priority, reverse=True)

    return intent_graphs

# Apply P15 patch (overwrites P14 patch)
CognitionEngine.understand = _understand_with_consolidation


# ─── P16: Concept Validation Layer ───────────────────────────────

# Valid state transitions
LIFECYCLE_TRANSITIONS = {
    ConceptLifecycle.EMERGING: {ConceptLifecycle.VALIDATED, ConceptLifecycle.INVALIDATED},
    ConceptLifecycle.VALIDATED: {ConceptLifecycle.DEPRECATED, ConceptLifecycle.INVALIDATED},
    ConceptLifecycle.DEPRECATED: {ConceptLifecycle.INVALIDATED},
    ConceptLifecycle.INVALIDATED: set(),  # Terminal state
}


@dataclass
class ConceptValidationRecord:
    """Record of a concept validation check."""
    concept_id: str
    timestamp: float
    old_state: ConceptLifecycle
    new_state: ConceptLifecycle
    reason: str
    evidence_count: int
    success_rate: float
    counter_examples: List[str] = field(default_factory=list)


class CounterExampleDetector:
    """Detects executions that contradict a concept.

    P16: This is the "immune system" — it finds evidence that a
    concept is wrong, preventing concept drift.

    A counter-example is an execution where:
    1. The concept predicted success, but execution failed
    2. The concept predicted failure, but execution succeeded
    3. The concept's pattern matched, but outcome was unexpected
    """

    def __init__(self, min_counter_examples: int = 3):
        self.min_counter_examples = min_counter_examples

    def detect(self, concept: Concept,
               executions: List[ActionExecution]) -> List[ActionExecution]:
        """Find counter-examples for a concept."""
        counter_examples = []

        for execution in executions:
            if self._is_counter_example(concept, execution):
                counter_examples.append(execution)

        return counter_examples

    def _is_counter_example(self, concept: Concept,
                            execution: ActionExecution) -> bool:
        """Check if an execution is a counter-example."""
        # Check if execution matches concept pattern
        if not self._matches_pattern(concept, execution):
            return False  # Not relevant

        # Counter-example: concept predicts success, but execution failed
        if concept.success_rate > 0.5 and not execution.success:
            return True

        # Counter-example: concept predicts failure, but execution succeeded
        if concept.success_rate < 0.5 and execution.success:
            return True

        return False

    def _matches_pattern(self, concept: Concept,
                         execution: ActionExecution) -> bool:
        """Check if execution matches concept's pattern."""
        # Match by action type
        if concept.action_type == execution.action_type:
            return True

        # Match by title
        if concept.action_template in execution.action_title:
            return True

        # Match by tags
        execution_tags = {execution.action_type}
        if set(concept.tags) & execution_tags:
            return True

        return False


class ConfidenceDecay:
    """Reduces concept confidence over time without reinforcement.

    P16: This prevents stale concepts from persisting indefinitely.
    Concepts that aren't reinforced naturally decay.

    Decay formula:
        new_confidence = old_confidence * (1 - decay_rate * time_factor)

    Where time_factor increases with time since last use.
    """

    def __init__(self, base_decay_rate: float = 0.01,
                 max_decay: float = 0.5):
        self.base_decay_rate = base_decay_rate
        self.max_decay = max_decay

    def apply(self, concept: Concept, current_time: float) -> float:
        """Apply confidence decay to a concept."""
        hours_since_use = (current_time - concept.last_used) / 3600

        if hours_since_use < 1:
            return concept.confidence  # No decay for recent use

        # Time factor: increases with time
        time_factor = min(1.0, hours_since_use / 168)  # Normalize to 1 week

        # Decay amount
        decay = self.base_decay_rate * time_factor
        decay = min(decay, self.max_decay)

        # Apply decay
        new_confidence = concept.confidence * (1 - decay)
        return max(0.0, new_confidence)

    def should_deprecate(self, concept: Concept,
                         current_time: float) -> bool:
        """Check if concept should be deprecated."""
        # Deprecate if confidence drops below threshold
        if concept.confidence < 0.3:
            return True

        # Deprecate if not used for a long time
        hours_since_use = (current_time - concept.last_used) / 3600
        if hours_since_use > 720:  # 30 days
            return True

        return False


class ConceptValidator:
    """P16: Orchestrates concept validation pipeline.

    This is the "quality control" for learned concepts.
    It ensures only reliable knowledge persists.

    Pipeline:
        Concept + Executions → Counter-Example Detection
                            → Confidence Decay
                            → Lifecycle Transition
                            → Concept Update/Invalidation
    """

    def __init__(self):
        self.counter_example_detector = CounterExampleDetector(min_counter_examples=3)
        self.confidence_decay = ConfidenceDecay(base_decay_rate=0.01)
        self.validation_history: List[ConceptValidationRecord] = []

    def validate(self, concept: Concept,
                 executions: List[ActionExecution],
                 current_time: float) -> ConceptLifecycle:
        """Validate a concept against recent executions.

        Returns the new lifecycle state.
        """
        # Phase 1: Apply confidence decay
        new_confidence = self.confidence_decay.apply(concept, current_time)
        concept.confidence = new_confidence

        # Phase 2: Detect counter-examples
        counter_examples = self.counter_example_detector.detect(concept, executions)

        # Phase 3: Determine lifecycle transition
        new_state = self._determine_state(concept, counter_examples, current_time)

        # Phase 4: Record validation
        if new_state != concept.lifecycle if hasattr(concept, 'lifecycle') else ConceptLifecycle.EMERGING:
            self._record_validation(concept, new_state, counter_examples)

        return new_state

    def _determine_state(self, concept: Concept,
                         counter_examples: List[ActionExecution],
                         current_time: float) -> ConceptLifecycle:
        """Determine the new lifecycle state."""
        current_state = getattr(concept, 'lifecycle', ConceptLifecycle.EMERGING)

        # Check for invalidation (critical counter-examples)
        if len(counter_examples) >= self.counter_example_detector.min_counter_examples:
            return ConceptLifecycle.INVALIDATED

        # Check for deprecation (declining performance)
        if self.confidence_decay.should_deprecate(concept, current_time):
            if current_state == ConceptLifecycle.VALIDATED:
                return ConceptLifecycle.DEPRECATED
            elif current_state == ConceptLifecycle.EMERGING:
                return ConceptLifecycle.INVALIDATED

        # Check for validation (enough evidence, high success rate)
        if current_state == ConceptLifecycle.EMERGING:
            if (concept.evidence_count >= 10 and
                    concept.success_rate >= 0.7):
                return ConceptLifecycle.VALIDATED

        return current_state

    def _record_validation(self, concept: Concept,
                           new_state: ConceptLifecycle,
                           counter_examples: List[ActionExecution]):
        """Record a validation event."""
        record = ConceptValidationRecord(
            concept_id=concept.concept_id,
            timestamp=time.time(),
            old_state=getattr(concept, 'lifecycle', ConceptLifecycle.EMERGING),
            new_state=new_state,
            reason=f'Counter-examples: {len(counter_examples)}',
            evidence_count=concept.evidence_count,
            success_rate=concept.success_rate,
            counter_examples=[e.execution_id for e in counter_examples[:5]],
        )
        self.validation_history.append(record)

    def get_validation_history(self, concept_id: str) -> List[ConceptValidationRecord]:
        """Get validation history for a concept."""
        return [r for r in self.validation_history if r.concept_id == concept_id]


class ConceptInvalidator:
    """Removes invalid concepts from memory.

    P16: This is the "garbage collector" for bad knowledge.
    It ensures concept memory stays clean.
    """

    def __init__(self):
        self.invalidated_concepts: List[Concept] = []
        self.invalidation_reasons: Dict[str, str] = {}

    def invalidate(self, concept: Concept, reason: str):
        """Invalidate a concept."""
        concept.lifecycle = ConceptLifecycle.INVALIDATED
        self.invalidated_concepts.append(concept)
        self.invalidation_reasons[concept.concept_id] = reason

    def is_invalid(self, concept: Concept) -> bool:
        """Check if a concept is invalid."""
        return getattr(concept, 'lifecycle', ConceptLifecycle.EMERGING) == ConceptLifecycle.INVALIDATED

    def get_invalid_concepts(self) -> List[Concept]:
        """Get all invalid concepts."""
        return self.invalidated_concepts

    def summary(self) -> Dict[str, Any]:
        """Get invalidation summary."""
        return {
            'total_invalidated': len(self.invalidated_concepts),
            'reasons': dict(self.invalidation_reasons),
        }


class ConceptValidationEngine:
    """P16: Orchestrates the full concept validation pipeline.

    This is the "immune system" of the cognitive architecture.
    It ensures only validated knowledge persists.

    Pipeline:
        Concept Memory → Validation → Invalidation/Cleanup
                                      ↓
                              Clean Concept Memory
    """

    def __init__(self):
        self.validator = ConceptValidator()
        self.invalidator = ConceptInvalidator()
        self._validation_count = 0
        self._last_validation = 0.0

    def validate_concept(self, concept: Concept,
                         executions: List[ActionExecution]) -> ConceptLifecycle:
        """Validate a single concept."""
        new_state = self.validator.validate(
            concept, executions, time.time()
        )

        # Update concept lifecycle
        old_state = getattr(concept, 'lifecycle', ConceptLifecycle.EMERGING)
        concept.lifecycle = new_state

        # Handle state transitions
        if new_state == ConceptLifecycle.INVALIDATED:
            self.invalidator.invalidate(concept, 'Validation failed')
        elif new_state == ConceptLifecycle.DEPRECATED:
            concept.confidence *= 0.8  # Reduce confidence

        return new_state

    def validate_all(self, concept_memory: ConceptMemory,
                     execution_buffer: ExperienceBuffer) -> Dict[str, ConceptLifecycle]:
        """Validate all concepts in memory."""
        results = {}
        executions = execution_buffer.buffer

        for concept_id, concept in concept_memory.concepts.items():
            new_state = self.validate_concept(concept, executions)
            results[concept_id] = new_state

        # Clean up invalid concepts
        self._cleanup_invalid(concept_memory)

        self._validation_count += 1
        self._last_validation = time.time()

        return results

    def _cleanup_invalid(self, concept_memory: ConceptMemory):
        """Remove invalid concepts from memory."""
        invalid_ids = [
            cid for cid, concept in concept_memory.concepts.items()
            if self.invalidator.is_invalid(concept)
        ]

        for cid in invalid_ids:
            concept = concept_memory.concepts.pop(cid)
            # Clean up indexes
            concept_memory._by_type[concept.action_type] = [
                c for c in concept_memory._by_type[concept.action_type]
                if c.concept_id != cid
            ]
            for tag in concept.tags:
                concept_memory._by_tag[tag] = [
                    c for c in concept_memory._by_tag[tag]
                    if c.concept_id != cid
                ]

    def summary(self) -> Dict[str, Any]:
        """Get validation summary."""
        return {
            'validation_count': self._validation_count,
            'last_validation': self._last_validation,
            'invalidator': self.invalidator.summary(),
            'validator_history_count': len(self.validator.validation_history),
        }


# ─── Global Concept Validation Engine ────────────────────────────

_validation_engine = ConceptValidationEngine()

def get_validation_engine() -> ConceptValidationEngine:
    """Get the global concept validation engine."""
    return _validation_engine


# ─── Updated MemoryConsolidationEngine with P16 Validation ───────

# Store original consolidate method
_original_consolidate = MemoryConsolidationEngine.consolidate

def _consolidate_with_validation(self):
    """Extended consolidation: adds P16 concept validation."""
    # Call original consolidation (extracts concepts)
    _original_consolidate(self)

    # P16: Validate all concepts
    _validation_engine.validate_all(
        self.concept_memory,
        self.experience_buffer
    )

MemoryConsolidationEngine.consolidate = _consolidate_with_validation
