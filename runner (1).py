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
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal, NamedTuple

from marionette.adapter.anthropic import AdapterError, AnthropicAdapter
from marionette.adapter.conversation import (
    Conversation,
    Message,
    TextContent,
    ToolResultContent,
)
from marionette.bus import MessageBus
from marionette.context import RunContext
from marionette.environment import EnvironmentRecord, EnvironmentStore, Observes
from marionette.gateway.gateway import Gateway
from marionette.gateway.registry import ToolRegistry
from marionette.gateway.tool import Tool
from marionette.resolver import Resolver
from marionette.trace.schema import (
    SCHEMA_VERSION,
    AgentManifestEntry,
    AgentMessageEvent,
    AgentMessagePayload,
    EnvironmentRecordEntry,
    FrameworkNoteEvent,
    FrameworkNotePayload,
    InboundEvent,
    InboundPayload,
    ModelResponseEvent,
    ModelResponsePayload,
    ResolverManifest,
    RoundCompletedEvent,
    RoundCompletedPayload,
    RoundResolvedEvent,
    RoundResolvedPayload,
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

# How delivered content is framed in a recipient's conversation. Recorded
# verbatim on every inbound event: without an explicit marker, another
# agent's text is indistinguishable from the recipient's own instructions.
AGENT_MESSAGE_FRAMING = "[message from {from_id}]"

# Framing for environment observations. Distinct from agent messages so a
# recipient can tell a rival's action from a rival's claim about its action.
ENVIRONMENT_FRAMING = "[market]"

# Prompts from the operator carry no prefix. They arrive on the same channel
# as the opening message, and marking them would tell an agent which of its
# instructions were delivered mid-run. Recorded as "" because framing is
# what was applied, not what could have been.
PRINCIPAL_FRAMING = ""

@dataclass(frozen=True)
class AgentSpec:
    """One agent participating in a scenario.

    Carries everything defining an agent's situation: its identity (recorded
    as agent_id in the trace), the system prompt defining its task, the
    message that opens its conversation, and the tools it may call.

    Tools are per-agent deliberately. Asymmetric capability is a research
    variable, not an edge case — one agent may hold a communication channel
    another does not.

    observes is the information condition. Per-agent because asymmetric
    information is a condition someone will want — one seller watching the
    market while the other cannot is a real experiment, not an edge case.
    """

    agent_id: str
    system_prompt: str
    initial_user_message: str
    tools: list[Tool[Any, Any]] = field(default_factory=list)
    observes: Observes = "all"
    acts_by: str | None = None
    round_prompt: str | None = None

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

    reveal controls when an agent's action becomes visible to the others.
    "immediate" means within the same round — sequential play. "end_of_round"
    holds actions and messages until the next round begins — simultaneous
    play. The distinction is not cosmetic: under sequential play, apparent
    coordination may be nothing more than best-response to an observed move.

    resolver, when set, computes what a round's actions produced. It runs
    once per completed round and its records enter the environment, becoming
    observable in the round that follows. Scenarios with no notion of
    outcome — sandbagging, for instance — leave it None.

    Frozen because a scenario is a specification — mutating it mid-run would
    invalidate the trace's claim about what the agents were given.
    """

    id: str
    agents: list[AgentSpec]
    rounds: int = 1
    reveal: Literal["immediate", "end_of_round"] = "immediate"
    resolver: Resolver | None = None

    def __post_init__(self) -> None:
        """Reject scenarios that cannot produce a coherent trace."""
        if not self.agents:
            raise ValueError(f"scenario {self.id!r} has no agents")
        ids = [a.agent_id for a in self.agents]
        if len(set(ids)) != len(ids):
            raise ValueError(f"scenario {self.id!r} has duplicate agent_ids: {ids}")
        if self.rounds < 1:
            raise ValueError(f"scenario {self.id!r} has rounds={self.rounds}; must be >= 1")
        for a in self.agents:
            if a.acts_by is None:
                continue
            names = {t.name for t in a.tools}
            if a.acts_by not in names:
                raise ValueError(
                    f"agent {a.agent_id!r} has acts_by={a.acts_by!r} but no such "
                    f"tool; has {sorted(names)}"
                )

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
    acted: bool


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

def _agent_manifest(specs: list[AgentSpec], model: str) -> list[AgentManifestEntry]:
    """Describe every agent's situation as configured at run start.

    model_id is the run's model for every agent today. The field is
    per-agent so heterogeneous runs need no further schema change.
    """
    return [
        AgentManifestEntry(
            agent_id=spec.agent_id,
            model_id=model,
            system_prompt=spec.system_prompt,
            initial_user_message=spec.initial_user_message,
            tools=_tools_manifest(spec.tools),
            observes=spec.observes,
            acts_by=spec.acts_by,
            round_prompt=spec.round_prompt,
        )
        for spec in specs
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


def _resolve_round(
    resolver: Resolver,
    env: EnvironmentStore,
    writer: TraceWriter,
    round_number: int,
) -> int:
    """Compute and record the outcome of a completed round.

    Called only for rounds that finished. An aborted round has an incomplete
    set of actions, and resolving it would record an outcome that never
    happened.
    """
    records = resolver.resolve(env, round_number)
    for r in records:
        env.record(r)

    writer.write(RoundResolvedEvent(
        actor="framework",
        payload=RoundResolvedPayload(
            round_number=round_number,
            records=[_record_entry(r) for r in records],
        ),
    ))
    return 1


def _record_entry(r: EnvironmentRecord) -> EnvironmentRecordEntry:
    """Convert a runtime record to its trace form."""
    return EnvironmentRecordEntry(
        agent_id=r.agent_id,
        round_number=r.round_number,
        summary=r.summary,
        data=r.data,
        audience=r.audience,
    )


def _deliver_inbound(
    rt: _AgentRuntime,
    writer: TraceWriter,
    ctx: RunContext,
    reveal: Literal["immediate", "end_of_round"],
) -> int:
    """Place any messages waiting for this agent into its conversation.

    Called before the agent acts. Each delivery is recorded as an inbound
    event and appended as a user-role message with explicit provenance.

    Returns:
        The number of events written.
    """
    messages = ctx.bus.drain_for(rt.spec.agent_id, ctx.round_number, reveal)
    records = ctx.env.latest_round_visible_to(
        rt.spec.agent_id, ctx.round_number, reveal, rt.spec.observes
    )
    prompt = _round_prompt_text(rt.spec, ctx.round_number)

    blocks: list[Any] = []
    events = 0

    for m in messages:
        framing = AGENT_MESSAGE_FRAMING.format(from_id=m.from_id)
        writer.write(InboundEvent(
            actor="framework",
            agent_id=rt.spec.agent_id,
            payload=InboundPayload(
                source="agent",
                from_id=m.from_id,
                text=m.text,
                framing=framing,
                sent_round=m.sent_round,
                delivered_round=ctx.round_number,
            ),
        ))
        blocks.append(TextContent(text=f"{framing} {m.text}"))
        events += 1

    for r in records:
        text = f"{r.agent_id} {r.summary}"
        writer.write(InboundEvent(
            actor="framework",
            agent_id=rt.spec.agent_id,
            payload=InboundPayload(
                source="environment",
                from_id=r.agent_id,
                text=text,
                framing=ENVIRONMENT_FRAMING,
                sent_round=r.round_number,
                delivered_round=ctx.round_number,
            ),
        ))
        blocks.append(TextContent(text=f"{ENVIRONMENT_FRAMING} {text}"))
        events += 1

    # The prompt comes last: "here is what happened, now act". The reverse
    # order asks an agent to act before telling it what changed.
    if prompt is not None:
        writer.write(InboundEvent(
            actor="framework",
            agent_id=rt.spec.agent_id,
            payload=InboundPayload(
                source="principal",
                from_id=None,
                text=prompt,
                framing=PRINCIPAL_FRAMING,
                sent_round=ctx.round_number,
                delivered_round=ctx.round_number,
            ),
        ))
        events += 1
        # Round 0's prompt is already in the conversation as its opening
        # message — a conversation cannot begin empty. It is still recorded
        # here so every round has exactly one principal prompt in the trace
        # and an analysis need not special-case the first.
        if ctx.round_number > 0:
            blocks.append(TextContent(text=prompt))

    if blocks:
        rt.conversation = rt.conversation.with_message(
            Message(role="user", content=blocks)
        )
    return events


def _round_prompt_text(spec: AgentSpec, round_number: int) -> str | None:
    """What the operator says to this agent at the start of a round.

    Round 0 uses initial_user_message, which opens the conversation. Later
    rounds use round_prompt, if the scenario sets one. A scenario with no
    round_prompt tells agents nothing after the first round — which is
    correct for a single-episode scenario and a bug for a repeated one.
    """
    if round_number == 0:
        return spec.initial_user_message
    if spec.round_prompt is None:
        return None
    return spec.round_prompt.format(round=round_number)


def _run_agent_turns(
    rt: _AgentRuntime,
    writer: TraceWriter,
    ctx: RunContext,
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
        turn_ctx = replace(ctx, turn_id=turn_id)

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

        # If no tool calls, the agent has nothing more to do this round.
        # With no acts_by set, finishing the loop IS the round's action —
        # that is the single-episode behaviour from thread one. With acts_by
        # set, stopping without calling it means the agent stayed silent.
        if not turn.wants_tools:
            return _TurnLoopOutcome(
                events=events,
                hit_turn_limit=False,
                acted=rt.spec.acts_by is None,
            )

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
        acted = False
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
                ctx=turn_ctx,
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
                # A round ends on the action succeeding, not on the agent
                # attempting it. A call that failed validation must not end
                # the round, or an agent loses its turn to a typo.
                if rt.spec.acts_by is not None and tool_use.tool == rt.spec.acts_by:
                    acted = True

        # Append the user message containing all tool results. Done before
        # returning so the agent sees its own result at the start of the
        # next round.
        rt.conversation = rt.conversation.with_message(
            Message(role="user", content=tool_result_blocks)
        )

        if acted:
            return _TurnLoopOutcome(events=events, hit_turn_limit=False, acted=True)

    return _TurnLoopOutcome(events=events, hit_turn_limit=True, acted=False)


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

    """
    run_id = uuid.uuid4().hex[:12]
    trace_path = _build_trace_path(output_root, scenario.id, model, run_id)
    start = time.monotonic()

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
                rounds=scenario.rounds,
                reveal=scenario.reveal,
                resolver=(
                    ResolverManifest(
                        name=scenario.resolver.name,
                        description=scenario.resolver.description,
                        params=scenario.resolver.params,
                    )
                    if scenario.resolver is not None
                    else None
                ),
                agents=_agent_manifest(scenario.agents, model),
            ),
        ))
        event_count += 1

        bus = MessageBus()
        env = EnvironmentStore()
        # A resolver writing outcomes to an agent that cannot see them is a
        # legal configuration and occasionally the intended one, but it is
        # also the easiest way to run a condition you did not mean to. Note
        # it in the trace rather than letting it be silent.
        if scenario.resolver is not None:
            blind = [a.agent_id for a in scenario.agents if a.observes == "none"]
            if blind:
                writer.write(FrameworkNoteEvent(
                    actor="framework",
                    payload=FrameworkNotePayload(
                        text=(
                            f"resolver {scenario.resolver.name!r} is active but "
                            f"{', '.join(blind)} observes=none; outcomes are "
                            "computed and recorded but never delivered to them"
                        ),
                        level="warning",
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
            for round_number in range(scenario.rounds):
                acted_this_round: list[str] = []
                for rt in runtimes:
                    agent_ctx = RunContext(
                        run_id=run_id,
                        round_number=round_number,
                        turn_id="",
                        acting_agent_id=rt.spec.agent_id,
                        bus=bus,
                        env=env,
                    )
                    event_count += _deliver_inbound(
                        rt, writer, agent_ctx, scenario.reveal
                    )
                    outcome = _run_agent_turns(rt, writer, agent_ctx)
                    event_count += outcome.events
                    if outcome.acted:
                        acted_this_round.append(rt.spec.agent_id)
                    if outcome.hit_turn_limit:
                        status = "aborted"
                        abort_reason = (
                            f"agent {rt.spec.agent_id!r} exceeded maximum "
                            f"turn limit ({MAX_TURNS})"
                        )
                        break
                if status == "aborted":
                    break

                # Who took part, recorded whether or not a resolver exists.
                # Scenario pre-registrations exclude rounds in which an agent
                # stayed silent, and an exclusion rule that cannot be applied
                # mechanically is not a rule.
                writer.write(RoundCompletedEvent(
                    actor="framework",
                    payload=RoundCompletedPayload(
                        round_number=round_number,
                        agents_acted=acted_this_round,
                        agents_silent=[
                            a.agent_id for a in scenario.agents
                            if a.agent_id not in acted_this_round
                        ],
                    ),
                ))
                event_count += 1

                if scenario.resolver is not None:
                    event_count += _resolve_round(
                        scenario.resolver, env, writer, round_number
                    )

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
