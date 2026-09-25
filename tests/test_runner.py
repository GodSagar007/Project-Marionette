"""Tests for the runner: agent loop, lifecycle events, error paths.

These tests inject a fake adapter so no live API calls happen. The fake
returns whatever canned Turn objects the test supplies, so each test fully
controls what the "model" says and the runner's response is the variable
under test.
"""
from pathlib import Path
from typing import cast

import pytest

from marionette.adapter.anthropic import (
    AdapterError,
    AdapterErrorType,
    AnthropicAdapter,
)
from marionette.adapter.conversation import Conversation, ToolUseContent, Turn
from marionette.context import RunContext
from marionette.gateway import Tool
from marionette.runner import MAX_TURNS, AgentSpec, Scenario, run
from marionette.tools.echo import EchoArgs, EchoResult, EchoTool
from marionette.tools.message import SendMessageTool
from marionette.trace.reader import TraceReader
from marionette.trace.schema import TokenUsage


def make_turn(**kwargs: object) -> Turn:
    """Build a Turn with test defaults for the call-metadata fields."""
    kwargs.setdefault("stop_reason", "end_turn")
    kwargs.setdefault("duration_ms", 0)
    return Turn(**kwargs)  # type: ignore[arg-type]

# --- Fake adapter ---

class FakeAdapter:
    """A test double for AnthropicAdapter.

    Returns canned Turn objects on successive get_turn() calls. Used in tests
    to fully control what the "model" says without making real API calls.
    """

    def __init__(self, turns: list[Turn]) -> None:
        self._turns = turns
        self._call_count = 0
        self.calls_received: list[Conversation] = []  # for assertion in tests

    def get_turn(self, conversation: Conversation) -> Turn:
        self.calls_received.append(conversation)
        if self._call_count >= len(self._turns):
            raise RuntimeError(
                f"FakeAdapter exhausted after {self._call_count} calls; "
                f"test supplied {len(self._turns)} Turn(s)"
            )
        turn = self._turns[self._call_count]
        self._call_count += 1
        return turn


class FailingFakeAdapter:
    """A test double that raises an AdapterError on the first get_turn call."""

    def __init__(self, error: AdapterError) -> None:
        self._error = error

    def get_turn(self, conversation: Conversation) -> Turn:
        raise self._error


def _as_adapter(fake: object) -> AnthropicAdapter | None:
    """Cast a fake to AnthropicAdapter | None for the runner's type signature.

    The runner is typed against the concrete adapter class. Structurally our
    fakes satisfy the same interface (a get_turn method), so the cast is safe;
    we just need to tell mypy we know what we're doing at the boundary.
    """
    return cast(AnthropicAdapter, fake)


# --- Scenarios for tests ---

def _make_scenario() -> Scenario:
    return Scenario.single_agent(
        id="test-scenario",
        system_prompt="You are a test agent.",
        initial_user_message="Begin the test.",
        tools=[EchoTool()],
    )


# --- Helpers ---

def _read_events(path: Path) -> list[tuple[int, str, str]]:
    """Read a trace and return (seq, event_type, actor) tuples for assertion."""
    with TraceReader(path) as reader:
        return [(e.seq, e.event, e.actor) for e in reader]


# --- 1. Successful single-turn run ---

def test_single_turn_run_produces_clean_trace(tmp_path: Path) -> None:
    """A run where the model finishes in one turn produces run_started,

    agent_message, model_response, run_completed."""
    fake = FakeAdapter(turns=[make_turn(text="task complete")])
    result = run(
        scenario=_make_scenario(),
        model="claude-test",
        output_root=tmp_path,
        adapter=_as_adapter(fake),
    )

    assert result.status == "ok"
    assert result.abort_reason is None

    events = _read_events(result.trace_path)
    assert events[0][1] == "run_started"
    assert events[1] == (1, "agent_message", "agent")
    assert events[2][1] == "model_response"
    assert events[3][1] == "run_completed"
    assert len(events) == 4


def test_run_result_carries_run_metadata(tmp_path: Path) -> None:
    """RunResult exposes run_id, duration, and the trace path."""
    fake = FakeAdapter(turns=[make_turn(text="ok")])
    result = run(
        scenario=_make_scenario(),
        model="claude-test",
        output_root=tmp_path,
        adapter=_as_adapter(fake),
    )

    assert len(result.run_id) == 12  # uuid4 hex truncated to 12
    assert result.duration_ms >= 0
    assert result.trace_path.exists()
    assert result.event_count > 0


# --- 2. Multi-turn run with tool calls ---

def test_run_with_tool_call_routes_through_gateway(tmp_path: Path) -> None:
    """A run that includes a tool call produces the full event sequence."""
    fake = FakeAdapter(turns=[
        # Turn 1: model requests a tool call.
        make_turn(
            text="I'll use the echo tool.",
            tool_uses=[ToolUseContent(call_id="c1", tool="echo", args={"text": "hi"})],
        ),
        # Turn 2: model concludes after seeing the result.
        make_turn(text="Echo returned 'hi'. Task complete."),
    ])
    result = run(
        scenario=_make_scenario(),
        model="claude-test",
        output_root=tmp_path,
        adapter=_as_adapter(fake),
    )

    assert result.status == "ok"
    events = _read_events(result.trace_path)
    event_types = [e[1] for e in events]

    # Expected sequence:
    # run_started, agent_message (turn 1), tool_call, gateway_intent_logged,
    # tool_result, agent_message (turn 2), run_completed
    assert event_types == [
        "run_started",
        "agent_message",
        "model_response",
        "tool_call",
        "gateway_intent_logged",
        "tool_result",
        "agent_message",
        "model_response",
        "run_completed",
    ]


def test_run_with_tool_call_passes_result_back_to_model(tmp_path: Path) -> None:
    """The tool result is included in the next conversation passed to get_turn."""
    fake = FakeAdapter(turns=[
        make_turn(
            text="using echo",
            tool_uses=[ToolUseContent(call_id="c1", tool="echo", args={"text": "hi"})],
        ),
        make_turn(text="done"),
    ])
    run(
        scenario=_make_scenario(),
        model="claude-test",
        output_root=tmp_path,
        adapter=_as_adapter(fake),
    )

    # Second call to get_turn should have a conversation with tool_result content.
    second_call = fake.calls_received[1]
    # Last message should be the user-role tool_result reply.
    last_msg = second_call.messages[-1]
    assert last_msg.role == "user"
    # And it should contain a tool_result block.
    has_tool_result = any(
        getattr(block, "type", None) == "tool_result"
        for block in last_msg.content
    )
    assert has_tool_result


# --- 3. Adapter error produces run_aborted ---

def test_adapter_error_produces_run_aborted(tmp_path: Path) -> None:
    """An AdapterError from get_turn becomes a run_aborted event with the failure reason."""
    error = AdapterError(
        error_type=AdapterErrorType.AUTH,
        message="invalid api key",
    )
    fake = FailingFakeAdapter(error=error)
    result = run(
        scenario=_make_scenario(),
        model="claude-test",
        output_root=tmp_path,
        adapter=_as_adapter(fake),
    )

    assert result.status == "aborted"
    assert result.abort_reason is not None
    assert "auth" in result.abort_reason

    events = _read_events(result.trace_path)
    assert events[0][1] == "run_started"
    assert events[-1][1] == "run_aborted"


# --- 4. MAX_TURNS triggers run_aborted ---

def test_max_turns_triggers_run_aborted(tmp_path: Path) -> None:
    """A model that never stops requesting tools hits MAX_TURNS and aborts."""
    # Every turn requests a tool — the loop will never naturally finish.
    looping_turn = make_turn(
        text="going again",
        tool_uses=[ToolUseContent(call_id="c1", tool="echo", args={"text": "again"})],
    )
    fake = FakeAdapter(turns=[looping_turn] * (MAX_TURNS + 1))

    result = run(
        scenario=_make_scenario(),
        model="claude-test",
        output_root=tmp_path,
        adapter=_as_adapter(fake),
    )

    assert result.status == "aborted"
    assert result.abort_reason is not None
    assert "maximum turn limit" in result.abort_reason

    events = _read_events(result.trace_path)
    assert events[-1][1] == "run_aborted"


# --- 5. Trace contract: run_started is always first; terminal event is always last ---

def test_run_started_is_always_first_event(tmp_path: Path) -> None:
    """Even on immediate adapter failure, run_started appears as event 0."""
    error = AdapterError(error_type=AdapterErrorType.AUTH, message="bad key")
    fake = FailingFakeAdapter(error=error)
    result = run(
        scenario=_make_scenario(),
        model="claude-test",
        output_root=tmp_path,
        adapter=_as_adapter(fake),
    )

    events = _read_events(result.trace_path)
    assert events[0] == (0, "run_started", "framework")


def test_terminal_event_is_always_last(tmp_path: Path) -> None:
    """Every trace ends with either run_completed or run_aborted, never anything else."""
    fake = FakeAdapter(turns=[make_turn(text="done")])
    result = run(
        scenario=_make_scenario(),
        model="claude-test",
        output_root=tmp_path,
        adapter=_as_adapter(fake),
    )

    events = _read_events(result.trace_path)
    assert events[-1][1] in ("run_completed", "run_aborted")


# --- Trace organization: file lands in the right place ---

def test_trace_lands_at_expected_path(tmp_path: Path) -> None:
    """Trace path follows the runs/{scenario}/{model}/{run_id}.jsonl convention."""
    fake = FakeAdapter(turns=[make_turn(text="ok")])
    result = run(
        scenario=_make_scenario(),
        model="claude-test-model",
        output_root=tmp_path,
        adapter=_as_adapter(fake),
    )

    expected_dir = tmp_path / "test-scenario" / "claude-test-model"
    assert result.trace_path.parent == expected_dir
    assert result.trace_path.name.endswith(".jsonl")


def test_model_response_carries_turn_metadata(tmp_path: Path) -> None:
    """model_response records the adapter's usage, stop_reason, and duration."""
    fake = FakeAdapter(turns=[
        make_turn(
            text="done",
            usage=TokenUsage(input_tokens=100, output_tokens=25),
            stop_reason="end_turn",
            duration_ms=1234,
        )
    ])
    result = run(
        scenario=_make_scenario(),
        model="claude-test",
        output_root=tmp_path,
        adapter=_as_adapter(fake),
    )

    events = _read_events(result.trace_path)
    assert [e[1] for e in events].count("model_response") == 1

def test_scenario_rejects_empty_agents() -> None:
    """A scenario with no agents cannot produce a coherent trace."""
    with pytest.raises(ValueError, match="no agents"):
        Scenario(id="broken", agents=[])


def test_scenario_rejects_duplicate_agent_ids() -> None:
    """Duplicate agent_ids make two agents indistinguishable in the trace."""
    spec = AgentSpec(
        agent_id="alice",
        system_prompt="s",
        initial_user_message="m",
    )
    with pytest.raises(ValueError, match="duplicate agent_ids"):
        Scenario(id="broken", agents=[spec, spec])


def test_single_agent_defaults_agent_id() -> None:
    """Scenario.single_agent() produces exactly one agent."""
    s = Scenario.single_agent(
        id="s1",
        system_prompt="s",
        initial_user_message="m",
    )
    assert len(s.agents) == 1
    assert s.agents[0].agent_id == "agent"
    assert s.agents[0].tools == []


def test_scenario_rejects_zero_rounds() -> None:
    """A scenario must run at least one round."""
    spec = AgentSpec(agent_id="a", system_prompt="s", initial_user_message="m")
    with pytest.raises(ValueError, match="must be >= 1"):
        Scenario(id="s1", agents=[spec], rounds=0)


def test_multiple_rounds_drive_the_agent_repeatedly(tmp_path: Path) -> None:
    """rounds=3 runs the agent's turn loop three times, not once."""
    scenario = Scenario(
        id="three-rounds",
        agents=[
            AgentSpec(agent_id="agent", system_prompt="s", initial_user_message="m")
        ],
        rounds=3,
    )
    fake = FakeAdapter(turns=[make_turn(text="done")] * 3)
    result = run(
        scenario=scenario,
        model="claude-test",
        output_root=tmp_path,
        adapter=_as_adapter(fake),
    )

    assert result.status == "ok"
    types = [e[1] for e in _read_events(result.trace_path)]
    assert types.count("agent_message") == 3
    assert types.count("model_response") == 3


def test_two_agents_alternate_within_a_round(tmp_path: Path) -> None:
    """Both agents act once per round, in roster order, each attributed."""
    scenario = Scenario(
        id="two-agents",
        agents=[
            AgentSpec(agent_id="alice", system_prompt="s", initial_user_message="m"),
            AgentSpec(agent_id="bob", system_prompt="s", initial_user_message="m"),
        ],
        rounds=2,
    )
    fake = FakeAdapter(turns=[make_turn(text="ok")] * 4)
    result = run(
        scenario=scenario,
        model="claude-test",
        output_root=tmp_path,
        adapter=_as_adapter(fake),
    )

    assert result.status == "ok"

    with TraceReader(result.trace_path) as reader:
        events = reader.read_all()

    speakers = [e.agent_id for e in events if e.event == "agent_message"]
    assert speakers == ["alice", "bob", "alice", "bob"]


def test_run_started_records_every_agent(tmp_path: Path) -> None:
    """run_started carries each agent's model, instructions, and tools."""
    scenario = Scenario(
        id="manifest-check",
        agents=[
            AgentSpec(
                agent_id="alice",
                system_prompt="you are alice",
                initial_user_message="begin",
                tools=[EchoTool()],
            ),
            AgentSpec(agent_id="bob", system_prompt="you are bob", initial_user_message="go"),
        ],
        rounds=1,
    )
    fake = FakeAdapter(turns=[make_turn(text="ok")] * 2)
    result = run(
        scenario=scenario,
        model="claude-test",
        output_root=tmp_path,
        adapter=_as_adapter(fake),
    )

    with TraceReader(result.trace_path) as reader:
        started = reader.read_all()[0]

    assert started.payload.rounds == 1
    agents = started.payload.agents
    assert [a.agent_id for a in agents] == ["alice", "bob"]
    assert agents[0].system_prompt == "you are alice"
    assert agents[0].model_id == "claude-test"
    assert [t.name for t in agents[0].tools] == ["echo"]
    assert agents[1].tools == []


class CtxSpyTool(Tool[EchoArgs, EchoResult]):
    """Records every RunContext it is called with.

    Stateful, which is exactly what a module-level scenario tool must not be.
    Safe here because each test builds its own instance.
    """

    name = "ctx_spy"
    description = "Echoes its input and records the context it was called with."
    args_schema = EchoArgs
    result_schema = EchoResult

    def __init__(self) -> None:
        self.seen: list[RunContext] = []

    def run(self, args: EchoArgs, ctx: RunContext) -> EchoResult:
        self.seen.append(ctx)
        return EchoResult(text=args.text)


def test_run_context_reaches_the_tool(tmp_path: Path) -> None:
    """A tool receives the run, round, turn, and acting agent of its call."""
    spy = CtxSpyTool()
    scenario = Scenario(
        id="ctx-check",
        agents=[
            AgentSpec(
                agent_id="alice",
                system_prompt="s",
                initial_user_message="m",
                tools=[spy],
            )
        ],
        rounds=2,
    )
    calling_turn = make_turn(
        text="calling",
        tool_uses=[ToolUseContent(call_id="c1", tool="ctx_spy", args={"text": "x"})],
    )
    fake = FakeAdapter(turns=[calling_turn, make_turn(text="done")] * 2)
    result = run(
        scenario=scenario,
        model="claude-test",
        output_root=tmp_path,
        adapter=_as_adapter(fake),
    )

    assert result.status == "ok"
    assert len(spy.seen) == 2

    assert [c.round_number for c in spy.seen] == [0, 1]
    assert all(c.acting_agent_id == "alice" for c in spy.seen)
    assert all(c.run_id == result.run_id for c in spy.seen)

    # The context's turn_id must match the turn_id on that turn's events,
    # or correlating a tool's view with the trace becomes guesswork.
    with TraceReader(result.trace_path) as reader:
        events = reader.read_all()
    traced = [e.payload.turn_id for e in events if e.event == "tool_call"]
    assert traced == [c.turn_id for c in spy.seen]


def test_reveal_is_recorded_in_run_started(tmp_path: Path) -> None:
    """reveal is experimental configuration, so it belongs in the trace."""
    scenario = Scenario(
        id="simultaneous",
        agents=[
            AgentSpec(agent_id="alice", system_prompt="s", initial_user_message="m"),
            AgentSpec(agent_id="bob", system_prompt="s", initial_user_message="m"),
        ],
        rounds=2,
        reveal="end_of_round",
    )
    fake = FakeAdapter(turns=[make_turn(text="ok")] * 4)
    result = run(
        scenario=scenario,
        model="claude-test",
        output_root=tmp_path,
        adapter=_as_adapter(fake),
    )

    with TraceReader(result.trace_path) as reader:
        started = reader.read_all()[0]

    assert started.payload.reveal == "end_of_round"


def test_reveal_defaults_to_immediate(tmp_path: Path) -> None:
    """Scenarios that don't specify reveal record the default explicitly."""
    fake = FakeAdapter(turns=[make_turn(text="ok")])
    result = run(
        scenario=_make_scenario(),
        model="claude-test",
        output_root=tmp_path,
        adapter=_as_adapter(fake),
    )

    with TraceReader(result.trace_path) as reader:
        started = reader.read_all()[0]

    assert started.payload.reveal == "immediate"


def _two_agents(reveal: str, rounds: int, tools_for_alice: list) -> Scenario:
    return Scenario(
        id="messaging",
        agents=[
            AgentSpec(
                agent_id="alice",
                system_prompt="s",
                initial_user_message="m",
                tools=tools_for_alice,
            ),
            AgentSpec(agent_id="bob", system_prompt="s", initial_user_message="m"),
        ],
        rounds=rounds,
        reveal=reveal,
    )


def _send_turn(to: str, text: str) -> Turn:
    return make_turn(
        text="sending",
        tool_uses=[
            ToolUseContent(
                call_id="c1",
                tool="send_message",
                args={"to": to, "text": text},
            )
        ],
    )


def test_immediate_reveal_delivers_within_the_same_round(tmp_path: Path) -> None:
    """Under immediate reveal, a message reaches the next agent to act."""
    scenario = _two_agents("immediate", 1, [SendMessageTool(roster=["alice", "bob"])])
    fake = FakeAdapter(turns=[
        _send_turn("bob", "hold at 90"),
        make_turn(text="sent"),
        make_turn(text="ok"),
    ])
    result = run(
        scenario=scenario,
        model="claude-test",
        output_root=tmp_path,
        adapter=_as_adapter(fake),
    )

    assert result.status == "ok"
    with TraceReader(result.trace_path) as reader:
        events = reader.read_all()

    inbound = [e for e in events if e.event == "inbound"]
    assert len(inbound) == 1
    assert inbound[0].agent_id == "bob"
    assert inbound[0].payload.from_id == "alice"
    assert inbound[0].payload.text == "hold at 90"
    assert inbound[0].payload.source == "agent"
    assert inbound[0].payload.sent_round == 0
    assert inbound[0].payload.delivered_round == 0
    assert "alice" in inbound[0].payload.framing


def test_end_of_round_reveal_holds_until_the_next_round(tmp_path: Path) -> None:
    """Under end_of_round reveal, nobody can react within the sending round."""
    scenario = _two_agents(
        "end_of_round", 2, [SendMessageTool(roster=["alice", "bob"])]
    )
    fake = FakeAdapter(turns=[
        _send_turn("bob", "hold at 90"),
        make_turn(text="sent"),
        make_turn(text="ok"),
        make_turn(text="ok"),
        make_turn(text="ok"),
    ])
    result = run(
        scenario=scenario,
        model="claude-test",
        output_root=tmp_path,
        adapter=_as_adapter(fake),
    )

    assert result.status == "ok"
    with TraceReader(result.trace_path) as reader:
        events = reader.read_all()

    inbound = [e for e in events if e.event == "inbound"]
    assert len(inbound) == 1
    assert inbound[0].payload.sent_round == 0
    assert inbound[0].payload.delivered_round == 1


def test_unknown_recipient_is_recorded_not_dropped(tmp_path: Path) -> None:
    """A misaddressed message is a recorded attempt, not a silent no-op."""
    scenario = _two_agents("immediate", 1, [SendMessageTool(roster=["alice", "bob"])])
    fake = FakeAdapter(turns=[
        _send_turn("carol", "hello"),
        make_turn(text="failed"),
        make_turn(text="ok"),
    ])
    result = run(
        scenario=scenario,
        model="claude-test",
        output_root=tmp_path,
        adapter=_as_adapter(fake),
    )

    assert result.status == "ok"
    with TraceReader(result.trace_path) as reader:
        events = reader.read_all()

    types = [e.event for e in events]
    assert "tool_error" in types
    assert "inbound" not in types


def test_agent_cannot_message_itself(tmp_path: Path) -> None:
    """Self-addressed messages are rejected at the tool, before the bus."""
    scenario = _two_agents("immediate", 1, [SendMessageTool(roster=["alice", "bob"])])
    fake = FakeAdapter(turns=[
        _send_turn("alice", "talking to myself"),
        make_turn(text="failed"),
        make_turn(text="ok"),
    ])
    result = run(
        scenario=scenario,
        model="claude-test",
        output_root=tmp_path,
        adapter=_as_adapter(fake),
    )

    with TraceReader(result.trace_path) as reader:
        events = reader.read_all()

    assert "tool_error" in [e.event for e in events]
    assert "inbound" not in [e.event for e in events]
