"""Tests for the TraceReader — lenient parsing, schema version detection, round-trip."""

import json
import logging
from pathlib import Path

import pytest

from marionette.trace.reader import TraceReader
from marionette.trace.schema import (
    SCHEMA_VERSION,
    AgentMessageEvent,
    AgentMessagePayload,
    RunCompletedEvent,
    RunCompletedPayload,
    RunStartedEvent,
    RunStartedPayload,
    ToolCallEvent,
    ToolCallPayload,
    ToolResultEvent,
    ToolResultPayload,
    TraceEvent,
)
from marionette.trace.writer import TraceWriter


def _make_run_started(schema_version: str = SCHEMA_VERSION) -> RunStartedEvent:
    """Helper: build a RunStartedEvent, optionally with a custom schema version."""
    return RunStartedEvent(
        actor="framework",
        payload=RunStartedPayload(
            schema_version=schema_version,
            run_id="r1",
            scenario_id="s",
            model_id="m",
            seed=0,
            framework_version="0.1.0",
            dev_mode=True,
        ),
    )


# --- Round-trip: the load-bearing property ---

def test_round_trip_preserves_events(tmp_path: Path) -> None:
    """Events written and read back are equal in meaningful fields."""
    originals: list[TraceEvent] = [
        _make_run_started(),
        AgentMessageEvent(actor="agent", payload=AgentMessagePayload(text="hello")),
        ToolCallEvent(actor="agent", payload=ToolCallPayload(
            tool="echo", call_id="c1", args={"text": "test"},
        )),
        ToolResultEvent(actor="tool:echo", payload=ToolResultPayload(
            call_id="c1", result="test",
        )),
        RunCompletedEvent(actor="framework", payload=RunCompletedPayload(
            status="ok", duration_ms=100, event_count=5,
        )),
    ]

    path = tmp_path / "round_trip.jsonl"
    with TraceWriter(path) as w:
        for event in originals:
            w.write(event)

    with TraceReader(path) as r:
        read_back = r.read_all()

    assert len(read_back) == len(originals)
    for original, read in zip(originals, read_back, strict=True):
        assert read.event == original.event
        assert read.actor == original.actor
        assert read.payload == original.payload


def test_round_trip_assigns_correct_seqs(tmp_path: Path) -> None:
    """Read-back events have sequential seqs starting from 0."""
    path = tmp_path / "seqs.jsonl"
    with TraceWriter(path) as w:
        for _ in range(5):
            w.write(_make_run_started())

    with TraceReader(path) as r:
        events = r.read_all()

    assert [e.seq for e in events] == [0, 1, 2, 3, 4]


# --- Lenient parsing: corrupt lines are skipped ---

@pytest.mark.parametrize("corrupt_line", [
    "this is not json at all",
    '{"event": "unknown_event_type"}',
    '{"event": "tool_call", "payload": {"missing_fields": true}}',
    '{"not_an_event_object": true}',
])
def test_reader_skips_corrupt_lines(corrupt_line: str, tmp_path: Path) -> None:
    """Each kind of malformed line is skipped, valid lines around it pass through."""
    path = tmp_path / "corrupt.jsonl"

    # Write a valid event, then corruption, then another valid event
    with TraceWriter(path) as w:
        w.write(_make_run_started())

    with path.open("a", encoding="utf-8") as f:
        f.write(corrupt_line + "\n")

    with TraceWriter(path) as w:
        w.write(AgentMessageEvent(actor="agent", payload=AgentMessagePayload(text="after")))

    with TraceReader(path) as r:
        events = r.read_all()

    # Two valid events came through; the corrupt line was skipped
    assert len(events) == 2
    assert events[0].event == "run_started"
    assert events[1].event == "agent_message"


def test_reader_skips_blank_lines_silently(tmp_path: Path) -> None:
    """Blank lines in the file are ignored without warning."""
    path = tmp_path / "blanks.jsonl"
    with TraceWriter(path) as w:
        w.write(_make_run_started())

    with path.open("a", encoding="utf-8") as f:
        f.write("\n\n\n")  # several blank lines

    with TraceReader(path) as r:
        events = r.read_all()

    assert len(events) == 1


def test_reader_warns_on_invalid_json(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Invalid JSON triggers a warning message that includes the line number."""
    path = tmp_path / "bad_json.jsonl"
    path.write_text("this is not json\n", encoding="utf-8")

    with (
        caplog.at_level(logging.WARNING, logger="marionette.trace.reader"),
        TraceReader(path) as r,
    ):
        list(r)

    assert "line 1" in caplog.text


# --- Schema version detection ---

def test_reader_detects_schema_version(tmp_path: Path) -> None:
    """Reader records the schema version from the first run_started event."""
    path = tmp_path / "version.jsonl"
    with TraceWriter(path) as w:
        w.write(_make_run_started(schema_version="1.0.0"))

    with TraceReader(path) as r:
        list(r)
        assert r._detected_schema_version == "1.0.0"


def test_reader_warns_on_major_version_mismatch(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Reading a trace from a different major version emits a warning."""
    path = tmp_path / "future.jsonl"
    with TraceWriter(path) as w:
        w.write(_make_run_started(schema_version="99.0.0"))

    with (
        caplog.at_level(logging.WARNING, logger="marionette.trace.reader"),
        TraceReader(path) as r,
    ):
        list(r)
    assert "version mismatch" in caplog.text.lower()


def test_reader_silent_on_same_major_version(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Same major version (different patch) produces no warning."""
    # Pretend the trace was written by a future patch version within our major.
    # We can't make SCHEMA_VERSION dynamic, so write whatever current major.patch+1 is.
    parts = SCHEMA_VERSION.split(".")
    future_within_major = f"{parts[0]}.{int(parts[1]) + 1}.0"

    path = tmp_path / "patch.jsonl"
    with TraceWriter(path) as w:
        w.write(_make_run_started(schema_version=future_within_major))

    with (
        caplog.at_level(logging.WARNING, logger="marionette.trace.reader"),
        TraceReader(path) as r,
    ):
        list(r)

    assert "version mismatch" not in caplog.text.lower()


# --- Lifecycle ---

def test_reader_works_as_context_manager(tmp_path: Path) -> None:
    """Reader closes its file when exiting a with block."""
    path = tmp_path / "ctx.jsonl"
    with TraceWriter(path) as w:
        w.write(_make_run_started())

    with TraceReader(path) as r:
        events = r.read_all()

    assert len(events) == 1


def test_double_close_is_safe(tmp_path: Path) -> None:
    """Calling close twice on a reader does not raise."""
    path = tmp_path / "dc.jsonl"
    with TraceWriter(path) as w:
        w.write(_make_run_started())

    r = TraceReader(path)
    r.close()
    r.close()


def test_read_all_returns_list(tmp_path: Path) -> None:
    """read_all returns a list, not a generator."""
    path = tmp_path / "list.jsonl"
    with TraceWriter(path) as w:
        w.write(_make_run_started())

    with TraceReader(path) as r:
        events = r.read_all()

    assert isinstance(events, list)


def test_file_contents_are_jsonl(tmp_path: Path) -> None:
    """Sanity: the writer produces valid JSONL (one JSON object per line)."""
    path = tmp_path / "shape.jsonl"
    with TraceWriter(path) as w:
        w.write(_make_run_started())
        w.write(AgentMessageEvent(actor="agent", payload=AgentMessagePayload(text="x")))

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    for line in lines:
        json.loads(line)  # would raise if not valid JSON
