"""Input inference: auto-generate mock arguments so user-defined functions
can be traced without requiring the user to also provide a call site.

Pipeline:
  1. inspect.signature → get parameter names & defaults
  2. ast.parse → find attribute accesses (.next, .left, .val, etc.)
  3. Map param name + AST hints → mock value type
  4. Generate mock object with required attributes
"""

from __future__ import annotations
import ast
import inspect
import textwrap
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


# ── Mock factories ──────────────────────────────────────────────────────

def _make_linked_list(values=(1, 2, 3)) -> Any:
    """Build a singly-linked list: node(val) -> node(val) -> ... -> None.
    Returns the head node.
    """
    class _ListNode:
        def __init__(self, val, next=None):
            self.val = val
            self.next = next
        def __repr__(self):
            return f"{self.val} -> {self.next.val if self.next else 'None'}"

    nodes = [_ListNode(v) for v in values]
    for i in range(len(nodes) - 1):
        nodes[i].next = nodes[i + 1]
    return nodes[0]


def _make_binary_tree() -> Any:
    """Build a small binary tree:
          1
         / \
        2   3
       / \
      4   5
    Returns the root node.
    """
    class _TreeNode:
        def __init__(self, val, left=None, right=None):
            self.val = val
            self.left = left
            self.right = right
        def __repr__(self):
            return f"TreeNode({self.val})"

    root = _TreeNode(1)
    root.left = _TreeNode(2)
    root.right = _TreeNode(3)
    root.left.left = _TreeNode(4)
    root.left.right = _TreeNode(5)
    return root


def _make_array() -> list:
    return [3, 1, 4, 1, 5, 9, 2, 6]


def _make_dict() -> dict:
    return {"a": 1, "b": 2, "c": 3}


# ── AST analysis ────────────────────────────────────────────────────────

def _collect_ast_hints(func_node: ast.FunctionDef) -> dict:
    """Walk the function body and collect structural hints.

    Returns dict with keys:
      - attr_accesses: set of attribute names accessed (e.g. {"next", "val", "left"})
      - has_recursion: bool
      - subscript_targets: set of names that are indexed (e.g. {"arr"})
      - method_calls: set of method names called (e.g. {"append", "pop"})
    """
    hints: dict = {
        "attr_accesses": set(),
        "has_recursion": False,
        "subscript_targets": set(),
        "method_calls": set(),
    }

    for node in ast.walk(func_node):
        # Attribute access: obj.attr
        if isinstance(node, ast.Attribute):
            hints["attr_accesses"].add(node.attr)

        # Self-call → recursion
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == func_node.name:
                hints["has_recursion"] = True

        # Subscript: obj[key]
        if isinstance(node, ast.Subscript):
            if isinstance(node.value, ast.Name):
                hints["subscript_targets"].add(node.value.id)

        # Method call: obj.method()
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                hints["method_calls"].add(node.func.attr)

    return hints


# ── Parameter → mock mapping ────────────────────────────────────────────

_LINKED_LIST_NAMES = {"head", "node", "curr", "current", "first", "root", "start", "ptr", "list_node", "n1"}
_TREE_NAMES = {"root", "tree_root", "tree", "node", "parent"}
_ARRAY_NAMES = {"arr", "array", "nums", "numbers", "data", "items", "values", "elements", "seq", "lst"}
_STRING_NAMES = {"s", "text", "string", "name", "key", "pattern", "word", "path"}
_NUMERIC_NAMES = {"n", "size", "count", "x", "num", "val", "value", "limit", "k", "target", "idx", "index"}


def _classify_param(name: str, hints: dict) -> str:
    """Classify parameter into a type category."""
    n = name.lower().replace("_", "")

    attr = hints.get("attr_accesses", set())

    # Strong signal: .next access → linked list
    if "next" in attr and any(word in n for word in ("head", "node", "curr", "current", "first", "root", "start", "ptr", "n1")):
        return "linked_list"

    # Strong signal: .left or .right access → binary tree
    if ("left" in attr or "right" in attr) and any(word in n for word in ("root", "node", "parent", "tree")):
        return "binary_tree"

    # Name-based fallback
    if name in _LINKED_LIST_NAMES:
        return "linked_list"
    if name in _TREE_NAMES and ("left" in attr or "right" in attr):
        return "binary_tree"
    if name in _ARRAY_NAMES:
        return "array"
    if name in _STRING_NAMES:
        return "string"
    if name in _NUMERIC_NAMES:
        return "number"

    # Default: try linked list if .next is used anywhere in the function
    if "next" in attr:
        return "linked_list"
    if "left" in attr or "right" in attr:
        return "binary_tree"

    return "none"


def _generate_mock(param_name: str, param_type: str) -> Any:
    """Generate a mock value based on classification."""
    if param_type == "linked_list":
        return _make_linked_list()
    if param_type == "binary_tree":
        return _make_binary_tree()
    if param_type == "array":
        return _make_array()
    if param_type == "string":
        return "hello"
    if param_type == "number":
        return 5
    return None


# ── Main entry point ────────────────────────────────────────────────────

def infer_args(func: Callable, code: str) -> Tuple[tuple, dict]:
    """Infer function arguments from signature + code analysis.

    Args:
        func: The callable (from imported user module).
        code: The raw user code string (for AST analysis).

    Returns:
        (args_tuple, meta_dict)
        meta_dict contains: {"classifications": {param_name: type_str}, "hints": {...}}
    """
    try:
        sig = inspect.signature(func)
    except (ValueError, TypeError):
        return (), {"error": "Cannot inspect signature"}

    # Parse AST
    hints: dict = {"attr_accesses": set(), "has_recursion": False, "subscript_targets": set(), "method_calls": set()}
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func.__name__:
                hints = _collect_ast_hints(node)
                break
    except SyntaxError:
        pass

    args = []
    classifications = {}
    for name, param in sig.parameters.items():
        # Skip self/cls
        if name in ("self", "cls"):
            continue

        # If parameter has a default value, use it
        if param.default is not inspect.Parameter.empty:
            args.append(param.default)
            classifications[name] = "default"
            continue

        ptype = _classify_param(name, hints)
        classifications[name] = ptype
        args.append(_generate_mock(name, ptype))

    return tuple(args), {"classifications": classifications, "hints": {k: list(v) if isinstance(v, set) else v for k, v in hints.items()}}
