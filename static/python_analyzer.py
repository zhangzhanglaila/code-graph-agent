"""Static analysis for Python source code using AST."""

from __future__ import annotations
import ast
import os
from typing import List, Optional

from core.graph import CausalGraph
from core.node import CodeNode
from core.edge_types import EdgeType


class PythonAnalyzer:
    """Build causal graph from Python source via AST parsing."""

    def analyze_file(self, file_path: str) -> CausalGraph:
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()
        return self.analyze_source(source, file_path)

    def analyze_source(self, source: str, file_path: str = "<unknown>") -> CausalGraph:
        graph = CausalGraph()
        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError:
            return graph

        lines = source.splitlines()
        analyzer = _FileAnalyzer(file_path, lines, graph)
        analyzer.visit(tree)
        return graph

    def analyze_directory(self, dir_path: str) -> CausalGraph:
        merged = CausalGraph()
        for root, _, files in os.walk(dir_path):
            for fname in files:
                if fname.endswith(".py"):
                    fpath = os.path.join(root, fname)
                    sub = self.analyze_file(fpath)
                    merged.merge_from(sub)
        return merged


class _FileAnalyzer(ast.NodeVisitor):
    """Walk AST and emit nodes + edges."""

    def __init__(self, file_path: str, lines: List[str], graph: CausalGraph):
        self.file_path = file_path
        self.lines = lines
        self.graph = graph
        self._current_func: Optional[str] = None
        self._var_assignments: dict[str, str] = {}  # var -> node_id where assigned
        self._defined_funcs: dict[str, int] = {}     # func_name -> line

    def _node_id(self, line: int) -> str:
        return CodeNode.make_id(self.file_path, line)

    def _get_line(self, line: int) -> str:
        if 1 <= line <= len(self.lines):
            return self.lines[line - 1].strip()
        return ""

    def _add_code_node(self, line: int, node_type: str = "CODE", label: str = "") -> CodeNode:
        nid = self._node_id(line)
        if self.graph.has_node(nid):
            return self.graph.get_node(nid)
        node = CodeNode(
            node_id=nid,
            file_path=self.file_path,
            line_number=line,
            code_content=self._get_line(line),
            node_type=node_type,
            semantic_label=label,
        )
        self.graph.add_node(node)
        return node

    # ── Function definitions ─────────────────────────────────────────

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._process_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._process_func(node)

    def _process_func(self, node):
        self._add_code_node(node.lineno, label=f"function {node.name}")
        self._defined_funcs[node.name] = node.lineno
        old = self._current_func
        self._current_func = node.name
        self.generic_visit(node)
        self._current_func = old

    # ── Assignments ──────────────────────────────────────────────────

    def visit_Assign(self, node: ast.Assign):
        self._add_code_node(node.lineno, label="assignment")
        for target in node.targets:
            for name in _extract_names(target):
                self._var_assignments[name] = self._node_id(node.lineno)

        # Track data dependencies from RHS
        for name in _extract_names_from_value(node.value):
            if name in self._var_assignments:
                self.graph.add_edge(
                    self._var_assignments[name],
                    self._node_id(node.lineno),
                    EdgeType.DATA_DEPENDENCY,
                )
        self.generic_visit(node)

    # ── Function calls ───────────────────────────────────────────────

    def visit_Call(self, node: ast.Call):
        func_name = _get_call_name(node)
        if func_name and func_name in self._defined_funcs:
            def_line = self._defined_funcs[func_name]
            caller_id = self._node_id(node.lineno)
            callee_id = self._node_id(def_line)
            self._add_code_node(node.lineno, label=f"calls {func_name}")
            self._add_code_node(def_line, label=f"function {func_name}")
            self.graph.add_edge(caller_id, callee_id, EdgeType.CALL_RELATION)
        self.generic_visit(node)

    # ── Control flow ─────────────────────────────────────────────────

    def visit_If(self, node: ast.If):
        self._add_code_node(node.lineno, label="if-branch")
        self.generic_visit(node)

    def visit_For(self, node: ast.For):
        self._add_code_node(node.lineno, label="for-loop")
        self.generic_visit(node)

    def visit_While(self, node: ast.While):
        self._add_code_node(node.lineno, label="while-loop")
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try):
        self._add_code_node(node.lineno, label="try-block")
        for handler in node.handlers:
            self._add_code_node(handler.lineno, label="except-handler")
        self.generic_visit(node)

    # ── Return / Raise ───────────────────────────────────────────────

    def visit_Return(self, node: ast.Return):
        self._add_code_node(node.lineno, label="return")
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise):
        self._add_code_node(node.lineno, label="raise")
        self.generic_visit(node)

    # ── Import ───────────────────────────────────────────────────────

    def visit_Import(self, node: ast.Import):
        self._add_code_node(node.lineno, label="import")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        self._add_code_node(node.lineno, label="import-from")
        self.generic_visit(node)


# ── Helpers ──────────────────────────────────────────────────────────

def _extract_names(target) -> List[str]:
    """Extract variable names from assignment targets."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names = []
        for elt in target.elts:
            names.extend(_extract_names(elt))
        return names
    if isinstance(target, ast.Attribute):
        return [target.attr]
    return []


def _extract_names_from_value(node) -> List[str]:
    """Extract referenced names from RHS of assignment."""
    names: List[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.append(child.id)
    return names


def _get_call_name(node: ast.Call) -> Optional[str]:
    """Get the function name from a Call node."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None
