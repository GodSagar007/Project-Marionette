"""Tests for the runner: agent loop, lifecycle events, error paths.

These tests inject a fake adapter so no live API calls happen. The fake
returns whatever canned Turn objects the test supplies, so each test fully
controls what the "model" says and the runner's response is the variable
under test.
"""

from pathlib import Path
from typing import cast

from marionette.adapter.anthropic import (
    AdapterError,
    AdapterErrorType,
    AnthropicAdapter,
)
from marionette.adapter.conversation import Conversation, ToolUseContent, Turn
from marionette.runner import MAX_TURNS, Scenario, run
from marionette.tools.echo import EchoTool
from marionette.trace.reader import TraceReader

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
    return Scenario(
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

    agent_message, run_completed."""
    fake = FakeAdapter(turns=[Turn(text="task complete")])
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
    assert events[2][1] == "run_completed"
    assert len(events) == 3


def test_run_result_carries_run_metadata(tmp_path: Path) -> None:
    """RunResult exposes run_id, duration, and the trace path."""
    fake = FakeAdapter(turns=[Turn(text="ok")])
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
        Turn(
            text="I'll use the echo tool.",
            tool_uses=[ToolUseContent(call_id="c1", tool="echo", args={"text": "hi"})],
        ),
        # Turn 2: model concludes after seeing the result.
        Turn(text="Echo returned 'hi'. Task complete."),
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
        "tool_call",
        "gateway_intent_logged",
        "tool_result",
        "agent_message",
        "run_completed",
    ]


def test_run_with_tool_call_passes_result_back_to_model(tmp_path: Path) -> None:
    """The tool result is included in the next conversation passed to get_turn."""
    fake = FakeAdapter(turns=[
        Turn(
            text="using echo",
            tool_uses=[ToolUseContent(call_id="c1", tool="echo", args={"text": "hi"})],
        ),
        Turn(text="done"),
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
    looping_turn = Turn(
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
    fake = FakeAdapter(turns=[Turn(text="done")])
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
    fake = FakeAdapter(turns=[Turn(text="ok")])
    result = run(
        scenario=_make_scenario(),
        model="claude-test-model",
        output_root=tmp_path,
        adapter=_as_adapter(fake),
    )

    expected_dir = tmp_path / "test-scenario" / "claude-test-model"
    assert result.trace_path.parent == expected_dir
    assert result.trace_path.name.endswith(".jsonl")
