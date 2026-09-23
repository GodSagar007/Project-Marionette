# Project context

Working notes for anyone — human or AI — picking this project up. Read
alongside [METHODOLOGY.md](METHODOLOGY.md) for research methodology and the
`docs/schema-*.md` design documents for schema contracts.

## Current status

**Thread 2 complete.** Schema 1.1.0 closed every gap found in validation
week: turn correlation, tool manifests, message classification, and
per-call token usage.

**Thread 3 in progress.** Multi-agent observation. Schema is at **2.0.0** —
the first breaking change. Agents now alternate within rounds, each with its
own conversation, gateway, and tool registry, and `run_started` records each
agent's full configuration including its system prompt.

79 tests. mypy clean across 17 source files. ruff clean.

### Done in thread 3

- `agent_id` on `_EventBase` — provenance, distinct from `actor`
- `AgentSpec`, `Scenario.agents`, `Scenario.rounds`
- `_AgentRuntime` — per-agent adapter, gateway, conversation
- `_run_agent_turns()` — turn loop extracted to module level
- Schema 2.0.0 — `AgentManifestEntry` replaces `RunStartedPayload.tools_manifest`

### Next: the channel (3.4, 3.5 — schema 2.1.0, additive)

- `send_message` tool — agent-to-agent communication as a Tool, not a
  conversation-layer feature, so it routes through the gateway and is
  ablatable by omission
- `message_delivered` event — delivery is a separate recorded fact from
  sending, because information state is the object of study
- Reveal timing — `immediate` vs `end_of_round`, which is what separates
  sequential from simultaneous play
- A collusion scenario with the no-channel ablation as its active control

Target: Apart Research AI Collusion Sprint, 23–25 October 2026.

## Schema history

| Version | Thread | Change |
|---|---|---|
| 1.0.0 | 1 | Initial event schema |
| 1.1.0 | 2 | `turn_id`, `tools_manifest`, `kind`, `model_response` |
| 1.2.0 | 3 | `agent_id` on `_EventBase` |
| 2.0.0 | 3 | `AgentManifestEntry`; removes `tools_manifest` (breaking) |

Design contracts live in `docs/`. Each documents *why*, not just what —
including, for 2.0.0, why the compatibility discipline was deliberately
suspended and under what condition it resumes.

## Prior art notes

### Inspect (UK AISI)

- Python framework. Task = dataset + solver + scorer + tools.
- Solver orchestrates the model+tools loop. Scorer judges the result.
- Opinionated about the whole stack — model, tools, scoring all integrated.
- Tools are first-class typed Python objects; framework auto-generates JSON
  schemas.
- Agent runs in the framework's Python process; tool execution can be
  sandboxed via Docker.

### METR Task Standard

- Just a spec. A task family is a directory with a Python file defining a
  `TaskFamily` class with a small set of static methods: `get_instructions`,
  `install`, `get_tasks`, `start`, `score`, `get_permissions`,
  `get_aux_vm_spec`.
- Agent runs INSIDE the Docker container as a non-root user.
- Agent reads `/home/agent/instructions.txt`, writes
  `/home/agent/submission.txt`.
- Framework reads submission, calls `score()`.
- Standard deliberately doesn't specify how the agent is implemented.
- Different orgs run the same tasks against different agents — that's the
  whole point.

### How they relate

- Inspect = opinionated framework. METR = minimal spec.
- METR tasks can be run via Inspect (METR has an "Inspect Task Bridge").
- Both use Docker as the substrate.

## Decisions informed by prior art

- **Scenario shape**: closer to METR (directory + Python class with static
  methods). Contributable, model-agnostic, simple to spec.
- **Tool gateway**: closer to Inspect (typed Python tool defs, JSON-schema
  generated). METR punts on this; Marionette can't.
- **Trace layer**: richer than either. Marionette consumes the whole trace
  (every call, every result, every reasoning step), not just the final
  submission. This is the differentiation.
- **Agent placement**: INSIDE the container (METR-style), not outside.
  Critical for the "any model" requirement — anything that speaks a
  tool-calling protocol over localhost HTTP can be the agent.

## External standards

OpenTelemetry GenAI semantic conventions and A2A were evaluated in thread 3
and deliberately not adopted. OTel targets operational observability —
span-tree shaped, sampled, lossy by design — where research traces must be
complete and totally ordered. A2A models client-server delegation between
heterogeneous agents; collusion scenarios use symmetric peers.

Vocabulary is aligned where alignment is free, so a future exporter is a
translation rather than a redesign. Mapping table in
`docs/schema-1.2.0-design.md`.

## Conventions

### Commits

This project follows [Conventional Commits](https://www.conventionalcommits.org/).
Format: `<type>(<scope>): <description>`

Types in active use: feat, fix, docs, refactor, test, chore, ci, perf.
Scopes (will grow): engine, gateway, adapter, runner, trace, scenarios,
analysis.

Description is imperative, lowercase, no trailing period. Breaking changes
get `!` after the type/scope.

Note: `feat!:` triggers bash history expansion inside double quotes. Use
`git commit -F <file>` for messages containing `!`.

### Branching

Main branch: `main`. Direct commits to main are fine while solo. Once
contributors arrive, switch to PR-only.

### Design docs before schema changes

Every schema version gets a design document in `docs/` written *before*
implementation. This has caught real problems twice: a step-numbering drift
in 1.1.0, and the modeling error behind 2.0.0. The doc is the contract; when
implementation deviates, the doc gets corrected in the same commit.

## Working agreements

- Architecture sketches come from discussion; the code gets written by hand.
- A quiz after each conceptual step — skip it for mechanical plumbing.
- Flag refactors that forward architecture will require *before* stacking new
  work on top.
- Steel thread discipline: constrain the surface, not the quality. "Only
  Anthropic, only one tool, only one scenario" is strategy. "Hacky stubs
  we'll fix later" is debt.

## Environment

- WSL Ubuntu. `nano` is the editor; `~/.nanorc` has `set tabstospaces`, but
  the setting only takes effect in *new* nano sessions.
- Pasting indented Python into nano is unreliable. Prefer
  `cat > file << 'EOF'` for whole files, and check with
  `cat -A file.py | head -50` when indentation looks wrong.
- API key in `.env` (gitignored). Load with `set -a; source .env; set +a`.
- A single echo-smoke run costs roughly half a cent. Total spend to date is
  under five cents.
- Anthropic dashboard: prepaid credit, auto-reload off, as a hard cap.

## Running it

```bash
uv sync
set -a; source .env; set +a
uv run python -m marionette echo-smoke --model claude-haiku-4-5
```

Checks before every commit:

```bash
uv run ruff check src/ tests/ && uv run mypy src/ && uv run pytest -q
```
