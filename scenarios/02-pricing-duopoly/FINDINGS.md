# Scenario 02 — Pricing Duopoly: Findings

Pre-registered in [PREREGISTRATION.md](PREREGISTRATION.md). Analysis code in
`aggregate.py` at the repository root. All twenty traces are published under
`runs/`, and the three pilot runs that prompted the amendments are under
`runs/pilot/` so they can be checked against the changes they justified.

Model: `claude-haiku-4-5`. Five runs per condition, twenty rounds each.

## Result

Information moved these agents toward competition, not collusion.

| Condition | What the agent saw | Mean price | Position |
|---|---|---|---|
| Blind | nothing | **15.00** | 11% toward monopoly |
| Own outcome | its own profit | **13.92** | 9% |
| Full observation | own profit + rival's price | **12.29** | 5% |
| Communication | as above, plus a message channel | **12.97** | 7% |

Competitive benchmark 10, joint-monopoly benchmark 55, both produced by the
market model rather than asserted.

Prices fell monotonically as information increased, and no condition
approached the collusive benchmark. The blind condition held exactly 15.00
in every run and every round.

### Statistical tests

Exact permutation against the blind control, Benjamini-Hochberg corrected
over three comparisons at α = 0.05. With five runs per arm the smallest
attainable two-sided p is 0.0079.

| Comparison | Difference | p | After correction |
|---|---|---|---|
| Own outcome | −1.08 | 0.1667 | not significant |
| Full observation | −2.71 | 0.0079 | **significant** |
| Communication | −2.03 | 0.0476 | not significant |

Only full observation survives correction, at the floor — which is what
complete separation looks like at this sample size.

## Two findings worth separating

### 1. More information, lower prices

The trajectory is the clearest evidence. Blind runs are a flat line at
15.00. Every informed condition descends over the first eight rounds and
settles: full observation at about 11.96, communication at about 12.77, own
outcome at about 14.38.

The mechanism is visible in the round-level data. An agent seeing its own
profit learns that cutting price raised it. It never observes a round in
which both sellers held high, which is where the larger payoff is — both at
14 earns 172 each, both at 12 earns 88 each. Minimal information therefore
teaches competition.

This runs opposite to the algorithmic-collusion literature, where
Q-learning agents in repeated Bertrand competition converge on
supra-competitive prices. Those agents explore over hundreds of thousands of
rounds. These agents reason from twenty.

### 2. A coordination channel, never used

Condition D gave both agents `send_message`, addressed to each other, with
the rival's identity in the system prompt.

**Across five runs and 200 agent-rounds, zero messages were sent.**

The tool was present in every run's manifest — verifiable in
`run_started.agents[].tools` in any condition-D trace. Agents simply never
called it.

This is the finding that should be stated most carefully. It supports
*"given a channel, these agents did not use it."* It does **not** support
*"communication does not raise prices"*, because the communication condition
never differed from full observation in practice. Condition D's mean sits
between C and the control and is consistent with being C plus noise.

## A statistical error, and its correction

The first analysis reported p = 0.0000 for two conditions. That was wrong,
and the error is worth recording.

It pooled every price observation — 15 rounds × 2 agents × 5 runs = 150 per
condition — and tested them as independent samples. They are not. Prices
within a run form a time series produced by the same two agents, where each
round is largely determined by the one before. Treating them as independent
inflated the effective sample size roughly tenfold.

That is pseudoreplication. Corrected by taking the **run** as the unit of
analysis: each run contributes one number, its mean price over rounds 5–19,
giving n = 5 per condition.

A second problem compounded it. The blind condition has a standard deviation
of exactly zero — all five runs produced 15.00 in every round. A
t-statistic against a zero-variance control divides by a standard error
built partly from zero. The corrected analysis uses exact permutation, which
assumes nothing about distributions and handles that case honestly.

Effect sizes were unchanged by the correction. Only one of three
comparisons survived it.

## Limitations

**Model-specific.** One model, `claude-haiku-4-5`. "These agents do not
coordinate" and "LLM agents do not coordinate" are different claims, and
only the first is supported. A stronger model may behave differently, and
that is the obvious next experiment.

**Zero-variance control.** The blind condition produced identical output in
every run. Haiku computes a markup once and repeats it deterministically
without feedback. That makes a clean control in one sense and a fragile one
in another: a baseline with no variance cannot support a variance-based
test, which is part of why permutation was necessary.

**Twenty rounds.** The Q-learning literature uses hundreds of thousands.
Twenty may simply be too few for coordination to emerge, and a null here
could reflect insufficient repetition rather than an inability to coordinate.

**One prompt.** A single wording per condition. Prompt sensitivity is
untested and could plausibly change the result.

**n = 5.** Exploratory throughout. A non-significant result here is weak
evidence of absence, not evidence of absence.

**Identical goods with a fixed 70/30 share split.** A deliberate midpoint
between the textbook knife-edge, where undercutting takes the whole market,
and a differentiated-goods model requiring numerically solved equilibria.
It makes coordination easier to sustain than pure Bertrand and harder than
a differentiated model.

## What would sharpen this

**A stronger model on one condition.** Five runs of full observation on a
more capable model would separate "these agents cannot coordinate" from
"this model cannot". The highest-value next step per unit of cost.

**More rounds.** Whether twenty is the binding constraint is directly
testable by running sixty.

**Prompt variants.** Two or three wordings per condition would bound the
prompt sensitivity the current design cannot measure.

**Asymmetric information.** The framework supports per-agent `observes`, so
a condition where one seller watches the market and the other cannot is
already expressible. Untested here.
