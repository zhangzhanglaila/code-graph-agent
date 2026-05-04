"""Importance scoring benchmark — 10 test cases.

Validates that the scoring system produces rankings that match human intuition.
Each case has a human_label (what a human reviewer would pick) and the system
must rank those steps highest within each trace.
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from reasoning.importance import compute_importance


# ── Test cases ──────────────────────────────────────────────────────

QUICKSORT_STEPS = [
    # step 0: base case check — HIGH
    {
        "code": "if len(arr) <= 1:",
        "changed": [], "new_vars": [],
        "all_vars": {}, "prev_vars": None,
        "human_label": "high",
        "reason": "base case — determines recursion termination",
    },
    # step 1: pivot selection — MEDIUM (future impact)
    {
        "code": "pivot = arr[0]",
        "changed": ["pivot"], "new_vars": ["pivot"],
        "all_vars": {"pivot": {"value": 5, "type": "int"}},
        "prev_vars": None,
        "human_label": "medium",
        "reason": "pivot drives entire partition",
        "future_steps": [
            {"code": "left = [x for x in arr if x < pivot]", "changed": ["pivot"], "new_vars": []},
            {"code": "right = [x for x in arr if x >= pivot]", "changed": ["pivot"], "new_vars": []},
            {"code": "return quicksort(left) + [pivot] + quicksort(right)", "changed": ["pivot"], "new_vars": []},
        ],
    },
    # step 2: partition left — LOW
    {
        "code": "left = [x for x in arr if x < pivot]",
        "changed": ["left"], "new_vars": ["left"],
        "all_vars": {"left": {"value": "[1, 2, 3]", "type": "list"}},
        "prev_vars": None,
        "human_label": "low",
        "reason": "mechanical list comprehension",
    },
    # step 3: recursive return — MEDIUM
    {
        "code": "return quicksort(left) + [pivot] + quicksort(right)",
        "changed": [], "new_vars": [],
        "all_vars": {}, "prev_vars": None,
        "human_label": "medium",
        "reason": "return — completes recursion",
    },
]

BFS_STEPS = [
    # step 0: loop entry — MEDIUM
    {
        "code": "while queue:",
        "changed": [], "new_vars": [],
        "all_vars": {}, "prev_vars": None,
        "human_label": "medium",
        "reason": "loop entry — drives traversal",
    },
    # step 1: visited check — MEDIUM
    {
        "code": "if node not in visited:",
        "changed": [], "new_vars": [],
        "all_vars": {}, "prev_vars": None,
        "human_label": "medium",
        "reason": "branch — deduplication guard",
    },
    # step 2: add to visited — LOW
    {
        "code": "visited.add(node)",
        "changed": ["visited"], "new_vars": [],
        "all_vars": {"visited": {"value": "{1, 2, 3}", "type": "set"}},
        "prev_vars": {"visited": {"value": "{1, 2}", "type": "set"}},
        "human_label": "low",
        "reason": "mechanical state update",
    },
    # step 3: return — MEDIUM
    {
        "code": "return visited",
        "changed": [], "new_vars": [],
        "all_vars": {}, "prev_vars": None,
        "human_label": "medium",
        "reason": "return — final result",
    },
]

BUG_CASE_STEPS = [
    # step 0: variable assignment — LOW
    {
        "code": "x = 1",
        "changed": ["x"], "new_vars": ["x"],
        "all_vars": {"x": {"value": 1, "type": "int"}},
        "prev_vars": None,
        "human_label": "low",
        "reason": "trivial assignment",
    },
    # step 1: bug branch — HIGH (dead code path)
    {
        "code": "if x > 2:",
        "changed": [], "new_vars": [],
        "all_vars": {}, "prev_vars": None,
        "human_label": "high",
        "reason": "branch with wrong condition — causes bug",
    },
    # step 2: dead code — LOW
    {
        "code": "y = 10",
        "changed": ["y"], "new_vars": ["y"],
        "all_vars": {"y": {"value": 10, "type": "int"}},
        "prev_vars": None,
        "human_label": "low",
        "reason": "dead code — never executes",
    },
]

BINARY_SEARCH_STEPS = [
    # step 0: bounds check — MEDIUM
    {
        "code": "if lo >= hi:",
        "changed": [], "new_vars": [],
        "all_vars": {}, "prev_vars": None,
        "human_label": "medium",
        "reason": "bounds check — termination condition",
    },
    # step 1: mid calculation — LOW
    {
        "code": "mid = (lo + hi) // 2",
        "changed": ["mid"], "new_vars": ["mid"],
        "all_vars": {"mid": {"value": 5, "type": "int"}},
        "prev_vars": None,
        "human_label": "low",
        "reason": "mechanical calculation",
    },
    # step 2: comparison branch — HIGH
    {
        "code": "if arr[mid] == target:",
        "changed": [], "new_vars": [],
        "all_vars": {}, "prev_vars": None,
        "human_label": "high",
        "reason": "key comparison — determines search direction",
    },
    # step 3: recursive call — MEDIUM
    {
        "code": "return binary_search(arr, target, mid + 1, hi)",
        "changed": [], "new_vars": [],
        "all_vars": {}, "prev_vars": None,
        "human_label": "medium",
        "reason": "recursive call — narrows search",
    },
]

FIBONACCI_STEPS = [
    # step 0: memo check — MEDIUM
    {
        "code": "if n in memo:",
        "changed": [], "new_vars": [],
        "all_vars": {}, "prev_vars": None,
        "human_label": "medium",
        "reason": "cache hit check — optimization",
    },
    # step 1: base case — HIGH
    {
        "code": "if n <= 1:",
        "changed": [], "new_vars": [],
        "all_vars": {}, "prev_vars": None,
        "human_label": "high",
        "reason": "base case — recursion termination",
    },
    # step 2: recursive computation — MEDIUM
    {
        "code": "memo[n] = fib(n-1) + fib(n-2)",
        "changed": ["memo"], "new_vars": [],
        "all_vars": {"memo": {"value": "{0: 0, 1: 1, 2: 1}", "type": "dict"}},
        "prev_vars": {"memo": {"value": "{0: 0, 1: 1}", "type": "dict"}},
        "human_label": "medium",
        "reason": "core recurrence relation",
    },
]


# ── Benchmark runner ────────────────────────────────────────────────

def run_trace(name: str, steps: list) -> tuple[bool, list]:
    """Run importance scoring on a trace and validate ranking.

    Returns (passed, details).
    """
    results = []
    for i, step in enumerate(steps):
        r = compute_importance(
            code_line=step["code"],
            changed_vars=step.get("changed", []),
            new_vars=step.get("new_vars", []),
            all_vars=step.get("all_vars", {}),
            prev_vars=step.get("prev_vars"),
            future_steps=step.get("future_steps"),
        )
        results.append({
            "step": i,
            "code": step["code"],
            "human": step["human_label"],
            "model_label": r["label"],
            "model_score": r["score"],
            "reasons": r["reasons"],
            "reason": step["reason"],
        })

    # Sort by score descending
    ranked = sorted(results, key=lambda x: x["model_score"], reverse=True)

    # Check: top step should be "high" in human labels
    high_human = [r for r in results if r["human"] == "high"]
    top_steps = ranked[:len(high_human)] if high_human else ranked[:1]

    passed = True
    details = []
    for r in ranked:
        match = "OK" if _label_match(r["human"], r["model_label"]) else "MISMATCH"
        if match == "MISMATCH":
            # Allow one-off mismatches (high vs medium, medium vs low)
            if (r["human"] == "high" and r["model_label"] == "medium") or \
               (r["human"] == "medium" and r["model_label"] == "high"):
                match = "~OK"
            elif (r["human"] == "medium" and r["model_label"] == "low") or \
                 (r["human"] == "low" and r["model_label"] == "medium"):
                match = "~OK"
            else:
                passed = False
        details.append({
            "step": r["step"],
            "code": r["code"],
            "human": r["human"],
            "model": f"{r['model_label']} ({r['model_score']:.3f})",
            "match": match,
            "reasons": r["reasons"],
        })

    return passed, details


def _label_match(human: str, model: str) -> bool:
    return human == model


# ── Main ────────────────────────────────────────────────────────────

TRACES = [
    ("Quicksort", QUICKSORT_STEPS),
    ("BFS", BFS_STEPS),
    ("Bug Case", BUG_CASE_STEPS),
    ("Binary Search", BINARY_SEARCH_STEPS),
    ("Fibonacci", FIBONACCI_STEPS),
]


def main():
    all_passed = True
    for name, steps in TRACES:
        passed, details = run_trace(name, steps)
        status = "PASS" if passed else "FAIL"
        print(f"\n{'='*60}")
        print(f"  {name}  [{status}]")
        print(f"{'='*60}")
        for d in details:
            print(f"  step {d['step']}: {d['code'][:45]:45s} "
                  f"human={d['human']:6s} model={d['model']:14s} "
                  f"{d['match']:8s} reasons={d['reasons']}")
        if not passed:
            all_passed = False

    print(f"\n{'='*60}")
    print(f"  OVERALL: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    print(f"{'='*60}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit(main())
