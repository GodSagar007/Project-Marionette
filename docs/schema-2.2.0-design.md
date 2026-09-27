# Schema 2.2.0 — Outcome Resolution

Status: in progress. Thread three, continuing from 2.1.0.

Additive to the trace schema. Additive to the Python API — a new optional
`Scenario` field and a new optional field on `EnvironmentRecord`.

## The problem

Agents can record actions and observe each other's actions. They cannot
observe *consequences*.

In the algorithmic-collusion literature, consequences are the mechanism.
Q-learning sellers converge on supra-competitive prices because undercutting
is punished and cooperation is rewarded across rounds. Remove the reward
signal and there is nothing to converge on. The same holds for LLM agents:
prices alone are noise; prices plus profit is a game.

Computing a consequence requires every agent's action for the round. No
single tool call knows that — a tool sees only its own arguments. So the
rule cannot live in a tool.

It cannot live in `EnvironmentStore` either, which must stay generic across
scenarios, nor in the runner, which must stay scenario-agnostic.

## A rejected design, and why

The first proposal was a callable on `Scenario`:

    outcome_for: Callable[[EnvironmentStore, str, int, Reveal], str | None]

The runner would call it per agent per round and push the returned string as
an observation. It is about half the code of what follows. It is also wrong,
in three ways worth recording so the idea is not re-proposed.

**A function pointer cannot be recorded.** `Scenario` is a specification, and
the roadmap has scenarios loading from directories with frozen-hash
verification. A callable cannot be hashed, serialized, or written to a
trace. The trace would report the numbers agents saw while saying nothing
about the rule that produced them — exactly the failure schema 2.0.0 existed
to correct.

**Outcomes would never become data.** The callable returns prose, landing in
an inbound event's `text`. Who won, how many units, what profit — none
enters the trace as structured values. An analyst would have to
re-implement the market rule to recover profit from prices.

**It bundles four responsibilities.** Computing outcomes, applying reveal,
selecting an audience, and rendering text. Every future scenario would
reimplement all four.

The corrected design takes the opposite view: an outcome is a fact about the
world, so it should be *recorded*, not rendered. Existing delivery machinery
then carries it without modification.

## Decision 1: Resolver is a declared object, not a function

    class Resolver(ABC):
        """A scenario's rule for turning a round's actions into outcomes."""

        name: str
        description: str

        @property
        def params(self) -> dict[str, Any]:
            """The constants governing this rule, for the trace."""

        @abstractmethod
        def resolve(
            self,
            env: EnvironmentStore,
            round_number: int,
        ) -> list[EnvironmentRecord]:
            """Compute outcome records for a completed round."""

Shaped like `Tool` deliberately: a named, described, declaratively
parameterised object rather than a bare callable. `run_started` records
`{name, description, params}`, so a trace states which rule governed its
world and with what constants.

`params` is a property derived from the resolver's attributes rather than a
separate dict. A resolver holding `cost = 10.0` while reporting
`params = {"cost": 12.0}` would be undetectable and would silently
invalidate every analysis built on the trace. Deriving it makes the drift
impossible.

`resolve()` takes the store and a round, not a `RunContext`. It has no
business with the message bus, and a narrower signature says so.

Resolvers must tolerate agents that did not act. An agent may fail to call
its tool, or abort mid-round. What that means is the rule's business —
excluded from the market, treated as a default — but it must be a decision
rather than a crash.

## Decision 2: outcomes are always observed in the following round

The resolver runs when every agent has acted. Its records therefore cannot
exist until the round is over, and cannot be seen until the next round
begins — regardless of `reveal`.

`reveal` still governs raw actions. Under `immediate`, an agent sees a
rival's price within the round it was set. It sees the *outcome* of that
round only afterwards, because the outcome did not exist yet.

This is a property of the world, not a configuration choice, and it is
stated here because it is otherwise natural to assume `immediate` reveals
everything immediately.

## Decision 3: records carry an audience

    audience: str | None = None      # None = public

A rival's price is public. A seller's own profit is not.

`EnvironmentStore.visible_to` returns public records from other agents, plus
private records addressed to the asking agent. This also corrects an
existing gap: the current implementation excludes an agent's own records
entirely, so an agent cannot be shown anything about itself. Under a market
rule it must be.

Private outcomes are what make information asymmetry expressible. A scenario
where one agent sees the other's costs and the other does not is a condition,
and conditions must be representable without changing the framework.

## Decision 4: round_resolved records what happened, inbound records what was told

Two events, deliberately not one.

`round_resolved` carries every outcome record the resolver produced for a
round, public and private alike. It is ground truth: what the world did.

`inbound` continues to record what an individual agent was shown.

Under private audiences these differ, and the difference is precisely what an
information-asymmetry analysis reads. Collapsing them would make it
unrecoverable.

`round_resolved` also closes a gap that would otherwise be silent: outcomes
from the final round are computed and never delivered, because no round
follows. Without this event they would vanish from the trace entirely.

    class RoundResolvedPayload(_StrictBase):
        round_number: int
        records: list[EnvironmentRecordEntry]

## Changes

- `Resolver` ABC in `marionette/resolver.py`
- `EnvironmentRecord.audience: str | None = None`
- `EnvironmentStore.visible_to` honours audience
- `Scenario.resolver: Resolver | None = None`
- `RunStartedPayload.resolver: ResolverManifest | None = None`
- `RoundResolvedEvent` / `RoundResolvedPayload`
- Runner calls `resolve()` at the end of each round, writes records to the
  store, emits `round_resolved`

Scenarios without a resolver are unaffected. Sandbagging sets none and
observes no behaviour change.

## Compatibility

Additive. 2.1.0 traces load; a 2.1.0 reader skips `round_resolved` as an
unknown event and ignores the new fields.

## Deferred

- Resolvers running more than once per round
- Resolver access to the message bus
- Scenario-level termination conditions (stop when prices converge)

All additive. None require revisiting the above.
