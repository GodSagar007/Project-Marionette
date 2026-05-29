"""Tests for the AnthropicAdapter: translation, parsing, error handling.

These tests do not make real API calls. They inject a fake client that returns
canned responses, so the suite is fast, free, deterministic, and offline.
"""

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from anthropic import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)
from anthropic.types import Message as AnthropicMessage
from anthropic.types import TextBlock, ToolUseBlock, Usage

from marionette.adapter.anthropic import (
    AdapterError,
    AdapterErrorType,
    AnthropicAdapter,
    _block_to_anthropic,
    _to_anthropic_messages,
    to_anthropic_tool_spec,
)
from marionette.adapter.conversation import (
    Conversation,
    Message,
    TextContent,
    ToolResultContent,
    ToolUseContent,
)
from marionette.tools.echo import EchoTool

# --- Helpers: construct fake Anthropic responses ---

def _make_fake_response(
    text_parts: list[str] | None = None,
    tool_uses: list[tuple[str, str, dict[str, Any]]] | None = None,
) -> AnthropicMessage:
    """Construct a fake AnthropicMessage for tests.

    Args:
        text_parts: List of text strings; each becomes a TextBlock.
        tool_uses: List of (id, name, input) tuples; each becomes a ToolUseBlock.

    Returns:
        An AnthropicMessage suitable for returning from a mock client.
    """
    content: list[Any] = []
    for text in text_parts or []:
        content.append(TextBlock(type="text", text=text, citations=None))
    for call_id, tool_name, tool_input in tool_uses or []:
        content.append(ToolUseBlock(
            type="tool_use",
            id=call_id,
            name=tool_name,
            input=tool_input,
        ))

    return AnthropicMessage(
        id="msg_test",
        type="message",
        role="assistant",
        model="claude-test",
        content=content,
        stop_reason="end_turn" if not tool_uses else "tool_use",
        stop_sequence=None,
        usage=Usage(input_tokens=10, output_tokens=10),
    )


def _make_fake_client(response: AnthropicMessage) -> MagicMock:
    """Create a fake client whose messages.create returns the given response."""
    client = MagicMock()
    client.messages.create.return_value = response
    return client


# --- Tool spec translation ---

def test_to_anthropic_tool_spec_has_required_fields() -> None:
    """A tool's Anthropic spec has name, description, and input_schema."""
    spec = to_anthropic_tool_spec(EchoTool())
    assert spec["name"] == "echo"
    assert "description" in spec
    assert spec["input_schema"]["type"] == "object"
    assert "text" in spec["input_schema"]["properties"]


# --- Conversation translation ---

def test_text_block_translates_to_anthropic_format() -> None:
    """A TextContent block becomes Anthropic's text dict."""
    block = TextContent(text="hello")
    assert _block_to_anthropic(block) == {"type": "text", "text": "hello"}


def test_tool_use_block_translates_with_field_renames() -> None:
    """A ToolUseContent block becomes Anthropic's tool_use dict.

    Note the field renames: our call_id → Anthropic's id, our tool → name,
    our args → input.
    """
    block = ToolUseContent(call_id="c1", tool="echo", args={"text": "hi"})
    assert _block_to_anthropic(block) == {
        "type": "tool_use",
        "id": "c1",
        "name": "echo",
        "input": {"text": "hi"},
    }


def test_tool_result_block_translates_with_field_renames() -> None:
    """A ToolResultContent block becomes Anthropic's tool_result dict."""
    block = ToolResultContent(call_id="c1", result="hi")
    assert _block_to_anthropic(block) == {
        "type": "tool_result",
        "tool_use_id": "c1",
        "content": "hi",
    }


def test_tool_result_block_marks_errors() -> None:
    """A tool result with is_error=True includes the flag in Anthropic's format."""
    block = ToolResultContent(call_id="c1", result="oops", is_error=True)
    result = _block_to_anthropic(block)
    assert result["is_error"] is True


def test_conversation_translates_to_messages_list() -> None:
    """A Conversation produces an Anthropic-format messages list, system excluded."""
    conv = Conversation(system="be helpful").with_message(
        Message(role="user", content=[TextContent(text="hi")])
    )
    messages = _to_anthropic_messages(conv)
    assert messages == [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]}
    ]


# --- Response parsing (via get_turn with a fake client) ---

def test_get_turn_extracts_text() -> None:
    """A response with only text produces a Turn with that text and no tool calls."""
    fake_response = _make_fake_response(text_parts=["hello world"])
    client = _make_fake_client(fake_response)
    adapter = AnthropicAdapter(model="claude-test", tools=[EchoTool()], client=client)
    conv = Conversation(system="be helpful")

    turn = adapter.get_turn(conv)

    assert turn.text == "hello world"
    assert turn.tool_uses == []
    assert turn.wants_tools is False


def test_get_turn_extracts_tool_calls() -> None:
    """A response with a tool_use block produces a Turn with that tool call."""
    fake_response = _make_fake_response(
        text_parts=["I'll use echo."],
        tool_uses=[("c1", "echo", {"text": "hi"})],
    )
    client = _make_fake_client(fake_response)
    adapter = AnthropicAdapter(model="claude-test", tools=[EchoTool()], client=client)

    turn = adapter.get_turn(Conversation(system="be helpful"))

    assert turn.text == "I'll use echo."
    assert len(turn.tool_uses) == 1
    assert turn.tool_uses[0].call_id == "c1"
    assert turn.tool_uses[0].tool == "echo"
    assert turn.tool_uses[0].args == {"text": "hi"}
    assert turn.wants_tools is True


def test_get_turn_concatenates_multiple_text_blocks() -> None:
    """Multiple text blocks in the response are joined with newlines."""
    fake_response = _make_fake_response(text_parts=["first", "second"])
    client = _make_fake_client(fake_response)
    adapter = AnthropicAdapter(model="claude-test", tools=[EchoTool()], client=client)

    turn = adapter.get_turn(Conversation(system="be helpful"))

    assert turn.text == "first\nsecond"


# --- Error handling ---

def _make_failing_client(exception: Exception) -> MagicMock:
    """Create a fake client whose messages.create raises the given exception."""
    client = MagicMock()
    client.messages.create.side_effect = exception
    return client


def _fake_http_response(status: int) -> httpx.Response:
    """Create a real httpx.Response that SDK exceptions can wrap."""
    return httpx.Response(status_code=status, request=httpx.Request("POST", "http://test"))


def test_get_turn_wraps_auth_error() -> None:
    """An AuthenticationError becomes an AdapterError with error_type AUTH."""
    client = _make_failing_client(AuthenticationError(
        message="bad key",
        response=_fake_http_response(401),
        body=None,
    ))
    adapter = AnthropicAdapter(model="claude-test", tools=[EchoTool()], client=client)

    with pytest.raises(AdapterError) as exc_info:
        adapter.get_turn(Conversation(system="x"))

    assert exc_info.value.error_type == AdapterErrorType.AUTH


def test_get_turn_wraps_bad_request_error() -> None:
    """A BadRequestError becomes an AdapterError with error_type BAD_REQUEST."""
    client = _make_failing_client(BadRequestError(
        message="malformed",
        response=_fake_http_response(400),
        body=None,
    ))
    adapter = AnthropicAdapter(model="claude-test", tools=[EchoTool()], client=client)

    with pytest.raises(AdapterError) as exc_info:
        adapter.get_turn(Conversation(system="x"))

    assert exc_info.value.error_type == AdapterErrorType.BAD_REQUEST


def test_get_turn_wraps_rate_limit_error() -> None:
    """A RateLimitError becomes an AdapterError with error_type RATE_LIMIT_EXHAUSTED."""
    client = _make_failing_client(RateLimitError(
        message="too many requests",
        response=_fake_http_response(429),
        body=None,
    ))
    adapter = AnthropicAdapter(model="claude-test", tools=[EchoTool()], client=client)

    with pytest.raises(AdapterError) as exc_info:
        adapter.get_turn(Conversation(system="x"))

    assert exc_info.value.error_type == AdapterErrorType.RATE_LIMIT_EXHAUSTED


def test_get_turn_wraps_network_error() -> None:
    """An APIConnectionError becomes an AdapterError with error_type NETWORK."""
    client = _make_failing_client(APIConnectionError(
        message="network down",
        request=httpx.Request("POST", "http://test"),
    ))
    adapter = AnthropicAdapter(model="claude-test", tools=[EchoTool()], client=client)

    with pytest.raises(AdapterError) as exc_info:
        adapter.get_turn(Conversation(system="x"))

    assert exc_info.value.error_type == AdapterErrorType.NETWORK


def test_adapter_error_preserves_cause() -> None:
    """The original exception is preserved as .cause for downstream inspection."""
    original = AuthenticationError(
        message="bad key",
        response=_fake_http_response(401),
        body=None,
    )
    client = _make_failing_client(original)
    adapter = AnthropicAdapter(model="claude-test", tools=[EchoTool()], client=client)

    with pytest.raises(AdapterError) as exc_info:
        adapter.get_turn(Conversation(system="x"))

    assert exc_info.value.cause is original
