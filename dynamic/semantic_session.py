"""Semantic Session — Persistent investigation workspace.

Saves queries, plans, results, facts, narratives into a .semantic-session/ directory.
Enables "human + agent co-reasoning" — investigations persist across sessions.

Structure:
    .semantic-session/
        session.json          — metadata (created, code_hash, description)
        queries/
            001_why_memo.json — each query with timestamp, plan, result, trace
            002_trace_a.json
        snapshots/
            001_pdg.json      — PDG snapshot at query time
            001_facts.json    — facts at query time
        notes/
            001.md            — user notes attached to queries

Usage:
    session = SemanticSession.create(".semantic-session", code="def fib...", description="Fibonacci investigation")
    entry = session.save_query("WHY memo", query_result, pdg, facts)
    session.add_note(entry.id, "Root cause is in the initialization")
    report = session.export_report()
"""

from __future__ import annotations
import json
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class QueryEntry:
    """A saved query with its result and metadata."""
    id: int
    query_text: str
    query_kind: str
    timestamp: str
    result: dict
    trace: dict
    plan: List[str]
    note: str = ''

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'query_text': self.query_text,
            'query_kind': self.query_kind,
            'timestamp': self.timestamp,
            'result_summary': self._result_summary(),
            'trace_steps': len(self.trace.get('steps', [])),
            'plan': self.plan,
            'note': self.note,
        }

    def _result_summary(self) -> str:
        r = self.result
        if r.get('narrative', {}).get('title'):
            return r['narrative']['title']
        if r.get('text'):
            return r['text'][:100]
        if r.get('facts'):
            return f"{len(r['facts'])} facts"
        if r.get('history'):
            return f"{len(r['history'])} versions"
        if r.get('steps'):
            return f"{len(r['steps'])} steps"
        return str(r.get('success', ''))


@dataclass
class SessionMeta:
    """Session metadata."""
    created: str
    code_hash: str
    description: str
    query_count: int = 0
    last_activity: str = ''

    def to_dict(self) -> dict:
        return asdict(self)


class SemanticSession:
    """Persistent investigation workspace for semantic queries."""

    def __init__(self, session_dir: str, meta: SessionMeta, queries: List[QueryEntry]):
        self.dir = session_dir
        self.meta = meta
        self.queries = queries

    @classmethod
    def create(cls, session_dir: str, code: str = '', description: str = '') -> 'SemanticSession':
        """Create a new semantic session."""
        os.makedirs(session_dir, exist_ok=True)
        os.makedirs(os.path.join(session_dir, 'queries'), exist_ok=True)
        os.makedirs(os.path.join(session_dir, 'snapshots'), exist_ok=True)
        os.makedirs(os.path.join(session_dir, 'notes'), exist_ok=True)

        import hashlib
        code_hash = hashlib.md5(code.encode()).hexdigest()[:8] if code else 'empty'

        meta = SessionMeta(
            created=datetime.now().isoformat(),
            code_hash=code_hash,
            description=description or f'Session {datetime.now().strftime("%Y%m%d_%H%M%S")}',
        )

        # Save meta
        with open(os.path.join(session_dir, 'session.json'), 'w', encoding='utf-8') as f:
            json.dump(meta.to_dict(), f, indent=2, ensure_ascii=False)

        return cls(session_dir, meta, [])

    @classmethod
    def load(cls, session_dir: str) -> 'SemanticSession':
        """Load an existing session."""
        meta_path = os.path.join(session_dir, 'session.json')
        if not os.path.exists(meta_path):
            raise FileNotFoundError(f'No session found at {session_dir}')

        with open(meta_path, 'r', encoding='utf-8') as f:
            meta_dict = json.load(f)
        meta = SessionMeta(**meta_dict)

        # Load queries
        queries = []
        queries_dir = os.path.join(session_dir, 'queries')
        if os.path.isdir(queries_dir):
            for fname in sorted(os.listdir(queries_dir)):
                if fname.endswith('.json'):
                    with open(os.path.join(queries_dir, fname), 'r', encoding='utf-8') as f:
                        q_dict = json.load(f)
                    queries.append(QueryEntry(**q_dict))

        return cls(session_dir, meta, queries)

    def save_query(self, query_text: str, result: dict, pdg=None, facts=None) -> QueryEntry:
        """Save a query result to the session."""
        self.meta.query_count += 1
        self.meta.last_activity = datetime.now().isoformat()

        # Extract trace and plan from result
        trace = result.pop('_trace', {})
        plan = []
        for step in trace.get('steps', []):
            if step.get('detail', {}).get('pipeline'):
                plan = step['detail']['pipeline']
                break

        entry = QueryEntry(
            id=self.meta.query_count,
            query_text=query_text,
            query_kind=result.get('query', 'unknown'),
            timestamp=datetime.now().isoformat(),
            result=result,
            trace=trace,
            plan=plan,
        )

        self.queries.append(entry)

        # Save query file
        fname = f'{entry.id:03d}_{query_text.replace(" ", "_").lower()[:30]}.json'
        query_path = os.path.join(self.dir, 'queries', fname)
        with open(query_path, 'w', encoding='utf-8') as f:
            json.dump({
                'id': entry.id,
                'query_text': entry.query_text,
                'query_kind': entry.query_kind,
                'timestamp': entry.timestamp,
                'result': entry.result,
                'trace': entry.trace,
                'plan': entry.plan,
                'note': entry.note,
            }, f, indent=2, ensure_ascii=False, default=str)

        # Save PDG snapshot if provided
        if pdg is not None:
            snap_path = os.path.join(self.dir, 'snapshots', f'{entry.id:03d}_pdg.json')
            with open(snap_path, 'w', encoding='utf-8') as f:
                json.dump(pdg.stats(), f, indent=2)

        # Save facts snapshot if provided
        if facts is not None:
            facts_path = os.path.join(self.dir, 'snapshots', f'{entry.id:03d}_facts.json')
            with open(facts_path, 'w', encoding='utf-8') as f:
                json.dump([fact.to_dict() for fact in facts], f, indent=2, ensure_ascii=False)

        # Update session meta
        self._save_meta()

        return entry

    def add_note(self, query_id: int, note: str):
        """Attach a note to a query."""
        for entry in self.queries:
            if entry.id == query_id:
                entry.note = note
                break

        # Save note file
        note_path = os.path.join(self.dir, 'notes', f'{query_id:03d}.md')
        with open(note_path, 'w', encoding='utf-8') as f:
            f.write(note)

        # Update query file
        queries_dir = os.path.join(self.dir, 'queries')
        for fname in os.listdir(queries_dir):
            if fname.startswith(f'{query_id:03d}_'):
                qpath = os.path.join(queries_dir, fname)
                with open(qpath, 'r', encoding='utf-8') as f:
                    qdata = json.load(f)
                qdata['note'] = note
                with open(qpath, 'w', encoding='utf-8') as f:
                    json.dump(qdata, f, indent=2, ensure_ascii=False)
                break

    def list_queries(self) -> List[dict]:
        """List all saved queries."""
        return [q.to_dict() for q in self.queries]

    def get_query(self, query_id: int) -> Optional[QueryEntry]:
        """Get a specific query by ID."""
        for q in self.queries:
            if q.id == query_id:
                return q
        return None

    def export_report(self) -> str:
        """Export the session as a human-readable report."""
        lines = [
            f'# Semantic Investigation: {self.meta.description}',
            f'',
            f'Created: {self.meta.created}',
            f'Code hash: {self.meta.code_hash}',
            f'Queries: {len(self.queries)}',
            f'Last activity: {self.meta.last_activity}',
            '',
            '---',
            '',
        ]

        for entry in self.queries:
            lines.append(f'## Query #{entry.id}: `{entry.query_text}`')
            lines.append(f'Time: {entry.timestamp}')
            if entry.plan:
                lines.append(f'Plan: `{" → ".join(entry.plan)}`')
            lines.append('')

            # Result summary
            lines.append(f'**Result:** {entry._result_summary()}')
            lines.append('')

            # Trace
            if entry.trace.get('steps'):
                lines.append('**Execution Trace:**')
                for step in entry.trace['steps']:
                    ms = f' ({step["duration_ms"]:.1f}ms)' if step.get('duration_ms') else ''
                    lines.append(f'  - [{step["phase"]}] {step["description"]}{ms}')
                lines.append('')

            # Note
            if entry.note:
                lines.append(f'**Note:** {entry.note}')
                lines.append('')

            lines.append('---')
            lines.append('')

        return '\n'.join(lines)

    def export_json(self) -> dict:
        """Export the session as JSON."""
        return {
            'meta': self.meta.to_dict(),
            'queries': [
                {
                    'id': q.id,
                    'query_text': q.query_text,
                    'query_kind': q.query_kind,
                    'timestamp': q.timestamp,
                    'result': q.result,
                    'trace': q.trace,
                    'plan': q.plan,
                    'note': q.note,
                }
                for q in self.queries
            ],
        }

    def _save_meta(self):
        """Save updated metadata."""
        meta_path = os.path.join(self.dir, 'session.json')
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(self.meta.to_dict(), f, indent=2, ensure_ascii=False)
