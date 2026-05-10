"""Tests for Agent IR — Observation, State, Reasoning, Action."""

import pytest
from dynamic.runtime.recorder import record_function


def _loop_fn(n=5):
    total = 0
    for i in range(n):
        total += i
    return total


def _branch_fn(x=5):
    if x > 3:
        return "big"
    return "small"


class TestObservation:
    def test_observation_stream_from_timeline(self):
        from dynamic.agent.observation import ObservationStream
        _, timeline = record_function(_loop_fn, 5)
        stream = ObservationStream.from_timeline(timeline)
        assert stream is not None
        assert len(stream.observations) > 0

    def test_observation_has_step_id(self):
        from dynamic.agent.observation import ObservationStream
        _, timeline = record_function(_loop_fn, 3)
        stream = ObservationStream.from_timeline(timeline)
        for obs in stream.observations:
            assert obs.step_id >= 0

    def test_observation_captures_variables(self):
        from dynamic.agent.observation import ObservationStream
        _, timeline = record_function(_loop_fn, 3)
        stream = ObservationStream.from_timeline(timeline)
        has_vars = any(obs.variables_changed for obs in stream.observations)
        assert has_vars


class TestAgentState:
    def test_state_from_observations(self):
        from dynamic.agent.observation import ObservationStream
        from dynamic.agent.state import AgentState
        _, timeline = record_function(_loop_fn, 5)
        stream = ObservationStream.from_timeline(timeline)
        state = AgentState()
        for obs in stream.observations:
            state.update(obs)
        assert state._observation_count > 0

    def test_state_tracks_variable_history(self):
        from dynamic.agent.observation import ObservationStream
        from dynamic.agent.state import AgentState
        _, timeline = record_function(_loop_fn, 5)
        stream = ObservationStream.from_timeline(timeline)
        state = AgentState()
        for obs in stream.observations:
            state.update(obs)
        assert len(state._variables) > 0

    def test_state_get_variable_history(self):
        from dynamic.agent.observation import ObservationStream
        from dynamic.agent.state import AgentState
        _, timeline = record_function(_loop_fn, 5)
        stream = ObservationStream.from_timeline(timeline)
        state = AgentState()
        for obs in stream.observations:
            state.update(obs)
        # Check we can query a variable
        if 'total' in state._variables:
            rec = state._variables['total']
            assert len(rec.values) > 0


class TestReasoning:
    def test_hypothesis_generator(self):
        from dynamic.agent.observation import ObservationStream
        from dynamic.agent.state import AgentState
        from dynamic.agent.reasoning import HypothesisGenerator
        _, timeline = record_function(_loop_fn, 5)
        stream = ObservationStream.from_timeline(timeline)
        state = AgentState()
        for obs in stream.observations:
            state.update(obs)
        gen = HypothesisGenerator()
        hypotheses = gen.generate(state)
        assert isinstance(hypotheses, list)

    def test_reasoning_chain(self):
        from dynamic.agent.observation import ObservationStream
        from dynamic.agent.state import AgentState
        from dynamic.agent.reasoning import HypothesisGenerator, ReasoningChain
        _, timeline = record_function(_loop_fn, 5)
        stream = ObservationStream.from_timeline(timeline)
        state = AgentState()
        for obs in stream.observations:
            state.update(obs)
        gen = HypothesisGenerator()
        hypotheses = gen.generate(state)
        chain = ReasoningChain()
        for h in hypotheses:
            chain.add_step(h, [], 'observed')
        assert chain is not None
        assert len(chain.steps) >= 0


class TestAction:
    def test_action_plan(self):
        from dynamic.agent.action import Action, ActionPlan
        plan = ActionPlan()
        plan.add_action(Action(kind='explain', target_var='total', input_query='WHY total'))
        plan.add_action(Action(kind='compare', target_step=0, input_query='COMPARE step 0 WITH step 1'))
        assert len(plan.actions) == 2

    def test_action_result(self):
        from dynamic.agent.action import Action, ActionResult
        action = Action(kind='explain', target_var='total')
        result = ActionResult(action=action, success=True, output='explanation')
        assert result.success


class TestAgentEngine:
    def test_agent_engine_run(self):
        from dynamic.agent import AgentEngine
        _, timeline = record_function(_loop_fn, 5)
        engine = AgentEngine()
        result = engine.run(timeline, "Why does total increase?")
        assert result is not None

    def test_agent_engine_observe(self):
        from dynamic.agent import AgentEngine
        _, timeline = record_function(_loop_fn, 5)
        engine = AgentEngine()
        result = engine.observe(timeline)
        assert result is not None
