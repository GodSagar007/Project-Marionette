# Schema 2.0.0 — Agent-Scoped Configuration

Status: in progress. Thread three, supersedes the 1.2.0 design for the
run_started payload.

The first breaking change to the trace schema. It corrects a modeling error
that has been present since 1.1.0 and was invisible while Marionette could
only observe one agent.

## The error

Schema 1.1.0 (§2.2) added `tools_manifest` to `RunStartedPayload`, closing a
reproducibility gap: traces recorded what an agent *did* with its tools but
not what tools it *had*.

The field was placed on `run_started`. At the time there was exactly one
agent, so "the run's tools" and "the agent's tools" named the same object and
the conflation cost nothing.

They are not the same object. A tool manifest describes an agent's situation.
`run_started` describes a run. Filing one under the other was wrong on the
day it was written; multi-agent support merely made it visible.

This distinction matters because the fix follows from it. The problem is not
"the manifest cannot express two agents" — that framing invites a second
manifest somewhere else plus a precedence rule. The problem is that the
manifest is attached to the wrong subject. There is one correct place for it,
and it is not `run_started`.

## A second gap, same class

2.2 asked what tools the agent had. It never asked what the agent was *told*.

System prompts and opening messages appear nowhere in the trace. They live
only in the scenario source. This is exactly the argument 2.2 rejected for
tools: a trace should be self-describing, reproducible without the scenario
file sitting beside it.

The gap is more consequential than the tools one.

**Sandbagging (Scenario 01).** The experimental manipulation — whether the
agent believes it is being evaluated — is expressed in the system prompt. A
trace currently cannot report which condition it recorded. The condition
would have to be inferred from a filename or a lab notebook. For a scenario
whose METHODOLOGY.md commits to pre-registration and active controls, that is
not acceptable: the trace cannot evidence the very variable under test.

**Collusion.** Whether agents received symmetric or asymmetric instructions
is a variable to be reported, not reconstructed. Asymmetric prompting is a
condition, and conditions belong in the data.

Both gaps have the same shape and the same fix, so they are closed together.

## The change

    class AgentManifestEntry(_StrictBase):
        """One agent's situation as configured at run start."""

        agent_id: str
        model_id: str
        system_prompt: str
        initial_user_message: str
        tools: list[ToolManifestEntry] = Field(default_factory=list)

    class RunStartedPayload(_StrictBase):
        schema_version: str
        run_id: str
        scenario_id: str
        model_id: str
        seed: int
        framework_version: str
        dev_mode: bool
        rounds: int = 1
        agents: list[AgentManifestEntry] = Field(default_factory=list)
        # tools_manifest — REMOVED. See "Why not additive" below.

`rounds` is recorded because the number of interaction rounds is part of the
experimental configuration. A three-round run and a thirty-round run are
different experiments, and the trace should say which it was.

### Why nested, not a separate `agent_started` event

An `agent_started` event per agent was considered and rejected.

The agent roster is fixed at run start. No agent joins partway through in
either research line. The experimental setup is therefore a single atomic
fact, and recording it atomically means a trace containing `run_started`
describes the complete configuration — even if writing stopped one
millisecond later.

Splitting across N+1 events would trade that guarantee for dynamic-roster
flexibility that no current or planned scenario needs. If agents ever do join
mid-run, that is a genuinely new event with genuinely different semantics
(`agent_joined`), not a reason to fragment static configuration now.

### Why `model_id` appears twice

`run_started.model_id` is the run's default model. `AgentManifestEntry.model_id`
is the model that agent actually used.

These are different facts, not a duplication with a precedence rule. The
per-agent value is always present and always authoritative; the run-level
value records what was requested.

Heterogeneous agents are a real collusion variable — one model negotiating
against another, or two instances of the same model. The runner sets both
fields from the same source today. Supporting genuinely per-agent models
later becomes a runner change with no further schema work, which is worth
securing now while the schema is already breaking.

## Why not additive

Removing a field is not additive. This is a major version bump, and that
contradicts the compatibility discipline established in 1.1.0 §Migration.

The alternative was to retain `tools_manifest`, never write to it, and
document it as vestigial. That preserves the letter of the discipline and
violates its purpose: every future reader would find two fields describing
tools and have to learn which to trust.

The discipline exists to protect research data. There is none yet. What
breaks is a handful of echo-smoke traces and one compatibility test — no
published result, no analysed run, nothing anyone will need again.

A major bump will never be cheaper than it is today. Carrying a dead field to
preserve smoke-test traces is the kind of compromise that accrues interest
for years.

There is a secondary benefit. The compatibility tests currently only
demonstrate that additive changes are additive. After this bump they encode a
real incompatibility — a 1.x trace that legitimately fails to load — which is
a materially stronger guarantee than the one they assert today.

## Compatibility

**Backward: partial, and asymmetric.** A 1.0.0 trace loads — it predates
`tools_manifest`, so `run_started` carries no field 2.0.0 rejects, and
`agents` simply defaults to empty. The trace reads, degraded: it reports no
agent configuration because none was ever recorded.

A 1.1.0 or 1.2.0 trace does not. Its `run_started` carries `tools_manifest`,
now an unexpected field, which `_StrictBase` rejects on `extra="forbid"`.
Because `TraceReader` is lenient, that line is skipped with a warning rather
than raising — the file still opens and its other events still load, but the
run's configuration is gone.

This asymmetry is worth stating plainly: the traces that fail are the newer
ones. Verified against the implementation rather than assumed.

## Implementation order

- **2.0.1** `AgentManifestEntry`, `RunStartedPayload.agents` and `rounds`,
  remove `tools_manifest`, bump `SCHEMA_VERSION`
- **2.0.2** runner builds the agent manifest; remove the multi-agent
  `NotImplementedError` guard
- **2.0.3** compatibility tests assert that 1.x traces fail to load; delete
  `runs/`
- **2.0.4** a two-agent scenario exercising the path end to end

## Relationship to the 1.2.0 design

The 1.2.0 document remains the contract for `agent_id` on `_EventBase`
(Decision 2), the channel-as-tool decision (Decision 3), and the separation
of execution order from game structure (Decision 1). Those are unaffected.

Only its §Changes item 2 is superseded: per-agent tool manifests are
delivered here, by relocating the manifest rather than duplicating it.
