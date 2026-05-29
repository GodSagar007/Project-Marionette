"""The Anthropic-specific adapter.

Translates between Marionette's provider-agnostic types (Conversation, Message,
Turn, Tool) and Anthropic's API format. This is the only module in the codebase
that imports the anthropic SDK; every other component sees only our types.

For thread one this is the sole adapter. Adding a second provider means adding
a sibling module (e.g. openai.py) with its own translation functions and adapter
class — none of the framework's other components change.
"""

from typing import Any, cast

from anthropic import Anthropic
from anthropic.types import Message as AnthropicMessage
from anthropic.types import TextBlock, ToolUseBlock

from marionette.adapter.conversation import (
    ContentBlock,
    Conversation,
    TextContent,
    ToolResultContent,
    ToolUseContent,
    Turn,
)
from marionette.gateway.tool import Tool


def to_anthropic_tool_spec(tool: Tool[Any, Any]) -> dict[str, Any]:
    """Convert a Marionette Tool into Anthropic's tool-definition dict.

    Anthropic expects tools in this shape:
        {"name": str, "description": str, "input_schema": JSON Schema dict}

    The input_schema is generated from the tool's pydantic args_schema using
    pydantic's built-in JSON Schema export. Pydantic includes some cosmetic
    fields (top-level "title", per-property "title") that Anthropic ignores;
    we leave them for simplicity.

    Args:
        tool: The Marionette tool to translate.

    Returns:
        A dict in Anthropic's tool-definition format, ready to pass as one
        element of the `tools` parameter to the messages API.
    """
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.args_schema.model_json_schema(),
    }


def _block_to_anthropic(block: ContentBlock) -> dict[str, Any]:
    """Translate one of our content blocks to Anthropic's dict format.

    Maps:
        TextContent          → {"type": "text", "text": ...}
        ToolUseContent       → {"type": "tool_use", "id": ..., "name": ..., "input": ...}
        ToolResultContent    → {"type": "tool_result", "tool_use_id": ..., "content": ...}

    The field renames (call_id → id / tool_use_id, args → input, result → content)
    are the only translation work. Anthropic's id and our call_id are the same
    concept; the rename keeps the boundary clean.
    """
    if isinstance(block, TextContent):
        return {"type": "text", "text": block.text}
    if isinstance(block, ToolUseContent):
        return {
            "type": "tool_use",
            "id": block.call_id,
            "name": block.tool,
            "input": block.args,
        }
    if isinstance(block, ToolResultContent):
        result: dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": block.call_id,
            "content": str(block.result),
        }
        if block.is_error:
            result["is_error"] = True
        return result
    # Exhaustive via the discriminated union; this is unreachable in practice.
    raise ValueError(f"unsupported content block type: {type(block).__name__}")


def _to_anthropic_messages(conversation: Conversation) -> list[dict[str, Any]]:
    """Translate our Conversation's messages into Anthropic's messages list.

    The system prompt is NOT included here — Anthropic takes it as a separate
    top-level `system` parameter, not as a message. The caller (get_turn)
    handles that.
    """
    return [
        {
            "role": msg.role,
            "content": [_block_to_anthropic(block) for block in msg.content],
        }
        for msg in conversation.messages
    ]


def _parse_response(response: AnthropicMessage) -> Turn:
    """Parse an Anthropic response into our Turn.

    Walks Anthropic's content blocks, accumulating text and tool_use blocks.
    Multiple text blocks (uncommon but possible) are concatenated with newlines.
    Tool_use blocks become our ToolUseContent for the runner to route.
    """
    text_parts: list[str] = []
    tool_uses: list[ToolUseContent] = []

    for block in response.content:
        if isinstance(block, TextBlock):
            text_parts.append(block.text)
        elif isinstance(block, ToolUseBlock):
            tool_uses.append(
                ToolUseContent(
                    call_id=block.id,
                    tool=block.name,
                    args=dict(block.input) if isinstance(block.input, dict) else {},
                )
            )
        # Other block types (thinking, etc.) are deferred — see schema deferrals.

    return Turn(text="\n".join(text_parts), tool_uses=tool_uses)


class AnthropicAdapter:
    """One-turn adapter for Anthropic's messages API.

    Holds the SDK client and the model identifier. Each get_turn() call performs
    exactly one API exchange: translate our conversation to Anthropic's format,
    call the API once, parse the response into our Turn. The agent loop (when
    to call get_turn again with the next conversation state) lives in the runner.
    """

    def __init__(
        self,
        model: str,
        tools: list[Tool[Any, Any]],
        max_tokens: int = 4096,
        client: Anthropic | None = None,
    ) -> None:
        """Create an adapter bound to a specific model and tool set.

        Args:
            model: The Anthropic model identifier (e.g. "claude-3-7-sonnet-20250219").
            tools: The tools to expose to the model on every turn.
            max_tokens: Maximum tokens the model may generate per response.
            client: Optional pre-constructed Anthropic client. If None, the SDK
                constructs one using the ANTHROPIC_API_KEY environment variable.
                Tests inject a mock client here.
        """
        self._client = client if client is not None else Anthropic()
        self._model = model
        self._max_tokens = max_tokens
        self._tool_specs = [to_anthropic_tool_spec(t) for t in tools]

    def get_turn(self, conversation: Conversation) -> Turn:
        """Run one model exchange and return the parsed Turn.

        The runner calls this in a loop, routing any returned tool_uses through
        the gateway and appending results to the conversation, until a Turn
        comes back with no tool_uses (the model is done).

        Args:
            conversation: The full conversation state (system prompt + history).

        Returns:
            A Turn with the model's text output and any tool calls it requested.
        """
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=conversation.system,
            messages=cast(Any, _to_anthropic_messages(conversation)),
            tools=cast(Any,self._tool_specs),
        )
        return _parse_response(response)
