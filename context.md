\## Prior art notes



\### Inspect (UK AISI)

\- Python framework. Task = dataset + solver + scorer + tools.

\- Solver orchestrates the model+tools loop. Scorer judges the result.

\- Opinionated about the whole stack — model, tools, scoring all integrated.

\- Tools are first-class typed Python objects; framework auto-generates JSON schemas.

\- Agent runs in the framework's Python process; tool execution can be sandboxed via Docker.



\### METR Task Standard

\- Just a spec. A task family is a directory with a Python file defining

&#x20; a TaskFamily class with a small set of static methods:

&#x20; get\_instructions, install, get\_tasks, start, score, get\_permissions, get\_aux\_vm\_spec.

\- Agent runs INSIDE the Docker container as a non-root user.

\- Agent reads /home/agent/instructions.txt, writes /home/agent/submission.txt.

\- Framework reads submission, calls score().

\- Standard deliberately doesn't specify how the agent is implemented.

\- Different orgs run the same tasks against different agents — that's the whole point.



\### How they relate

\- Inspect = opinionated framework. METR = minimal spec.

\- METR tasks can be run via Inspect (METR has an "Inspect Task Bridge").

\- Both use Docker as the substrate.



\## Decisions informed by prior art



\- \*\*Scenario shape\*\*: closer to METR (directory + Python class with static

&#x20; methods). Contributable, model-agnostic, simple to spec.

\- \*\*Tool gateway\*\*: closer to Inspect (typed Python tool defs, JSON-schema

&#x20; generated). METR punts on this; Marionette can't.

\- \*\*Trace layer\*\*: richer than either. Marionette consumes the whole

&#x20; trace (every call, every result, every reasoning step), not just final

&#x20; submission. This is the differentiation.

\- \*\*Agent placement\*\*: INSIDE the container (METR-style), not outside.

&#x20; Critical for the "any model" requirement — anything that speaks

&#x20; tool-calling protocol over localhost HTTP can be the agent.



\## Conventions



\### Commits

This project follows \[Conventional Commits](https://www.conventionalcommits.org/).

Format: `<type>(<scope>): <description>`



Types in active use: feat, fix, docs, refactor, test, chore, ci, perf.

Scopes (will grow): engine, gateway, adapter, scenarios, analysis.

Description is imperative, lowercase, no trailing period.



Breaking changes get `!` after the type/scope.



\### Branching

Main branch: `main`. Direct commits to main are fine while solo.

Once contributors arrive, switch to PR-only.

Phase 2 (Engine): STEEL THREAD ONE COMPLETE.

All five components built and tested:
- Trace system (schema, writer, reader) — 25 tests
- Tool gateway (Tool ABC, registry, gateway core) — 17 tests
- Adapter (Anthropic SDK, conversation types, translation, error handling) — 17 tests
- Runner (agent loop, lifecycle events, CLI) — 8 tests

Framework runs end-to-end via:
  uv run python -m marionette echo-smoke --model <id>

### What's next when resuming

The steel thread is closed. Next decisions are about *what to build with it*.
Three reasonable directions:

1. **Run thread one for real** — set an API key, run echo-smoke against
   several models (haiku, sonnet, opus), inspect the traces, write up
   what the framework actually produces. This is the validation pass:
   does the trace make sense to read? Are there obvious holes in what
   we record? Worth doing before building more — implementation feedback
   from real runs always reveals things the design didn't anticipate.

2. **Begin a second steel thread** — extract the Adapter protocol, add
   a second provider (OpenAI), refactor to thread-aware abstractions.
   Builds toward multi-provider studies.

3. **Move toward the real research scenario** — start implementing the
   features sandbagging-under-evaluation requires (three-condition
   tool-description swap, per-trial seed recording, judge layer hookup).
   Builds toward Phase 4.

Recommend (1) first — always validate the existing thread against reality
before adding more. Bugs found by running take an hour to fix; the same
bugs found by users after publication take months.
