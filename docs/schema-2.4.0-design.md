# Schema 2.4.0 — Round Completion

Status: in progress. Thread three.

Additive to the trace schema. Additive to the Python API.

Fixes a bug the first pilot run exposed: across twenty rounds, each agent
acted once.

## What the pilot found

Running condition A of scenario 02 produced two price records for twenty
rounds, and 42 model calls where ~80 were expected. Every round after the
first resolved to nothing.

The cause is that `_run_agent_turns` returns when the agent stops calling
tools. That is the episode loop from thread one, where one agent ran to
completion and the run ended. Rounds were added around it without changing
it.

So "the agent has finished this round" and "the agent has finished" became
the same event. An agent prices, says it is done, and every later round
finds a conversation whose last message says exactly that. It answers that
it is still done.

Echo-smoke never caught this because it is one round.

## Why a round prompt is not the fix

The obvious repair is to tell the agent a new round began. It would work,
and it would be wrong.

The framework would still have no notion of a round ending. The symptom
would go while the confusion stayed, and the next scenario with a different
action structure would rediscover it.

It would also leave the conditions incomparable in a way unrelated to the
experiment. In conditions C and D an observation arrives each round and
incidentally functions as a prompt. In condition A nothing arrives. The
control would differ from the treatments in *why rounds continue*, not only
in information.

A round prompt is still needed — an agent must know a new round has begun —
but as a small part of the fix rather than the whole of it.

## Decision 1: a round ends when the agent acts

    acts_by: str | None = None      # on AgentSpec

The name of the tool whose successful call completes this agent's round.

`None` preserves today's behaviour: run until the agent stops calling tools.
Sandbagging has no per-round action and sets nothing.

In scenario 02 it is `set_price`. In a negotiation it might be a different
tool; in a scenario with two required actions, `acts_by` is insufficient and
that is future work rather than a reason to generalise now.

Per-agent rather than per-scenario, following 2.3.0: a monitor agent that
observes without acting is a role someone will want, and it would set
`acts_by` to nothing while its counterparts set it.

**Successful means the gateway returned a result.** Not that the agent
emitted a tool call. A `set_price` that fails validation must not end a
round, or an agent loses its turn to a typo — and the already-priced guard
would make a retry impossible.

`MAX_TURNS` remains as a backstop. An agent that never calls its action tool
still terminates.

This also bounds the turn budget by design. An agent that ends its round on
its action cannot spend ten turns arguing with a tool error, which was the
cost risk the pilot was run to measure.

### Validation

`Scenario.__post_init__` rejects an `acts_by` naming a tool the agent does
not have. The failure mode otherwise is silent: every round runs to
`MAX_TURNS` and the run costs five times what it should.

## Decision 2: the round prompt is a principal message

    round_prompt: str | None = None      # on AgentSpec, a template taking {round}

Delivered at the start of each round as an `inbound` event with
`source="principal"` — a mid-run instruction from the agent's operator,
which is what this is. The source value already exists in the 2.1.0
Literal; nothing in the schema changes.

**Ordering: observations first, then the prompt.** "Here is what happened,
now act" is coherent. The reverse is not.

**Round 0 is recorded the same way.** Its prompt arrives as the opening
conversation message rather than an appended one, because a conversation
cannot begin empty. But the runner still placed that text into the agent's
context, which is what `inbound` records. Emitting it uniformly means an
analysis need not special-case the first round.

`initial_user_message` therefore *is* round 0's prompt. When `round_prompt`
is set it covers rounds 1 onward. The mechanical asymmetry is inherent to
how conversations start; the trace does not inherit it.

## Decision 3: participation is recorded separately from outcome

    class RoundCompletedPayload(_StrictBase):
        round_number: int
        agents_acted: list[str]
        agents_silent: list[str]

Emitted at the end of every round, whether or not a resolver exists.

`round_resolved` records what the world produced. `round_completed` records
who took part. They are different facts, and only the second exists in a
scenario with no outcome rule.

This is required, not decorative. Scenario 02's pre-registration excludes
rounds in which either agent posted no price. That rule needs those rounds
to be **findable**, and a `framework_note` containing prose is not findable.
An exclusion criterion that cannot be applied mechanically is not a
criterion.

## Changes

- `AgentSpec.acts_by: str | None = None`
- `AgentSpec.round_prompt: str | None = None`
- `AgentManifestEntry` gains both — they are the experimental configuration
- `RoundCompletedEvent` / `RoundCompletedPayload`
- `_run_agent_turns` returns on a successful `acts_by` call
- Runner delivers the round prompt after observations
- `Scenario.__post_init__` validates `acts_by` against the agent's tools

## Compatibility

Additive. 2.3.0 traces load; a 2.3.0 reader skips `round_completed` and
ignores the new fields. Scenarios setting neither field behave exactly as
before — echo-smoke and any sandbagging scenario are unaffected.

## Deferred

- Rounds completed by any of several tools
- Rounds completed by a condition rather than a tool call
- Recording the `round_prompt` template in `run_started` as well as its
  rendered text per round

All additive.
