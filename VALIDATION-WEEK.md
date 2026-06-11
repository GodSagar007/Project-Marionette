# Validation Week — Findings & Thread Two Planning

**Date:** 2026-06-11
**Scope:** First steel thread of the engine — trace system, gateway, adapter, runner
**Method:** Three scripted scenarios + two real-API runs against `claude-haiku-4-5`
**Outcome:** Foundation solid. Five additive findings logged. Zero catastrophic issues.

---

## 1. Purpose of validation

The first steel thread closed with all five engine components built and 67 unit
tests passing. Tests verify correctness against a specification *we wrote* —
they cannot verify the specification matches what real research needs.

Validation week tested the running framework against scenarios the test suite
didn't anticipate, read the resulting traces by hand, and surfaced gaps where
the framework is *correct but incomplete*. The goal was not to find bugs; the
goal was to find unstated requirements before building further.

---

## 2. What was tested

### Scripted scenarios (no API cost, controlled inputs)

| Scenario | Purpose |
|---|---|
| **Parallel tool calls** | Two echo calls in one turn — does the runner handle parallel routing? |
| **Structured tool result** | Multi-field pydantic result — does structure preserve? |
| **Argumentative agent** | Three-iteration reasoning trail — does the trace read as narrative? |

### Real-API runs (claude-haiku-4-5, ~$0.01 total)

| Scenario | Purpose |
|---|---|
| **echo-smoke (real)** | Baseline: real model on the smallest possible task |
| **parallel-calls-real** | Validate: do real models emit parallel calls organically? |

---

## 3. Findings

Each finding is sorted by *severity* and *scope*. Severity is honest: most are
real but bounded structural gaps, not foundation issues. Scope indicates
whether the fix is local (single field) or architectural (schema bump).

### Finding 1 — Turn boundaries are not encoded in the trace

**Severity:** High
**Scope:** Schema (additive)
**Confirmed by:** Real-API parallel-calls run (Haiku 4.5)

When a model emits multiple `tool_use` blocks in one turn, the trace records
them as a flat sequence: `tool_call`, `gateway_intent_logged`, `tool_result`
repeated per call. The structural information that they came from *one*
assistant turn is **lost in the trace**.

The real-API run confirmed this empirically: Haiku 4.5 emitted three parallel
echo calls. All nine events (3 × call/intent/result) landed within 220
microseconds of each other — turn membership is *inferable* from timestamp
clustering, but only because the tools were in-process. With any I/O-bound
tool, even that inference breaks.

**Why it matters for research:** Analysis tools cannot reliably ask "how often
does each model use parallel calls?" — a real cross-model behavioral question.

**Proposed fix:** Add `turn_id` field (UUID per assistant turn) to `tool_call`,
`gateway_intent_logged`, `tool_result`, and `tool_error` events. Runner
generates one UUID per `adapter.get_turn()` and stamps all subsequent events
from that turn. Schema bump 1.0.0 → 1.1.0 (additive, non-breaking).

---

### Finding 2 — The tool surface at run-time is not recorded

**Severity:** High
**Scope:** Schema (additive)
**Confirmed by:** Scripted structured-result run, reinforced by real run

`run_started` records the scenario id, model id, seed, and framework version.
It does *not* record what tools were available, their descriptions, their
input schemas, or their result schemas.

This means a trace is not self-contained: to interpret a run, future
researchers would need the exact source code of every tool at trace-time.
Git history makes this *possible* but fragile — tool descriptions evolve, and
verifying "the model saw the same tool surface in run A as in run B" is
manual archaeology rather than a trace property.

**Why it matters for research:** For pre-registered experiments (e.g.
sandbagging-under-evaluation), proving that conditions A and B presented
identical tool surfaces is methodologically essential. The trace must
support that proof mechanically.

**Proposed fix:** Add `tools_manifest` field to `RunStartedPayload`. Manifest
is a list, one entry per registered tool, each containing `name`,
`description`, `args_schema` (as JSON Schema), and `result_schema`. The
existing `to_anthropic_tool_spec()` machinery already produces most of this;
extracting a provider-neutral version is a small refactor.

---

### Finding 3 — `agent_message` conflates reasoning, summary, and chitchat

**Severity:** Medium
**Scope:** Schema (additive classification)
**Confirmed by:** All scenarios — most starkly on real-API echo-smoke

The real model's single agent_message read:
> "Perfect! The echo tool has successfully returned the phrase 'marionette is online'. The tool call worked as expected, confirming that the system is functioning properly."

That one message contains three different things: a friendly acknowledgement
(*"Perfect!"*), a summary of what happened (*"echo tool has returned…"*), and
self-meta-commentary about the test itself (*"confirming that the system is
functioning properly"*).

For misuse research, especially sandbagging-under-evaluation, the model's
*self-meta-commentary* is exactly the signal of interest. Currently it's just
text alongside summary and chitchat. Analysis tools that want to extract
"the model's reasoning vs. its actions" have no structural handle.

**Why it matters for research:** Sandbagging detection depends on
distinguishing what the model *says about its behavior* from what the model
*does*. Today the trace makes that distinction available only via prose
parsing — which is unreliable and model-specific.

**Proposed fix:** Add `kind` discriminator to `AgentMessagePayload`:
`Literal["reasoning", "summary", "final", "other"]`. The runner cannot reliably
classify these from the model's output — but an external judge layer (which
the project already plans) can post-process traces to tag each message. The
schema needs to *permit* classification even if writing it is deferred.

**Alternative:** Treat as fully a downstream analysis concern. Don't change
the schema; let judges produce their own annotation artifacts. Decision
needed during thread-two planning.

---

### Finding 4 — Real models can skip narration entirely

**Severity:** Low (calibration, not a defect)
**Scope:** No code change required
**Confirmed by:** Real-API echo-smoke (no pre-action narration); parallel run (no narration between any tool calls)

Scripted scenarios assume the model will narrate intent before tool calls and
summarize after. Real models do neither reliably:

- On the smoke run: zero pre-action narration, one post-action summary.
- On the parallel run: zero narration between any of the three tool calls,
  one post-action summary.

This is not a framework defect. It's real-model behavior — narration density
is a model-level variable, shaped by training and prompt design, not by
framework structure.

**Why it matters:** Analyzers cannot assume `agent_message` events appear
in any predictable pattern. Code that, for example, expects "one
`agent_message` before each `tool_call`" will break on most real traces.
Tools should treat `agent_message` events as optional, not structurally
guaranteed.

**Implication:** The framework's choice to *not* force narration is correct.
Forcing it would mask exactly the cross-model differences worth studying.
Keep the trace honest about what the model actually produced.

**Action:** Document in next walkthrough; no code change.

---

### Finding 5 — Token usage is discarded

**Severity:** Medium-high
**Scope:** Schema (additive) + adapter capture
**Confirmed by:** Both real-API runs

The Anthropic SDK returns `usage` data on every response (input tokens, output
tokens, cache hits where applicable). The adapter discards this. The trace has
no record of what each call consumed or produced.

**Why it matters for research:**

1. **Cross-model cost comparison.** Cohort study budgeting needs per-run cost
   estimates. Without per-event token counts, this is unmeasurable from the
   trace.

2. **Verbosity comparison across models.** Comparing "how much did each model
   say" by word count or character count is unreliable across formatting
   styles. Token counts are the right unit.

3. **Detecting truncation.** A response cut off by `max_tokens` looks the
   same as a complete response in the current trace. The `stop_reason` and
   `usage` data would distinguish them.

**Proposed fix:** Adapter captures `response.usage` and `response.stop_reason`
from each API call. Runner attaches this data to either the `agent_message`
event or a new `model_response` event. Schema bump (1.0.0 → 1.1.0) covers
this alongside `turn_id`.

---

## 4. The meta-finding

The five findings cluster into a coherent shape. **The current schema records
what happened. It loses meta-information about what was happening.**

| Lost meta-information | Finding |
|---|---|
| Which events came from one assistant turn | 1 |
| What tools the agent was given | 2 |
| What kind of message the agent produced | 3 |
| How long the model talked / what it cost | 5 |

These are not five independent fixes. They are **one architectural layer
missing**: a *meta-structure* over the existing event stream. Designing them
together produces one coherent schema 1.1.0; patching them piecemeal produces
several uncoordinated refactors.

Finding 4 is calibration, not a structural gap — it's data about what real
models do, not a fix for the schema.

---

## 5. What the foundation got right

Equally important to record:

- **Sequence numbering is correct under parallel calls.** No gaps, no
  duplicates, strict monotonicity verified on the real parallel run.
- **Timestamps are clean.** Microsecond UTC, strictly increasing, expose
  real API latency naturally.
- **The "logged before routed" property holds.** Even on the real-API run,
  intent appears in the trace before any execution.
- **Round-trip integrity verified.** Three scripted runs and two real runs
  all produced traces that read back through `TraceReader` without warnings.
- **Cost is predictable.** Two API runs cost <$0.02 total; the project
  budget for thread-two work is comfortable.
- **The framework does not normalize model outputs.** This is the right
  design — model differences are the data; comparison happens via uniform
  event vocabulary, not via flattening prose.

---

## 6. Recommendations for thread two

### Primary work

Build a **schema 1.0.0 → 1.1.0 pass** that addresses findings 1, 2, 3, 5
together. Specific changes:

1. Add `turn_id: str | None` to tool-related events (1)
2. Add `tools_manifest: list[ToolSpec]` to `RunStartedPayload` (2)
3. Add `kind: Literal[...] | None` to `AgentMessagePayload` (3)
4. Add `usage: TokenUsage | None` to `AgentMessagePayload` (5)
5. Bump `SCHEMA_VERSION` to `"1.1.0"`
6. Update writer and reader to handle the new fields
7. Add tests covering each new field's presence on real flows
8. Verify the reader still loads 1.0.0 traces unchanged (lenient-on-read)

All changes are **additive within major version**. Existing traces remain
valid. Older readers ignore unknown fields gracefully (Postel's law working
as designed).

### Secondary work

- Extract an `Adapter` `Protocol` so non-Anthropic adapters (and test fakes)
  don't need `cast(AnthropicAdapter, ...)`. This was logged at runner
  implementation time but deferred. Worth doing alongside schema work.
- Build a small **trace analyzer** (`marionette-analyze` or similar) that
  exercises the schema as a consumer. This is *the* test of whether the
  new fields make analysis cleaner. Don't ship the schema change without
  using it from at least one read-side tool.

### Deferred (not thread two)

- Multiple provider support (OpenAI, Google). Wait until the protocol
  extraction is real.
- Real scenario tooling — loading from `scenarios/NN-name/` directories,
  parsing SCENARIO.md, verifying frozen hashes. Tied to running the actual
  research scenario.
- Streaming agent output. Currently we capture only completed responses.
  Worth doing only when there's a research reason.
- Redaction logic. Schema is redaction-friendly; the logic itself isn't
  needed until traces contain sensitive content.
- Reader summary mode for high-skip Phase 4 scenarios.

---

## 7. Closing

Validation week did its job. The foundation is solid; the gaps are bounded,
known, and prioritized. The system runs against real models, produces honest
traces, and stays within budget.

The next session opens thread two with a clear plan: one coherent schema
evolution covering the four structural findings, an analyzer to verify the
schema serves consumers, and a protocol extraction to prepare for the second
provider.
