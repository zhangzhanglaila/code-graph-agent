"""Insight Summarizer — cognitive-level function understanding.

Three layers:
1. Pattern Detection  — accumulation, mapping, selection, ordering, search, dp
2. Phase Compression  — 30 steps → 3 phases (init, iteration, return)
3. Insight Generation  — one-sentence algorithm-level explanation
"""

from __future__ import annotations
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from dynamic.runtime.recorder import ExecutionTimeline, ExecutionStep


# ── Pattern definitions ──────────────────────────────────────────────

@dataclass
class Pattern:
    name: str
    confidence: float
    evidence: List[str]
    description: str


@dataclass
class Phase:
    name: str
    start_step: int
    end_step: int
    description: str
    key_variables: List[str]
    step_count: int


@dataclass
class Insight:
    one_liner: str
    algorithm_type: str
    patterns: List[Pattern]
    phases: List[Phase]
    explanation_levels: Dict[str, str]  # level1/level2/level3
    confidence: float


# ── Pattern detectors ────────────────────────────────────────────────

def _detect_patterns(timeline: ExecutionTimeline, result: Any) -> List[Pattern]:
    """Detect algorithmic patterns from execution timeline."""
    patterns: List[Pattern] = []
    steps = timeline.steps

    # Build variable change profiles
    var_changes: Dict[str, List[Tuple[int, str]]] = {}
    for step in steps:
        for name in step.changed_vars:
            if name not in var_changes:
                var_changes[name] = []
            snap = step.variables.get(name)
            if snap:
                var_changes[name].append((step.step_index, snap.value_repr))

    # 1. Accumulation pattern: variable repeatedly grows
    for var, changes in var_changes.items():
        if len(changes) >= 3:
            values = [v for _, v in changes]
            if _is_growing(values):
                patterns.append(Pattern(
                    name="accumulation",
                    confidence=0.9,
                    evidence=[f"{var} grew from {values[0]} to {values[-1]} over {len(values)} updates"],
                    description=f"Variable '{var}' accumulates values over iterations",
                ))

    # 2. Dict/List building pattern: container grows via append/update
    for step in steps:
        code = step.code_line.strip()
        for var in step.changed_vars:
            snap = step.variables.get(var)
            if snap and snap.value_type in ("dict", "list"):
                if ".append(" in code or "[" in code and "] =" in code:
                    patterns.append(Pattern(
                        name="building",
                        confidence=0.85,
                        evidence=[f"'{var}' modified at step {step.step_index}: {code}"],
                        description=f"Variable '{var}' is built incrementally",
                    ))
                    break

    # 3. Selection/filtering pattern: if-guard in loop
    loop_vars = set()
    filter_evidence = []
    for step in steps:
        code = step.code_line.strip()
        if code.startswith("for ") or code.startswith("while "):
            for name in step.variables:
                loop_vars.add(name)
        if code.startswith("if ") and loop_vars:
            filter_evidence.append(f"Filter at step {step.step_index}: {code}")

    if filter_evidence and len(filter_evidence) >= 2:
        patterns.append(Pattern(
            name="selection",
            confidence=0.8,
            evidence=filter_evidence[:3],
            description="Loop contains conditional filtering",
        ))

    # 4. Sorting pattern
    for step in steps:
        code = step.code_line.strip()
        if "sorted(" in code or ".sort(" in code:
            patterns.append(Pattern(
                name="ordering",
                confidence=0.95,
                evidence=[f"Sort operation at step {step.step_index}: {code}"],
                description="Data is sorted before use",
            ))

    # 5. DP/memoization pattern: dict used as cache
    for step in steps:
        code = step.code_line.strip()
        for var_name, snap in step.variables.items():
            if snap.value_type == "dict" and ("memo" in var_name.lower() or "cache" in var_name.lower()):
                patterns.append(Pattern(
                    name="memoization",
                    confidence=0.9,
                    evidence=[f"Cache '{var_name}' detected at step {step.step_index}"],
                    description=f"Dynamic programming with cache '{var_name}'",
                ))
                break

    # 6. Search pattern: looking for specific value
    for step in steps:
        code = step.code_line.strip()
        if "break" in code and step.changed_vars:
            patterns.append(Pattern(
                name="search",
                confidence=0.7,
                evidence=[f"Early exit at step {step.step_index}: {code}"],
                description="Search with early termination",
            ))

    # 7. Swap pattern: a, b = b, a
    for step in steps:
        code = step.code_line.strip()
        if re.match(r"\w+,\s*\w+\s*=\s*\w+,\s*\w+", code):
            patterns.append(Pattern(
                name="swap",
                confidence=0.85,
                evidence=[f"Variable swap at step {step.step_index}: {code}"],
                description="Variables are swapped each iteration",
            ))

    # 8. Mapping pattern: transform input → output
    for step in steps:
        code = step.code_line.strip()
        for func in ("map(", "lambda", "comprehension"):
            if func in code:
                patterns.append(Pattern(
                    name="transformation",
                    confidence=0.75,
                    evidence=[f"Transform at step {step.step_index}: {code}"],
                    description="Data is transformed from one form to another",
                ))
                break

    # Deduplicate by name, keep highest confidence
    seen: Dict[str, Pattern] = {}
    for p in patterns:
        if p.name not in seen or p.confidence > seen[p.name].confidence:
            seen[p.name] = p
    return list(seen.values())


def _is_growing(values: List[str]) -> bool:
    """Check if a sequence of repr values shows growth."""
    try:
        nums = []
        for v in values:
            cleaned = v.strip("[](){}").split(",")[0].strip()
            nums.append(float(cleaned))
        return len(nums) >= 2 and nums[-1] > nums[0]
    except (ValueError, IndexError):
        # Check dict growth
        if all(v.startswith("{") for v in values):
            return len(values[-1]) > len(values[0])
        # Check list growth
        if all(v.startswith("[") for v in values):
            return len(values[-1]) > len(values[0])
        return False


# ── Phase compression ────────────────────────────────────────────────

def _compress_phases(timeline: ExecutionTimeline) -> List[Phase]:
    """Compress N steps into 3-5 semantic phases."""
    steps = timeline.steps
    if not steps:
        return []

    phases: List[Phase] = []
    current_phase_start = 0
    current_phase_type = "init"

    # Classify each step
    step_types = []
    for step in steps:
        code = step.code_line.strip()
        if not code or code.startswith("#"):
            step_types.append("empty")
        elif any(code.startswith(k) for k in ("def ", "class ", "import ", "from ")):
            step_types.append("definition")
        elif any(code.startswith(k) for k in ("for ", "while ")):
            step_types.append("loop_header")
        elif code.startswith("if ") or code.startswith("elif "):
            step_types.append("condition")
        elif code.startswith("return "):
            step_types.append("return")
        elif step.new_vars and not step.changed_vars:
            step_types.append("init")
        elif step.changed_vars:
            step_types.append("mutation")
        else:
            step_types.append("other")

    # Phase boundaries: transitions between major phases
    for i, stype in enumerate(step_types):
        # Transition: init → iteration
        if stype == "loop_header" and current_phase_type == "init":
            phases.append(Phase(
                name="Initialization",
                start_step=current_phase_start,
                end_step=i - 1,
                description="Set up initial state and variables",
                key_variables=_get_phase_vars(steps[current_phase_start:i]),
                step_count=i - current_phase_start,
            ))
            current_phase_start = i
            current_phase_type = "iteration"

        # Transition: iteration → post-processing
        elif stype == "return" and current_phase_type == "iteration":
            phases.append(Phase(
                name="Iteration",
                start_step=current_phase_start,
                end_step=i - 1,
                description="Main computation loop",
                key_variables=_get_phase_vars(steps[current_phase_start:i]),
                step_count=i - current_phase_start,
            ))
            current_phase_start = i
            current_phase_type = "finalize"

        # Transition: init → finalize (no loop)
        elif stype == "return" and current_phase_type == "init":
            phases.append(Phase(
                name="Computation",
                start_step=current_phase_start,
                end_step=i - 1,
                description="Direct computation without iteration",
                key_variables=_get_phase_vars(steps[current_phase_start:i]),
                step_count=i - current_phase_start,
            ))
            current_phase_start = i
            current_phase_type = "finalize"

    # Last phase
    if current_phase_start < len(steps):
        name = {
            "init": "Computation",
            "iteration": "Iteration (continued)",
            "finalize": "Return",
        }.get(current_phase_type, "Finalization")

        phases.append(Phase(
            name=name,
            start_step=current_phase_start,
            end_step=len(steps) - 1,
            description=_describe_final_phase(steps[current_phase_start:]),
            key_variables=_get_phase_vars(steps[current_phase_start:]),
            step_count=len(steps) - current_phase_start,
        ))

    # If no phases detected, create a single phase
    if not phases:
        phases.append(Phase(
            name="Execution",
            start_step=0,
            end_step=len(steps) - 1,
            description="Single-pass execution",
            key_variables=_get_phase_vars(steps),
            step_count=len(steps),
        ))

    return phases


def _get_phase_vars(steps: List[ExecutionStep]) -> List[str]:
    """Get the most important variables in a phase."""
    var_importance: Dict[str, int] = {}
    for step in steps:
        for name in step.changed_vars:
            var_importance[name] = var_importance.get(name, 0) + 2
        for name in step.new_vars:
            var_importance[name] = var_importance.get(name, 0) + 3
    sorted_vars = sorted(var_importance.items(), key=lambda x: -x[1])
    return [name for name, _ in sorted_vars[:5]]


def _describe_final_phase(steps: List[ExecutionStep]) -> str:
    for step in steps:
        code = step.code_line.strip()
        if code.startswith("return "):
            return f"Return result: {code}"
    return "Finalization"


# ── Insight generation ───────────────────────────────────────────────

def _generate_insight(
    timeline: ExecutionTimeline,
    result: Any,
    func_name: str,
    patterns: List[Pattern],
    phases: List[Phase],
) -> str:
    """Generate a one-sentence cognitive-level insight."""
    result_repr = repr(result)
    if len(result_repr) > 80:
        result_repr = result_repr[:77] + "..."

    # Build insight from patterns
    parts = []

    # What does it produce?
    result_type = type(result).__name__
    if isinstance(result, dict):
        parts.append(f"builds a dictionary ({len(result)} keys)")
    elif isinstance(result, list):
        parts.append(f"builds a list ({len(result)} items)")
    elif isinstance(result, (int, float)):
        parts.append(f"computes {result_repr}")
    elif isinstance(result, str):
        parts.append(f"produces a string")
    elif isinstance(result, tuple):
        parts.append(f"returns a tuple")
    else:
        parts.append(f"returns {result_type}")

    # How does it do it?
    pattern_names = [p.name for p in patterns]
    if "memoization" in pattern_names:
        parts.append("using dynamic programming with memoization")
    elif "accumulation" in pattern_names and "selection" in pattern_names:
        parts.append("by accumulating filtered values")
    elif "accumulation" in pattern_names:
        parts.append("by iteratively accumulating values")
    elif "building" in pattern_names and "selection" in pattern_names:
        parts.append("by building a collection from filtered inputs")
    elif "building" in pattern_names:
        parts.append("by incrementally building a data structure")
    elif "ordering" in pattern_names:
        parts.append("after sorting the input")
    elif "search" in pattern_names:
        parts.append("through iterative search")
    elif "swap" in pattern_names:
        parts.append("using variable swapping across iterations")
    else:
        # Fallback: describe phases
        if len(phases) == 3:
            parts.append(f"in {phases[1].name.lower()}")
        elif len(phases) == 2:
            parts.append(f"through {phases[0].name.lower()} and {phases[1].name.lower()}")

    # What's the data source?
    init_phase = next((p for p in phases if p.name == "Initialization"), None)
    if init_phase and init_phase.key_variables:
        source_vars = [v for v in init_phase.key_variables[:2] if v not in ("i", "j", "k", "n")]
        if source_vars:
            parts.append(f"from {', '.join(source_vars)}")

    if func_name:
        return f"{func_name}() {' '.join(parts)}"
    return " ".join(parts).capitalize()


def _generate_level_explanations(
    timeline: ExecutionTimeline,
    result: Any,
    func_name: str,
    patterns: List[Pattern],
    phases: List[Phase],
) -> Dict[str, str]:
    """Generate three levels of explanation."""
    result_repr = repr(result)
    if len(result_repr) > 100:
        result_repr = result_repr[:97] + "..."

    # Level 1: Step-by-step (what happened)
    level1_lines = []
    for step in timeline.steps:
        code = step.code_line.strip()
        if not code:
            continue
        change_info = ""
        if step.changed_vars:
            change_info = f"  [{', '.join(step.changed_vars)} changed]"
        level1_lines.append(f"  Step {step.step_index}: {code}{change_info}")
    level1 = f"Execution trace ({len(timeline.steps)} steps):\n" + "\n".join(level1_lines[:20])
    if len(level1_lines) > 20:
        level1 += f"\n  ... ({len(level1_lines) - 20} more steps)"

    # Level 2: Pattern-level (how it works)
    level2_lines = []
    for phase in phases:
        vars_str = ", ".join(phase.key_variables[:3]) if phase.key_variables else ""
        level2_lines.append(f"  Phase: {phase.name} ({phase.step_count} steps)")
        level2_lines.append(f"    {phase.description}")
        if vars_str:
            level2_lines.append(f"    Key variables: {vars_str}")
    level2_lines.append("")
    for p in patterns:
        level2_lines.append(f"  Pattern: {p.name} (confidence {p.confidence:.0%})")
        level2_lines.append(f"    {p.description}")
        if p.evidence:
            level2_lines.append(f"    Evidence: {p.evidence[0]}")
    level2 = f"Algorithm structure ({len(phases)} phases, {len(patterns)} patterns):\n" + "\n".join(level2_lines)

    # Level 3: Cognitive insight (why it works)
    insight = _generate_insight(timeline, result, func_name, patterns, phases)
    level3 = f"Insight: {insight}"

    return {
        "level1_trace": level1,
        "level2_pattern": level2,
        "level3_insight": level3,
    }


# ── Public API ───────────────────────────────────────────────────────

def summarize_insight(
    timeline: ExecutionTimeline,
    result: Any,
    func_name: str = "",
) -> Insight:
    """Produce cognitive-level insight from execution timeline."""
    patterns = _detect_patterns(timeline, result)
    phases = _compress_phases(timeline)
    one_liner = _generate_insight(timeline, result, func_name, patterns, phases)
    levels = _generate_level_explanations(timeline, result, func_name, patterns, phases)

    # Determine algorithm type
    algo_type = "general"
    pattern_names = {p.name for p in patterns}
    if "memoization" in pattern_names:
        algo_type = "dynamic_programming"
    elif "accumulation" in pattern_names and "selection" in pattern_names:
        algo_type = "filter_accumulate"
    elif "accumulation" in pattern_names:
        algo_type = "accumulate"
    elif "building" in pattern_names:
        algo_type = "construction"
    elif "search" in pattern_names:
        algo_type = "search"
    elif "ordering" in pattern_names:
        algo_type = "sort_transform"

    # Confidence from pattern strengths
    if patterns:
        confidence = max(p.confidence for p in patterns)
    else:
        confidence = 0.5

    return Insight(
        one_liner=one_liner,
        algorithm_type=algo_type,
        patterns=patterns,
        phases=phases,
        explanation_levels=levels,
        confidence=confidence,
    )


def insight_text(insight: Insight) -> str:
    """Format insight as human-readable text."""
    lines = []
    lines.append("=" * 60)
    lines.append("INSIGHT")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"  {insight.one_liner}")
    lines.append("")
    lines.append(f"  Algorithm type: {insight.algorithm_type}")
    lines.append(f"  Confidence: {insight.confidence:.0%}")
    lines.append("")

    if insight.phases:
        lines.append("Phases:")
        for p in insight.phases:
            lines.append(f"  {p.name} (steps {p.start_step}-{p.end_step}, {p.step_count} steps)")
            lines.append(f"    {p.description}")
        lines.append("")

    if insight.patterns:
        lines.append("Patterns detected:")
        for p in insight.patterns:
            lines.append(f"  [{p.name}] {p.description} ({p.confidence:.0%})")
        lines.append("")

    # Level 3 insight
    lines.append(insight.explanation_levels.get("level3_insight", ""))

    return "\n".join(lines)
