"""Artifact Graph — content-addressable build pipeline.

Core abstractions:
    Artifact       — a content-addressed computation result
    PipelineNode   — a computation step with typed inputs/outputs
    ArtifactGraph  — the DAG of nodes and artifacts

Usage:
    graph = ArtifactGraph()
    code_artifact = graph.ingest("code", source_code, version="1.0")
    timeline_artifact = graph.compute("timeline", {"code": code_artifact})
    pdg_artifact = graph.compute("pdg", {"timeline": timeline_artifact})

    # If source_code changes, timeline + pdg are transitively invalidated
    code_artifact.invalidate()
    graph.recompute()  # only recomputes what changed
"""

from __future__ import annotations
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set


def content_hash(*parts: Any) -> str:
    """Deterministic hash of arbitrary content."""
    h = hashlib.sha256()
    for part in parts:
        if isinstance(part, bytes):
            h.update(part)
        elif isinstance(part, str):
            h.update(part.encode("utf-8"))
        else:
            h.update(json.dumps(part, sort_keys=True, default=str).encode("utf-8"))
    return h.hexdigest()[:16]


@dataclass
class Artifact:
    """A content-addressed computation result."""

    artifact_id: str
    kind: str                  # "code", "timeline", "pdg", "facts", "identity", ...
    content_hash: str          # hash of inputs + version
    data: Any = None           # the actual computed result
    metadata: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    valid: bool = True
    inputs: Dict[str, str] = field(default_factory=dict)  # kind → artifact_id

    def invalidate(self):
        """Mark this artifact and all downstream as stale."""
        self.valid = False

    def to_dict(self) -> dict:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "content_hash": self.content_hash,
            "valid": self.valid,
            "inputs": self.inputs,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


@dataclass
class PipelineNode:
    """A computation step in the build pipeline.

    Each node:
        - consumes input artifacts by kind
        - produces an output artifact
        - can be invalidated and recomputed
    """

    kind: str                              # output kind
    compute_fn: Callable[..., Any]         # (input_data) → output_data
    input_kinds: List[str] = field(default_factory=list)  # required input kinds

    def compute(self, inputs: Dict[str, Artifact]) -> Any:
        """Run the computation with resolved inputs."""
        input_data = {k: inputs[k].data for k in self.input_kinds if k in inputs}
        return self.compute_fn(**input_data)


class ArtifactGraph:
    """The build pipeline DAG.

    Manages artifacts and pipeline nodes. Supports:
        - ingest: create an artifact from external input
        - compute: run a pipeline node to produce an artifact
        - invalidate: mark artifacts stale
        - recompute: only recompute what changed
    """

    def __init__(self):
        self.artifacts: Dict[str, Artifact] = {}          # artifact_id → Artifact
        self.nodes: Dict[str, PipelineNode] = {}          # kind → PipelineNode
        self._kind_index: Dict[str, List[str]] = {}       # kind → [artifact_id, ...]
        self._downstream: Dict[str, Set[str]] = {}        # artifact_id → {dependent artifact_ids}

    # ── Node registration ────────────────────────────────────────

    def register(self, node: PipelineNode):
        """Register a pipeline node."""
        self.nodes[node.kind] = node

    def register_many(self, nodes: List[PipelineNode]):
        for node in nodes:
            self.register(node)

    # ── Artifact creation ────────────────────────────────────────

    def ingest(self, kind: str, data: Any, version: str = "", metadata: dict = None) -> Artifact:
        """Create an artifact from external input (code, config, etc.)."""
        h = content_hash(data, version)
        artifact_id = f"{kind}:{h}"

        if artifact_id in self.artifacts:
            existing = self.artifacts[artifact_id]
            existing.valid = True
            return existing

        artifact = Artifact(
            artifact_id=artifact_id,
            kind=kind,
            content_hash=h,
            data=data,
            metadata=metadata or {},
        )
        self.artifacts[artifact_id] = artifact
        self._kind_index.setdefault(kind, []).append(artifact_id)
        return artifact

    def compute(self, kind: str, inputs: Dict[str, Artifact], metadata: dict = None) -> Artifact:
        """Run a pipeline node to produce an artifact."""
        node = self.nodes.get(kind)
        if not node:
            raise ValueError(f"No pipeline node registered for kind: {kind}")

        # Build content hash from inputs
        input_hashes = {k: a.content_hash for k, a in inputs.items()}
        h = content_hash(kind, input_hashes)
        artifact_id = f"{kind}:{h}"

        # Cache hit
        if artifact_id in self.artifacts and self.artifacts[artifact_id].valid:
            return self.artifacts[artifact_id]

        # Compute
        data = node.compute(inputs)
        artifact = Artifact(
            artifact_id=artifact_id,
            kind=kind,
            content_hash=h,
            data=data,
            metadata=metadata or {},
            inputs={k: a.artifact_id for k, a in inputs.items()},
        )
        self.artifacts[artifact_id] = artifact
        self._kind_index.setdefault(kind, []).append(artifact_id)

        # Track downstream dependencies
        for inp in inputs.values():
            self._downstream.setdefault(inp.artifact_id, set()).add(artifact_id)

        return artifact

    # ── Invalidation ─────────────────────────────────────────────

    def invalidate(self, artifact_id: str):
        """Invalidate an artifact and all downstream transitively."""
        if artifact_id not in self.artifacts:
            return

        visited = set()
        queue = [artifact_id]
        while queue:
            aid = queue.pop(0)
            if aid in visited:
                continue
            visited.add(aid)
            if aid in self.artifacts:
                self.artifacts[aid].valid = False
            for dep in self._downstream.get(aid, set()):
                if dep not in visited:
                    queue.append(dep)

    def invalidate_kind(self, kind: str):
        """Invalidate all artifacts of a given kind."""
        for aid in self._kind_index.get(kind, []):
            self.invalidate(aid)

    # ── Recomputation ────────────────────────────────────────────

    def recompute(self) -> List[str]:
        """Recompute all invalid artifacts. Returns list of recomputed artifact IDs."""
        recomputed = []

        # Topological sort: process nodes whose inputs are all valid
        changed = True
        while changed:
            changed = False
            for kind, node in self.nodes.items():
                for aid in self._kind_index.get(kind, []):
                    art = self.artifacts[aid]
                    if art.valid:
                        continue

                    # Check if all inputs are valid
                    inputs_valid = True
                    for inp_kind, inp_aid in art.inputs.items():
                        if inp_aid in self.artifacts and not self.artifacts[inp_aid].valid:
                            inputs_valid = False
                            break

                    if not inputs_valid:
                        continue

                    # Recompute
                    resolved_inputs = {}
                    for inp_kind, inp_aid in art.inputs.items():
                        if inp_aid in self.artifacts:
                            resolved_inputs[inp_kind] = self.artifacts[inp_aid]

                    new_data = node.compute(resolved_inputs)
                    art.data = new_data
                    art.valid = True
                    art.created_at = time.time()
                    recomputed.append(aid)
                    changed = True

        return recomputed

    # ── Query ────────────────────────────────────────────────────

    def get_latest(self, kind: str) -> Optional[Artifact]:
        """Get the most recent valid artifact of a given kind."""
        for aid in reversed(self._kind_index.get(kind, [])):
            art = self.artifacts[aid]
            if art.valid:
                return art
        return None

    def get_by_id(self, artifact_id: str) -> Optional[Artifact]:
        return self.artifacts.get(artifact_id)

    def is_valid(self, artifact_id: str) -> bool:
        art = self.artifacts.get(artifact_id)
        return art is not None and art.valid

    def stats(self) -> dict:
        total = len(self.artifacts)
        valid = sum(1 for a in self.artifacts.values() if a.valid)
        return {
            "total_artifacts": total,
            "valid_artifacts": valid,
            "invalid_artifacts": total - valid,
            "pipeline_nodes": len(self.nodes),
            "kinds": list(self._kind_index.keys()),
        }
