"""Default build pipeline — maps code → timeline → pdg → facts → identity → narrative.

This is the canonical computation pipeline for the Why-Code-Agent system.
Each step is a PipelineNode that consumes artifacts and produces new ones.

Usage:
    from dynamic.artifacts.pipeline import build_pipeline, run_full
    graph = build_pipeline()
    result = run_full(graph, source_code, func_name="fibonacci")
"""

from __future__ import annotations
import os
import sys
from typing import Any, Dict

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from dynamic.artifacts.graph import ArtifactGraph, PipelineNode, Artifact


# ── Pipeline node functions ──────────────────────────────────────

def _compute_timeline(code: str) -> Any:
    """Execute code and produce an ExecutionTimeline."""
    from dynamic.runtime.recorder import record_function
    from api.services.helpers import extract_func_name, import_code_as_module
    from api.input_inference import infer_args

    func_name = extract_func_name(code, "")
    module = import_code_as_module(code)
    func = getattr(module, func_name)
    func_file = os.path.abspath(func.__code__.co_filename)
    inferred_args, _ = infer_args(func, code)
    result, timeline = record_function(func, *inferred_args, target_files={func_file})
    try:
        os.unlink(func_file)
    except OSError:
        pass
    return timeline


def _compute_pdg(timeline: Any) -> Any:
    """Build RuntimePDG from timeline."""
    from dynamic.runtime.pdg import RuntimePDG
    return RuntimePDG.from_timeline(timeline)


def _compute_semantic_model(pdg: Any) -> Any:
    """Lower RuntimePDG to SemanticExecutionModel (language-agnostic IR)."""
    from dynamic.semantic_ir import build_from_pdg
    return build_from_pdg(pdg)


def _compute_facts(semantic_model: Any) -> Any:
    """Extract semantic facts from SemanticExecutionModel."""
    from dynamic.semantic.facts import FactExtractor
    return FactExtractor(semantic_model).extract_all()


def _compute_identity(semantic_model: Any, facts: Any) -> Any:
    """Identify semantic archetypes from SemanticExecutionModel."""
    from dynamic.semantic.identity import SemanticIdentifier
    return SemanticIdentifier.identify(semantic_model, facts)


def _compute_fingerprint(semantic_model: Any, facts: Any) -> Any:
    """Generate execution fingerprint from SemanticExecutionModel."""
    from dynamic.semantic.fingerprint import SemanticFingerprint
    return SemanticFingerprint.generate(semantic_model, facts)


def _compute_narrative(semantic_model: Any, facts: Any) -> Any:
    """Build narrative engine from SemanticExecutionModel."""
    from dynamic.semantic.narrative import NarrativeEngine
    return NarrativeEngine(semantic_model, facts)


def _compute_steps_data(timeline: Any) -> Any:
    """Convert timeline to serializable step dicts."""
    from api.services.analysis import build_steps_data
    return build_steps_data(timeline)


# ── Pipeline definition ──────────────────────────────────────────

DEFAULT_NODES = [
    PipelineNode(kind="timeline", compute_fn=_compute_timeline, input_kinds=["code"]),
    PipelineNode(kind="steps_data", compute_fn=_compute_steps_data, input_kinds=["timeline"]),
    PipelineNode(kind="pdg", compute_fn=_compute_pdg, input_kinds=["timeline"]),
    PipelineNode(kind="semantic_model", compute_fn=_compute_semantic_model, input_kinds=["pdg"]),
    PipelineNode(kind="facts", compute_fn=_compute_facts, input_kinds=["semantic_model"]),
    PipelineNode(kind="identity", compute_fn=_compute_identity, input_kinds=["semantic_model", "facts"]),
    PipelineNode(kind="fingerprint", compute_fn=_compute_fingerprint, input_kinds=["semantic_model", "facts"]),
    PipelineNode(kind="narrative", compute_fn=_compute_narrative, input_kinds=["semantic_model", "facts"]),
]


def build_pipeline() -> ArtifactGraph:
    """Create a pipeline graph with all default nodes registered."""
    graph = ArtifactGraph()
    graph.register_many(DEFAULT_NODES)
    return graph


def run_full(graph: ArtifactGraph, code: str, version: str = "") -> Dict[str, Artifact]:
    """Run the full pipeline from code. Returns all artifacts."""
    code_art = graph.ingest("code", code, version=version)

    timeline_art = graph.compute("timeline", {"code": code_art})
    steps_art = graph.compute("steps_data", {"timeline": timeline_art})
    pdg_art = graph.compute("pdg", {"timeline": timeline_art})
    model_art = graph.compute("semantic_model", {"pdg": pdg_art})
    facts_art = graph.compute("facts", {"semantic_model": model_art})
    identity_art = graph.compute("identity", {"semantic_model": model_art, "facts": facts_art})
    fingerprint_art = graph.compute("fingerprint", {"semantic_model": model_art, "facts": facts_art})
    narrative_art = graph.compute("narrative", {"semantic_model": model_art, "facts": facts_art})

    return {
        "code": code_art,
        "timeline": timeline_art,
        "steps_data": steps_art,
        "pdg": pdg_art,
        "semantic_model": model_art,
        "facts": facts_art,
        "identity": identity_art,
        "fingerprint": fingerprint_art,
        "narrative": narrative_art,
    }
