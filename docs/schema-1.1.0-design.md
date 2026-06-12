# Schema 1.1.0 — Design Document

**Status:** Approved for implementation
**Scope:** Additive schema evolution within major version 1
**Findings addressed:** 1, 2, 3, 5 from VALIDATION-WEEK.md
**Backwards compatibility:** Full — old readers gracefully ignore new fields and new event types; old traces remain valid input to new readers.

---

## 1. Overview

This document specifies the additive changes to the trace schema for the
1.0.0 → 1.1.0 bump. Four changes:

1. `turn_id` field on turn-scoped events
2. `tools_manifest` on `RunStartedPayload`
3. `kind` discriminator on `AgentMessagePayload`
4. A new `model_response` event type carrying per-API-call metadata

The bump is *fully additive*. No existing fields are renamed, removed, or
have their meaning changed. Readers built against 1.0.0 see new fields and
ignore them; they see the new `model_response` event type, log a warning
under their lenient-parse policy, and skip it. Readers built against
1.1.0 see old traces, find new fields missing, and treat them as None or
absent.

This is Postel's law under evolution: the format grew; both directions
keep working.

---

## 2. Change 1 — `turn_id` on turn-scoped events

### Purpose

A model turn produces one or more events. The schema currently records the
events but not their grouping. With parallel tool calls (confirmed in
real-API validation), this means the trace cannot distinguish:

- *"Model emitted alpha and beta in one assistant response (parallel)"*
- *"Model emitted alpha; saw result; emitted beta in a follow-up response"*

A `turn_id` field — a UUID shared by all events in one model turn — makes
the grouping explicit.

### Where it goes

A nullable field on every event that belongs to a specific model turn:

- `AgentMessageEvent.turn_id`
- `ToolCallEvent.turn_id`
- `GatewayIntentLoggedEvent.turn_id`
- `ToolResultEvent.turn_id`
- `ToolErrorEvent.turn_id`
- `ModelResponseEvent.turn_id` (the new event from §5)

Framework lifecycle events (`run_started`, `run_completed`, `run_aborted`,
`framework_note`) do *not* have `turn_id`. They don't belong to a model
turn — they bracket or annotate the whole run.

### Type

```python
turn_id: str | None = None
```

A UUID4 hex string (no dashes), generated once per `adapter.get_turn()`
call in the runner. Same 12-character convention as `run_id`. Defaulting
to `None` so existing payload construction in 1.0.0 tests still works
without modification.

### Cross-event semantics

When a model emits text + tool calls in one response, all of it belongs
to one assistant turn semantically. The `agent_message` and the
`tool_call` events derived from that response share a `turn_id`. The
gateway's events (`gateway_intent_logged`, `tool_result`, `tool_error`)
inherit the turn_id from the originating `tool_call`. The
`model_response` event for that API call also carries the same turn_id.

This couples the gateway's signature slightly to the new field. We accept
that cost: the alternative — gateway events without turn_id — would mean
tool execution events couldn't be grouped to their model turn at all.

### Adapter responsibility

`Turn` (the adapter's return type) does not carry a turn_id. The adapter
returns a parsed turn; the runner *generates* the turn_id at the moment
it processes the turn. This keeps the adapter provider-agnostic —
different providers don't need to know about our turn-id concept.

### Migration

Old traces have no `turn_id` field. New readers see `None` for each event
and group-by-turn analyses return "one turn per event" as the fallback.
Conservative, correct degradation: traces predating turn_id look like
single-call turns, because that's all the reader can tell.

---

## 3. Change 2 — `tools_manifest` on `RunStartedPayload`

### Purpose

A reproducibility-grade trace must record what tools the agent was given,
not just what the agent did with them. Currently only `scenario_id` is
recorded — proving "run A and run B saw identical tool surfaces" requires
checking out the source code at trace-time.

A `tools_manifest` field captures the actual tool surface at run-time.

### The new type

A new pydantic model in `schema.py`:

```python
class ToolManifestEntry(_StrictBase):
    """One entry in the tools manifest — what a tool looked like at run-time."""

    name: str
    description: str
    args_schema: dict[str, Any]      # JSON Schema as a dict
    result_schema: dict[str, Any]    # JSON Schema as a dict
```

The `args_schema` and `result_schema` come from
`pydantic.BaseModel.model_json_schema()`. Same machinery
`to_anthropic_tool_spec` already uses — we just call it for both args and
result, and the runner attaches the result to the `RunStartedPayload`.

### Where it goes on the payload

```python
class RunStartedPayload(_StrictBase):
    schema_version: str
    run_id: str
    scenario_id: str
    model_id: str
    seed: int
    framework_version: str
    dev_mode: bool
    tools_manifest: list[ToolManifestEntry] = Field(default_factory=list)
```

Defaulted to empty list so 1.0.0-style construction still works.

### Provider-neutral by design

The manifest records *what the tool is*, not *what any specific provider
sees*. Anthropic's `input_schema` and OpenAI's `parameters` and Google's
`function_declarations` are all derived from the same underlying tool
definition. The manifest captures the underlying definition.

If a future research question is *"did the model see this tool in the
provider-specific format X?"* — that's a different question requiring a
different artifact (the actual API payload sent). Out of scope for the
manifest.

### When the manifest is computed

At runner start, before `run_started` is emitted. The runner walks
`scenario.tools`, calls `model_json_schema()` on each tool's `args_schema`
and `result_schema`, builds the entries, and includes them in the
`RunStartedPayload`.

The manifest reflects whatever tool implementations were live at run-time
— including any per-instance configuration. It is the *actual* tool
surface, not the *declared* one.

### Migration

Old `RunStartedPayload` has no `tools_manifest`. New reader sees an empty
list (the default). Analysis tools that need the manifest gracefully
report "manifest unavailable for this trace" — older trace, no
reproducibility guarantee at this level.

---

## 4. Change 3 — `kind` on `AgentMessagePayload`

### Purpose

Real models produce agent messages serving different roles: reasoning
before action, summarizing after, declaring a final answer, or just
acknowledgement chitchat. Today all are indistinguishable in the trace.

The most-cited example from validation: Haiku's *"Perfect! The echo tool
has successfully returned... confirming that the system is functioning
properly."* conflates acknowledgement, summary, and meta-commentary about
the test itself. For sandbagging research, the meta-commentary is exactly
the signal we want to isolate.

A `kind` discriminator field permits classification. Crucially, the field
is **optional and not auto-classified** — the framework records the text
honestly without inferring intent. Classification comes later from an
external judge layer (planned but not yet built).

### Where it goes

```python
class AgentMessagePayload(_StrictBase):
    text: str
    kind: Literal["reasoning", "summary", "final", "other"] | None = None
```

### The four categories

- **`reasoning`** — model is thinking aloud before taking action. Often
  appears before tool calls; may justify the upcoming choice.
- **`summary`** — model is recapping what just happened. Often appears
  after tool results.
- **`final`** — model is producing its concluding output. The terminal
  message of a successful task. Distinguished from `summary` by being
  the actual answer rather than meta-narration about it.
- **`other`** — acknowledgement, hedging, chitchat, anything that doesn't
  fit the above. Catch-all to keep the schema honest about the messy
  reality of LLM output.

Defaulting to `None` (unclassified) is the honest default. A trace
emitted by the runner today doesn't classify anything; future analysis
tools add classification by post-processing the trace.

### Why the runner does not classify

Classification is a research output, not a recording mechanism. A
framework that auto-classified would have to choose a classifier
(rule-based? prompt-based? model-specific?), and that choice would become
part of the methodology — invisibly baked into every trace.

Letting an external judge layer classify, and recording the judge's
output as a `kind` value, keeps the framework's role strictly as
recording.

The schema includes the field so future judge layers can write into trace
events. The field's *presence* signals "this dimension exists"; its
*value* remains `None` until classified.

### Migration

Old traces have no `kind` field. New readers see `None`. Analyses that
depend on classification handle `None` as "unclassified" — same as a
1.1.0 trace where classification simply hasn't been added yet.

---

## 5. Change 4 — New `model_response` event

### Purpose

The Anthropic SDK returns per-API-call metadata that the framework
currently discards: token usage (input, output, cache), stop reason, and
the call's latency. This is research-critical data:

- **Cross-model cost comparison** requires per-call token counts
- **Verbosity comparison across models** requires tokens (word counts are
  unreliable across formatting styles)
- **Detecting truncation** requires `stop_reason` — a response cut off by
  `max_tokens` looks identical to a complete response in the current
  trace

Rather than denormalize this metadata across content events, it gets its
own event type. One API call → one `model_response` event with the
call's metadata.

### Why a new event type, not a field

Token usage and stop reason are not about *what the model said*; they're
about *what the model call cost and how it ended*. Different concern,
different event. `agent_message` and `tool_call` stay focused on the
model's outputs; `model_response` records the call-level metadata.

This also makes turn boundaries naturally visible in the event stream —
a `model_response` event implicitly marks the end of one API call's
output. The combination of `turn_id` (on every event of a turn) and the
presence of a `model_response` event makes turn structure first-class in
the trace.

A single canonical place for usage data keeps analyzers simple: "sum
tokens across all `model_response` events" is the correct query for
total run cost, with no scanning across other event types and no
deduplication concerns.

### The new types

```python
class TokenUsage(_StrictBase):
    """Token usage reported by the provider for one API call."""

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0       # Anthropic-specific; defaults for providers without
    cache_write_tokens: int = 0


class ModelResponsePayload(_StrictBase):
    """Per-API-call metadata. Emitted once per adapter.get_turn() call."""

    turn_id: str                     # required — links to the turn's other events
    usage: TokenUsage                # required — the reason this event exists
    stop_reason: str                 # required — "end_turn" / "tool_use" / "max_tokens" / etc.
    duration_ms: int                 # required — wall-clock for this API call


class ModelResponseEvent(_EventBase):
    """Records metadata about one API call to the model provider."""

    event: Literal["model_response"] = "model_response"
    payload: ModelResponsePayload
```

The `TraceEvent` discriminated union grows from 9 entries to 10:

```python
TraceEvent = Annotated[
    RunStartedEvent
    | RunCompletedEvent
    | RunAbortedEvent
    | AgentMessageEvent
    | ToolCallEvent
    | GatewayIntentLoggedEvent
    | ToolResultEvent
    | ToolErrorEvent
    | FrameworkNoteEvent
    | ModelResponseEvent,         # ← new
    Field(discriminator="event"),
]
```

### Emission order within a turn

The runner emits `model_response` once per `adapter.get_turn()` call,
*after* the events derived from that turn's content. The sequence within
one turn becomes:

```
1. agent_message       (if model produced text — optional)
2. tool_call           (one per tool the model invoked — zero or more)
3. gateway_intent_logged + tool_result   (one each per tool_call)
4. model_response      ← marks end of turn's events
```

A typical turn produces 1 + N + 2N + 1 events (N = number of tool calls).
The `model_response` is always last in its turn, always present, always
carries usage and stop_reason.

### Adapter responsibility — capture, don't emit

The adapter parses usage, stop_reason, and call duration from the API
response and surfaces them as fields on the `Turn` object. The adapter
does *not* write events — that stays the runner's job. The `Turn` type
grows new fields:

```python
class Turn(BaseModel):
    text: str
    tool_uses: list[ToolUseContent] = Field(default_factory=list)
    usage: TokenUsage                    # ← new, required
    stop_reason: str                     # ← new, required
    duration_ms: int                     # ← new, required

    @property
    def wants_tools(self) -> bool:
        return len(self.tool_uses) > 0
```

`duration_ms` is measured by the adapter around the SDK call (start with
`time.monotonic()`, subtract after). This isolates *API call* latency
from anything happening in the runner's loop.

Test doubles (`ScriptedAdapter`, `FakeAdapter` in runner tests) populate
these with sensible defaults; existing fakes need small updates to set
them.

### Provider Variation

Token-usage shape differs across providers:

- Anthropic: `input_tokens`, `output_tokens`,
  `cache_read_input_tokens`, `cache_creation_input_tokens`
- OpenAI: `prompt_tokens`, `completion_tokens`, `total_tokens`
- Google: input/output counts under different names

The `TokenUsage` model uses Anthropic's conceptual fields as a baseline,
with cache fields defaulted to 0 for providers without them. When the
OpenAI adapter lands, its `_parse_response` translates OpenAI's naming
into `TokenUsage`'s fields. The schema captures the underlying concept
without locking in any single provider's terminology.

### Migration

Old traces have no `model_response` events. Cost analysis on old traces
reports "unavailable." That's accurate — those traces were written
before token capture was implemented.

Old readers loading a 1.1.0 trace encounter the unknown event type
`"model_response"`. The reader's lenient parsing logs a warning and skips
the event; the rest of the trace still loads. No crash, no corruption —
exactly the format-evolution behavior we designed for.

---

## 6. Version bump

Update `src/marionette/trace/schema.py`:

```python
SCHEMA_VERSION = "1.1.0"
```

The reader's existing major-version compatibility check continues to
work — major version 1 matches major version 1, no warning emitted on
load of either 1.0.0 or 1.1.0 traces.

No bump to `framework_version` is required from this change alone. That
field tracks the Python package version (`pyproject.toml`'s
`[project].version`), which moves on its own schedule.

---

## 7. What gets tested

1. **A 1.1.0 trace round-trips correctly.** Write events with new fields
   populated; emit a `model_response` event; read everything back; assert
   equality.

2. **A 1.0.0 trace loads cleanly under the new reader.** A hand-written
   JSONL file with old-format events (no `turn_id`, no `tools_manifest`,
   no `kind`, no `model_response` events at all) loads without warnings
   or errors. Each missing field defaults to `None` or its declared
   default.

3. **The runner generates `turn_id` correctly.** Multi-turn scenarios
   produce distinct turn_ids; events within one turn share an id;
   framework events have no turn_id.

4. **The manifest correctly captures the tool surface.** A scenario with
   the echo tool produces a `RunStartedEvent` whose `tools_manifest`
   contains one entry with the right name, description, and JSON-schema
   content for both args and result.

5. **`model_response` emission is correct.** Mock the adapter to return
   `Turn`s with specific usage, stop_reason, and duration_ms values;
   assert that a `model_response` event is emitted after each turn's
   content events, with matching field values.

6. **Multi-turn usage aggregation works.** A scenario producing N turns
   yields N `model_response` events; summing their usage gives the
   correct total cost.

7. **Old readers tolerate new traces.** Simulate by parsing a 1.1.0
   trace's JSON lines through a `TypeAdapter` built without
   `ModelResponseEvent` in the union. The unknown event type should
   trigger a lenient skip, not a crash.

---

## 8. Implementation order

Build in this sequence; each step is independently testable and
committable:

**2.1** — Add `turn_id` to existing payloads; runner generates one per
`get_turn()` and stamps events. Tests cover stamping and grouping.

**2.2** — Add `tools_manifest` and `ToolManifestEntry`; runner emits at
start.

**2.3** — Add `kind` to `AgentMessagePayload`. Field-only; classification
not implemented (deferred to judge layer). Tests verify field exists,
defaults to None, and accepts valid Literals.

**2.4** — Add `TokenUsage`, `ModelResponsePayload`, `ModelResponseEvent`;
update `TraceEvent` union. Adapter captures usage/stop_reason/duration
from API response into `Turn`. Runner emits `model_response` after each
turn's content events.

**2.5** — Final tests: 1.0.0 backward-compatibility load, version bump
verification, end-to-end round trip with all new fields populated, real
API smoke run to verify usage data flows correctly.

Commits are conventional-format (`feat(trace): add turn_id to
turn-scoped events`, etc.) for clean history.

---

## 9. What this does *not* change

For honesty about scope:

- No changes to error handling. The adapter's `AdapterError` taxonomy
  and the gateway's `ToolError` taxonomy stay as-is.
- No changes to the writer's flush discipline or context-manager
  behavior. The 1.0.0 writer correctness properties carry forward.
- No changes to schema discipline: still strict-on-write
  (`extra="forbid"`, frozen models), still lenient-on-read.
- No automatic classification of agent messages. The `kind` field
  exists but is never set by the runner.
- No new error event types. `tool_error` and `run_aborted` already
  cover the failure paths.
- No streaming support. Token usage is captured per *complete* response;
  streaming would require a different model.
