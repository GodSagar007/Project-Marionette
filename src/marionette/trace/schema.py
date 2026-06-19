"""Trace event schema for Marionette.

Defines the structured event types written to JSONL trace files by the runner,
gateway, and tools. The schema is a discriminated union over event types,
with each event carrying common metadata (seq, ts, actor) and a type-specific
payload.

Schema is versioned. Evolution is by addition only within a major version:
new fields and new event types are non-breaking. Field removal, renaming, or
semantic changes require a major version bump.
"""
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.1.0"

class _StrictBase(BaseModel):
    """Base class for all trace payloads.

    Forbids extra fields on write — payloads must declare every field they emit.
    This is the strict-on-write half of the schema discipline; the reader will
    be lenient separately.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class RunStartedPayload(_StrictBase):
    """Payload for the run_started event. Emitted once, at the start of each run."""

    schema_version: str
    run_id: str
    scenario_id: str
    model_id: str
    seed: int
    framework_version: str
    dev_mode: bool


class ToolCallPayload(_StrictBase):
    """Payload for tool_call events. The agent's *intent* to invoke a tool."""

    tool: str
    call_id: str
    args: dict[str, Any]
    turn_id: str | None = None

class ToolResultPayload(_StrictBase):
    """Payload for tool_result events. The actual return from a tool execution."""

    call_id: str
    result: Any
    turn_id: str | None = None

class RunCompletedPayload(_StrictBase):
    """Payload for run_completed events. Emitted once, at the end of a successful run."""

    status: Literal["ok"]
    duration_ms: int
    event_count: int


class RunAbortedPayload(_StrictBase):
    """Payload for run_aborted events. Emitted once, at the end of a failed or cancelled run."""

    reason: str
    error_type: str | None
    duration_ms: int
    event_count: int


class AgentMessagePayload(_StrictBase):
    """Payload for agent_message events. The agent's textual output."""

    text: str
    turn_id: str | None = None

class GatewayIntentLoggedPayload(_StrictBase):
    """Payload: gateway_intent_logged events.Records gateway observed a tool call before routed."""

    call_id: str
    turn_id: str | None = None

class ToolErrorPayload(_StrictBase):
    """Payload for tool_error events. A tool invocation that failed."""

    call_id: str
    error_type: str
    message: str
    turn_id: str | None = None

class FrameworkNotePayload(_StrictBase):
    """Payload for framework_note events. Diagnostic instrumentation, not a domain event."""

    text: str
    level: Literal["debug", "info", "warning"]

class _EventBase(BaseModel):
    """Base class for all trace events.

    Carries common metadata (seq, ts, actor) shared across all event types.
    The `event` discriminator field is declared per-subclass as a Literal.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    seq: int = 0
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    actor: str


class RunStartedEvent(_EventBase):
    """Emitted once, at the very start of each run."""

    event: Literal["run_started"] = "run_started"
    payload: RunStartedPayload


class ToolCallEvent(_EventBase):
    """Emitted by the model adapter when the agent invokes a tool."""

    event: Literal["tool_call"] = "tool_call"
    payload: ToolCallPayload


class ToolResultEvent(_EventBase):
    """Emitted by the gateway when a tool returns a result."""

    event: Literal["tool_result"] = "tool_result"
    payload: ToolResultPayload

class RunCompletedEvent(_EventBase):
    """Emitted once, at the end of a successful run."""

    event: Literal["run_completed"] = "run_completed"
    payload: RunCompletedPayload


class RunAbortedEvent(_EventBase):
    """Emitted once, at the end of a failed or cancelled run."""

    event: Literal["run_aborted"] = "run_aborted"
    payload: RunAbortedPayload


class AgentMessageEvent(_EventBase):
    """Emitted by the model adapter for each textual message from the agent."""

    event: Literal["agent_message"] = "agent_message"
    payload: AgentMessagePayload


class GatewayIntentLoggedEvent(_EventBase):
    """Emitted by the gateway immediately before routing a tool call."""

    event: Literal["gateway_intent_logged"] = "gateway_intent_logged"
    payload: GatewayIntentLoggedPayload


class ToolErrorEvent(_EventBase):
    """Emitted by the gateway when a tool invocation fails."""

    event: Literal["tool_error"] = "tool_error"
    payload: ToolErrorPayload


class FrameworkNoteEvent(_EventBase):
    """Emitted by the framework for diagnostic notes that aren't domain events."""

    event: Literal["framework_note"] = "framework_note"
    payload: FrameworkNotePayload


TraceEvent = Annotated[
    RunStartedEvent
    | RunCompletedEvent
    | RunAbortedEvent
    | AgentMessageEvent
    | ToolCallEvent
    | GatewayIntentLoggedEvent
    | ToolResultEvent
    | ToolErrorEvent
    | FrameworkNoteEvent,
    Field(discriminator="event"),
]
"""The discriminated union of all event types in the schema.

External code should annotate event variables with `TraceEvent`. Pydantic
resolves to the correct concrete event class by reading the `event` field.
"""
