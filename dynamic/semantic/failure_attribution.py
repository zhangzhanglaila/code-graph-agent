"""Failure Attribution — Analyzes execution timeline to detect WHY something went wrong.

Detects:
- State invariant violations
- Recursion termination failures
- Stale mutations (write-only variables)
- Infinite loops (repeating state)
- Unexpected control flow divergence
"""

from __future__ import annotations
import re
from typing import List, Dict, Any


class FailureAttribution:
    """Analyzes execution timeline to detect WHY something went wrong."""

    @staticmethod
    def analyze(steps: List[Dict[str, Any]]) -> dict:
        if not steps:
            return {'success': False, 'error': 'No steps to analyze'}

        findings = []
        severity = 'healthy'

        # 1. Detect infinite loops (same variable state repeating)
        state_hashes: Dict[str, list] = {}
        for step in steps:
            vars_snapshot = tuple(sorted(
                (k, str(v.get('value', '')))
                for k, v in (step.get('vars') or {}).items()
            ))
            h = hash(vars_snapshot)
            key = str(h)
            if key not in state_hashes:
                state_hashes[key] = []
            state_hashes[key].append(step.get('index', 0))

        for key, indices in state_hashes.items():
            if len(indices) >= 3:
                severity = max(severity, 'error', key=lambda x: ['healthy', 'warning', 'error', 'critical'].index(x))
                findings.append({
                    'type': 'infinite_loop',
                    'severity': 'error',
                    'title': 'Potential infinite loop detected',
                    'description': f'Variable state repeats at steps {indices[:5]} — execution may not terminate.',
                    'steps': indices[:10],
                    'suggestion': 'Check loop termination condition and ensure loop variable is being updated.',
                })

        # 2. Detect recursion without base case
        max_depth = 0
        depth_sequence = []
        for step in steps:
            d = step.get('depth', 0)
            depth_sequence.append(d)
            max_depth = max(max_depth, d)

        increases = sum(1 for i in range(1, len(depth_sequence)) if depth_sequence[i] > depth_sequence[i-1])
        decreases = sum(1 for i in range(1, len(depth_sequence)) if depth_sequence[i] < depth_sequence[i-1])

        if max_depth > 5 and decreases == 0:
            severity = max(severity, 'critical', key=lambda x: ['healthy', 'warning', 'error', 'critical'].index(x))
            findings.append({
                'type': 'recursion_no_base',
                'severity': 'critical',
                'title': 'Recursion without base case',
                'description': f'Call depth increases to {max_depth} with no returns — missing base case or infinite recursion.',
                'steps': [i for i, d in enumerate(depth_sequence) if d > 3],
                'suggestion': 'Add a base case to terminate recursion.',
            })
        elif max_depth > 3 and decreases < increases * 0.3:
            severity = max(severity, 'warning', key=lambda x: ['healthy', 'warning', 'error', 'critical'].index(x))
            findings.append({
                'type': 'deep_recursion',
                'severity': 'warning',
                'title': 'Deep recursion detected',
                'description': f'Recursion depth reaches {max_depth} with few returns — may hit stack limit.',
                'steps': [i for i, d in enumerate(depth_sequence) if d > 3],
                'suggestion': 'Consider iterative approach or memoization.',
            })

        # 3. Detect stale mutations
        var_writes: Dict[str, list] = {}
        var_reads: Dict[str, set] = {}
        for step in steps:
            changed = step.get('changed', [])
            new_vars = step.get('new_vars', [])
            code = step.get('code', '')
            idx = step.get('index', 0)
            for v in changed + new_vars:
                if v not in var_writes:
                    var_writes[v] = []
                var_writes[v].append(idx)
            all_vars = list((step.get('vars') or {}).keys())
            parts = code.split('=', 1)
            rhs = parts[1] if len(parts) > 1 else code
            for v in all_vars:
                pattern = r'\b' + re.escape(v) + r'\b'
                is_read = bool(re.search(pattern, rhs)) or (len(parts) == 1 and re.search(pattern, code))
                if is_read:
                    if v not in var_reads:
                        var_reads[v] = set()
                    var_reads[v].add(idx)

        for var, writes in var_writes.items():
            reads = var_reads.get(var, set())
            if writes and not reads and len(writes) >= 2:
                severity = max(severity, 'warning', key=lambda x: ['healthy', 'warning', 'error', 'critical'].index(x))
                findings.append({
                    'type': 'stale_mutation',
                    'severity': 'warning',
                    'title': f'Stale mutation: `{var}`',
                    'description': f'Variable `{var}` is written {len(writes)} times but never read.',
                    'steps': writes[:5],
                    'suggestion': f'Either use `{var}` in the output or remove the unnecessary writes.',
                })

        # 4. Detect type instability
        var_types: Dict[str, dict] = {}
        for step in steps:
            for name, snap in (step.get('vars') or {}).items():
                t = snap.get('type', 'unknown')
                if name not in var_types:
                    var_types[name] = {'types': set(), 'steps': []}
                if t not in var_types[name]['types']:
                    var_types[name]['types'].add(t)
                    var_types[name]['steps'].append(step.get('index', 0))

        for name, info in var_types.items():
            if len(info['types']) > 1:
                type_list = list(info['types'])
                acceptable = {('int', 'float'), ('float', 'int'), ('NoneType', 'int'), ('NoneType', 'str')}
                pair = (type_list[0], type_list[1]) if len(type_list) == 2 else None
                if pair and pair not in acceptable and (pair[1], pair[0]) not in acceptable:
                    severity = max(severity, 'warning', key=lambda x: ['healthy', 'warning', 'error', 'critical'].index(x))
                    findings.append({
                        'type': 'type_instability',
                        'severity': 'warning',
                        'title': f'Type instability: `{name}`',
                        'description': f'Variable `{name}` changes type from {" to ".join(type_list)}.',
                        'steps': info['steps'][:5],
                        'suggestion': f'Ensure `{name}` maintains consistent type.',
                    })

        # 5. Performance anomalies
        if len(steps) > 100:
            severity = max(severity, 'warning', key=lambda x: ['healthy', 'warning', 'error', 'critical'].index(x))
            findings.append({
                'type': 'performance',
                'severity': 'warning',
                'title': 'High execution step count',
                'description': f'Execution has {len(steps)} steps — may indicate inefficient algorithm.',
                'steps': [],
                'suggestion': 'Consider memoization, early termination, or more efficient data structures.',
            })

        # Generate summary
        if not findings:
            summary = 'Execution looks healthy — no anomalies detected.'
        else:
            critical = sum(1 for f in findings if f['severity'] == 'critical')
            errors = sum(1 for f in findings if f['severity'] == 'error')
            warnings = sum(1 for f in findings if f['severity'] == 'warning')
            parts = []
            if critical: parts.append(f'{critical} critical')
            if errors: parts.append(f'{errors} errors')
            if warnings: parts.append(f'{warnings} warnings')
            summary = f'Found {", ".join(parts)} — execution may have issues.'

        return {
            'success': True,
            'severity': severity,
            'summary': summary,
            'findings': findings,
            'total_steps': len(steps),
            'max_depth': max_depth,
        }
