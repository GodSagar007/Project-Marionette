# Project: Marionette

> *The agent thinks it's acting freely. The framework holds the strings.*

An open observation environment for AI agents. Marionette gives an LLM agent tools and a goal, lets it act inside a synthetic world that feels real, and captures every action it takes — including the ones it shouldn't try.
For contributors and AI assistants: see context.md for the full project context, design decisions, and current state.
---

## Status

**Early design phase.** No working code yet. This repository currently contains the project's design documents and prior-art notes. Engine implementation begins shortly.

If you've landed here from the wider internet: come back in a few months. There'll be something to look at then.

---

## What it is

When an AI agent is handed real tools — a browser, a shell, an email account, a Python interpreter — what does it actually do? Not what it claims it would do; what it tries to do, including the choices it makes when nobody is watching.

Marionette is the watching.

The agent operates inside a containerized synthetic environment where every tool routes through bookkeeping middleware. Every call is captured before it executes. The framework is model-agnostic: any LLM that can speak a tool-calling protocol can be the subject — frontier hosted models, open-weights models, fine-tuned variants, custom endpoints.

## Why

Frontier labs run agents through staged scenarios internally. Anthropic, OpenAI, and DeepMind all have versions of this infrastructure. UK AISI's Inspect framework and METR's Task Standard are partial public counterparts.

There is no clean, open, model-agnostic *observation environment* that independent researchers, security practitioners, and smaller labs can run themselves against arbitrary agents.

Marionette exists to fill that gap.

## How it works (planned)

1. **Containerized world.** The agent operates inside a Docker container with bounded affordances.
2. **Tool gateway.** A FastAPI service exposes tools to the agent; every call is logged before being routed.
3. **Real isolated services + high-fidelity mocks.** Sandboxed Python execution. A real headless browser pointed at a sandbox web. Mock email, mock CRM, mock Slack — fidelity high enough that the agent can't tell.
4. **Universal model adapter.** OpenAI-compatible (covering ~30 providers), native Anthropic, native Google, raw HTTP for private endpoints. Bring your own model.
5. **Trace logger.** Structured JSONL of every action, tool call, result, and reasoning step.
6. **Scenario library.** Python-defined scenarios across categories: unauthorized data access, deception about actions, persistence attempts, off-task drift, social engineering of mock colleagues, tool-affordance exploitation, authority manipulation.
7. **Analysis layer.** Rule-based flags + LLM-as-judge with prompt-injection isolation.

## Roadmap

In Progress.

## Prior art

Marionette is built with deep respect for the people who got here first.

- [Inspect](https://inspect.aisi.org.uk/) — UK AISI's evaluation framework
- [METR Task Standard](https://github.com/METR/task-standard) — independent eval methodology
- Anthropic's research on agentic misalignment
- Apollo Research on deception in language models

These projects are not Marionette. Inspect is an evals framework; METR is a task standard; Marionette is an observation environment with a different shape and a different question. The field's vocabulary and abstractions came from these projects, and citing them is owed.

## Contributing

Not yet. Once the engine works end-to-end and the first scenarios are running, contribution guidelines will land here.

## License

To be decided — likely Apache 2.0.

## Contact

Open an issue. Or don't. The project will speak for itself when there's something to speak for.
