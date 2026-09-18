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
from typing import Any, Literal, NamedTuple

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

# Hard ceiling on agent loop iterations, per agent per round. A misbehaving
# model that keeps calling tools forever shouldn't run indefinitely.
# Echo-smoke finishes in 2-3 turns; this caps the worst case generously.
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

    Carries an identifier (for trace organization), the agents taking part,
    and how many rounds they act for. Use Scenario.single_agent() for the
    one-agent case.

    A round is one pass in which every agent acts once. Single-agent
    scenarios use rounds=1: the agent's turn loop runs to completion and the
    run ends. Multi-agent scenarios use rounds>1 to produce repeated
    interaction, which is what makes coordination possible at all.

    Frozen because a scenario is a specification — mutating it mid-run would
    invalidate the trace's claim about what the agents were given.
    """

    id: str
    agents: list[AgentSpec]
    rounds: int = 1

    def __post_init__(self) -> None:
        """Reject scenarios that cannot produce a coherent trace."""
        if not self.agents:
            raise ValueError(f"scenario {self.id!r} has no agents")
        ids = [a.agent_id for a in self.agents]
        if len(set(ids)) != len(ids):
            raise ValueError(f"scenario {self.id!r} has duplicate agent_ids: {ids}")
        if self.rounds < 1:
            raise ValueError(f"scenario {self.id!r} has rounds={self.rounds}; must be >= 1")

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


@dataclass
class _AgentRuntime:
    """Mutable per-agent state for the duration of a run.

    One per AgentSpec. Holds the agent's adapter, its gateway (and through it
    its own tool registry), and its conversation as that accumulates.

    Separate conversations are the whole point: each agent sees only what it
    was given and what it did. Nothing crosses between agents except through
    an explicit channel recorded in the trace.
    """

    spec: AgentSpec
    adapter: AnthropicAdapter
    gateway: Gateway
    conversation: Conversation


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


class _TurnLoopOutcome(NamedTuple):
    """What one agent's turn loop produced.

    Attributes:
        events: Number of trace events written during the loop.
        hit_turn_limit: True if the loop exhausted MAX_TURNS without the
            agent ever stopping — a run-aborting condition.
    """

    events: int
    hit_turn_limit: bool


def _build_trace_path(output_root: Path, scenario_id: str, model: str, run_id: str) -> Path:
    """Compute the canonical trace file path for a run.

    Format: {output_root}/{scenario_id}/{model_slug}/{run_id}.jsonl

    Slashes in the model id (e.g. "claude-3-7-sonnet-20250219") are kept
    as-is; the model id is already safe to use as a directory name.
    """
    return output_root / scenario_id / model / f"{run_id}.jsonl"


def _tools_manifest(tools: list[Tool[Any, Any]]) -> list[ToolManifestEntry]:
    """Describe a tool set as it was presented to an agent.

    Sorted by name so two identical runs produce identical traces.
    """
    return [
        ToolManifestEntry(
            name=tool.name,
            description=tool.description,
            args_schema=tool.args_schema.model_json_schema(),
            result_schema=tool.result_schema.model_json_schema(),
        )
        for tool in sorted(tools, key=lambda t: t.name)
    ]


def _build_runtime(
    spec: AgentSpec,
    model: str,
    adapter: AnthropicAdapter | None,
    writer: TraceWriter,
) -> _AgentRuntime:
    """Set up one agent's adapter, gateway, and opening conversation.

    Args:
        spec: The agent's specification.
        model: Model id, used only if an adapter must be constructed.
        adapter: Pre-constructed adapter, or None to build one. Tests inject
            a fake here.
        writer: Trace writer, handed to the agent's gateway.
    """
    registry = ToolRegistry()
    for tool in spec.tools:
        registry.register(tool)

    return _AgentRuntime(
        spec=spec,
        adapter=(
            adapter if adapter is not None
            else AnthropicAdapter(model=model, tools=spec.tools)
        ),
        gateway=Gateway(registry, writer),
        conversation=Conversation(system=spec.system_prompt).with_message(
            Message(
                role="user",
                content=[TextContent(text=spec.initial_user_message)],
            )
        ),
    )


def _run_agent_turns(
    rt: _AgentRuntime,
    writer: TraceWriter,
    max_turns: int = MAX_TURNS,
) -> _TurnLoopOutcome:
    """Drive one agent until it stops calling tools or max_turns is reached.

    Mutates rt.conversation as the exchange accumulates. The agent's context
    therefore carries forward across rounds, which is what makes repeated
    interaction meaningful rather than a sequence of unrelated prompts.

    Args:
        rt: The agent's runtime state. Its conversation is updated in place.
        writer: Trace writer. Events are attributed to rt.spec.agent_id.
        max_turns: Ceiling on model calls before the loop gives up.

    Returns:
        Events written, and whether the ceiling was hit.

    Raises:
        AdapterError: Propagated to the caller, which aborts the run.
    """
    events = 0
    agent_id = rt.spec.agent_id

    for _turn_number in range(max_turns):
        turn = rt.adapter.get_turn(rt.conversation)
        turn_id = uuid.uuid4().hex[:12]

        # Record the model's textual output, if any.
        if turn.text:
            writer.write(AgentMessageEvent(
                actor="agent",
                agent_id=agent_id,
                payload=AgentMessagePayload(text=turn.text, turn_id=turn_id),
            ))
            events += 1

        writer.write(ModelResponseEvent(
            actor="framework",
            agent_id=agent_id,
            payload=ModelResponsePayload(
                turn_id=turn_id,
                usage=turn.usage,
                stop_reason=turn.stop_reason,
                duration_ms=turn.duration_ms,
            ),
        ))
        events += 1

        # If no tool calls, the agent is done for this round.
        if not turn.wants_tools:
            return _TurnLoopOutcome(events=events, hit_turn_limit=False)

        # Build an assistant message representing what the model just emitted
        # (text + tool_uses), so the next turn's conversation history is correct.
        assistant_content: list[Any] = []
        if turn.text:
            assistant_content.append(TextContent(text=turn.text))
        assistant_content.extend(turn.tool_uses)
        rt.conversation = rt.conversation.with_message(
            Message(role="assistant", content=assistant_content)
        )

        # Record each tool call as an event, route through the gateway, and
        # append the result to the conversation for the next turn.
        tool_result_blocks: list[Any] = []
        for tool_use in turn.tool_uses:
            writer.write(ToolCallEvent(
                actor="agent",
                agent_id=agent_id,
                payload=ToolCallPayload(
                    tool=tool_use.tool,
                    call_id=tool_use.call_id,
                    args=tool_use.args,
                    turn_id=turn_id,
                ),
            ))
            events += 1

            result = rt.gateway.route(
                tool_name=tool_use.tool,
                call_id=tool_use.call_id,
                raw_args=tool_use.args,
                turn_id=turn_id,
                agent_id=agent_id,
            )
            # The gateway writes two events per call: intent, then either
            # result or error. Counted here since the writer doesn't report back.
            events += 2

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
        rt.conversation = rt.conversation.with_message(
            Message(role="user", content=tool_result_blocks)
        )

    return _TurnLoopOutcome(events=events, hit_turn_limit=True)


def run(
    scenario: Scenario,
    model: str,
    output_root: Path,
    seed: int = 0,
    dev_mode: bool = True,
    adapter: AnthropicAdapter | None = None,
) -> RunResult:
    """Execute one scenario run end-to-end.

    Wires together the trace writer, per-agent gateways, and adapters; drives
    each agent's turn loop for scenario.rounds rounds; emits run lifecycle
    events; returns a summary RunResult.

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
            is built per agent from `model` and that agent's tools. Tests
            inject a fake.

    Returns:
        A RunResult summarizing the run outcome and trace location.

    Raises:
        NotImplementedError: If the scenario has more than one agent. The
            structure supports it; the trace schema does not yet.
    """
    run_id = uuid.uuid4().hex[:12]
    trace_path = _build_trace_path(output_root, scenario.id, model, run_id)
    start = time.monotonic()

    if len(scenario.agents) > 1:
        # run_started carries a single flat tools_manifest. With several
        # agents holding different tools it would silently under-report, and
        # a trace that misstates what an agent was given is worse than no
        # trace. Per-agent manifests land in 3.3b; until then, fail loudly.
        raise NotImplementedError(
            f"scenario {scenario.id!r} has {len(scenario.agents)} agents; "
            "multi-agent runs need per-agent tool manifests (3.3b)"
        )

    status: Literal["ok", "aborted"] = "ok"
    abort_reason: str | None = None
    event_count = 0

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
                tools_manifest=_tools_manifest(scenario.agents[0].tools),
            ),
        ))
        event_count += 1

        runtimes = [
            _build_runtime(spec, model, adapter, writer)
            for spec in scenario.agents
        ]

        # The round loop. Each round, every agent acts once — where "acting
        # once" means driving its own turn loop until it stops calling tools.
        try:
            for _round_number in range(scenario.rounds):
                for rt in runtimes:
                    outcome = _run_agent_turns(rt, writer)
                    event_count += outcome.events
                    if outcome.hit_turn_limit:
                        status = "aborted"
                        abort_reason = (
                            f"agent {rt.spec.agent_id!r} exceeded maximum "
                            f"turn limit ({MAX_TURNS})"
                        )
                        break
                if status == "aborted":
                    break

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
