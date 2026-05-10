"""Subproblem Builder — builds dependency graphs of code subproblems."""

from __future__ import annotations
from typing import Any, Dict, List


def build_subproblem_graph(pdg: Any, facts: list) -> Dict:
    """Build a subproblem dependency graph from PDG and facts.

    Returns a dict with nodes (subproblems) and edges (dependencies).
    """
    # Extract subproblems from PDG functions and loop blocks
    subproblems = []
    seen_funcs = set()

    for nid, node in pdg.nodes.items():
        func = getattr(node, 'func', '')
        if func and func not in seen_funcs:
            seen_funcs.add(func)
            subproblems.append({
                "id": f"func_{func}",
                "name": func,
                "type": "function",
                "steps": 1,
            })

    # Add loop subproblems
    loop_facts = [f for f in facts if 'loop' in getattr(f, 'kind', '').lower()]
    for i, fact in enumerate(loop_facts):
        subproblems.append({
            "id": f"loop_{i}",
            "name": getattr(fact, 'subject', f'loop_{i}'),
            "type": "loop",
            "iterations": getattr(fact, 'metadata', {}).get('iterations', 0),
        })

    # Build edges from PDG call edges
    edges = []
    for edge in pdg.edges:
        if getattr(edge, 'kind', '') == 'call':
            source_func = pdg.nodes.get(edge.source)
            target_func = pdg.nodes.get(edge.target)
            if source_func and target_func:
                src_name = getattr(source_func, 'func', '')
                tgt_name = getattr(target_func, 'func', '')
                if src_name and tgt_name and src_name != tgt_name:
                    edges.append({
                        "from": f"func_{src_name}",
                        "to": f"func_{tgt_name}",
                        "type": "call",
                    })

    # Shared subproblems (variables accessed by multiple functions)
    shared = []
    var_access = {}
    for node in pdg.nodes.values():
        func = getattr(node, 'func', '')
        for var in getattr(node, 'vars', {}).keys():
            if var not in var_access:
                var_access[var] = set()
            var_access[var].add(func)

    for var, funcs in var_access.items():
        if len(funcs) > 1:
            shared.append({
                "id": f"shared_{var}",
                "variable": var,
                "shared_by": list(funcs),
                "access_count": len(funcs),
            })

    return {
        "subproblems": subproblems,
        "edges": edges,
        "shared_subproblems": shared,
        "total_subproblems": len(subproblems),
        "unique_subproblems": len(set(s["name"] for s in subproblems)),
    }
