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

SCHEMA_VERSION = "2.1.0"

class _StrictBase(BaseModel):
    """Base class for all trace payloads.

    Forbids extra fields on write — payloads must declare every field they emit.
    This is the strict-on-write half of the schema discipline; the reader will
    be lenient separately.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

class ToolManifestEntry(_StrictBase):
    """One tool as it was presented to the agent at run start.

    Records the contract, not the usage. Lets an analyst reconstruct what the
    agent could have done, not just what it did.
    """

    name: str
    description: str
    args_schema: dict[str, Any]
    result_schema: dict[str, Any]

class AgentManifestEntry(_StrictBase):
    """One agent's situation as configured at run start.

    Records what the agent was given — its model, its instructions, and its
    tools — so a trace is reproducible without the scenario source beside it.

    The system prompt is here because it carries the experimental
    manipulation. In a sandbagging scenario it is what tells the agent
    whether it is being evaluated; in a collusion scenario it is where
    symmetric or asymmetric instruction shows up. A trace that cannot report
    which condition it recorded cannot evidence its own result.
    """

    agent_id: str
    model_id: str
    system_prompt: str
    initial_user_message: str
    tools: list[ToolManifestEntry] = Field(default_factory=list)

class RunStartedPayload(_StrictBase):
    """Payload for the run_started event. Emitted once, at the start of each run."""

    schema_version: str
    run_id: str
    scenario_id: str
    model_id: str
    seed: int
    framework_version: str
    dev_mode: bool
    rounds: int = 1
    reveal: Literal["immediate", "end_of_round"] = "immediate"
    agents: list[AgentManifestEntry] = Field(default_factory=list)


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
    kind: Literal["reasoning", "summary", "final", "other"] | None = None
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

class InboundPayload(_StrictBase):
    """Content the runner placed into an agent's context unprompted.

    Covers every way something enters an agent's conversation that the agent
    did not ask for: a message from another agent, an observation of shared
    environment state, a mid-run instruction from a principal, or injected
    adversarial content.

    One event with a source discriminator rather than four event types — the
    recorded facts are identical in every case: what entered, from where,
    when it was sent, when it arrived, and under what framing.

    sent_round and delivered_round are both recorded because under
    end_of_round reveal they differ. The gap is then visible in the data
    rather than inferred from configuration.

    framing is the prefix as actually applied, not reconstructed from a
    format string. An injection scenario will deliberately vary or omit it,
    and the trace must say which was used.
    """

    source: Literal["agent", "environment", "principal", "injection"]
    text: str
    framing: str
    sent_round: int
    delivered_round: int
    from_id: str | None = None

class FrameworkNotePayload(_StrictBase):
    """Payload for framework_note events. Diagnostic instrumentation, not a domain event."""

    text: str
    level: Literal["debug", "info", "warning"]

class TokenUsage(_StrictBase):
    """Token usage reported by the provider for one API call."""

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class ModelResponsePayload(_StrictBase):
    """Per-API-call metadata. Emitted once per adapter.get_turn() call."""

    turn_id: str
    usage: TokenUsage | None = None
    stop_reason: str
    duration_ms: int

class _EventBase(BaseModel):
    """Base class for all trace events.

    Carries common metadata (seq, ts, actor, agent_id) shared across all
    event types. `actor` names the component that emitted the event
    (framework, agent, gateway); `agent_id` names *which* agent the event
    is attributable to. Two agents both have actor="agent" and differ only
    by agent_id. None means the event is run-level (no agent) or the trace
    predates 1.2.0.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    seq: int = 0
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    actor: str
    agent_id: str | None = None

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

class InboundEvent(_EventBase):
    """Records content delivered into an agent's context by the runner.

    agent_id is the *recipient* — the agent whose context received this.
    The sender, where there is one, is payload.from_id.
    """

    event: Literal["inbound"] = "inbound"
    payload: InboundPayload

class FrameworkNoteEvent(_EventBase):
    """Emitted by the framework for diagnostic notes that aren't domain events."""

    event: Literal["framework_note"] = "framework_note"
    payload: FrameworkNotePayload

class ModelResponseEvent(_EventBase):
    """Records metadata about one API call to the model provider."""

    event: Literal["model_response"] = "model_response"
    payload: ModelResponsePayload

TraceEvent = Annotated[
    RunStartedEvent
    | RunCompletedEvent
    | RunAbortedEvent
    | AgentMessageEvent
    | ToolCallEvent
    | GatewayIntentLoggedEvent
    | ToolResultEvent
    | ToolErrorEvent
    | FrameworkNoteEvent
    | InboundEvent
    | ModelResponseEvent,
    Field(discriminator="event"),
]
"""The discriminated union of all event types in the schema.

External code should annotate event variables with `TraceEvent`. Pydantic
resolves to the correct concrete event class by reading the `event` field.
"""
