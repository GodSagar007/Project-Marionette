"""Provider-agnostic conversation types for Marionette.

These types are the framework's own representation of a conversation with an
agent. They are deliberately independent of any provider's API format — the
adapter translates between these types and a specific provider (e.g. Anthropic)
at its boundary. This containment means adding a new provider touches only that
provider's adapter, never the components that pass conversations around.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TextContent(BaseModel):
    """A block of text content within a message."""

    model_config = ConfigDict(frozen=True)

    type: Literal["text"] = "text"
    text: str


class ToolUseContent(BaseModel):
    """An assistant's request to invoke a tool."""

    model_config = ConfigDict(frozen=True)

    type: Literal["tool_use"] = "tool_use"
    call_id: str
    tool: str
    args: dict[str, Any]


class ToolResultContent(BaseModel):
    """The result of a tool invocation, fed back into the conversation."""

    model_config = ConfigDict(frozen=True)

    type: Literal["tool_result"] = "tool_result"
    call_id: str
    result: Any
    is_error: bool = False


# A content block is one of the three types above, discriminated by `type`.
ContentBlock = Annotated[
    TextContent | ToolUseContent | ToolResultContent,
    Field(discriminator="type"),
]


class Message(BaseModel):
    """One message in the conversation: a role plus a list of content blocks."""

    model_config = ConfigDict(frozen=True)

    role: Literal["user", "assistant"]
    content: list[ContentBlock]


class Conversation(BaseModel):
    """The running conversation: a system prompt plus ordered messages.

    Frozen at the type level for individual messages, but the conversation
    itself grows by constructing new Conversation instances (or via a helper
    that returns an extended copy) — the runner appends as the agent loop
    progresses.
    """

    model_config = ConfigDict(frozen=True)

    system: str
    messages: list[Message] = Field(default_factory=list)

    def with_message(self, message: Message) -> "Conversation":
        """Return a new Conversation with one message appended.

        Immutable update: the original is unchanged, a new instance is returned.
        """
        return Conversation(system=self.system, messages=[*self.messages, message])


class Turn(BaseModel):
    """The parsed result of one model exchange.

    Carries the text the model produced, any tool calls it requested, and
    whether the model is done (no tool calls means the agent loop can stop).
    """

    model_config = ConfigDict(frozen=True)

    text: str
    tool_uses: list[ToolUseContent] = Field(default_factory=list)

    @property
    def wants_tools(self) -> bool:
        """True if the model requested at least one tool call."""
        return len(self.tool_uses) > 0
