"""Semantic Diff — Compare two executions at the semantic level.

Not code-line diff. Semantic diff answers:

  "Why does this run differ from that run?"

Compares:
  - PDG structure (nodes, edges, topology)
  - Data dependencies (new/removed/diverged RAW edges)
  - Variable evolution (SSA version changes, value shifts)
  - Root causes (which nodes are roots in each run)
  - Semantic facts (new/removed/changed patterns)
  - Complexity metrics (depth, fan-in, fan-out, cyclomatic)
  - Narrative divergence (how explanations change)

Usage:
    diff = SemanticDiffer.compare(pdg_a, facts_a, pdg_b, facts_b)
    print(diff.summary())
    print(diff.to_text())
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Any


# ─── Diff Items ─────────────────────────────────────────────────

@dataclass
class DiffItem:
    """A single semantic difference between two runs."""
    category: str       # 'topology' | 'dependency' | 'variable' | 'root_cause' | 'fact' | 'complexity' | 'narrative'
    severity: str       # 'info' | 'warning' | 'regression' | 'improvement'
    description: str
    run_a: Any = None   # value in run A
    run_b: Any = None   # value in run B
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'category': self.category,
            'severity': self.severity,
            'description': self.description,
            'run_a': self.run_a,
            'run_b': self.run_b,
            'detail': self.detail,
        }


@dataclass
class SemanticDiffReport:
    """Full diff between two execution runs."""
    items: List[DiffItem] = field(default_factory=list)
    summary_a: dict = field(default_factory=dict)
    summary_b: dict = field(default_factory=dict)

    # Aggregate metrics
    topology_delta: dict = field(default_factory=dict)
    dependency_delta: dict = field(default_factory=dict)
    complexity_delta: dict = field(default_factory=dict)

    def add(self, item: DiffItem):
        self.items.append(item)

    @property
    def regressions(self) -> List[DiffItem]:
        return [i for i in self.items if i.severity == 'regression']

    @property
    def improvements(self) -> List[DiffItem]:
        return [i for i in self.items if i.severity == 'improvement']

    @property
    def warnings(self) -> List[DiffItem]:
        return [i for i in self.items if i.severity == 'warning']

    def by_category(self, category: str) -> List[DiffItem]:
        return [i for i in self.items if i.category == category]

    def summary(self) -> str:
        cats = {}
        for item in self.items:
            cats[item.category] = cats.get(item.category, 0) + 1
        parts = [f'{cat}: {count}' for cat, count in sorted(cats.items())]
        reg = len(self.regressions)
        imp = len(self.improvements)
        return f'SemanticDiff: {len(self.items)} changes ({reg} regressions, {imp} improvements) — {", ".join(parts)}'

    def to_dict(self) -> dict:
        return {
            'items': [i.to_dict() for i in self.items],
            'summary': self.summary(),
            'summary_a': self.summary_a,
            'summary_b': self.summary_b,
            'topology_delta': self.topology_delta,
            'dependency_delta': self.dependency_delta,
            'complexity_delta': self.complexity_delta,
            'counts': {
                'total': len(self.items),
                'regressions': len(self.regressions),
                'improvements': len(self.improvements),
                'warnings': len(self.warnings),
            },
        }

    def to_text(self) -> str:
        lines = ['Semantic Diff Report', '═' * 60, '']

        # Summary
        lines.append(self.summary())
        lines.append('')

        # Topology
        if self.topology_delta:
            lines.append('── Topology ──')
            for k, v in self.topology_delta.items():
                lines.append(f'  {k}: {v}')
            lines.append('')

        # Complexity
        if self.complexity_delta:
            lines.append('── Complexity ──')
            for k, v in self.complexity_delta.items():
                if isinstance(v, dict):
                    lines.append(f'  {k}:')
                    for kk, vv in v.items():
                        lines.append(f'    {kk}: {vv}')
                else:
                    lines.append(f'  {k}: {v}')
            lines.append('')

        # Regressions (most important)
        if self.regressions:
            lines.append('── Regressions ──')
            for item in self.regressions:
                lines.append(f'  [{item.category}] {item.description}')
            lines.append('')

        # Improvements
        if self.improvements:
            lines.append('── Improvements ──')
            for item in self.improvements:
                lines.append(f'  [{item.category}] {item.description}')
            lines.append('')

        # Warnings
        if self.warnings:
            lines.append('── Warnings ──')
            for item in self.warnings:
                lines.append(f'  [{item.category}] {item.description}')
            lines.append('')

        # Info
        infos = [i for i in self.items if i.severity == 'info']
        if infos:
            lines.append('── Changes ──')
            for item in infos:
                lines.append(f'  [{item.category}] {item.description}')

        return '\n'.join(lines)


# ─── Semantic Differ ────────────────────────────────────────────

class SemanticDiffer:
    """Compares two executions at the semantic level."""

    @classmethod
    def compare(cls, model_a, facts_a, model_b, facts_b,
                narrative_a=None, narrative_b=None) -> SemanticDiffReport:
        """Compare two runs and produce a SemanticDiffReport."""
        report = SemanticDiffReport()

        # Build summaries
        report.summary_a = cls._build_summary(pdg_a, facts_a)
        report.summary_b = cls._build_summary(pdg_b, facts_b)

        # Run all diff passes
        cls._diff_topology(pdg_a, pdg_b, report)
        cls._diff_dependencies(pdg_a, pdg_b, report)
        cls._diff_variables(pdg_a, pdg_b, report)
        cls._diff_root_causes(pdg_a, pdg_b, report)
        cls._diff_facts(facts_a, facts_b, report)
        cls._diff_complexity(pdg_a, pdg_b, report)
        if narrative_a and narrative_b:
            cls._diff_narrative(narrative_a, narrative_b, report)

        return report

    @staticmethod
    def _build_summary(pdg, facts) -> dict:
        stats = pdg.stats()
        return {
            'nodes': stats.get('nodes', 0),
            'edges': stats.get('edges', 0),
            'edge_kinds': stats.get('edge_kinds', {}),
            'variables': stats.get('variables', 0),
            'max_depth': stats.get('max_depth', 0),
            'facts': len(facts),
            'fact_kinds': list(set(f.kind for f in facts)),
        }

    # ── Topology ──

    @staticmethod
    def _diff_topology(pdg_a, pdg_b, report: SemanticDiffReport):
        nodes_a = set(pdg_a.nodes.keys())
        nodes_b = set(pdg_b.nodes.keys())
        added = nodes_b - nodes_a
        removed = nodes_a - nodes_b

        report.topology_delta = {
            'nodes_a': len(nodes_a),
            'nodes_b': len(nodes_b),
            'added': len(added),
            'removed': len(removed),
        }

        if len(added) > 0:
            report.add(DiffItem(
                category='topology',
                severity='info' if len(added) < 5 else 'warning',
                description=f'{len(added)} new execution steps appeared',
                run_a=len(nodes_a), run_b=len(nodes_b),
                detail={'added_steps': sorted(added)[:10]},
            ))

        if len(removed) > 0:
            report.add(DiffItem(
                category='topology',
                severity='info' if len(removed) < 5 else 'warning',
                description=f'{len(removed)} execution steps disappeared',
                run_a=len(nodes_a), run_b=len(nodes_b),
                detail={'removed_steps': sorted(removed)[:10]},
            ))

        # Edge count comparison
        edges_a = len(pdg_a.edges)
        edges_b = len(pdg_b.edges)
        if edges_a != edges_b:
            delta = edges_b - edges_a
            severity = 'info'
            if abs(delta) > edges_a * 0.3:
                severity = 'regression' if delta > 0 else 'improvement'
            report.add(DiffItem(
                category='topology',
                severity=severity,
                description=f'Edge count changed: {edges_a} → {edges_b} ({delta:+d})',
                run_a=edges_a, run_b=edges_b,
            ))

    # ── Dependencies ──

    @staticmethod
    def _diff_dependencies(pdg_a, pdg_b, report: SemanticDiffReport):
        # Extract data edges as (src, tgt, var) tuples
        edges_a = set()
        for e in pdg_a.edges:
            if e.kind == 'data':
                edges_a.add((e.source, e.target, e.var))

        edges_b = set()
        for e in pdg_b.edges:
            if e.kind == 'data':
                edges_b.add((e.source, e.target, e.var))

        added = edges_b - edges_a
        removed = edges_a - edges_b

        report.dependency_delta = {
            'data_edges_a': len(edges_a),
            'data_edges_b': len(edges_b),
            'added': len(added),
            'removed': len(removed),
        }

        if added:
            # Group by variable
            by_var = {}
            for src, tgt, var in added:
                by_var.setdefault(var, []).append((src, tgt))
            for var, pairs in by_var.items():
                report.add(DiffItem(
                    category='dependency',
                    severity='warning',
                    description=f'New data dependency: {var} gained {len(pairs)} new edge(s)',
                    detail={'variable': var, 'edges': pairs[:5]},
                ))

        if removed:
            by_var = {}
            for src, tgt, var in removed:
                by_var.setdefault(var, []).append((src, tgt))
            for var, pairs in by_var.items():
                report.add(DiffItem(
                    category='dependency',
                    severity='regression',
                    description=f'Lost data dependency: {var} lost {len(pairs)} edge(s)',
                    detail={'variable': var, 'edges': pairs[:5]},
                ))

        # Detect dependency reversals (A→B became B→A)
        reversed_deps = set()
        for src_a, tgt_a, var_a in removed:
            if (tgt_a, src_a, var_a) in added:
                reversed_deps.add((src_a, tgt_a, var_a))
        if reversed_deps:
            report.add(DiffItem(
                category='dependency',
                severity='regression',
                description=f'{len(reversed_deps)} dependency edge(s) reversed direction',
                detail={'reversed': list(reversed_deps)[:5]},
            ))

    # ── Variables ──

    @staticmethod
    def _diff_variables(pdg_a, pdg_b, report: SemanticDiffReport):
        vars_a = set()
        for node in pdg_a.nodes.values():
            vars_a.update(node.vars.keys())

        vars_b = set()
        for node in pdg_b.nodes.values():
            vars_b.update(node.vars.keys())

        added_vars = vars_b - vars_a
        removed_vars = vars_a - vars_b

        if added_vars:
            report.add(DiffItem(
                category='variable',
                severity='info',
                description=f'New variables appeared: {", ".join(sorted(added_vars))}',
                detail={'variables': sorted(added_vars)},
            ))

        if removed_vars:
            report.add(DiffItem(
                category='variable',
                severity='warning',
                description=f'Variables disappeared: {", ".join(sorted(removed_vars))}',
                detail={'variables': sorted(removed_vars)},
            ))

        # Compare SSA version counts for shared variables
        shared = vars_a & vars_b
        for var in sorted(shared):
            versions_a = set()
            versions_b = set()
            for node in pdg_a.nodes.values():
                if var in node.vars:
                    versions_a.add(node.vars[var].version)
            for node in pdg_b.nodes.values():
                if var in node.vars:
                    versions_b.add(node.vars[var].version)

            if versions_a != versions_b:
                max_a = max(versions_a) if versions_a else 0
                max_b = max(versions_b) if versions_b else 0
                if max_a != max_b:
                    severity = 'info'
                    if max_b > max_a * 1.5:
                        severity = 'warning'
                    report.add(DiffItem(
                        category='variable',
                        severity=severity,
                        description=f'{var} SSA versions changed: {max_a} → {max_b}',
                        run_a=max_a, run_b=max_b,
                        detail={'variable': var},
                    ))

        # Compare final values for shared variables
        for var in sorted(shared):
            # Find the last node that has this variable
            last_a = max((n for n in pdg_a.nodes.values() if var in n.vars), key=lambda n: n.id, default=None)
            last_b = max((n for n in pdg_b.nodes.values() if var in n.vars), key=lambda n: n.id, default=None)
            if last_a and last_b:
                val_a = last_a.vars[var].value
                val_b = last_b.vars[var].value
                if val_a != val_b:
                    report.add(DiffItem(
                        category='variable',
                        severity='regression',
                        description=f'{var} final value changed: {val_a} → {val_b}',
                        run_a=val_a, run_b=val_b,
                        detail={'variable': var, 'type_a': last_a.vars[var].type, 'type_b': last_b.vars[var].type},
                    ))

    # ── Root Causes ──

    @staticmethod
    def _diff_root_causes(pdg_a, pdg_b, report: SemanticDiffReport):
        # Compare root cause nodes (nodes with no incoming data edges)
        def find_roots(pdg):
            incoming = set()
            for e in pdg.edges:
                if e.kind == 'data':
                    incoming.add(e.target)
            return set(pdg.nodes.keys()) - incoming

        roots_a = find_roots(pdg_a)
        roots_b = find_roots(pdg_b)

        added = roots_b - roots_a
        removed = roots_a - roots_b

        if added:
            codes = []
            for rid in sorted(added):
                node = pdg_b.nodes.get(rid)
                if node:
                    codes.append(f'#{rid}:{node.code.strip()[:40]}')
            report.add(DiffItem(
                category='root_cause',
                severity='warning',
                description=f'{len(added)} new root cause(s): {", ".join(codes[:3])}',
                detail={'added_roots': sorted(added)},
            ))

        if removed:
            codes = []
            for rid in sorted(removed):
                node = pdg_a.nodes.get(rid)
                if node:
                    codes.append(f'#{rid}:{node.code.strip()[:40]}')
            report.add(DiffItem(
                category='root_cause',
                severity='info',
                description=f'{len(removed)} root cause(s) no longer present: {", ".join(codes[:3])}',
                detail={'removed_roots': sorted(removed)},
            ))

    # ── Facts ──

    @staticmethod
    def _diff_facts(facts_a, facts_b, report: SemanticDiffReport):
        # Group facts by kind
        kinds_a: Dict[str, int] = {}
        kinds_b: Dict[str, int] = {}
        for f in facts_a:
            kinds_a[f.kind] = kinds_a.get(f.kind, 0) + 1
        for f in facts_b:
            kinds_b[f.kind] = kinds_b.get(f.kind, 0) + 1

        all_kinds = set(kinds_a.keys()) | set(kinds_b.keys())
        for kind in sorted(all_kinds):
            count_a = kinds_a.get(kind, 0)
            count_b = kinds_b.get(kind, 0)
            if count_a != count_b:
                delta = count_b - count_a
                severity = 'info'
                if kind.startswith('causal.') and delta < 0:
                    severity = 'improvement'
                elif kind.startswith('variable.mutation') and delta > count_a * 0.5:
                    severity = 'warning'
                report.add(DiffItem(
                    category='fact',
                    severity=severity,
                    description=f'{kind}: {count_a} → {count_b} ({delta:+d})',
                    run_a=count_a, run_b=count_b,
                ))

        # Compare fact descriptions for drift
        descs_a = {f.description for f in facts_a}
        descs_b = {f.description for f in facts_b}
        new_descs = descs_b - descs_a
        lost_descs = descs_a - descs_b
        if new_descs or lost_descs:
            report.add(DiffItem(
                category='fact',
                severity='info',
                description=f'Fact descriptions: {len(new_descs)} new, {len(lost_descs)} lost',
                detail={'new_count': len(new_descs), 'lost_count': len(lost_descs),
                        'new_sample': list(new_descs)[:3], 'lost_sample': list(lost_descs)[:3]},
            ))

    # ── Complexity ──

    @staticmethod
    def _diff_complexity(pdg_a, pdg_b, report: SemanticDiffReport):
        def calc_complexity(pdg):
            stats = pdg.stats()
            nodes = stats.get('nodes', 0)
            edges = stats.get('edges', 0)
            edge_kinds = stats.get('edge_kinds', {})

            # Fan-in: max incoming edges to any node
            incoming: Dict[int, int] = {}
            outgoing: Dict[int, int] = {}
            for e in pdg.edges:
                incoming[e.target] = incoming.get(e.target, 0) + 1
                outgoing[e.source] = outgoing.get(e.source, 0) + 1

            max_fan_in = max(incoming.values()) if incoming else 0
            max_fan_out = max(outgoing.values()) if outgoing else 0
            avg_fan_in = sum(incoming.values()) / len(incoming) if incoming else 0

            # Depth: longest path
            depth = stats.get('max_depth', 0)

            # Data density: data edges / nodes
            data_edges = edge_kinds.get('data', 0)
            data_density = data_edges / nodes if nodes > 0 else 0

            return {
                'nodes': nodes,
                'edges': edges,
                'max_fan_in': max_fan_in,
                'max_fan_out': max_fan_out,
                'avg_fan_in': round(avg_fan_in, 2),
                'depth': depth,
                'data_density': round(data_density, 2),
                'edge_kinds': edge_kinds,
            }

        comp_a = calc_complexity(pdg_a)
        comp_b = calc_complexity(pdg_b)

        report.complexity_delta = {
            'run_a': comp_a,
            'run_b': comp_b,
        }

        # Compare key metrics
        for metric in ['nodes', 'edges', 'max_fan_in', 'max_fan_out', 'depth', 'data_density']:
            val_a = comp_a[metric]
            val_b = comp_b[metric]
            if val_a != val_b:
                delta = val_b - val_a
                severity = 'info'
                if metric == 'max_fan_in' and delta > 3:
                    severity = 'regression'
                elif metric == 'depth' and delta > 2:
                    severity = 'regression'
                elif metric == 'data_density' and delta > 0.5:
                    severity = 'warning'
                report.add(DiffItem(
                    category='complexity',
                    severity=severity,
                    description=f'{metric}: {val_a} → {val_b} ({delta:+.2f})',
                    run_a=val_a, run_b=val_b,
                ))

    # ── Narrative ──

    @staticmethod
    def _diff_narrative(narrative_a, narrative_b, report: SemanticDiffReport):
        # Compare titles
        title_a = getattr(narrative_a, 'title', '')
        title_b = getattr(narrative_b, 'title', '')
        if title_a != title_b:
            report.add(DiffItem(
                category='narrative',
                severity='info',
                description=f'Narrative focus changed: "{title_a}" → "{title_b}"',
                run_a=title_a, run_b=title_b,
            ))

        # Compare segment counts
        segs_a = getattr(narrative_a, 'segments', [])
        segs_b = getattr(narrative_b, 'segments', [])
        if len(segs_a) != len(segs_b):
            report.add(DiffItem(
                category='narrative',
                severity='info',
                description=f'Narrative segments: {len(segs_a)} → {len(segs_b)}',
                run_a=len(segs_a), run_b=len(segs_b),
            ))

        # Compare segment roles
        roles_a = [s.role for s in segs_a]
        roles_b = [s.role for s in segs_b]
        if roles_a != roles_b:
            report.add(DiffItem(
                category='narrative',
                severity='info',
                description=f'Narrative structure changed: {"→".join(roles_a)} → {"→".join(roles_b)}',
                detail={'roles_a': roles_a, 'roles_b': roles_b},
            ))

        # Compare summaries
        summary_a = getattr(narrative_a, 'summary', '')
        summary_b = getattr(narrative_b, 'summary', '')
        if summary_a != summary_b:
            report.add(DiffItem(
                category='narrative',
                severity='info',
                description='Narrative summary diverged',
                detail={'summary_a': summary_a[:100], 'summary_b': summary_b[:100]},
            ))
