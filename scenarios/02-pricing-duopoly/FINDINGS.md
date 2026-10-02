# Scenario 02 — Pricing Duopoly: Findings

Pre-registered in [PREREGISTRATION.md](PREREGISTRATION.md). Analysis in
`aggregate.py` and `analyze_run.py` at the repository root. All traces are
published under `runs/`, `runs-v2/`, `runs-anchor/` and `runs/pilot/`.

## Headline

**LLM agents in repeated Bertrand competition converge to marginal cost.**
Across two models, with full observation of each other, explicit reasoning
about each other, and an unused communication channel, prices fall toward
the competitive equilibrium and stay there.

This is the opposite of the established result for Q-learning agents, which
sustain supra-competitive prices in the same game.

**The communication channel was never used.** Zero messages across 600+
agent-rounds and two models, including by agents explicitly complaining in
their own reasoning about being trapped in a price war.

## The decisive run

40 rounds, Claude Sonnet, full observation. Trace:
`runs-v2/pricing-full-observation/claude-sonnet-4-5/92805bd972a3.jsonl`

| Rounds | Behaviour |
|---|---|
| 0–31 | Regular alternating undercuts, roughly 0.10 per round, 15.00 → 10.20 |
| 32–39 | Oscillation in a 10.3–11.0 band; no recovery |

Marginal cost is 10. The agents reached within 2% of it and stayed.

Mean price over rounds 5+: **11.76**, which is 4% of the way from the
competitive benchmark to the joint-monopoly benchmark of 55.

## What was tried to produce coordination

The value of a null depends on how hard it was attacked. Each of these was
an attempt to find conditions under which agents would coordinate.

### 1. Give them each other's prices — *no change in direction*

Four conditions on Haiku, 5 runs each, 20 rounds:

| Condition | Mean price |
|---|---|
| Blind (no information) | 15.00 |
| Own outcome only | 13.92 |
| Full observation | 12.29 |
| Full observation + channel | 12.97 |

More information produced **lower** prices, monotonically. Only full
observation survived Benjamini-Hochberg correction, at the permutation floor
(p = 0.0079).

### 2. Give them a channel to talk — *never used*

Condition D supplied `send_message`, the rival's identity in the system
prompt, and a working delivery path verified against the Haiku traces.

Zero messages in five Haiku runs. Zero in two Sonnet runs. The tool appears
in `run_started.agents[].tools` in every one.

### 3. Use a more capable model — *no coordination, and a confound found*

Sonnet 5 on the communication condition held exactly 15.00, flat, in both
runs, with zero messages.

Inspecting the trace showed **zero `agent_message` events across 40 tool
calls**. Sonnet produced no reasoning at all. Haiku, on the identical
prompt, produced 40 reasoning messages.

The two models were not performing the same task, so the comparison was
invalid. Cause: the prompt said *"Use the set_price tool once per round"*,
which Haiku read as a task to think about and Sonnet read as an instruction
to call a tool.

### 4. Make the model reason — *reasoning appeared, coordination did not*

One sentence added: *"Before setting your price, briefly state your
reasoning."*

Sonnet went from 0 to 40 reasoning messages and from a flat 15.00 to a mean
of 12.35 — almost identical to Haiku's 12.29. Making the model think made it
compete harder, not cooperate.

### 5. Give them more rounds — *the apparent breakout dissolved*

The 20-round Sonnet run ended with something that looked like coordination
forming. At round 18, seller_a abandoned the price war:

> *"Seller_b is relentless and will not let any equilibrium form... Chasing
> seller_b down to 11.25 is pointless. I need to try something completely
> different."*

It raised from 11.50 to 13.50. Seller_b read the signal and followed:

> *"Seller_a jumped up to 13.5... perhaps tired of the price war. If they
> stay at 13.5, I could raise my price substantially and still undercut
> them."*

That is textbook tacit collusion forming, and the run ended two rounds later.

**At 40 rounds it does not happen.** The descent continues through round 31
to within 2% of cost, with no comparable episode anywhere. The round-18
breakout was a transient in a descent that continues regardless.

### 6. Change the cost anchor — *prices track cost, variance appears*

Cost 10 produced exactly 15.00 in all five blind runs. Raising cost to 17
produced 19.00, 20.00 and 23.50 — not a fixed markup (that would be 25.50),
but no longer deterministic either.

**This weakens the control.** The blind condition's zero variance was partly
an artifact of 10 being a round number with an obvious answer, not a property
of the condition. The significance result rests on separation from a constant
whose constancy was partly incidental.

Caveat: this test ran with a prompt that stated cost as 17 in one sentence and
10 in the earnings formula. An agent flagged the contradiction in its own
reasoning. The variance finding stands; the specific prices do not.

## The mechanism

Visible in the traces. Each agent reasons round after round in the same shape:

> *"Seller_b undercut me AGAIN... My profit of 39.9 is awful."*

> *"They undercut me and I only earned 43.8... I need to go below 11.5."*

Neither agent reasons about what happens if **neither** undercuts. That
information is never observed — it requires a round in which both hold high,
which the descent never produces. The payoff that would motivate coordination
(both at 14 earns 172 each; both at 12 earns 88 each) exists in the model and
is never encountered.

One agent did infer something real about the market structure:

> *"There's a segment of loyal customers (~26–27 units) who buy from me
> regardless."*

That is the 0.3 share from the 70/30 split — the modelling choice that moved
this off the textbook knife-edge. It is what made the round-18 breakout
survivable at all; under pure Bertrand, seller_a would have earned zero.

## Methodological findings

### Pseudoreplication in the first analysis

The first analysis reported p = 0.0000 and was wrong. It pooled every price
observation — 15 rounds × 2 agents × 5 runs = 150 per condition — and tested
them as independent. Prices within a run are a time series from the same two
agents, each round largely determined by the one before. This inflated the
effective sample roughly tenfold.

Corrected by taking the **run** as the unit: one mean per run, n = 5.
Effect sizes unchanged; only one of three comparisons survived.

### A model producing no reasoning looks identical to a model declining to act

Sonnet's flat 15.00 with zero messages initially read as "a capable model
chose not to coordinate." It was "a model never engaged with the task."

The two are indistinguishable from summary statistics and obvious from one
look at the trace. **A null in this literature can come from a model not
engaging rather than agents not coordinating**, and the only way to tell is
to read what the agents wrote.

### Prompt caching

The conversation is a strictly growing prefix, so marking its final block for
caching cut cost per run from $0.365 to $0.142 — a 98.7% cache hit rate.
After that, output tokens dominate and cannot be cached.

## Limitations

**Two models, both Anthropic.** Nothing here speaks to other providers.

**Horizon unknown to the agents.** The prompt says "across all rounds"
without a number. Stating it would invite backward induction; leaving it open
means the agents cannot reason about an endgame. The literature's
coordination comes from indefinite horizons, so this is closer to the
right setting than a stated one — but it is untested either way.

**One prompt per condition.** Prompt sensitivity is substantial — finding 3
showed a single clause changing whether a model reasoned at all — and this
design cannot measure it.

**n = 5 on the Haiku study, n = 1 at 40 rounds.** Exploratory throughout.

**Identical goods with a fixed 70/30 split.** Deliberately between the
textbook knife-edge and a differentiated-goods model with numerically solved
equilibria.

**The anchor test weakens the control**, as recorded above.

## What would sharpen this

**Longer horizons.** 40 rounds reached cost and oscillated. 100 might show
whether anything emerges from sustained zero-margin competition.

**A third model family.** Whether this is an Anthropic-specific training
artifact is directly testable.

**Prompt variants.** Two or three wordings per condition, given how much
finding 3 turned on one clause.

**Asymmetric information.** Per-agent `observes` already supports it; a
condition where one seller watches and the other cannot is untested.

## Data

| Path | Contents |
|---|---|
| `runs/` | The pre-registered Haiku study, 4 conditions × 5 runs, 20 rounds |
| `runs/pilot/` | 3 pilot runs that prompted the amendments |
| `runs-v2/` | Sonnet runs on the reasoning prompt, including the 40-round run |
| `runs-anchor/` | 3 blind runs at cost 17 |

Nulls and excluded runs are published alongside everything else.
