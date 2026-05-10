"""Step Explainer — generates per-step explanations for execution traces."""

from __future__ import annotations
from typing import Any, Dict, List


def explain_steps(steps_data: List[Dict], func_name: str = "", **kwargs) -> List[Dict]:
    """Generate explanations for each step in the execution trace.

    Returns a list of explanation dicts, one per step.
    """
    explanations = []
    for i, step in enumerate(steps_data):
        code = step.get("code", "").strip()
        line = step.get("line", 0)
        func = step.get("func", func_name)
        vars_changed = step.get("changed_vars", [])
        depth = step.get("depth", 0)

        # Build a simple explanation based on the code
        explanation = _explain_line(code, step, i, len(steps_data))
        explanations.append({
            "step": i,
            "line": line,
            "code": code,
            "explanation": explanation,
            "func": func,
            "depth": depth,
        })

    return explanations


def explain_step_focused(
    steps_data: List[Dict],
    step_index: int,
    window_before: int = 2,
    window_after: int = 2,
    **kwargs,
) -> Dict:
    """Focused explanation for a specific step with context window."""
    if step_index < 0 or step_index >= len(steps_data):
        return {"error": f"Step {step_index} out of range"}

    step = steps_data[step_index]
    code = step.get("code", "").strip()

    # Get context window
    start = max(0, step_index - window_before)
    end = min(len(steps_data), step_index + window_after + 1)
    context = steps_data[start:end]

    return {
        "step": step_index,
        "code": code,
        "explanation": _explain_line(code, step, step_index, len(steps_data)),
        "context": [
            {"step": s.get("index", j + start), "code": s.get("code", "")}
            for j, s in enumerate(context)
        ],
    }


def _explain_line(code: str, step: Dict, index: int, total: int) -> str:
    """Generate a simple explanation for a line of code."""
    code_lower = code.lower().strip()

    if code_lower.startswith("def "):
        return f"Function definition: {code.split('(')[0].replace('def ', '')}"
    elif code_lower.startswith("return"):
        return f"Returns the computed result to the caller"
    elif code_lower.startswith("for "):
        return f"Loop iteration — repeats the block for each element"
    elif code_lower.startswith("while "):
        return f"Conditional loop — repeats while condition is true"
    elif code_lower.startswith("if ") or code_lower.startswith("elif "):
        return f"Conditional branch — takes this path when condition is true"
    elif code_lower.startswith("else"):
        return f"Else branch — executes when previous conditions were false"
    elif "=" in code and not code.startswith(" ") and not code.startswith("return"):
        var = code.split("=")[0].strip()
        return f"Assigns a value to `{var}`"
    elif ".append(" in code_lower:
        return f"Appends an element to a list"
    elif "print(" in code_lower:
        return f"Outputs a value to console"
    else:
        return f"Step {index + 1} of {total}"
