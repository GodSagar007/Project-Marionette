"""The Marionette runner.

Orchestrates a single scenario run end-to-end: sets up the trace writer, drives
the agent loop (adapter → gateway → adapter), emits run lifecycle events, and
cleans up. The runner is the only component that wires the adapter and gateway
together — everything else stays decoupled.

For thread one this lives in a single module with a small Scenario dataclass.
When scenario tooling matures (SCENARIO.md parsing, asset loading), Scenario
gets promoted to its own module under scenarios/.
"""

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from marionette.adapter.anthropic import AdapterError, AnthropicAdapter
from marionette.adapter.conversation import (
    Conversation,
    Message,
    TextContent,
    ToolResultContent,
)
from marionette.gateway.gateway import Gateway
from marionette.gateway.registry import ToolRegistry
from marionette.gateway.tool import Tool
from marionette.trace.schema import (
    SCHEMA_VERSION,
    AgentMessageEvent,
    AgentMessagePayload,
    ModelResponseEvent,
    ModelResponsePayload,
    RunAbortedEvent,
    RunAbortedPayload,
    RunCompletedEvent,
    RunCompletedPayload,
    RunStartedEvent,
    RunStartedPayload,
    ToolCallEvent,
    ToolCallPayload,
    ToolManifestEntry,
)
from marionette.trace.writer import TraceWriter

# Framework version — should match pyproject.toml [project].version. Kept in
# sync manually for thread one; future automation can derive it from package
# metadata.
FRAMEWORK_VERSION = "0.1.0"

# Hard ceiling on agent loop iterations. A misbehaving model that keeps calling
# tools forever shouldn't run indefinitely. Echo-smoke finishes in 2-3 turns;
# this caps the worst case generously.
MAX_TURNS = 10


@dataclass(frozen=True)
class AgentSpec:
    """One agent participating in a scenario.

    Carries everything defining an agent's situation: its identity (recorded
    as agent_id in the trace), the system prompt defining its task, the
    message that opens its conversation, and the tools it may call.

    Tools are per-agent deliberately. Asymmetric capability is a research
    variable, not an edge case — one agent may hold a communication channel
    another does not.
    """

    agent_id: str
    system_prompt: str
    initial_user_message: str
    tools: list[Tool[Any, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class Scenario:
    """A scenario the runner can execute.

    Carries an identifier (for trace organization) and the agents taking
    part. Use Scenario.single_agent() for the one-agent case.

    Frozen because a scenario is a specification — mutating it mid-run would
    invalidate the trace's claim about what the agents were given.
    """

    id: str
    agents: list[AgentSpec]

    def __post_init__(self) -> None:
        """Reject scenarios that cannot produce a coherent trace."""
        if not self.agents:
            raise ValueError(f"scenario {self.id!r} has no agents")
        ids = [a.agent_id for a in self.agents]
        if len(set(ids)) != len(ids):
            raise ValueError(f"scenario {self.id!r} has duplicate agent_ids: {ids}")

    @classmethod
    def single_agent(
        cls,
        id: str,
        system_prompt: str,
        initial_user_message: str,
        tools: list[Tool[Any, Any]] | None = None,
        agent_id: str = "agent",
    ) -> "Scenario":
        """Build a one-agent scenario."""
        return cls(
            id=id,
            agents=[
                AgentSpec(
                    agent_id=agent_id,
                    system_prompt=system_prompt,
                    initial_user_message=initial_user_message,
                    tools=list(tools) if tools else [],
                )
            ],
        )

@dataclass(frozen=True)
class RunResult:
    """The outcome of a single run.

    Returned by run() so callers can inspect whether the run succeeded, how
    long it took, and where the trace landed. All the detail lives in the
    trace file at trace_path; this is the summary handle.
    """

    run_id: str
    status: Literal["ok", "aborted"]
    duration_ms: int
    event_count: int
    trace_path: Path
    abort_reason: str | None = None


def _build_trace_path(output_root: Path, scenario_id: str, model: str, run_id: str) -> Path:
    """Compute the canonical trace file path for a run.

    Format: {output_root}/{scenario_id}/{model_slug}/{run_id}.jsonl

    Slashes in the model id (e.g. "claude-3-7-sonnet-20250219") are kept
    as-is; the model id is already safe to use as a directory name.
    """
    return output_root / scenario_id / model / f"{run_id}.jsonl"


def run(
    scenario: Scenario,
    model: str,
    output_root: Path,
    seed: int = 0,
    dev_mode: bool = True,
    adapter: AnthropicAdapter | None = None,
) -> RunResult:
    """Execute one scenario run end-to-end.

    Wires together the trace writer, gateway, and adapter; drives the agent
    loop until the model stops requesting tools or MAX_TURNS is reached;
    emits run lifecycle events; returns a summary RunResult.

    Args:
        scenario: The scenario to execute.
        model: The model identifier (passed to the adapter; also part of the
            trace file path).
        output_root: Root directory under which traces are written. The trace
            for this run lands at {output_root}/{scenario.id}/{model}/{run_id}.jsonl.
        seed: Optional seed value, recorded in run_started for reproducibility.
            The framework doesn't use this directly yet (model providers don't
            all support seeded generation); it's recorded for audit purposes.
        dev_mode: Whether the agent runs in-process (True) vs. sandboxed (False).
            Currently only True is supported; recorded in run_started so future
            traces can be filtered by run mode.
        adapter: Optional pre-constructed adapter. If None, an AnthropicAdapter
            is built from `model` and `scenario.tools`. Tests inject a fake.

    Returns:
        A RunResult summarizing the run outcome and trace location.
    """
    run_id = uuid.uuid4().hex[:12]
    agent = scenario.agents[0]
    trace_path = _build_trace_path(output_root, scenario.id, model, run_id)
    start = time.monotonic()

    if adapter is None:
        adapter = AnthropicAdapter(model=model, tools=agent.tools)

    registry = ToolRegistry()
    for tool in agent.tools:
        registry.register(tool)

    status: Literal["ok", "aborted"] = "ok"
    abort_reason: str | None = None
    event_count = 0
    manifest = [
        ToolManifestEntry(
            name=tool.name,
            description=tool.description,
            args_schema=tool.args_schema.model_json_schema(),
            result_schema=tool.result_schema.model_json_schema(),
        )
        for tool in sorted(agent.tools, key=lambda t: t.name)
    ]
    with TraceWriter(trace_path) as writer:
        # Emit run_started immediately, before anything else can fail.
        writer.write(RunStartedEvent(
            actor="framework",
            payload=RunStartedPayload(
                schema_version=SCHEMA_VERSION,
                run_id=run_id,
                scenario_id=scenario.id,
                model_id=model,
                seed=seed,
                framework_version=FRAMEWORK_VERSION,
                dev_mode=dev_mode,
                tools_manifest=manifest,
            ),
        ))
        event_count += 1

        gateway = Gateway(registry, writer)

        # Initialize the conversation with the system prompt and first user message.
        conversation = Conversation(system=agent.system_prompt).with_message(
            Message(
                role="user",
                content=[TextContent(text=agent.initial_user_message)],
            )
        )

        # The agent loop.
        try:
            for _turn_number in range(MAX_TURNS):
                turn = adapter.get_turn(conversation)
                turn_id = uuid.uuid4().hex[:12]

                # Record the model's textual output, if any.
                if turn.text:
                    writer.write(AgentMessageEvent(
                        actor="agent",
                        agent_id=agent.agent_id,
                        payload=AgentMessagePayload(text=turn.text,turn_id=turn_id,),
                    ))
                    event_count += 1
                writer.write(ModelResponseEvent(
                    actor="framework",
                    agent_id=agent.agent_id,
                    payload=ModelResponsePayload(
                        turn_id=turn_id,
                        usage=turn.usage,
                        stop_reason=turn.stop_reason,
                        duration_ms=turn.duration_ms,
                    ),
                ))
                event_count += 1
                # If no tool calls, the model is done.
                if not turn.wants_tools:
                    break

                # Build an assistant message representing what the model just emitted
                # (text + tool_uses), so the next turn's conversation history is correct.
                assistant_content: list[Any] = []
                if turn.text:
                    assistant_content.append(TextContent(text=turn.text))
                assistant_content.extend(turn.tool_uses)
                conversation = conversation.with_message(
                    Message(role="assistant", content=assistant_content)
                )

                # Record each tool call as an event, route through the gateway,
                # and append the result to the conversation for the next turn.
                tool_result_blocks: list[Any] = []
                for tool_use in turn.tool_uses:
                    writer.write(ToolCallEvent(
                        actor="agent",
                        agent_id=agent.agent_id,
                        payload=ToolCallPayload(
                            tool=tool_use.tool,
                            call_id=tool_use.call_id,
                            args=tool_use.args,
                        turn_id=turn_id,
                        ),
                    ))
                    event_count += 1

                    result = gateway.route(
                        tool_name=tool_use.tool,
                        call_id=tool_use.call_id,
                        raw_args=tool_use.args,
                    turn_id=turn_id,
                    agent_id=agent.agent_id,
                    )
                    # The gateway has already written gateway_intent_logged +
                    # tool_result/tool_error; we counted those in writer side-effects
                    # but for accuracy we re-read event_count from the writer later.
                    # For thread one, we just increment for the events we KNOW were
                    # emitted by the gateway (2 events per call: intent + result/error).
                    event_count += 2

                    # Build the tool_result content for the next conversation turn.
                    if result is None:
                        tool_result_blocks.append(ToolResultContent(
                            call_id=tool_use.call_id,
                            result="tool call failed; see trace for details",
                            is_error=True,
                        ))
                    else:
                        tool_result_blocks.append(ToolResultContent(
                            call_id=tool_use.call_id,
                            result=result.model_dump(),
                        ))

                # Append the user message containing all tool results.
                conversation = conversation.with_message(
                    Message(role="user", content=tool_result_blocks)
                )
            else:
                # The for loop exhausted without break — we hit MAX_TURNS.
                status = "aborted"
                abort_reason = f"exceeded maximum turn limit ({MAX_TURNS})"

        except AdapterError as e:
            status = "aborted"
            abort_reason = f"adapter error ({e.error_type}): {e.message}"

        duration_ms = int((time.monotonic() - start) * 1000)

        # Emit the terminal event.
        if status == "ok":
            writer.write(RunCompletedEvent(
                actor="framework",
                payload=RunCompletedPayload(
                    status="ok",
                    duration_ms=duration_ms,
                    event_count=event_count + 1,  # +1 for this event
                ),
            ))
        else:
            assert abort_reason is not None
            writer.write(RunAbortedEvent(
                actor="framework",
                payload=RunAbortedPayload(
                    reason=abort_reason,
                    error_type=None,
                    duration_ms=duration_ms,
                    event_count=event_count + 1,
                ),
            ))
        event_count += 1

    return RunResult(
        run_id=run_id,
        status=status,
        duration_ms=duration_ms,
        event_count=event_count,
        trace_path=trace_path,
        abort_reason=abort_reason,
    )
