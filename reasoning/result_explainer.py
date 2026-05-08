"""Result Explainer — produce human-readable "WHY this result" explanations.

Takes an ExecutionTimeline and a result, produces:
- One-line summary
- Step-by-step causal reasoning
- Variable lineage (where did the result value come from)
"""

from __future__ import annotations
import json
import os
from typing import Any, Dict, List, Optional, Set, Tuple

from dynamic.runtime.recorder import ExecutionTimeline, ExecutionStep


def explain_result(
    timeline: ExecutionTimeline,
    result: Any,
    func_name: str = "",
) -> dict:
    """Explain WHY a function produced this result.

    Returns structured explanation:
    {
        "summary": "one-line human-readable explanation",
        "result_value": "repr of result",
        "lineage": [step-by-step how result was computed],
        "key_variables": [variables that influenced the result],
        "critical_path": [steps that actually changed the result],
    }
    """
    result_repr = repr(result)
    steps = timeline.steps
    if not steps:
        return {"summary": f"Result: {result_repr}", "lineage": []}

    # Find the return step
    return_step = None
    for step in reversed(steps):
        if step.code_line.strip().startswith("return"):
            return_step = step
            break

    # Trace variable lineage: which variables contributed to the result?
    lineage = _trace_lineage(timeline, result, return_step)

    # Find critical path: steps where result-affecting variables changed
    critical_steps = _find_critical_steps(timeline, lineage)

    # Build summary
    summary = _build_summary(result, result_repr, lineage, critical_steps, func_name)

    return {
        "summary": summary,
        "result_value": result_repr,
        "func_name": func_name,
        "lineage": lineage,
        "critical_path": [
            {
                "step": s.step_index,
                "file": os.path.basename(s.file_path),
                "line": s.line_number,
                "code": s.code_line,
                "what_changed": s.changed_vars,
            }
            for s in critical_steps
        ],
        "total_steps": len(steps),
        "critical_steps": len(critical_steps),
    }


def _trace_lineage(
    timeline: ExecutionTimeline,
    result: Any,
    return_step: Optional[ExecutionStep],
) -> List[dict]:
    """Trace back from result to find which variables contributed.

    Traces transitive dependencies: if total depends on sorted_result
    which depends on result, we trace all three.
    """
    lineage = []
    traced_vars: Set[str] = set()

    if return_step is None:
        return lineage

    # Find the variable(s) in the return statement
    return_vars = _extract_return_vars(return_step)

    # Find where the return variable was DEFINED (assigned)
    # The variable appears in locals at step N, but was assigned at step N-1
    # We look for the step whose CODE assigns the variable
    creation_steps: Dict[str, int] = {}
    for i, step in enumerate(timeline.steps):
        for var_name in return_vars:
            if var_name in creation_steps:
                continue
            # Check if this step's code assigns the variable
            code = step.code_line.strip()
            if var_name in step.variables:
                # Look backwards for the assignment step
                for j in range(i, max(i - 3, -1), -1):
                    prev = timeline.steps[j]
                    prev_code = prev.code_line.strip()
                    # Check if prev step's code is an assignment to this var
                    if (f"{var_name} =" in prev_code or
                        f"{var_name}=" in prev_code or
                        f"{var_name}(" in prev_code):
                        creation_steps[var_name] = j
                        break
                if var_name not in creation_steps:
                    creation_steps[var_name] = i

    # BFS: trace each variable and its dependencies
    queue = list(return_vars)
    while queue:
        var_name = queue.pop(0)
        if var_name in traced_vars:
            continue
        traced_vars.add(var_name)

        history = timeline.get_variable_history(var_name)
        if not history:
            continue

        prev_val = None
        for step_idx, snap in history:
            step = timeline.get_step(step_idx)
            if step is None:
                continue

            is_creation = prev_val is None
            is_change = prev_val is not None and snap.value_repr != prev_val

            if is_creation or is_change:
                lineage.append({
                    "variable": var_name,
                    "step": step_idx,
                    "line": step.line_number,
                    "code": step.code_line,
                    "value": snap.value_repr,
                    "type": snap.value_type,
                    "event": "created" if is_creation else "changed",
                    "prev_value": prev_val if is_change else None,
                })

                # Find transitive dependencies:
                # 1. Variables in the current code line
                # 2. Variables that existed in the step right before creation
                code = step.code_line
                all_known_vars = set(step.variables.keys())
                if step_idx > 0:
                    prev_step = timeline.get_step(step_idx - 1)
                    if prev_step:
                        all_known_vars.update(prev_step.variables.keys())
                for other_name in all_known_vars:
                    if other_name != var_name and other_name in code and other_name not in traced_vars:
                        queue.append(other_name)

            prev_val = snap.value_repr

        # Also check the CREATION step's code for dependencies
        # (the step where the variable first appeared in new_vars)
        if var_name in creation_steps:
            create_step = timeline.get_step(creation_steps[var_name])
            if create_step:
                code = create_step.code_line
                all_known_vars = set(create_step.variables.keys())
                if create_step.step_index > 0:
                    prev_step = timeline.get_step(create_step.step_index - 1)
                    if prev_step:
                        all_known_vars.update(prev_step.variables.keys())
                for other_name in all_known_vars:
                    if other_name != var_name and other_name in code and other_name not in traced_vars:
                        queue.append(other_name)

    return lineage


def _extract_return_vars(step: ExecutionStep) -> List[str]:
    """Extract variable names from a return statement."""
    code = step.code_line.strip()
    if not code.startswith("return"):
        return []

    # return var_name
    parts = code.split()
    if len(parts) >= 2:
        expr = parts[1]
        # Simple variable
        if expr.isidentifier():
            return [expr]
        # Return expression with known variables
        result = []
        for name in step.variables:
            if name in expr:
                result.append(name)
        return result

    return []


def _find_critical_steps(
    timeline: ExecutionTimeline,
    lineage: List[dict],
) -> List[ExecutionStep]:
    """Find steps that actually changed result-affecting variables."""
    critical: List[ExecutionStep] = []
    lineage_vars = {item["variable"] for item in lineage}
    lineage_steps = {item["step"] for item in lineage}

    for step in timeline.steps:
        # Steps where lineage variables changed
        if any(v in lineage_vars for v in step.changed_vars):
            if step not in critical:
                critical.append(step)
        # Steps in the lineage
        if step.step_index in lineage_steps:
            if step not in critical:
                critical.append(step)

    critical.sort(key=lambda s: s.step_index)
    return critical


def _build_summary(
    result: Any,
    result_repr: str,
    lineage: List[dict],
    critical_steps: List[ExecutionStep],
    func_name: str,
) -> str:
    """Build a one-line human-readable summary."""
    if not lineage:
        return f"Result: {result_repr}"

    # Find the creation of the result variable
    creations = [l for l in lineage if l["event"] == "created"]
    changes = [l for l in lineage if l["event"] == "changed"]

    parts = []

    if func_name:
        parts.append(f"{func_name}() returned {result_repr}")

    if creations:
        c = creations[0]
        parts.append(f"because {c['variable']} was initialized to {c['value']} at line {c['line']}")

    if changes:
        last_change = changes[-1]
        parts.append(f"then {last_change['variable']} became {last_change['value']} at line {last_change['line']}")

    if not parts:
        parts.append(f"Result: {result_repr}")

    return " → ".join(parts) if len(parts) <= 3 else ". ".join(parts)


def explain_result_text(
    timeline: ExecutionTimeline,
    result: Any,
    func_name: str = "",
) -> str:
    """Produce a plain-text explanation suitable for terminal output."""
    info = explain_result(timeline, result, func_name)

    lines = []
    lines.append("=" * 60)
    lines.append("WHY THIS RESULT")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"  {info['summary']}")
    lines.append("")

    if info["lineage"]:
        lines.append("Variable Lineage:")
        for item in info["lineage"]:
            event = item["event"]
            var = item["variable"]
            val = item["value"]
            step = item["step"]
            line = item["line"]
            code = item.get("code", "")

            if event == "created":
                lines.append(f"  Step {step}: {var} = {val}  (created at line {line})")
                lines.append(f"           {code}")
            elif event == "changed":
                prev = item.get("prev_value", "?")
                lines.append(f"  Step {step}: {var}: {prev} → {val}  (line {line})")
                lines.append(f"           {code}")

    if info["critical_path"]:
        lines.append("")
        lines.append("Critical Path (steps that determined the result):")
        for cp in info["critical_path"]:
            lines.append(f"  Step {cp['step']}: {cp['code']}  ({', '.join(cp['what_changed'])})")

    lines.append("")
    lines.append(f"Total: {info['total_steps']} steps, {info['critical_steps']} critical")

    return "\n".join(lines)
