# Schema 1.2.0 — Multi-Agent Observation

Status: in progress. Thread three.

Extends 1.1.0 to observe runs containing more than one agent. Additive
within major version 1: new fields and new event types only.

## Motivation

Thread two closed the reproducibility gaps found in validation week. This
thread addresses a capability gap: Marionette can observe one agent acting
against tools, but not several agents acting in the presence of each other.

The immediate target is the AI Collusion Research Sprint (Apart Research,
23-25 October 2026). The durable target is multi-agent coordination as a
research subject — of which collusion is one instance.

## Decision 1: execution order is not game structure

Agents execute sequentially. One acts per round, single-threaded, so `seq`
remains a total order and the writer stays unchanged.

Sequential *execution* must not imply sequential *play*. If agent B observes
agent A's round-r action while choosing its own round-r action, the scenario
is a Stackelberg game, not Bertrand competition. These have different
equilibria, and coordination observed under sequential play may be nothing
more than best-response.

Visibility is therefore a scenario property, independent of execution:

- `reveal="immediate"` — round-r actions visible within round r (sequential)
- `reveal="end_of_round"` — round-r actions visible from round r+1
  (simultaneous)

Scenarios using `end_of_round` should alternate first-mover each round, or
fix it and pre-register the choice. Residual order effects are a confound
either way; the only unacceptable option is leaving it implicit.

## Decision 2: `agent_id` is distinct from `actor`

`actor` names the component that emitted an event: framework, agent,
gateway. `agent_id` names which agent the event is attributable to. Two
agents both carry `actor="agent"` and differ only by `agent_id`.

Declared on `_EventBase`, not on payloads. It is provenance metadata, the
same category as `actor`, not content.

Nullable for backward compatibility. For agent-attributable events the
runner always sets it, including single-agent runs. Run-level events
(run_started, run_completed, run_aborted) carry None because no agent is
responsible for them. None therefore means "run-level event, or a trace
predating 1.2.0" — never "a single-agent run we didn't bother labelling".

## Decision 3: the communication channel is a tool

Agent-to-agent messaging is a `Tool`, not a conversation-layer feature.

Consequences, all of them wanted:

- Sends route through the gateway, so the logged-before-routed audit
  invariant covers agent communication without new machinery.
- The channel appears in `tools_manifest`, so a trace records that an agent
  *had* a channel, not only that it used one.
- **The channel is ablatable by omission.** Running a scenario with and
  without the tool is the active control METHODOLOGY.md requires. Building
  communication into the conversation layer would make it structural and
  impossible to remove.

## Decision 4: delivery is recorded separately from sending

A tool call records that agent A *sent* a message. It does not record that
agent B *received* one.

For collusion research the object of study is each agent's information
state. A trace that cannot reconstruct what an agent saw, and when, cannot
support a claim about coordination. Sending and receiving are therefore
distinct recorded facts.

`message_delivered` is emitted by the runner when a message is injected into
a recipient's conversation. Delivery timing is where Decision 1 is
implemented: under `end_of_round`, messages sent in round r are delivered at
the start of round r+1.

## Relationship to external standards

OpenTelemetry's GenAI semantic conventions moved to a dedicated repository
in June 2026 and remain marked Development with no official release; the
agent-specific conventions are experimental. A2A is a client-server task
delegation protocol under the Linux Foundation, organised around Agent Cards
and capability discovery.

Marionette adopts neither, for reasons of kind rather than timing:

- OTel targets operational observability. Spans are a tree, sampled and
  lossy by design. Research traces must be complete and totally ordered.
- A2A models delegation between heterogeneous agents. Collusion scenarios
  use symmetric peers. Forcing the shape would add ceremony without meaning.

Vocabulary is aligned where alignment is free — `TokenUsage.input_tokens`
maps to `gen_ai.usage.input_tokens`, `call_id` to `gen_ai.tool.call.id` —
so that an exporter, if ever wanted, is mechanical. See §Field mapping.

## Changes

### 1. `agent_id` on `_EventBase`  — DONE (3.1)

    agent_id: str | None = None

### 2. `AgentSpec` and `Scenario.agents` — DONE (3.2)

Delivered as specced. Per-agent tool manifests, which this document assigned
here, were instead delivered by schema 2.0.0 — the manifest was relocated to
`AgentManifestEntry` rather than duplicated alongside the existing flat one.
See `docs/schema-2.0.0-design.md`.

### 3. Runner alternates over N agents — DONE (3.3)

Agents execute sequentially within each round, each with its own
conversation, gateway, and tool registry.

### 4. `send_message` tool, `message_delivered` event, reveal timing — 3.4

### 5. Collusion scenario with no-channel ablation — 3.5

## Field mapping (OTel GenAI, for reference only)

| Marionette | OTel GenAI |
|---|---|
| `TokenUsage.input_tokens` | `gen_ai.usage.input_tokens` |
| `TokenUsage.output_tokens` | `gen_ai.usage.output_tokens` |
| `ToolCallPayload.tool` | `gen_ai.tool.name` |
| `ToolCallPayload.call_id` | `gen_ai.tool.call.id` |
| `RunStartedPayload.model_id` | `gen_ai.request.model` |

No dependency is implied. This table exists so a future exporter is a
translation rather than a redesign.

## Compatibility

Backward: 1.1.0 traces load under 1.2.0 with `agent_id` defaulting to None.

Forward: a 1.1.0 reader meeting a 1.2.0 trace skips `message_delivered` as
an unknown event type and ignores `agent_id` as an unknown field. Tested in
`tests/test_schema_compat.py::test_unknown_event_type_is_skipped`.
