"""Static analysis for JavaScript/TypeScript source using regex-based parsing."""

from __future__ import annotations
import os
import re
from typing import List, Optional

from core.graph import CausalGraph
from core.node import CodeNode
from core.edge_types import EdgeType


# Patterns for JS/TS constructs
_FUNC_PATTERN = re.compile(
    r"(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[a-zA-Z_]\w*)\s*=>|(?:async\s+)?function\s+(\w+))"
)
_CALL_PATTERN = re.compile(r"(\w+)\s*\(")
_ASSIGN_PATTERN = re.compile(r"(?:const|let|var)\s+(\w+)\s*=")
_IMPORT_PATTERN = re.compile(r"""(?:import\s+.*?from\s+['"](.+?)['"]|require\s*\(\s*['"](.+?)['"]\s*\))""")
_IF_PATTERN = re.compile(r"^\s*(?:if|else\s+if)\s*\(")
_FOR_PATTERN = re.compile(r"^\s*(?:for|while)\s*\(")
_TRY_PATTERN = re.compile(r"^\s*try\s*\{")
_CATCH_PATTERN = re.compile(r"^\s*catch\s*\(")
_THROW_PATTERN = re.compile(r"^\s*throw\s+")
_RETURN_PATTERN = re.compile(r"^\s*return\s")


class JsAnalyzer:
    """Build causal graph from JS/TS source via regex-based parsing."""

    def analyze_file(self, file_path: str) -> CausalGraph:
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()
        return self.analyze_source(source, file_path)

    def analyze_source(self, source: str, file_path: str = "<unknown>") -> CausalGraph:
        graph = CausalGraph()
        lines = source.splitlines()
        defined_funcs: dict[str, int] = {}
        var_assignments: dict[str, str] = {}

        # First pass: collect function definitions
        for i, line in enumerate(lines, 1):
            m = _FUNC_PATTERN.search(line)
            if m:
                name = m.group(1) or m.group(2) or m.group(3)
                if name:
                    defined_funcs[name] = i

        # Second pass: build graph
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue

            nid = CodeNode.make_id(file_path, i)
            node = CodeNode(
                node_id=nid,
                file_path=file_path,
                line_number=i,
                code_content=stripped,
            )

            # Import
            if _IMPORT_PATTERN.search(line):
                node.semantic_label = "import"
                graph.add_node(node)
                continue

            # Function definition
            m = _FUNC_PATTERN.search(line)
            if m:
                name = m.group(1) or m.group(2) or m.group(3)
                if name:
                    node.semantic_label = f"function {name}"
                    graph.add_node(node)
                    continue

            # Assignment
            am = _ASSIGN_PATTERN.search(line)
            if am:
                var_name = am.group(1)
                node.semantic_label = "assignment"
                graph.add_node(node)
                # Data dependency: check if RHS references known vars
                for vname, vid in var_assignments.items():
                    if vname in line and vname != var_name:
                        graph.add_edge(vid, nid, EdgeType.DATA_DEPENDENCY)
                var_assignments[var_name] = nid
                continue

            # Function call
            call_matches = _CALL_PATTERN.findall(line)
            for call_name in call_matches:
                if call_name in defined_funcs:
                    callee_id = CodeNode.make_id(file_path, defined_funcs[call_name])
                    node.semantic_label = f"calls {call_name}"
                    graph.add_node(node)
                    if not graph.has_node(callee_id):
                        graph.add_node(CodeNode(
                            node_id=callee_id,
                            file_path=file_path,
                            line_number=defined_funcs[call_name],
                            code_content=lines[defined_funcs[call_name] - 1].strip(),
                            semantic_label=f"function {call_name}",
                        ))
                    graph.add_edge(nid, callee_id, EdgeType.CALL_RELATION)
                    break

            # Control flow
            if _IF_PATTERN.match(line):
                node.semantic_label = "if-branch"
            elif _FOR_PATTERN.match(line):
                node.semantic_label = "loop"
            elif _TRY_PATTERN.match(line):
                node.semantic_label = "try-block"
            elif _CATCH_PATTERN.match(line):
                node.semantic_label = "catch-handler"
            elif _THROW_PATTERN.match(line):
                node.semantic_label = "throw"
            elif _RETURN_PATTERN.match(line):
                node.semantic_label = "return"

            graph.add_node(node)

        return graph

    def analyze_directory(self, dir_path: str) -> CausalGraph:
        merged = CausalGraph()
        for root, _, files in os.walk(dir_path):
            for fname in files:
                if fname.endswith((".js", ".ts", ".jsx", ".tsx")):
                    fpath = os.path.join(root, fname)
                    sub = self.analyze_file(fpath)
                    merged.merge_from(sub)
        return merged
