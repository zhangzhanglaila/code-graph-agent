"""Dependency container — single source of truth for engine instances.

Enables:
    - Mock/test: replace engines with fakes
    - Plugin: swap engines at runtime
    - Singleton: one instance per request lifecycle
    - Replace: swap runtime engine without touching routes

Usage:
    from api.container import get_container, AppContainer

    @router.post("/api/analyze")
    async def analyze(req, container: AppContainer = Depends(get_container)):
        return container.analysis_service.analyze(req)
"""

from __future__ import annotations
import os
import sys
from dataclasses import dataclass
from typing import Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


@dataclass
class PipelineContext:
    """Pre-built pipeline: pdg + facts + engine + executor."""
    pdg: object
    facts: list
    engine: object
    executor: object


class AppContainer:
    """Central dependency container. All engine access goes through here."""

    def __init__(self):
        self._instances = {}

    # ── Runtime engines ───────────────────────────────────────────

    @property
    def recorder(self):
        """Execution recorder — records function execution into timeline."""
        if "recorder" not in self._instances:
            from dynamic.runtime.recorder import record_function
            self._instances["recorder"] = record_function
        return self._instances["recorder"]

    @property
    def pdg_class(self):
        """RuntimePDG class — builds program dependency graph from timeline."""
        if "pdg_class" not in self._instances:
            from dynamic.runtime.pdg import RuntimePDG
            self._instances["pdg_class"] = RuntimePDG
        return self._instances["pdg_class"]

    # ── Semantic engines ──────────────────────────────────────────

    @property
    def fact_extractor_class(self):
        if "fact_extractor_class" not in self._instances:
            from dynamic.semantic.facts import FactExtractor
            self._instances["fact_extractor_class"] = FactExtractor
        return self._instances["fact_extractor_class"]

    @property
    def narrative_engine_class(self):
        if "narrative_engine_class" not in self._instances:
            from dynamic.semantic.narrative import NarrativeEngine
            self._instances["narrative_engine_class"] = NarrativeEngine
        return self._instances["narrative_engine_class"]

    @property
    def identity_engine_class(self):
        if "identity_engine_class" not in self._instances:
            from dynamic.semantic.identity import SemanticIdentifier
            self._instances["identity_engine_class"] = SemanticIdentifier
        return self._instances["identity_engine_class"]

    @property
    def normalizer_class(self):
        if "normalizer_class" not in self._instances:
            from dynamic.semantic.identity_normalizer import IdentityNormalizer
            self._instances["normalizer_class"] = IdentityNormalizer
        return self._instances["normalizer_class"]

    @property
    def fingerprint_class(self):
        if "fingerprint_class" not in self._instances:
            from dynamic.semantic.fingerprint import SemanticFingerprint
            self._instances["fingerprint_class"] = SemanticFingerprint
        return self._instances["fingerprint_class"]

    @property
    def ontology_class(self):
        if "ontology_class" not in self._instances:
            from dynamic.semantic.ontology import SemanticOntology
            self._instances["ontology_class"] = SemanticOntology
        return self._instances["ontology_class"]

    @property
    def similarity_class(self):
        if "similarity_class" not in self._instances:
            from dynamic.semantic.similarity import SemanticSimilarity
            self._instances["similarity_class"] = SemanticSimilarity
        return self._instances["similarity_class"]

    @property
    def diff_class(self):
        if "diff_class" not in self._instances:
            from dynamic.semantic.diff import SemanticDiffer
            self._instances["diff_class"] = SemanticDiffer
        return self._instances["diff_class"]

    @property
    def failure_attribution_class(self):
        if "failure_attribution_class" not in self._instances:
            from dynamic.semantic.failure_attribution import FailureAttribution
            self._instances["failure_attribution_class"] = FailureAttribution
        return self._instances["failure_attribution_class"]

    @property
    def causal_chain_class(self):
        if "causal_chain_class" not in self._instances:
            from dynamic.semantic.causal_chain import CausalChainEngine
            self._instances["causal_chain_class"] = CausalChainEngine
        return self._instances["causal_chain_class"]

    @property
    def narrator_class(self):
        if "narrator_class" not in self._instances:
            from dynamic.semantic.narrator import SemanticNarrator
            self._instances["narrator_class"] = SemanticNarrator
        return self._instances["narrator_class"]

    @property
    def semantic_ir_builder(self):
        """SemanticExecutionModel builder — lowers RuntimePDG to semantic IR."""
        if "semantic_ir_builder" not in self._instances:
            from dynamic.semantic_ir import build_from_pdg
            self._instances["semantic_ir_builder"] = build_from_pdg
        return self._instances["semantic_ir_builder"]

    @property
    def feedback_loop(self):
        """Execution feedback loop — tracks action outcomes."""
        if "feedback_loop" not in self._instances:
            from dynamic.semantic.narrator import get_feedback_loop
            self._instances["feedback_loop"] = get_feedback_loop()
        return self._instances["feedback_loop"]

    @property
    def consolidation_engine(self):
        """Memory consolidation engine — cross-session learning."""
        if "consolidation_engine" not in self._instances:
            from dynamic.semantic.narrator import get_consolidation_engine
            self._instances["consolidation_engine"] = get_consolidation_engine()
        return self._instances["consolidation_engine"]

    @property
    def validation_engine(self):
        """Concept validation engine — validates learned concepts."""
        if "validation_engine" not in self._instances:
            from dynamic.semantic.narrator import get_validation_engine
            self._instances["validation_engine"] = get_validation_engine()
        return self._instances["validation_engine"]

    # ── Query engines ─────────────────────────────────────────────

    @property
    def query_executor_class(self):
        if "query_executor_class" not in self._instances:
            from dynamic.query.dsl import QueryExecutor
            self._instances["query_executor_class"] = QueryExecutor
        return self._instances["query_executor_class"]

    @property
    def agent_engine_class(self):
        if "agent_engine_class" not in self._instances:
            from dynamic.agent import AgentEngine
            self._instances["agent_engine_class"] = AgentEngine
        return self._instances["agent_engine_class"]

    @property
    def parse_query(self):
        if "parse_query" not in self._instances:
            from dynamic.query.dsl import parse_query
            self._instances["parse_query"] = parse_query
        return self._instances["parse_query"]

    @property
    def parse_temporal_query(self):
        if "parse_temporal_query" not in self._instances:
            from dynamic.query.temporal import parse_temporal_query
            self._instances["parse_temporal_query"] = parse_temporal_query
        return self._instances["parse_temporal_query"]

    # ── Pipeline builder ──────────────────────────────────────────

    def build_pipeline(self, timeline) -> PipelineContext:
        """Build the full analysis pipeline from a timeline.

        Returns PipelineContext with pdg, facts, engine, executor.
        Single source of truth for pipeline construction.
        """
        from dynamic.query.execution_metrics import execution_metrics

        with execution_metrics.stage('pdg_build'):
            pdg = self.pdg_class.from_timeline(timeline)

        with execution_metrics.stage('fact_extraction'):
            facts = self.fact_extractor_class(pdg).extract_all()

        with execution_metrics.stage('narrative_init'):
            engine = self.narrative_engine_class(pdg, facts)

        executor = self.query_executor_class(pdg, facts, engine)
        return PipelineContext(pdg=pdg, facts=facts, engine=engine, executor=executor)

    # ── Service layer ─────────────────────────────────────────────

    @property
    def analysis_service(self):
        if "analysis_service" not in self._instances:
            from api.services import analysis
            self._instances["analysis_service"] = analysis
        return self._instances["analysis_service"]

    # ── Plugin API ────────────────────────────────────────────────

    def replace(self, name: str, instance):
        """Replace an engine at runtime. Enables plugin/swap."""
        self._instances[name] = instance

    def reset(self):
        """Reset all instances. Useful for testing."""
        self._instances.clear()


# ── Singleton + FastAPI Depends ──────────────────────────────────

_container: Optional[AppContainer] = None


def get_container() -> AppContainer:
    """FastAPI dependency. Returns the singleton container."""
    global _container
    if _container is None:
        _container = AppContainer()
    return _container


def reset_container():
    """Reset the global container. For testing."""
    global _container
    _container = None
