"""Shared helpers for API routes — code execution, caching, utilities."""

from __future__ import annotations
import importlib
import os
import sys
import tempfile
import time
from typing import Optional

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

# ── Session Cache ────────────────────────────────────────────────

SESSION_CACHE: dict = {}
SESSION_TTL = 600  # 10 minutes


def cache_put(session_id: str, data: dict):
    SESSION_CACHE[session_id] = {**data, "_ts": time.time()}
    now = time.time()
    expired = [k for k, v in SESSION_CACHE.items() if now - v.get("_ts", 0) > SESSION_TTL]
    for k in expired:
        del SESSION_CACHE[k]


def cache_get(session_id: str) -> dict | None:
    entry = SESSION_CACHE.get(session_id)
    if not entry:
        return None
    if time.time() - entry.get("_ts", 0) > SESSION_TTL:
        del SESSION_CACHE[session_id]
        return None
    return entry


# ── Code Execution ───────────────────────────────────────────────

def write_temp_code(code: str, language: str) -> str:
    """Write code to a temp file and return the path."""
    ext = {"python": ".py", "javascript": ".js", "typescript": ".ts"}.get(language, ".py")
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=ext, delete=False, encoding="utf-8")
    tmp.write(code)
    tmp.close()
    return tmp.name


def extract_func_name(code: str, func_name: str) -> str:
    """Extract function name from code if not provided."""
    if func_name:
        return func_name
    for line in code.splitlines():
        line = line.strip()
        if line.startswith("def "):
            return line[4:].split("(")[0].strip()
    return ""


def import_code_as_module(code: str, module_name: str = "_user_code"):
    """Import user code as a module. Caller must clean up the temp file."""
    tmp_path = write_temp_code(code, "python")
    spec = importlib.util.spec_from_file_location(module_name, tmp_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── Timeline Analysis ────────────────────────────────────────────

def compute_control_edges(steps_data: list) -> list:
    """Compute control flow edges from the timeline."""
    edges = []
    stack = []

    for i, step in enumerate(steps_data):
        code = step.get("code", "").rstrip()
        if not code:
            continue

        indent = len(code) - len(code.lstrip())
        code_stripped = code.lstrip()

        while stack and stack[-1][1] >= indent:
            stack.pop()

        if stack:
            parent_idx = stack[-1][0]
            edges.append({"from": parent_idx, "to": step["index"], "type": "control"})

        is_control = False
        for prefix in ("if ", "elif ", "for ", "while ", "try:", "except ", "else:"):
            if code_stripped.startswith(prefix):
                is_control = True
                break

        if is_control:
            stack.append((step["index"], indent))

    return edges


def compute_loop_groups(steps_data: list) -> list:
    """Detect loop iteration groups."""
    if not steps_data:
        return []

    groups = []
    current_line = None
    current_steps = []
    iteration = 0

    for step in steps_data:
        line = step.get("line", 0)
        code = step.get("code", "").lstrip()
        is_loop_header = any(code.startswith(p) for p in ("for ", "while "))

        if line == current_line and not is_loop_header:
            current_steps.append(step["index"])
        else:
            if current_steps and len(current_steps) >= 3:
                groups.append({
                    "line": current_line,
                    "steps": current_steps,
                    "label": f"iteration {iteration}",
                })
                iteration += 1
            elif current_steps:
                iteration = 0
            current_line = line
            current_steps = [step["index"]]

    if current_steps and len(current_steps) >= 3:
        groups.append({
            "line": current_line,
            "steps": current_steps,
            "label": f"iteration {iteration}",
        })

    return groups
