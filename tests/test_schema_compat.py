"""Schema compatibility tests.

Verifies the additive-evolution claim from docs/schema-1.1.0-design.md:
new fields and new event types are non-breaking within a major version.

Backward compatibility (new code, old trace) is tested directly.
Forward compatibility (old code, new trace) is tested via its mechanism —
the reader skips unrecognised event types, which is what an old reader
does when it meets model_response.
"""

import json
from pathlib import Path

from marionette.trace.reader import TraceReader
from marionette.trace.schema import (
    AgentMessageEvent,
    AgentMessagePayload,
    ModelResponseEvent,
    ModelResponsePayload,
    TokenUsage,
)
from marionette.trace.writer import TraceWriter

_V1_0_0_EVENTS: list[dict[str, object]] = [
    {
        "seq": 0,
        "ts": "2026-06-01T10:00:00Z",
        "actor": "framework",
        "event": "run_started",
        "payload": {
            "schema_version": "1.0.0",
            "run_id": "r1",
            "scenario_id": "echo-smoke",
            "model_id": "claude-test",
            "seed": 42,
            "framework_version": "0.1.0",
            "dev_mode": False,
        },
    },
    {
        "seq": 1,
        "ts": "2026-06-01T10:00:01Z",
        "actor": "agent",
        "event": "agent_message",
        "payload": {"text": "hello"},
    },
    {
        "seq": 2,
        "ts": "2026-06-01T10:00:02Z",
        "actor": "framework",
        "event": "run_completed",
        "payload": {"status": "ok", "duration_ms": 100, "event_count": 3},
    },
]


def _write_lines(path: Path, events: list[dict[str, object]]) -> None:
    """Write raw JSONL, bypassing the writer — these are hand-built fixtures."""
    path.write_text(
        "".join(json.dumps(e) + "\n" for e in events),
        encoding="utf-8",
    )


def test_v1_0_0_trace_loads_with_new_fields_defaulted(tmp_path: Path) -> None:
    """A 1.0.0 trace loads under 1.1.0, new fields taking their defaults."""
    path = tmp_path / "old.jsonl"
    _write_lines(path, _V1_0_0_EVENTS)

    with TraceReader(path) as reader:
        events = reader.read_all()

    assert len(events) == 3

    started = events[0]
    assert started.event == "run_started"
    assert started.payload.tools_manifest == []
    assert started.agent_id is None
    msg = events[1]
    assert msg.event == "agent_message"
    assert msg.payload.turn_id is None
    assert msg.payload.kind is None


def test_v1_1_0_trace_round_trips(tmp_path: Path) -> None:
    """Every 1.1.0 field survives a write then read."""
    path = tmp_path / "new.jsonl"

    with TraceWriter(path) as writer:
        writer.write(AgentMessageEvent(
            actor="agent",
            payload=AgentMessagePayload(
                text="thinking about it",
                kind="reasoning",
                turn_id="abc123",
            ),
        ))
        writer.write(ModelResponseEvent(
            actor="framework",
            payload=ModelResponsePayload(
                turn_id="abc123",
                usage=TokenUsage(
                    input_tokens=669,
                    output_tokens=56,
                    cache_read_tokens=12,
                    cache_write_tokens=34,
                ),
                stop_reason="tool_use",
                duration_ms=1189,
            ),
        ))

    with TraceReader(path) as reader:
        events = reader.read_all()

    assert len(events) == 2

    msg = events[0]
    assert msg.payload.kind == "reasoning"
    assert msg.payload.turn_id == "abc123"

    resp = events[1]
    assert resp.event == "model_response"
    assert resp.payload.turn_id == "abc123"
    assert resp.payload.stop_reason == "tool_use"
    assert resp.payload.duration_ms == 1189
    assert resp.payload.usage is not None
    assert resp.payload.usage.input_tokens == 669
    assert resp.payload.usage.cache_write_tokens == 34


def test_model_response_tolerates_absent_usage(tmp_path: Path) -> None:
    """A provider that reports no tokens records absence, not zeros."""
    path = tmp_path / "nousage.jsonl"

    with TraceWriter(path) as writer:
        writer.write(ModelResponseEvent(
            actor="framework",
            payload=ModelResponsePayload(
                turn_id="t1",
                stop_reason="end_turn",
                duration_ms=500,
            ),
        ))

    with TraceReader(path) as reader:
        events = reader.read_all()

    assert len(events) == 1
    assert events[0].payload.usage is None


def test_unknown_event_type_is_skipped(tmp_path: Path) -> None:
    """Unrecognised event types are skipped, surrounding events still load.

    This is the mechanism that lets an old reader consume a newer trace:
    it cannot validate model_response, so it skips that line and keeps going.
    """
    path = tmp_path / "future.jsonl"
    _write_lines(path, [
        {
            "seq": 0,
            "ts": "2026-06-01T10:00:00Z",
            "actor": "agent",
            "event": "agent_message",
            "payload": {"text": "before"},
        },
        {
            "seq": 1,
            "ts": "2026-06-01T10:00:01Z",
            "actor": "framework",
            "event": "event_from_the_future",
            "payload": {"whatever": 1},
        },
        {
            "seq": 2,
            "ts": "2026-06-01T10:00:02Z",
            "actor": "agent",
            "event": "agent_message",
            "payload": {"text": "after"},
        },
    ])

    with TraceReader(path) as reader:
        events = reader.read_all()

    assert len(events) == 2
    assert events[0].payload.text == "before"
    assert events[1].payload.text == "after"

def test_agent_id_round_trips(tmp_path: Path) -> None:
    """agent_id survives write and read, and is distinct from actor."""
    path = tmp_path / "agents.jsonl"

    with TraceWriter(path) as writer:
        writer.write(AgentMessageEvent(
            actor="agent",
            agent_id="alice",
            payload=AgentMessagePayload(text="hello", turn_id="t1"),
        ))
        writer.write(AgentMessageEvent(
            actor="agent",
            agent_id="bob",
            payload=AgentMessagePayload(text="hi back", turn_id="t2"),
        ))

    with TraceReader(path) as reader:
        events = reader.read_all()

    assert [e.agent_id for e in events] == ["alice", "bob"]
    assert [e.actor for e in events] == ["agent", "agent"]
