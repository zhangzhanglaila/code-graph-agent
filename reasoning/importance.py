"""Hybrid importance scoring for execution steps.

Combines three signals:
- structural (0.4): AST-based code structure detection
- dynamic (0.4): value jumps, type changes, var count
- llm (0.2): semantic signal from LLM (if available)

Output: score 0-1 + reasons array
"""

from __future__ import annotations
import ast
import re
from typing import Any, Dict, List, Optional, Tuple


# ── Helpers ─────────────────────────────────────────────────────────

def _var_in_code(var: str, code: str) -> bool:
    """Check if var appears as a whole word in code (not substring)."""
    return bool(re.search(r'\b' + re.escape(var) + r'\b', code))


# ── Structural signals (AST-based) ──────────────────────────────────

def structural_score(code_line: str) -> Tuple[float, List[str]]:
    """Score based on AST node type. Returns (score, reasons)."""
    reasons = []
    score = 0.0

    # Try parsing as a statement
    node = _parse_stmt(code_line)
    if node is None:
        return 0.0, []

    # Walk AST and classify
    for n in ast.walk(node):
        if isinstance(n, ast.If):
            if _looks_like_base_case(n):
                reasons.append("base_case")
                score = max(score, 0.8)
            elif _looks_like_bounds_check(n):
                reasons.append("bounds_check")
                score = max(score, 0.7)
            else:
                reasons.append("branch")
                score = max(score, 0.6)
        elif isinstance(n, ast.For):
            reasons.append("loop_entry")
            score = max(score, 0.6)
        elif isinstance(n, ast.While):
            reasons.append("loop_entry")
            score = max(score, 0.6)
        elif isinstance(n, ast.Break):
            reasons.append("loop_break")
            score = max(score, 0.55)
        elif isinstance(n, ast.Continue):
            reasons.append("loop_continue")
            score = max(score, 0.45)
        elif isinstance(n, ast.Return):
            reasons.append("return")
            score = max(score, 0.65)
        elif isinstance(n, ast.Raise):
            reasons.append("raise")
            score = max(score, 0.6)
        elif isinstance(n, (ast.Try, ast.ExceptHandler)):
            reasons.append("error_boundary")
            score = max(score, 0.4)
        elif isinstance(n, ast.Yield):
            reasons.append("generator")
            score = max(score, 0.45)
        elif isinstance(n, ast.Assign):
            if not reasons:
                reasons.append("assignment")
                score = max(score, 0.15)
        elif isinstance(n, ast.AugAssign):
            reasons.append("mutation")
            score = max(score, 0.35)
        elif isinstance(n, ast.Call):
            func_name = _get_call_name(n)
            if func_name and func_name not in _BUILTIN_CALLS:
                if not any(r in reasons for r in ("branch", "loop_entry", "return", "raise")):
                    reasons.append("function_call")
                    score = max(score, 0.15)

    return min(score, 1.0), list(set(reasons))


def _parse_stmt(code_line: str) -> Optional[ast.AST]:
    """Parse a single line as a Python statement."""
    code_line = code_line.strip()
    if not code_line or code_line.startswith('#'):
        return None
    try:
        tree = ast.parse(code_line)
        if tree.body:
            return tree.body[0]
    except SyntaxError:
        pass

    # Compound statements (if/for/while/try) need a body
    # Add a dummy pass to make them parseable
    for prefix in ('if', 'elif', 'for', 'while', 'try', 'except', 'else', 'finally'):
        if code_line.startswith(prefix):
            try:
                tree = ast.parse(f"def _():\n    {code_line}\n        pass")
                if tree.body and hasattr(tree.body[0], 'body') and tree.body[0].body:
                    return tree.body[0].body[0]
            except SyntaxError:
                pass
            try:
                tree = ast.parse(f"def _():\n    {code_line}\n    pass")
                if tree.body and hasattr(tree.body[0], 'body') and tree.body[0].body:
                    return tree.body[0].body[0]
            except SyntaxError:
                pass

    # General fallback: wrap in function
    try:
        tree = ast.parse(f"def _():\n    {code_line}")
        if tree.body and hasattr(tree.body[0], 'body') and tree.body[0].body:
            return tree.body[0].body[0]
    except SyntaxError:
        pass
    return None


def _get_call_name(node: ast.Call) -> Optional[str]:
    """Extract function name from a Call node."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


_BASE_CASE_OPS = (ast.LtE, ast.Lt, ast.Eq)
_BOUNDS_CHECK_OPS = (ast.GtE, ast.Gt)


def _looks_like_base_case(node: ast.If) -> bool:
    """Detect common base case patterns: if len(x) <= 1, if x == 0, if not x."""
    test = node.test
    # `not x` — guard clause
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return True
    if isinstance(test, ast.BoolOp):
        # `if not x and ...` or `if not x or ...`
        for v in test.values:
            if isinstance(v, ast.UnaryOp) and isinstance(v.op, ast.Not):
                return True
    if not isinstance(test, ast.Compare):
        return False
    # len(x) <= 1, len(x) == 0, len(x) < 1
    if isinstance(test.left, ast.Call) and _get_call_name(test.left) == 'len':
        for op, comp in zip(test.ops, test.comparators):
            if isinstance(op, _BASE_CASE_OPS):
                if isinstance(comp, ast.Constant) and isinstance(comp.value, int) and comp.value <= 1:
                    return True
    # x == 0, x == None, n <= 1
    if isinstance(test.left, ast.Name):
        for op, comp in zip(test.ops, test.comparators):
            if isinstance(op, (ast.LtE, ast.Lt)) and isinstance(comp, ast.Constant):
                if isinstance(comp.value, int) and comp.value <= 1:
                    return True
            if isinstance(op, ast.Eq) and isinstance(comp, ast.Constant):
                if comp.value == 0 or comp.value is None:
                    return True
    return False


def _looks_like_bounds_check(node: ast.If) -> bool:
    """Detect bounds check patterns: if i >= len(arr), if idx > len(arr)."""
    test = node.test
    if not isinstance(test, ast.Compare):
        return False
    # i >= len(x), idx > len(x)
    for op, comp in zip(test.ops, test.comparators):
        if isinstance(op, _BOUNDS_CHECK_OPS):
            if isinstance(comp, ast.Call) and _get_call_name(comp) == 'len':
                return True
    # len(x) <= i  (reversed form)
    if isinstance(test.left, ast.Call) and _get_call_name(test.left) == 'len':
        for op in test.ops:
            if isinstance(op, (ast.LtE, ast.Lt)):
                return True
    return False


_BUILTIN_CALLS = {
    'print', 'range', 'len', 'int', 'str', 'float', 'list', 'dict',
    'set', 'tuple', 'type', 'isinstance', 'abs', 'max', 'min', 'sum',
    'sorted', 'reversed', 'enumerate', 'zip', 'map', 'filter',
    'True', 'False', 'None', 'bool', 'hasattr', 'getattr', 'setattr',
}


# ── Dynamic signals (value-aware) ───────────────────────────────────

def dynamic_score(
    changed_vars: List[str],
    new_vars: List[str],
    all_vars: Dict[str, Any],
    prev_vars: Optional[Dict[str, Any]] = None,
) -> Tuple[float, List[str]]:
    """Score based on execution state changes. Returns (score, reasons)."""
    reasons = []
    score = 0.0

    n_changed = len(changed_vars)
    n_new = len(new_vars)

    # New variables (first occurrence is meaningful)
    if n_new > 0:
        score += min(n_new * 0.1, 0.3)
        if n_new >= 3:
            reasons.append(f"{n_new}_new_vars")
        else:
            reasons.append("new_var")

    # Changed variables — but weighted by VALUE DELTA, not just count
    if n_changed > 0 and prev_vars:
        max_delta_score = 0.0
        for var in changed_vars:
            delta, delta_reason = _compute_value_delta(
                var, all_vars, prev_vars
            )
            max_delta_score = max(max_delta_score, delta)
            if delta_reason and delta_reason not in reasons:
                reasons.append(delta_reason)

        # Use the max delta as the dynamic signal for changes
        score += max_delta_score

        # If many vars changed, that's also meaningful
        if n_changed >= 3:
            reasons.append(f"{n_changed}_vars_changed")
            score += 0.1
    elif n_changed > 0:
        # No prev_vars available, fall back to count
        score += min(n_changed * 0.1, 0.3)
        reasons.append("state_change")

    return min(score, 1.0), reasons


def _compute_value_delta(
    var_name: str,
    all_vars: Dict[str, Any],
    prev_vars: Dict[str, Any],
) -> Tuple[float, Optional[str]]:
    """Compute the significance of a value change for a single variable.

    Returns (delta_score, reason).
    """
    if var_name not in prev_vars or var_name not in all_vars:
        return 0.0, None

    prev_entry = prev_vars[var_name]
    curr_entry = all_vars[var_name]

    prev_val = prev_entry.get("value") if isinstance(prev_entry, dict) else prev_entry
    curr_val = curr_entry.get("value") if isinstance(curr_entry, dict) else curr_entry
    prev_type = prev_entry.get("type") if isinstance(prev_entry, dict) else type(prev_val).__name__
    curr_type = curr_entry.get("type") if isinstance(curr_entry, dict) else type(curr_val).__name__

    # Type change — very significant
    if prev_type != curr_type:
        return 0.4, "type_change"

    # Boolean flip — check before numeric (bool is numeric in Python)
    if isinstance(prev_val, bool) and isinstance(curr_val, bool):
        if prev_val != curr_val:
            return 0.4, "boolean_flip"
        return 0.0, None

    # Try numeric comparison
    try:
        old_n = float(prev_val)
        new_n = float(curr_val)
        if old_n == 0 and new_n == 0:
            return 0.0, None
        denom = max(abs(old_n), 1)
        ratio = abs(new_n - old_n) / denom

        if ratio > 10:
            return 0.45, "large_value_jump"
        elif ratio > 2:
            return 0.3, "value_jump"
        elif ratio > 0.5:
            return 0.15, "value_change"
        else:
            return 0.05, None
    except (ValueError, TypeError):
        pass

    # String length change
    if isinstance(prev_val, str) and isinstance(curr_val, str):
        len_diff = abs(len(curr_val) - len(prev_val))
        if len_diff > 10:
            return 0.2, "string_growth"
        elif len_diff > 0:
            return 0.05, None

    # Collection size change (heuristic from repr)
    if isinstance(prev_val, str) and isinstance(curr_val, str):
        prev_count = prev_val.count(',')
        curr_count = curr_val.count(',')
        if abs(curr_count - prev_count) >= 2:
            return 0.25, "collection_growth"

    return 0.05, None


# ── LLM signal mapping ─────────────────────────────────────────────

def llm_score(importance_label: str, turning_point: bool = False) -> Tuple[float, List[str]]:
    """Map LLM importance label to score. Returns (score, reasons)."""
    reasons = []
    base = {"high": 0.8, "medium": 0.5, "low": 0.2}.get(importance_label, 0.5)

    if turning_point:
        base = max(base, 0.85)
        reasons.append("turning_point")

    if importance_label == "high":
        reasons.append("llm_high")
    elif importance_label == "low":
        reasons.append("llm_low")

    return base, reasons


# ── Future impact (propagation awareness) ───────────────────────────

def future_impact_score(
    changed_vars: List[str],
    future_steps: List[Dict[str, Any]],
    lookahead: int = 3,
) -> Tuple[float, List[str], List[int]]:
    """Score based on whether changed vars are used in future steps.

    A variable assignment that influences downstream steps is more important.
    Returns (score_boost, reasons, affected_step_indices).
    """
    if not changed_vars or not future_steps:
        return 0.0, [], []

    changed_set = set(changed_vars)
    impact_depth = 0
    affected = []

    for i, step in enumerate(future_steps[:lookahead]):
        if i >= lookahead:
            break
        # Check if any future step references these vars in its code or changed list
        step_changed = set(step.get("changed", []))
        step_new = set(step.get("new_vars", []))
        step_code = step.get("code", "")

        hit = False
        # Direct reference: var appears in future step's changed/new vars
        overlap = changed_set & (step_changed | step_new)
        if overlap:
            hit = True

        # Code-level reference: var name appears in future code (whole word)
        # Skip for single-char vars to avoid false positives (e.g. loop vars)
        if not hit:
            for var in changed_set:
                if len(var) >= 2 and _var_in_code(var, step_code):
                    hit = True
                    break

        if hit:
            impact_depth = max(impact_depth, i + 1)
            # Record the actual step index if available
            step_idx = step.get("index", i + 1)
            if step_idx not in affected:
                affected.append(step_idx)

    if impact_depth >= 3:
        return 0.25, ["future_impact"], affected
    elif impact_depth >= 2:
        return 0.2, ["future_impact"], affected
    elif impact_depth >= 1:
        return 0.15, ["future_impact"], affected
    return 0.0, [], []


# ── Hybrid blend ────────────────────────────────────────────────────

def compute_importance(
    code_line: str,
    changed_vars: List[str],
    new_vars: List[str],
    all_vars: Dict[str, Any],
    prev_vars: Optional[Dict[str, Any]] = None,
    llm_importance: Optional[str] = None,
    llm_turning_point: bool = False,
    future_steps: Optional[List[Dict[str, Any]]] = None,
) -> dict:
    """Compute hybrid importance score for a step.

    Returns:
        {
            "score": float 0-1,
            "label": "high" | "medium" | "low",
            "reasons": [str],
            "signals": {
                "structural": float,
                "dynamic": float,
                "llm": float,
            }
        }
    """
    s_score, s_reasons = structural_score(code_line)
    d_score, d_reasons = dynamic_score(changed_vars, new_vars, all_vars, prev_vars)
    f_score, f_reasons, affects = future_impact_score(changed_vars, future_steps or [])

    has_llm = llm_importance is not None
    if has_llm:
        l_score, l_reasons = llm_score(llm_importance, llm_turning_point)
        final_score = 0.4 * s_score + 0.4 * d_score + 0.2 * l_score
    else:
        l_score = 0.0
        l_reasons = []
        # No LLM: weight structural and dynamic more heavily
        final_score = 0.55 * s_score + 0.45 * d_score

    # Boost: if both structural and dynamic agree, signal is stronger
    if s_score >= 0.3 and d_score >= 0.2:
        final_score = min(final_score + 0.15, 1.0)
    # Boost: strong dynamic signal alone (e.g. large value jump) is meaningful
    elif d_score >= 0.4:
        final_score = min(final_score + 0.1, 1.0)

    # Boost: future impact — changed vars used downstream
    if f_score > 0:
        final_score = min(final_score + f_score, 1.0)

    if final_score >= 0.55:
        label = "high"
    elif final_score >= 0.30:
        label = "medium"
    else:
        label = "low"

    all_reasons = s_reasons + d_reasons + l_reasons + f_reasons

    explanation = explain_importance(all_reasons, code_line, changed_vars)

    return {
        "score": round(final_score, 3),
        "label": label,
        "reasons": list(dict.fromkeys(all_reasons)),  # dedupe preserving order
        "explanation": explanation,
        "affects": affects,
        "signals": {
            "structural": round(s_score, 3),
            "dynamic": round(d_score, 3),
            "llm": round(l_score, 3),
            "future": round(f_score, 3),
        },
    }


# ── Natural language explanation ────────────────────────────────────

_REASON_TEMPLATES: Dict[str, str] = {
    # Structural
    "base_case": "This is a base case that stops recursion and prevents infinite calls.",
    "bounds_check": "This is a bounds check that guards against out-of-range access.",
    "branch": "This branch changes the execution path based on a condition.",
    "loop_entry": "This loop drives the main iteration — each pass processes one unit of work.",
    "loop_break": "This break exits the loop early, which changes how many iterations run.",
    "loop_continue": "This continue skips the rest of the current iteration.",
    "return": "This return produces the final (or intermediate) result of the function.",
    "raise": "This raises an exception, interrupting normal execution flow.",
    "error_boundary": "This try/except block catches errors and determines recovery behavior.",
    "generator": "This yield produces a value lazily, controlling when computation happens.",
    "function_call": "This calls a function that performs significant work.",
    # Dynamic
    "new_var": "A new variable is introduced here.",
    "large_value_jump": "The value changes dramatically — a major state shift.",
    "value_jump": "The value changes significantly.",
    "value_change": "The value is updated.",
    "type_change": "The type changes — this restructures how data is represented.",
    "boolean_flip": "A boolean flag flips — this changes the program's understanding of state.",
    "string_growth": "A string grows significantly — data is being accumulated.",
    "collection_growth": "A collection grows — elements are being added.",
    "state_change": "Program state changes here.",
    "mutation": "A variable is mutated in place.",
    # Future impact
    "future_impact": "This step's result is used in the next few steps — it has downstream influence.",
    # LLM signals
    "turning_point": "This is a turning point where the algorithm's behavior fundamentally shifts.",
    "llm_high": "The AI model identifies this as a critical moment.",
    "llm_low": "The AI model considers this a minor step.",
}


def explain_importance(
    reasons: List[str],
    code_line: str,
    changed_vars: Optional[List[str]] = None,
) -> str:
    """Convert reason tags into a natural language explanation.

    Combines templates into a coherent paragraph, injecting variable names
    where relevant.
    """
    if not reasons:
        return "This step performs a routine operation."

    parts = []
    seen = set()
    var_str = ", ".join(changed_vars[:3]) if changed_vars else ""

    # Priority order: semantic > dynamic > generic state_change
    _PRIORITY = {
        "base_case": 0, "bounds_check": 0, "return": 0, "turning_point": 0,
        "branch": 1, "loop_entry": 1, "loop_break": 1, "raise": 1,
        "future_impact": 2,
        "large_value_jump": 3, "value_jump": 3, "type_change": 3, "boolean_flip": 3,
        "new_var": 4, "string_growth": 4, "collection_growth": 4,
        "mutation": 4, "function_call": 4,
        "state_change": 9, "value_change": 9,
    }
    sorted_reasons = sorted(reasons, key=lambda r: _PRIORITY.get(r, 5))

    for reason in sorted_reasons:
        if reason in seen:
            continue
        seen.add(reason)

        template = _REASON_TEMPLATES.get(reason)
        if not template:
            # Handle composite reasons like "3_new_vars", "4_vars_changed"
            if "_new_vars" in reason:
                n = reason.split("_")[0]
                template = f"{n} new variables are introduced at once — this is a setup step."
            elif "_vars_changed" in reason:
                n = reason.split("_")[0]
                template = f"{n} variables change simultaneously — this is a major state update."
            else:
                continue

        # Inject variable name for dynamic signals
        if var_str and reason in ("large_value_jump", "value_jump", "type_change",
                                   "boolean_flip", "string_growth", "collection_growth"):
            template = template.replace("The value", f"'{var_str}' value")
            template = template.replace("The type", f"'{var_str}' type")

        parts.append(template)

    if not parts:
        return "This step performs a routine operation."

    # Keep it concise: max 2 sentences
    if len(parts) == 1:
        return parts[0]
    return parts[0] + " " + parts[1]
