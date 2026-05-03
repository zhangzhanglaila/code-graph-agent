"""Why-Code-Agent — Code Causality Intelligence CLI.

Usage:
    python main.py analyze --project demo/ --error demo/auth.py:29
    python main.py explain --file demo/auth.py --line 17
    python main.py demo
"""

from __future__ import annotations
import argparse
import json
import os
import sys
import traceback
from typing import Optional

from core.graph import CausalGraph
from core.edge_types import EdgeType
from static.python_analyzer import PythonAnalyzer
from static.config_linker import ConfigLinker
from dynamic.tracer import LineTracer
from dynamic.exception_parser import ExceptionParser, catch_and_parse
from fusion.merge_engine import MergeEngine
from reasoning.llm_reasoner import LLMReasoner
from query.root_cause import RootCauseQuery
from visualization.graph_ui import GraphVisualizer


def run_analysis(
    project_path: str,
    error_file: Optional[str] = None,
    error_line: Optional[int] = None,
    config_file: Optional[str] = None,
    output_dir: str = "output",
    llm_provider: str = "anthropic",
    llm_model: str = "claude-sonnet-4-20250514",
) -> dict:
    """Run the full analysis pipeline."""
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 60)
    print("Why-Code-Agent: Code Causality Analysis")
    print("=" * 60)

    # ── Phase 1: Static Analysis ─────────────────────────────────────
    print("\n[1/6] Static analysis...")
    py_analyzer = PythonAnalyzer()
    static_graph = py_analyzer.analyze_directory(project_path)
    print(f"  → {static_graph.stats()['nodes']} nodes, {static_graph.stats()['edges']} edges")

    # ── Phase 2: Config Linking ──────────────────────────────────────
    print("\n[2/6] Config linking...")
    config_graph = CausalGraph()
    if config_file:
        linker = ConfigLinker()
        code_files = _collect_py_files(project_path)
        config_graph = linker.build_graph(config_file, code_files)
        print(f"  → {config_graph.stats()['nodes']} config nodes, {config_graph.stats()['edges']} links")

    # ── Phase 3: Dynamic Trace ───────────────────────────────────────
    print("\n[3/6] Dynamic tracing...")
    dynamic_graph = _try_dynamic_trace(project_path)

    # ── Phase 4: Exception Parsing ───────────────────────────────────
    print("\n[4/6] Exception parsing...")
    exception_graph = _try_exception_trace(project_path, error_file)

    # ── Phase 5: Graph Fusion ────────────────────────────────────────
    print("\n[5/6] Graph fusion...")
    merger = MergeEngine()
    fused_graph = merger.merge(
        static_graph=static_graph,
        dynamic_graphs=[dynamic_graph] if dynamic_graph else None,
        config_graph=config_graph if config_graph.nodes else None,
        exception_graph=exception_graph if exception_graph else None,
    )
    stats = fused_graph.stats()
    print(f"  → Fused: {stats['nodes']} nodes, {stats['edges']} edges")
    if stats.get("edge_types"):
        for etype, count in stats["edge_types"].items():
            print(f"    {etype}: {count}")

    # ── Phase 6: LLM Reasoning ───────────────────────────────────────
    print("\n[6/6] LLM reasoning...")
    reasoner = LLMReasoner(provider=llm_provider, model=llm_model)

    results = {}

    # Root cause analysis
    if error_file and error_line:
        error_node_id = f"{os.path.abspath(error_file)}:{error_line}"
        # Try both absolute and relative paths
        if not fused_graph.has_node(error_node_id):
            error_node_id = f"{error_file}:{error_line}"

        if fused_graph.has_node(error_node_id):
            print(f"\n  Analyzing root cause for {error_node_id}...")
            root_cause = reasoner.analyze_root_cause(
                error_info=f"Error at {error_file}:{error_line}",
                graph=fused_graph,
                error_node_id=error_node_id,
            )
            results["root_cause"] = root_cause
            print(f"  Symptom: {root_cause.get('symptom', 'N/A')}")
            print(f"  Direct cause: {root_cause.get('direct_cause', 'N/A')}")
            print(f"  Root cause: {root_cause.get('root_cause', 'N/A')}")
            print(f"  Confidence: {root_cause.get('confidence', 'N/A')}")

            # Query causal chain
            query = RootCauseQuery(fused_graph)
            chain_display = query.get_full_chain_display(error_node_id)
            print(f"\n{chain_display}")
            results["chain"] = query.get_root_cause_chain(error_node_id)

    # ── Visualization ────────────────────────────────────────────────
    print("\nGenerating visualization...")
    viz = GraphVisualizer()
    chain_ids = [link["node_id"] for link in results.get("chain", [])]
    html_path = viz.render(
        fused_graph,
        output_path=os.path.join(output_dir, "causal_graph.html"),
        title="Why-Code-Agent: Causal Analysis",
        highlight_chain=chain_ids if chain_ids else None,
    )
    print(f"  → Graph: {html_path}")

    # ── Save results ─────────────────────────────────────────────────
    results_path = os.path.join(output_dir, "analysis_results.json")
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"  → Results: {results_path}")

    return results


def run_explain(
    file_path: str,
    line_number: int,
    llm_provider: str = "anthropic",
    llm_model: str = "claude-sonnet-4-20250514",
) -> dict:
    """Explain why a specific code line exists."""
    print(f"Analyzing: {file_path}:{line_number}")

    # Static analysis of the file
    analyzer = PythonAnalyzer()
    graph = analyzer.analyze_file(file_path)

    # LLM explanation
    reasoner = LLMReasoner(provider=llm_provider, model=llm_model)
    result = reasoner.explain_code_existence(
        file_path=os.path.abspath(file_path),
        line_number=line_number,
        graph=graph,
    )

    print(f"\nPurpose: {result.get('purpose', 'N/A')}")
    if result.get("depends_on"):
        print("Dependencies:")
        for dep in result["depends_on"]:
            print(f"  - [{dep.get('type')}] {dep.get('ref')}: {dep.get('reason')}")
    print(f"Removal consequence: {result.get('removal_consequence', 'N/A')}")
    print(f"Confidence: {result.get('confidence', 'N/A')}")

    return result


def run_demo():
    """Run the login failure demo."""
    demo_dir = os.path.join(os.path.dirname(__file__), "demo")
    config_path = os.path.join(demo_dir, "config.yaml")
    error_file = os.path.join(demo_dir, "auth.py")

    # Find the error line (the RuntimeError raise)
    with open(error_file, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if "raise RuntimeError" in line:
                error_line = i
                break
        else:
            error_line = 29  # fallback

    print("Demo: Login failure root cause analysis")
    print(f"Project: {demo_dir}")
    print(f"Error: {error_file}:{error_line}")
    print()

    return run_analysis(
        project_path=demo_dir,
        error_file=error_file,
        error_line=error_line,
        config_file=config_path,
        output_dir="output",
    )


# ── Helpers ──────────────────────────────────────────────────────────

def _collect_py_files(dir_path: str) -> list:
    files = []
    for root, _, fnames in os.walk(dir_path):
        for fname in fnames:
            if fname.endswith(".py"):
                files.append(os.path.join(root, fname))
    return files


def _try_dynamic_trace(project_path: str) -> Optional[CausalGraph]:
    """Try to run dynamic tracing on demo module."""
    try:
        demo_main = os.path.join(project_path, "auth.py")
        if not os.path.exists(demo_main):
            return None

        # Import and trace the demo
        sys.path.insert(0, os.path.dirname(project_path))
        module_name = os.path.basename(project_path)

        tracer = LineTracer()
        try:
            from demo.auth import authenticate
            tracer.start()
            try:
                authenticate("alice", "correct_password")
            except Exception:
                pass
            tracer.stop()
        except ImportError:
            return None

        if tracer.events:
            graph = tracer.to_graph()
            print(f"  → {len(tracer.events)} trace events, {graph.stats()['nodes']} nodes")
            return graph
    except Exception as e:
        print(f"  → Dynamic trace skipped: {e}")
    return None


def _try_exception_trace(project_path: str, error_file: Optional[str]) -> Optional[CausalGraph]:
    """Try to capture exception from demo execution."""
    try:
        if not error_file:
            return None

        parser = ExceptionParser()
        try:
            sys.path.insert(0, os.path.dirname(project_path))
            from demo.auth import authenticate
            catch_and_parse(authenticate, "alice", "correct_password")
        except Exception:
            pass

        parsed = parser.parse_current_exception()
        if parsed:
            graph = parser.build_graph(parsed)
            print(f"  → Exception: {parsed.exception_type}: {parsed.message}")
            print(f"    {len(parsed.frames)} frames")
            return graph
    except Exception as e:
        print(f"  → Exception parsing skipped: {e}")
    return None


# ── CLI ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Why-Code-Agent: Code Causality Intelligence",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py demo                              Run the login failure demo
  python main.py analyze --project demo/ --error demo/auth.py:29
  python main.py explain --file demo/auth.py --line 17
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # analyze command
    analyze_p = subparsers.add_parser("analyze", help="Full causal analysis")
    analyze_p.add_argument("--project", required=True, help="Project directory to analyze")
    analyze_p.add_argument("--error", help="Error location (file:line)")
    analyze_p.add_argument("--config", help="Configuration file path")
    analyze_p.add_argument("--output", default="output", help="Output directory")
    analyze_p.add_argument("--provider", default="anthropic", choices=["anthropic", "openai", "mock"])
    analyze_p.add_argument("--model", default="claude-sonnet-4-20250514")

    # explain command
    explain_p = subparsers.add_parser("explain", help="Explain why a code line exists")
    explain_p.add_argument("--file", required=True, help="Source file path")
    explain_p.add_argument("--line", required=True, type=int, help="Line number")
    explain_p.add_argument("--provider", default="anthropic", choices=["anthropic", "openai", "mock"])
    explain_p.add_argument("--model", default="claude-sonnet-4-20250514")

    # demo command
    subparsers.add_parser("demo", help="Run the login failure demo")

    args = parser.parse_args()

    if args.command == "analyze":
        error_file, error_line = None, None
        if args.error:
            parts = args.error.rsplit(":", 1)
            error_file = parts[0]
            error_line = int(parts[1]) if len(parts) > 1 else None
        run_analysis(
            project_path=args.project,
            error_file=error_file,
            error_line=error_line,
            config_file=args.config,
            output_dir=args.output,
            llm_provider=args.provider,
            llm_model=args.model,
        )
    elif args.command == "explain":
        run_explain(
            file_path=args.file,
            line_number=args.line,
            llm_provider=args.provider,
            llm_model=args.model,
        )
    elif args.command == "demo":
        run_demo()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
