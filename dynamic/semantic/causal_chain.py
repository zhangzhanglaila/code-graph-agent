"""Causal Chain Engine — SSA-like versioned causal chain engine.

Key upgrade: each variable assignment creates a new VERSION.
x = 1  ->  x#1
x = 2  ->  x#2
x = 3  ->  x#3

Edges connect specific versions: x#1 -> y#1, x#2 -> z#1
This eliminates ambiguity in loops, reassignment, and mutation.
"""

from __future__ import annotations
import re
from typing import List, Dict, Any, Optional


class CausalChainEngine:
    """SSA-like versioned causal chain engine."""

    PYTHON_KEYWORDS = {
        'if', 'else', 'elif', 'for', 'while', 'return', 'def', 'class',
        'import', 'from', 'as', 'with', 'try', 'except', 'finally',
        'and', 'or', 'not', 'in', 'is', 'True', 'False', 'None',
        'range', 'len', 'int', 'str', 'float', 'list', 'dict', 'set',
        'sorted', 'sum', 'min', 'max', 'abs', 'append', 'extend',
        'print', 'type', 'isinstance', 'enumerate', 'zip', 'map', 'filter',
    }

    @staticmethod
    def build_dependency_graph(steps: List[Dict[str, Any]], block_meta: dict = None) -> dict:
        """Build SSA-like versioned dependency graph."""
        versions = {}
        current_version = {}
        var_version_count = {}
        step_versions = {}
        edges = []
        control_edges = []
        if block_meta is None:
            block_meta = {}

        for step in steps:
            idx = step.get('index', 0)
            code = step.get('code', '').strip()
            changed = step.get('changed', [])
            new_vars = step.get('new_vars', [])
            all_vars = list((step.get('vars') or {}).keys())
            line = step.get('line', 0)

            writes = list(set(changed + new_vars))
            write_set = set(writes)

            parts = code.split('=', 1)
            rhs = parts[1] if len(parts) > 1 else code
            rhs_tokens = set(re.findall(r'\b([a-zA-Z_]\w*)\b', rhs))
            read_vars = [v for v in all_vars if v in rhs_tokens and v not in CausalChainEngine.PYTHON_KEYWORDS]

            read_versions = []
            for v in read_vars:
                ver = current_version.get(v)
                if ver:
                    read_versions.append(ver)

            write_versions = []
            for v in writes:
                count = var_version_count.get(v, 0) + 1
                var_version_count[v] = count
                ver_name = f'{v}#{count}'
                current_version[v] = ver_name
                write_versions.append(ver_name)

                val = (step.get('vars') or {}).get(v, {}).get('value', '')
                versions[ver_name] = {
                    'var': v, 'version': count, 'step': idx,
                    'value': val, 'code': code, 'line': line,
                }

            step_versions[idx] = {
                'reads': read_versions, 'writes': write_versions,
                'code': code, 'line': line,
            }

            for rv in read_versions:
                for wv in write_versions:
                    edges.append({
                        'from': rv, 'to': wv,
                        'step_from': versions[rv]['step'], 'step_to': idx,
                        'type': 'data_flow',
                    })

            block_id = step.get('block_id', 0)
            if block_id and block_meta:
                block_info = block_meta.get(block_id, {})
                cond_step = block_info.get('condition_step', -1)
                if cond_step >= 0 and cond_step != idx:
                    cond_code = steps[cond_step].get('code', '') if cond_step < len(steps) else ''
                    cond_reads = step_versions.get(cond_step, {}).get('reads', [])
                    control_edges.append({
                        'condition_step': cond_step, 'branch_step': idx,
                        'condition_code': cond_code, 'condition_reads': cond_reads,
                        'block_id': block_id,
                    })

        return {
            'versions': versions, 'current_version': current_version,
            'var_version_count': var_version_count, 'step_versions': step_versions,
            'edges': edges, 'control_edges': control_edges,
        }

    @staticmethod
    def backward_slice(
        target_step: int, target_var: str, dep_graph: dict, max_depth: int = 20,
    ) -> list:
        """Backward slice using SSA versioned graph."""
        versions = dep_graph['versions']
        edges = dep_graph['edges']
        current_version = dep_graph['current_version']

        target_ver = None
        for ver_name, ver_meta in sorted(versions.items(), key=lambda x: -x[1]['step']):
            if ver_meta['var'] == target_var and ver_meta['step'] <= target_step:
                target_ver = ver_name
                break

        if not target_ver:
            target_ver = current_version.get(target_var)
        if not target_ver:
            return []

        reverse = {}
        for e in edges:
            if e['to'] not in reverse:
                reverse[e['to']] = []
            reverse[e['to']].append(e)

        visited = set()
        chain = []
        queue = [(target_ver, 0)]
        visited.add(target_ver)

        while queue:
            ver_name, depth = queue.pop(0)
            if depth > max_depth:
                continue

            ver_meta = versions.get(ver_name)
            if not ver_meta:
                continue

            chain.append({
                'step': ver_meta['step'], 'var': ver_meta['var'],
                'version': ver_name, 'value': ver_meta['value'],
                'code': ver_meta['code'], 'line': ver_meta['line'],
                'depth': depth,
                'role': 'root' if depth == 0 else 'contributor',
            })

            for e in reverse.get(ver_name, []):
                from_ver = e['from']
                if from_ver not in visited:
                    visited.add(from_ver)
                    queue.append((from_ver, depth + 1))

        chain.sort(key=lambda x: x['step'])
        if chain:
            chain[-1]['role'] = 'failure_point'
            chain[0]['role'] = 'root_cause'
        return chain

    @staticmethod
    def detect_failure_point(steps: List[Dict[str, Any]]) -> Optional[dict]:
        """Detect the failure point in execution."""
        if not steps:
            return None

        last_step = steps[-1]
        code = last_step.get('code', '')

        if 'return' in code:
            return_vars = list((last_step.get('vars') or {}).keys())
            return {
                'type': 'return', 'step': last_step.get('index', 0),
                'code': code, 'line': last_step.get('line', 0), 'vars': return_vars,
            }

        for step in reversed(steps[-5:]):
            code = step.get('code', '')
            if 'Error' in code or 'raise' in code or 'except' in code:
                return {
                    'type': 'exception', 'step': step.get('index', 0),
                    'code': code, 'line': step.get('line', 0),
                }

        return {
            'type': 'end', 'step': last_step.get('index', 0),
            'code': code, 'line': last_step.get('line', 0),
        }

    @staticmethod
    def analyze(steps: List[Dict[str, Any]], focus_var: str = '', block_meta: dict = None) -> dict:
        """Full causal chain analysis with SSA versioning."""
        if not steps:
            return {'success': False, 'error': 'No steps to analyze'}

        dep_graph = CausalChainEngine.build_dependency_graph(steps, block_meta=block_meta)
        edges = dep_graph.get('edges', [])

        failure = CausalChainEngine.detect_failure_point(steps)
        if not failure:
            return {'success': False, 'error': 'Could not detect failure point'}

        if focus_var:
            target_var = focus_var
        elif failure.get('vars'):
            target_var = failure['vars'][-1]
        else:
            recent_vars = {}
            for step in steps[-5:]:
                for v in step.get('changed', []) + step.get('new_vars', []):
                    recent_vars[v] = recent_vars.get(v, 0) + 1
            if recent_vars:
                target_var = max(recent_vars, key=recent_vars.get)
            else:
                return {'success': False, 'error': 'Could not determine target variable'}

        chain = CausalChainEngine.backward_slice(failure['step'], target_var, dep_graph)

        edge_lookup: Dict[str, list] = {}
        for e in edges:
            edge_lookup.setdefault(e['to'], []).append(e['from'])

        chain_versions = {link.get('version', link['var']) for link in chain}
        sentences = []
        for i, link in enumerate(chain):
            ver = link.get('version', link['var'])
            preds_in_chain = [p for p in edge_lookup.get(ver, []) if p in chain_versions]
            if i == 0 and not preds_in_chain:
                sentences.append(f'Root cause: `{ver}` = {link["value"]} at step {link["step"]} (line {link["line"]})')
            elif i == len(chain) - 1:
                if preds_in_chain:
                    sentences.append(f'Failure point: `{ver}` (← {", ".join(preds_in_chain)}) at step {link["step"]} (line {link["line"]})')
                else:
                    sentences.append(f'Failure point: `{ver}` at step {link["step"]} (line {link["line"]})')
            else:
                if preds_in_chain:
                    sentences.append(f'`{ver}` (← {", ".join(preds_in_chain)}) via `{link["code"][:50]}`')
                else:
                    sentences.append(f'`{ver}` = {link["value"]} via `{link["code"][:50]}`')

        causal_distance = len(chain)

        divergence = None
        for i, link in enumerate(chain):
            val = link.get('value', '')
            if val in ('None', '', '[]', '{}', '0', 'False') and i > 0:
                divergence = link
                break

        fan_in: Dict[str, int] = {}
        for e in edges:
            fan_in[e['to']] = fan_in.get(e['to'], 0) + 1

        return {
            'success': True, 'failure_point': failure, 'target_var': target_var,
            'causal_chain': chain, 'causal_sentences': sentences,
            'causal_distance': causal_distance, 'divergence_point': divergence,
            'control_edges': dep_graph.get('control_edges', []),
            'graph_stats': {
                'total_edges': len(edges),
                'unique_vars': len(dep_graph.get('versions', {})),
                'max_fan_in': max(fan_in.values(), default=0),
                'versioned': True,
            },
        }
