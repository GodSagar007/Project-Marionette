"""Tests for the Gateway — routing, the logged-before-routed property, error paths."""

from pathlib import Path

import pytest

from marionette.gateway import ToolRegistry
from marionette.gateway.gateway import Gateway
from marionette.gateway.tool import ToolErrorType
from marionette.tools.echo import EchoResult, EchoTool
from marionette.trace.reader import TraceReader
from marionette.trace.schema import ToolErrorEvent
from marionette.trace.writer import TraceWriter


@pytest.fixture
def gateway_and_path(tmp_path: Path) -> tuple[Gateway, TraceWriter, Path]:
    """A gateway with the echo tool registered, plus its writer and trace path."""
    path = tmp_path / "trace.jsonl"
    registry = ToolRegistry()
    registry.register(EchoTool())
    writer = TraceWriter(path)
    gateway = Gateway(registry, writer)
    return gateway, writer, path


def _read_events(path: Path) -> list[tuple[int, str, str]]:
    """Helper: read a trace and return (seq, event, actor) tuples."""
    with TraceReader(path) as reader:
        return [(e.seq, e.event, e.actor) for e in reader]


def test_successful_call_returns_result(
    gateway_and_path: tuple[Gateway, TraceWriter, Path],
) -> None:
    """A valid call returns the tool's result."""
    gateway, writer, _ = gateway_and_path
    result = gateway.route("echo", call_id="c1", raw_args={"text": "hello"})
    writer.close()
    assert isinstance(result, EchoResult)
    assert result.text == "hello"


def test_successful_call_logs_intent_then_result(
    gateway_and_path: tuple[Gateway, TraceWriter, Path],
) -> None:
    """A successful call writes gateway_intent_logged then tool_result."""
    gateway, writer, path = gateway_and_path
    gateway.route("echo", call_id="c1", raw_args={"text": "hi"})
    writer.close()

    events = _read_events(path)
    assert events == [
        (0, "gateway_intent_logged", "framework"),
        (1, "tool_result", "tool:echo"),
    ]


def test_unknown_tool_logs_intent_then_error(
    gateway_and_path: tuple[Gateway, TraceWriter, Path],
) -> None:
    """An unknown tool still logs intent FIRST, then the error."""
    gateway, writer, path = gateway_and_path
    result = gateway.route("nonexistent", call_id="c1", raw_args={})
    writer.close()

    assert result is None
    events = _read_events(path)
    assert events[0] == (0, "gateway_intent_logged", "framework")
    assert events[1][1] == "tool_error"


def test_unknown_tool_error_type(
    gateway_and_path: tuple[Gateway, TraceWriter, Path],
) -> None:
    """Unknown tool produces a tool_error with error_type unknown_tool."""
    gateway, writer, path = gateway_and_path
    gateway.route("nonexistent", call_id="c1", raw_args={})
    writer.close()

    with TraceReader(path) as reader:
        events = reader.read_all()
    error_event = events[1]
    assert isinstance(error_event, ToolErrorEvent)
    assert error_event.payload.error_type == ToolErrorType.UNKNOWN_TOOL


def test_invalid_args_logs_intent_then_error(
    gateway_and_path: tuple[Gateway, TraceWriter, Path],
) -> None:
    """Invalid args still logs intent FIRST, then the error."""
    gateway, writer, path = gateway_and_path
    result = gateway.route("echo", call_id="c1", raw_args={"wrong_field": "x"})
    writer.close()

    assert result is None
    events = _read_events(path)
    assert events[0] == (0, "gateway_intent_logged", "framework")
    assert events[1][1] == "tool_error"


def test_invalid_args_error_type(
    gateway_and_path: tuple[Gateway, TraceWriter, Path],
) -> None:
    """Invalid args produces a tool_error with error_type args_validation."""
    gateway, writer, path = gateway_and_path
    gateway.route("echo", call_id="c1", raw_args={"wrong_field": "x"})
    writer.close()

    with TraceReader(path) as reader:
        events = reader.read_all()
    error_event = events[1]
    assert isinstance(error_event, ToolErrorEvent)
    assert error_event.payload.error_type == ToolErrorType.ARGS_VALIDATION


def test_intent_always_logged_before_outcome(
    gateway_and_path: tuple[Gateway, TraceWriter, Path],
) -> None:
    """Across success and both failure modes, intent is always logged first.

    This is the research-integrity property: the trace records every attempted
    call before its outcome, so attempted-but-failed actions are first-class.
    """
    gateway, writer, path = gateway_and_path
    gateway.route("echo", call_id="ok", raw_args={"text": "hi"})         # success
    gateway.route("nope", call_id="unk", raw_args={})                    # unknown
    gateway.route("echo", call_id="bad", raw_args={"wrong": "x"})        # bad args
    writer.close()

    events = _read_events(path)
    # Every even-indexed event is an intent log; every odd one is its outcome.
    intent_events = [e for e in events if e[1] == "gateway_intent_logged"]
    assert len(intent_events) == 3  # one per call, regardless of outcome
    # First event of each pair is always the intent.
    assert events[0][1] == "gateway_intent_logged"
    assert events[2][1] == "gateway_intent_logged"
    assert events[4][1] == "gateway_intent_logged"
