"""Semantic layer — meaning, identity, reasoning, narration.

Contract:
    All modules in this layer MUST be pure functions over runtime artifacts.
    No runtime→semantic imports allowed.
    No implicit global state (except narrator.py singletons, which are
    service-layer concerns and should be accessed via api.container).

Input:  ExecutionTimeline, RuntimePDG, Facts
Output: Identity, Fingerprint, Similarity, Narrative, Diff
"""
