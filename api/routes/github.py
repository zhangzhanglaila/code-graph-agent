"""GitHub routes — repository analysis and import graph."""

from __future__ import annotations
import os
import sys
import subprocess
import tempfile
import glob

from fastapi import APIRouter

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from static.python_analyzer import PythonAnalyzer
from api.input_inference import infer_args

from api.services.helpers import import_code_as_module
from api.schemas.github import GitHubAnalyzeRequest, ImportGraphRequest

router = APIRouter()


@router.post("/api/github_analyze")
async def github_analyze(req: GitHubAnalyzeRequest):
    """Analyze a GitHub repository."""
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            clone_cmd = ['git', 'clone', '--depth', '1', req.repo_url, tmp_dir]
            result = subprocess.run(clone_cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                return {'success': False, 'error': f'Failed to clone repo: {result.stderr}'}

            py_files = glob.glob(os.path.join(tmp_dir, '**', '*.py'), recursive=True)
            if not py_files:
                return {'success': False, 'error': 'No Python files found in repository'}

            py_files = py_files[:req.max_files]

            analyses = []
            for py_file in py_files:
                try:
                    with open(py_file, 'r', encoding='utf-8') as f:
                        code = f.read()
                    rel_path = os.path.relpath(py_file, tmp_dir)

                    # Basic AST analysis
                    import ast
                    tree = ast.parse(code)
                    functions = []
                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef):
                            functions.append({
                                'name': node.name,
                                'line': node.lineno,
                                'args': [a.arg for a in node.args.args],
                            })

                    analyses.append({
                        'file': rel_path,
                        'functions': functions,
                        'lines': len(code.splitlines()),
                    })
                except Exception:
                    continue

            return {
                'success': True,
                'repo_url': req.repo_url,
                'files': analyses,
                'total_files': len(analyses),
            }
    except Exception as e:
        return {'success': False, 'error': str(e)}


@router.post("/api/import_graph")
async def import_graph(req: ImportGraphRequest):
    """Build import dependency graph for a GitHub repo."""
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            clone_cmd = ['git', 'clone', '--depth', '1', req.repo_url, tmp_dir]
            result = subprocess.run(clone_cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                return {'success': False, 'error': f'Failed to clone repo: {result.stderr}'}

            # Use ImportGraphBuilder from analyze routes
            from api.routes.analyze import ImportGraphBuilder
            graph = ImportGraphBuilder.build_graph(tmp_dir)
            return graph
    except Exception as e:
        return {'success': False, 'error': str(e)}
