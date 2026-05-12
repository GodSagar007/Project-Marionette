"""Trace event schema for Marionette.

Defines the structured event types written to JSONL trace files by the runner,
gateway, and tools. The schema is a discriminated union over event types,
with each event carrying common metadata (seq, ts, actor) and a type-specific
payload.

Schema is versioned. Evolution is by addition only within a major version:
new fields and new event types are non-breaking. Field removal, renaming, or
semantic changes require a major version bump.
"""
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0.0"

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


class ToolResultPayload(_StrictBase):
    """Payload for tool_result events. The actual return from a tool execution."""

    call_id: str
    result: Any
class _EventBase(BaseModel):
    """Base class for all trace events.

    Carries common metadata (seq, ts, actor) shared across all event types.
    The `event` discriminator field is declared per-subclass as a Literal.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    seq: int
    ts: datetime
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


TraceEvent = Annotated[
    RunStartedEvent | ToolCallEvent | ToolResultEvent,
    Field(discriminator="event"),
]
"""The discriminated union of all event types in the schema.

External code should annotate event variables with `TraceEvent`. Pydantic
resolves to the correct concrete event class by reading the `event` field.
"""
