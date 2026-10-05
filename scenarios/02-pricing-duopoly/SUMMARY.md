# Do LLM agents collude on price?

**No. They race each other to marginal cost.**

Two sellers, repeated Bertrand competition, 40 rounds. Full visibility of
each other's prices. A messaging tool available to both. Explicit reasoning
at every step.

Prices fell from 15.00 to 10.20 — within 2% of the cost of 10 — and stayed
there. **Zero messages sent, across two models and 600+ agent-rounds.**

This is the opposite of the established result. Q-learning agents in the same
game sustain supra-competitive prices; these converge to the competitive
equilibrium.

---

## What was tried, and what happened

| | Result |
|---|---|
| Hide all information | 15.00, flat |
| Show own profit | 13.92 |
| Show rival's price too | 12.29 |
| Add a messaging channel | 12.97, **never used** |
| Use a stronger model | Same convergence |
| Double the horizon to 40 rounds | Falls to 10.20 and stays |

More information produced *lower* prices, monotonically. Only full
observation survived correction (exact permutation, BH-adjusted, p = 0.0079).

## Why

The agents' own reasoning shows it:

> *"Seller_b undercut me AGAIN. My profit of 39.9 is awful. Seller_b is
> relentless and will not let any equilibrium form."* — seller_a, round 18

Neither agent ever reasons about what happens if **neither** undercuts. That
payoff exists in the model — both at 14 earns 172 each, both at 12 earns 88 —
but it requires a round in which both hold high, which the descent never
produces. The information that would motivate coordination is never observed.

## Two findings worth more than the headline

**A model producing no reasoning looks exactly like a model declining to
coordinate.** Sonnet initially held 15.00 flat with zero messages, which read
as a capable model choosing not to collude. The trace showed zero reasoning
output across 40 tool calls — it had never engaged with the task. One prompt
clause fixed it. The two cases are indistinguishable from summary statistics.

**A 20-round horizon would have reported the opposite result.** At round 18
one agent broke the price war, raised unilaterally, and the other followed —
textbook tacit collusion forming. The run ended two rounds later. At 40
rounds, no such episode occurs and the descent continues to cost. The
"coordination" was a transient.

## Method

Pre-registered before data collection. Amendments dated and justified against
the pilot runs that prompted them. Every trace published, including nulls and
excluded runs.

The first analysis reported p = 0.0000 and was wrong — it pooled 150 price
observations per condition as independent samples when they are a time series
from the same agents. Corrected to run-level analysis with exact permutation.
Effect sizes unchanged; two of three results lost significance.

## Built on

[Marionette](https://github.com/GodSagar007/Project-Marionette) — an open
agent observation framework. Traces are self-describing: every run records
each agent's model, prompts, tools, information scope, and the market rule
with its constants, so a result is reconstructable from the trace alone.

Full write-up: `scenarios/02-pricing-duopoly/FINDINGS.md`
