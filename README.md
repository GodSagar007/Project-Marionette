# Project: Marionette

> *The agent thinks it's acting freely. The framework holds the strings.*

An open observation environment for AI agents. Marionette gives LLM agents tools and a goal, lets them act inside a synthetic world that feels real, and captures every action they take — including the ones they shouldn't try.

### For contributors and AI assistants: see [context.md](context.md) for the full project context, [METHODOLOGY.md](METHODOLOGY.md) for the research methodology, and [VALIDATION-WEEK.md](VALIDATION-WEEK.md) for findings from the first runnable thread.

---

## Status

**Multi-agent observation working, and the first research scenario is
complete.** Agents receive a scenario, act in rounds, observe each other
through a shared environment, optionally message each other, and receive
outcomes computed by a scenario-supplied rule. Every condition is recorded in
the trace.

Traces are self-describing. `run_started` records each agent's model, system
prompt, opening message, tool contracts, information scope, and the market
rule with its constants — so a run can be reconstructed from the trace alone.
That matters for research: when an experimental condition lives in a system
prompt, a trace that cannot report its own condition cannot evidence its own
result.

### First result

[Scenario 02](scenarios/02-pricing-duopoly/FINDINGS.md) — a pricing duopoly
in four information conditions, pre-registered, run across two models.

**LLM agents in repeated Bertrand competition converge toward marginal
cost.** With full observation of each other, explicit reasoning about each
other, and a communication channel they never used, prices fall to within 2%
of cost over 40 rounds and stay there. That is the opposite of the
established result for Q-learning agents in the same game.

The findings document records six attempts to produce coordination and what
each showed, plus two methodological findings: pseudoreplication in the first
analysis, and that a model producing no reasoning at all is indistinguishable
from a model declining to coordinate unless you read the traces.

All ~30 traces are published, including nulls and excluded runs.

Built so far:

- **Trace system** — append-only JSONL, schema 2.4.0, durable writer, lenient reader
- **Tool gateway** — typed tools, schema-validated routing, "logged before routed" auditing
- **Model adapter** — Anthropic only, with prompt caching (98.7% hit rate on round-based runs)
- **Runner** — round-based multi-agent loop, per-agent conversations, gateways and registries
- **Environment** — shared world state with per-agent observation scope
- **Message bus** — agent-to-agent communication as a Tool, ablatable by omission
- **Resolvers** — scenario rules as declared, parameterised objects recorded in the trace

What's not built yet:

- Container runtime (agents currently run in-process via `dev_mode`)
- Multi-provider support (OpenAI, Google) — abstraction designed, not extracted
- Scenario directories with frozen-hash verification
- The analysis layer (rule-based flags, LLM-as-judge)
- Streaming output, redaction, reporting

If you're a researcher or contributor: the engine works and has produced one
complete study. Scenario tooling and the judge layer come next.

If you're a hiring manager or evaluator: start with
`scenarios/02-pricing-duopoly/`. It has a pre-registration written before any
data was collected, amendments dated and justified against the pilot runs
that prompted them, a findings document that records a statistical error in
the first analysis and its correction, and every trace published including
the nulls. `docs/schema-2.0.0-design.md` is the other place to look — it
documents a deliberate breaking change and the reasoning for it.

---

## What it is

When an AI agent is handed real tools — a browser, a shell, an email account, a Python interpreter — what does it actually do? Not what it claims it would do; what it tries to do, including the choices it makes when nobody is watching.

And when several agents share an environment, what do they do in the presence of each other?

Marionette is the watching.

Agents operate inside a containerized synthetic environment where every tool routes through bookkeeping middleware. Every call is captured before it executes. The framework is model-agnostic: any LLM that can speak a tool-calling protocol can be the subject — frontier hosted models, open-weights models, fine-tuned variants, custom endpoints.

## Why

Frontier labs run agents through staged scenarios internally. Anthropic, OpenAI, and DeepMind all have versions of this infrastructure. UK AISI's Inspect framework and METR's Task Standard are partial public counterparts.

There is no clean, open, model-agnostic *observation environment* that independent researchers, security practitioners, and smaller labs can run themselves against arbitrary agents.

Marionette exists to fill that gap.

## How it works

### Built and working today

1. **Tool gateway.** A registry of typed tools, each with a pydantic args schema and result schema. Every call is logged to the trace *before* routing — so attempted-but-blocked actions are first-class data, not invisible failures.
2. **Universal model adapter (Anthropic).** Translates between Marionette's provider-agnostic conversation types and Anthropic's API format. Adapter abstraction extracts cleanly when the second provider lands.
3. **Trace logger.** Structured JSONL of every action, tool call, result, and lifecycle event. Append-only writer with durable per-event flush; lenient reader that survives corrupted or schema-evolved files. Schema versioned with semver, and every version change carries a design document explaining why.
4. **Runner.** Drives a round-based loop over one or more agents, each with its own conversation, gateway, and tool registry. Emits run lifecycle events, handles adapter failures, caps runaway loops. CLI entry point: `uv run python -m marionette <scenario> --model <id>`.

### Planned

5. **Agent-to-agent channel.** Communication as a `Tool` rather than a conversation-layer feature — so it routes through the gateway, appears in the trace, and can be ablated by omission. Ablation is the active control that makes coordination claims testable.
6. **Containerized world.** Agents operate inside a Docker container with bounded affordances. Currently in-process via `dev_mode=True`.
7. **Real isolated services + high-fidelity mocks.** Sandboxed Python execution. A real headless browser pointed at a sandbox web. Mock email, mock CRM, mock Slack — fidelity high enough that the agent can't tell.
8. **Multiple model providers.** OpenAI-compatible (covering ~30 providers), native Google, raw HTTP for private endpoints. Currently Anthropic only.
9. **Scenario library.** Python-defined scenarios across categories: unauthorized data access, deception about actions, persistence attempts, off-task drift, social engineering of mock colleagues, tool-affordance exploitation, authority manipulation, multi-agent coordination. First research scenario (`scenarios/01-sandbagging-under-evaluation/`) is designed and frozen; engine support comes next.
10. **Analysis layer.** Rule-based flags + LLM-as-judge with prompt-injection isolation.

## Roadmap

The project is built in *steel threads* — narrow end-to-end paths, each production-quality at the surface area it covers, extended rather than rewritten.

- **Thread 1** ✓ Minimal scenario, Anthropic adapter, in-process tool execution
- **Thread 2** ✓ Schema 1.1.0 — turn correlation, tool manifests, message classification, per-call token usage
- **Thread 3** ✓ Multi-agent observation through schema 2.4.0 — agent identity, rounds, shared environment, communication channel, outcome resolvers. First research scenario run and published
- **Thread 4** — Scenario directories with frozen hashes, judge layer, Scenario 01 (sandbagging under evaluation)
- **Thread 5** — Second provider (OpenAI), provider-agnostic abstraction validated
- **Thread 6** — Container runtime, sandbox web
- **Thread 7** — Cohort study infrastructure, the actual research output

The second provider moved from thread 3 to thread 5 when multi-agent work overtook it. The reordering is left visible rather than quietly renumbered.

Findings from each completed thread are logged. See [VALIDATION-WEEK.md](VALIDATION-WEEK.md) for thread 1's validation pass, and `docs/` for the schema design contracts.

## Prior art

Marionette is built with deep respect for the people who got here first.

- [Inspect](https://inspect.aisi.org.uk/) — UK AISI's evaluation framework
- [METR Task Standard](https://github.com/METR/task-standard) — independent eval methodology
- Anthropic's research on agentic misalignment
- Apollo Research on deception in language models

These projects are not Marionette. Inspect is an evals framework; METR is a task standard; Marionette is an observation environment with a different shape and a different question. The field's vocabulary and abstractions came from these projects, and citing them is owed.

## Running it

If you have an Anthropic API key with a small amount of credit:

```bash
git clone https://github.com/GodSagar007/Project-Marionette.git
cd Project-Marionette
uv sync
export ANTHROPIC_API_KEY="sk-ant-..."
uv run python -m marionette echo-smoke --model claude-haiku-4-5
```

A trace appears at `runs/echo-smoke/claude-haiku-4-5/<run_id>.jsonl`. A single smoke run costs about half a cent.

For development without an API key, the test suite exercises every component end-to-end with a scripted adapter — no live calls. Run with `uv run pytest`.

## Contributing

Not yet. The engine runs, but the interfaces will evolve through threads 3 and 4. Once the agent-to-agent channel settles and the first real scenario runs, contribution guidelines will land here.

In the meantime: issues are welcome if you spot something. Particularly:
- Trace format observations (is the JSONL shape useful for analysis you'd actually do?)
- Provider-quirks documentation (if you've fought OpenAI vs. Anthropic tool-calling, what did you learn?)
- Threat-model gaps (what kinds of misuse should the framework be capturing that it isn't?)

## License

Apache 2.0. The patent grant clause matters for security tools.

## Contact

Open an issue. Or don't. The project speaks for itself when there's something to speak for.
