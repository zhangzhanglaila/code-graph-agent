"""Artifact Graph — content-addressable build pipeline.

Every computation result is an Artifact with a content hash.
Pipeline nodes compute artifacts from inputs.
When inputs change, downstream artifacts are transitively invalidated.
"""

from dynamic.artifacts.graph import ArtifactGraph, Artifact, PipelineNode
