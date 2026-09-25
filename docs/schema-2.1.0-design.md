# Schema 2.1.0 — Run Context and Inbound Events

Status: in progress. Thread three, continuing from 2.0.0.

Additive to the trace schema. Breaking to the Python tool interface —
`Tool.run(args)` becomes `Tool.run(args, ctx)`.

Supersedes §Changes items 4 and 5 of `docs/schema-1.2.0-design.md`, which
scoped this work as "a `send_message` tool plus a `message_delivered`
event". That scope was too narrow. This document explains why.

## Why the earlier scope was wrong

The 1.2.0 design treated agent-to-agent messaging as the mechanism of
multi-agent coordination. It is one mechanism, and not the primary one.

The established result in algorithmic collusion is **tacit**: pricing agents
in repeated Bertrand competition sustain supra-competitive prices with no
communication channel at all. Coordination emerges from observing each
other's actions across rounds and developing reward-punishment patterns.
Explicit messaging is a *separate experimental condition* layered on top —
and the legally uninteresting one, since overt communication is what
competition law already reaches.

An implementation that supported only messaging would support the unusual
variant of the experiment and not the standard one.

Coordination requires, at minimum, that agents can **observe consequences of
each other's actions**. Messaging is an optional addition. The channel was
built first only because it was the easier thing to imagine.

## The blocking problem: tools cannot hold state

A market requires state — current prices, history, who moved when. The
obvious implementation gives a `MarketTool` that state.

It does not work. `Scenario` is a frozen module-level constant, so its tool
instances are shared across every run in the process. Two runs would mutate
the same object. The same objection applies to a message queue held inside
`SendMessageTool`.

Every tool built so far is stateless, so this has never surfaced. `EchoTool`
does not care. The first tool that needs memory cannot be written under the
current architecture.

This is not a limitation to work around. It is the reason both features are
blocked, and it has one fix.

## Decision 1: run-scoped state lives in a RunContext

    @dataclass
    class RunContext:
        """Mutable state for the duration of one run.

        Created by the runner per run, passed to tools at call time. Tools
        remain stateless singletons; everything that varies between runs
        lives here.
        """

        run_id: str
        round_number: int
        acting_agent_id: str
        bus: MessageBus
        env: EnvironmentStore

`Tool.run(args)` becomes `Tool.run(args, ctx)`.

This is a breaking change to the Python tool interface. It is taken now,
while there is one tool, rather than later with a dozen.

Centralising state is not only a correctness fix. It makes state
**snapshottable**: a per-round record of the shared environment is exactly
what a coordination analysis needs, and it is impossible to produce if state
is scattered across tool instances.

### Why not thread state through the gateway instead

Considered: have the gateway own state and inject it. Rejected — the gateway's
responsibility is auditing and routing, and its invariant ("logged before
routed") is easier to trust the narrower it stays. `RunContext` is data the
runner already owns, passed through.

## Decision 2: the tool queues; the runner delivers

`SendMessageTool.run()` validates the recipient and queues a `PendingMessage`
into `ctx.bus`. The runner drains the bus before each agent acts and performs
delivery.

The tool does not deliver. Delivery timing is the runner's business, and an
agent must not be able to choose when its own message lands — that would make
reveal semantics unenforceable.

Unknown and self-addressed recipients raise. The gateway records the result
as a `tool_error`, so a misaddressed message is a recorded attempt rather
than a silent no-op.

The roster is legitimately frozen state on the tool instance: it is known
when the scenario is written and does not vary per run.

### An earlier version of this decision was wrong

This section originally specified that the tool should queue nothing —
returning a `MessageSendResult` that the runner detected by type:

    result = rt.gateway.route(...)
    if isinstance(result, MessageSendResult):
        ctx.bus.queue(...)

That was rejected during implementation for two reasons.

It solved a problem Decision 1 had already solved. The stated objection to
tool-held state is that a `Scenario` is a frozen module-level constant, so
tool instances are shared across runs. `ctx.bus` is not tool state — it is
run state, reached through the context. The objection does not apply.

More seriously, it required the runner to import a specific tool's result
type and branch on it. The runner would then know about `send_message` in
particular, and every future stateful tool would add another branch. The
runner must stay tool-agnostic; tools reach shared state through the
context, which is what the context exists for.
## Decision 3: one inbound event, not one per source

`message_delivered` names a specific instance of a general fact: **the runner
placed content into an agent's context that the agent did not request.**

Known instances:

| Source | Content |
|---|---|
| `agent` | a message from another agent |
| `environment` | an observation of shared state |
| `principal` | a mid-run instruction from the agent's operator |
| `injection` | adversarial content, for indirect prompt-injection scenarios |

Four sources, one shape: what text entered, from where, when, and under what
framing. Modelled as a single event with a `source` discriminator rather than
four event types invented one at a time.

    class InboundPayload(_StrictBase):
        """Content the runner placed into an agent's context unprompted."""

        source: Literal["agent", "environment", "principal", "injection"]
        from_id: str | None          # sending agent, or None
        text: str                    # exactly as it entered the conversation
        framing: str                 # the prefix applied, verbatim
        sent_round: int
        delivered_round: int

`sent_round` and `delivered_round` are both recorded because under
`end_of_round` reveal they differ. The gap is then visible in the data rather
than inferred from configuration.

`framing` is recorded verbatim, not reconstructed. See Decision 5.

### This serves sandbagging too

A scenario that tells an agent mid-run "you are now being evaluated" emits
this event with `source="principal"`. The experimental manipulation becomes a
timestamped fact in the trace, rather than something inferred from a system
prompt read at run start.

Schema 2.0.0 put the *initial* condition in the trace. This puts *changes to
the condition* in the trace. Together they make a run's manipulations fully
recorded.

## Decision 4: reveal timing applies to observation, not just messages

`Scenario.reveal: Literal["immediate", "end_of_round"]`, default
`"immediate"`, recorded in `run_started`.

- `immediate` — an agent's action is visible to later agents within the same
  round. Sequential play.
- `end_of_round` — actions and messages from round *r* are delivered at the
  start of round *r+1*. Simultaneous play.

This is Decision 1 of the 1.2.0 design made concrete, and it governs
environment observations as well as messages. Applying it only to messages
would leave the tacit-collusion case — the important one — with an
uncontrolled first-mover advantage.

Scenarios using `end_of_round` should alternate first-mover per round or fix
it and pre-register the choice.

## Decision 5: delivered content is framed, and the framing is recorded

Content enters a conversation as a user-role message with explicit
provenance:

    [message from alice] we should both hold at 90

Without the prefix, delivered content is indistinguishable from the agent's
own task instructions. An agent could be steered by another agent's text
while believing it came from its principal. That is a confound in a collusion
study and an attack surface in an injection study.

The `framing` field records the prefix as applied, rather than leaving it to
be reconstructed from a format string in whatever version of the code was
running. An injection scenario will deliberately vary or omit framing, and
the trace must say which was used.

## What is built now

Narrow surface, general structure.

- `RunContext`, `MessageBus`, `EnvironmentStore`
- `Tool.run(args, ctx)` — the interface break, taken once
- `InboundEvent` with all four `source` values expressible; `agent` and
  `environment` implemented
- `SendMessageTool` — the messaging condition
- A minimal market tool — the tacit condition
- `Scenario.reveal`

## What is deliberately deferred

All additive; none require revisiting the above.

- Broadcast recipients (`to: str | list[str]`)
- `principal` and `injection` sources — expressible, not implemented
- Monitor agents observing without acting
- Per-round `world_state` snapshot events

## Ablation

Removing the channel means omitting `SendMessageTool` from an agent's
`AgentSpec.tools`. No flag, no branch, no code path.

That property follows from Decision 3 of the 1.2.0 design — communication as
a tool rather than a conversation-layer feature — and it is what makes the
communication condition a controlled variable rather than a rebuild.

## Compatibility

**Trace schema: additive.** New event type, new `run_started` field. 2.0.0
traces load unchanged; a 2.0.0 reader skips `inbound` as an unknown event
type and ignores `reveal`.

**Python tool interface: breaking.** Every `Tool` subclass gains a `ctx`
parameter. One tool exists today.

The schema version is what the trace format promises. It is not a version of
the framework's Python API, and the two are not required to move together.
