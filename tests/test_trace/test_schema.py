"""Tests for the trace schema — discriminated union, immutability, strict construction."""


import pytest
from pydantic import TypeAdapter, ValidationError

from marionette.trace.schema import (
    SCHEMA_VERSION,
    AgentMessageEvent,
    AgentMessagePayload,
    RunStartedPayload,
    ToolCallEvent,
    TraceEvent,
)


def test_schema_version_is_semver_string() -> None:
    """SCHEMA_VERSION is a valid semver string."""
    parts = SCHEMA_VERSION.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)


def test_event_assigns_default_seq_and_ts() -> None:
    """Events constructed without explicit seq and ts get defaults."""
    event = AgentMessageEvent(
        actor="agent",
        payload=AgentMessagePayload(text="hello"),
    )
    assert event.seq == 0
    assert event.ts.tzinfo is not None  # has timezone (UTC)


def test_event_is_immutable() -> None:
    """Frozen=True prevents mutation after construction."""
    event = AgentMessageEvent(
        actor="agent",
        payload=AgentMessagePayload(text="hello"),
    )
    with pytest.raises(ValidationError):
        event.seq = 99


def test_payload_forbids_extra_fields() -> None:
    """Payloads reject unknown fields."""
    with pytest.raises(ValidationError, match="extra_forbidden"):
        AgentMessagePayload(text="hello", unknown_field="oops")  # type: ignore[call-arg]


def test_discriminated_union_dispatches_correctly() -> None:
    """Parsing raw JSON via the union returns the correct concrete class."""
    adapter: TypeAdapter[TraceEvent] = TypeAdapter(TraceEvent)
    raw = {
        "event": "tool_call",
        "seq": 5,
        "ts": "2026-05-09T14:32:01Z",
        "actor": "agent",
        "payload": {"tool": "echo", "call_id": "c1", "args": {"text": "hi"}},
    }
    parsed = adapter.validate_python(raw)
    assert isinstance(parsed, ToolCallEvent)
    assert parsed.payload.tool == "echo"


def test_discriminated_union_rejects_unknown_event() -> None:
    """Unknown event types fail validation cleanly."""
    adapter: TypeAdapter[TraceEvent] = TypeAdapter(TraceEvent)
    with pytest.raises(ValidationError, match="union_tag_invalid"):
        adapter.validate_python({
            "event": "made_up_event",
            "seq": 0,
            "ts": "2026-05-09T14:32:01Z",
            "actor": "x",
            "payload": {},
        })


def test_run_started_carries_schema_version() -> None:
    """RunStartedPayload requires schema_version, accepts any string for forward-compat."""
    payload = RunStartedPayload(
        schema_version="99.0.0",  # future version, should still construct
        run_id="r1",
        scenario_id="s",
        model_id="m",
        seed=0,
        framework_version="0.1.0",
        dev_mode=True,
    )
    assert payload.schema_version == "99.0.0"
