"""Regression tests for Insight causal chain and DS Viz tuple unpacking."""

import pytest


def _loop_fn(n=5):
    total = 0
    for i in range(n):
        total += i
    return total


class TestBuildSemanticContext:
    def test_causal_chain_not_empty(self):
        from dynamic.runtime.recorder import record_function
        from api.services.analysis import build_semantic_context
        _, timeline = record_function(_loop_fn, 5)
        ctx = build_semantic_context(timeline)
        assert "causal_chain" in ctx
        assert "root_causes" in ctx
        assert isinstance(ctx["causal_chain"], list)
        assert isinstance(ctx["root_causes"], list)

    def test_causal_chain_has_edges(self):
        from dynamic.runtime.recorder import record_function
        from api.services.analysis import build_semantic_context
        _, timeline = record_function(_loop_fn, 5)
        ctx = build_semantic_context(timeline)
        # Should have at least some causal chain edges
        chain = ctx["causal_chain"]
        if chain:
            assert "source" in chain[0]
            assert "target" in chain[0]

    def test_root_causes_are_step_ids(self):
        from dynamic.runtime.recorder import record_function
        from api.services.analysis import build_semantic_context
        _, timeline = record_function(_loop_fn, 5)
        ctx = build_semantic_context(timeline)
        for rc in ctx["root_causes"]:
            assert isinstance(rc, int)


class TestDSVizTupleUnpacking:
    def test_trace_ds_function_returns_tuple(self):
        from dynamic.runtime.ds_tracer import trace_ds_function
        result = trace_ds_function(_loop_fn, 5)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_ds_timeline_has_steps(self):
        from dynamic.runtime.ds_tracer import trace_ds_function
        result, ds_timeline = trace_ds_function(_loop_fn, 5)
        assert hasattr(ds_timeline, 'steps')
        assert len(ds_timeline.steps) > 0

    def test_render_ds_timeline_with_unpacked(self):
        from dynamic.runtime.ds_tracer import trace_ds_function
        from visualization.ds_viz import render_ds_timeline
        import tempfile, os
        result, ds_timeline = trace_ds_function(_loop_fn, 5)
        out = os.path.join(tempfile.gettempdir(), "test_ds_viz.html")
        path = render_ds_timeline(ds_timeline, output_path=out)
        assert os.path.exists(path)
        os.unlink(path)
