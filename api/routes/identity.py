"""Identity routes — semantic identity, fingerprint, similarity, diff."""

from __future__ import annotations
import os
import sys

from fastapi import APIRouter, Depends

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from dynamic.runtime.pdg import RuntimePDG
from dynamic.semantic.facts import FactExtractor
from dynamic.semantic.identity import SemanticIdentifier
from dynamic.semantic.identity_normalizer import IdentityNormalizer
from dynamic.semantic.fingerprint import SemanticFingerprint
from dynamic.semantic.similarity import SemanticSimilarity
from dynamic.semantic.ontology import SemanticOntology
from dynamic.semantic.diff import SemanticDiffer
from dynamic.semantic.narrative import NarrativeEngine

from api.services.analysis import prepare_execution, build_semantic_context
from api.schemas.identity import IdentityRequest, SimilarityRequest, SemanticDiffRequest
from api.container import get_container, AppContainer

router = APIRouter()


# ── Routes ───────────────────────────────────────────────────────

@router.post("/api/identity")
async def semantic_identity(req: IdentityRequest):
    """Recognize semantic archetypes in code execution."""
    func_file = None
    try:
        module, func, timeline, result, func_file = prepare_execution(
            req.code, req.func_name, req.language,
        )

        pdg = RuntimePDG.from_timeline(timeline)
        facts = FactExtractor(pdg).extract_all()
        identities = SemanticIdentifier.identify(pdg, facts)
        normal_form = IdentityNormalizer.normalize(identities, pdg)
        fingerprint = SemanticFingerprint.generate(pdg, facts)

        # Ontology enrichment
        ontology = SemanticOntology.default()
        enriched = {}
        for ci in normal_form.canonical_identities:
            concept = ontology.get(ci.canonical_id)
            if concept:
                enriched[ci.canonical_id] = {
                    'ancestors': ontology.ancestors(ci.canonical_id),
                    'siblings': ontology.siblings(ci.canonical_id),
                    'complexity_implication': concept.complexity_implication,
                    'common_mistakes': concept.common_mistakes,
                    'behaviors': concept.behaviors,
                    'invariants': concept.invariants,
                }

        return {
            "success": True,
            "identities": identities.to_dict(),
            "normal_form": normal_form.to_dict(),
            "fingerprint": fingerprint.to_dict(),
            "ontology": enriched,
        }
    except Exception as e:
        import traceback
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
    finally:
        if func_file:
            try:
                os.unlink(func_file)
            except OSError:
                pass


@router.post("/api/similarity")
async def semantic_similarity(req: SimilarityRequest):
    """Compare two code executions at the semantic level."""
    func_file_a = func_file_b = None
    try:
        _, _, tl_a, _, func_file_a = prepare_execution(req.code_a, req.func_name)
        _, _, tl_b, _, func_file_b = prepare_execution(req.code_b, req.func_name)

        pdg_a = RuntimePDG.from_timeline(tl_a)
        facts_a = FactExtractor(pdg_a).extract_all()
        fp_a = SemanticFingerprint.generate(pdg_a, facts_a)

        pdg_b = RuntimePDG.from_timeline(tl_b)
        facts_b = FactExtractor(pdg_b).extract_all()
        fp_b = SemanticFingerprint.generate(pdg_b, facts_b)

        ontology = SemanticOntology.default()
        engine = SemanticSimilarity()
        result = engine.compare(fp_a, fp_b, ontology)

        return {
            "success": True,
            "similarity": result.to_dict(),
            "fingerprint_a": fp_a.to_dict(),
            "fingerprint_b": fp_b.to_dict(),
        }
    except Exception as e:
        import traceback
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
    finally:
        for f in [func_file_a, func_file_b]:
            if f:
                try:
                    os.unlink(f)
                except OSError:
                    pass


@router.post("/api/semantic_diff")
async def semantic_diff(req: SemanticDiffRequest):
    """Semantic diff between two code executions."""
    func_file_a = func_file_b = None
    try:
        _, _, tl_a, _, func_file_a = prepare_execution(req.code_a, req.func_name)
        _, _, tl_b, _, func_file_b = prepare_execution(req.code_b, req.func_name)

        ctx_a = build_semantic_context(tl_a)
        ctx_b = build_semantic_context(tl_b)

        differ = SemanticDiffer()
        diff = differ.compare(
            ctx_a["pdg"], ctx_a["facts"], ctx_b["pdg"], ctx_b["facts"],
        )

        return {"success": True, "diff": diff.to_dict()}
    except Exception as e:
        import traceback
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
    finally:
        for f in [func_file_a, func_file_b]:
            if f:
                try:
                    os.unlink(f)
                except OSError:
                    pass
