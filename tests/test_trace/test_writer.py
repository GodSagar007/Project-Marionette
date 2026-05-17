"""Tests for the TraceWriter — seq stamping, durability, lifecycle."""

import json
from pathlib import Path

import pytest

from marionette.trace.schema import (
    AgentMessageEvent,
    AgentMessagePayload,
    RunStartedEvent,
    RunStartedPayload,
)
from marionette.trace.writer import TraceWriter


def _make_run_started() -> RunStartedEvent:
    """Helper: build a valid RunStartedEvent for tests that need a starter event."""
    return RunStartedEvent(
        actor="framework",
        payload=RunStartedPayload(
            schema_version="1.0.0",
            run_id="r1",
            scenario_id="s",
            model_id="m",
            seed=0,
            framework_version="0.1.0",
            dev_mode=True,
        ),
    )


def test_writer_creates_parent_directories(tmp_path: Path) -> None:
    """Writer creates intermediate directories without explicit setup."""
    path = tmp_path / "deeply" / "nested" / "trace.jsonl"
    with TraceWriter(path) as w:
        w.write(_make_run_started())
    assert path.exists()


def test_writer_assigns_sequential_seqs(tmp_path: Path) -> None:
    """Writer stamps seq 0, 1, 2, ... regardless of incoming event seq."""
    path = tmp_path / "trace.jsonl"
    with TraceWriter(path) as w:
        seq0 = w.write(_make_run_started())
        seq1 = w.write(AgentMessageEvent(actor="agent", payload=AgentMessagePayload(text="a")))
        seq2 = w.write(AgentMessageEvent(actor="agent", payload=AgentMessagePayload(text="b")))
    assert (seq0, seq1, seq2) == (0, 1, 2)


def test_writer_overrides_caller_supplied_seq(tmp_path: Path) -> None:
    """Writer ignores seq on incoming event; the writer's counter wins."""
    path = tmp_path / "trace.jsonl"
    # Construct events with bogus seq values
    e1 = RunStartedEvent(seq=999, actor="framework", payload=_make_run_started().payload)
    e2 = AgentMessageEvent(seq=42, actor="agent", payload=AgentMessagePayload(text="x"))

    with TraceWriter(path) as w:
        w.write(e1)
        w.write(e2)

    lines = path.read_text().strip().split("\n")
    line0 = json.loads(lines[0])
    line1 = json.loads(lines[1])
    assert line0["seq"] == 0
    assert line1["seq"] == 1


def test_writer_writes_one_line_per_event(tmp_path: Path) -> None:
    """Each write produces exactly one line in the file."""
    path = tmp_path / "trace.jsonl"
    with TraceWriter(path) as w:
        w.write(_make_run_started())
        w.write(AgentMessageEvent(actor="agent", payload=AgentMessagePayload(text="x")))
        w.write(AgentMessageEvent(actor="agent", payload=AgentMessagePayload(text="y")))

    lines = path.read_text().strip().split("\n")
    assert len(lines) == 3


def test_write_after_close_raises(tmp_path: Path) -> None:
    """Writing to a closed writer raises RuntimeError."""
    path = tmp_path / "trace.jsonl"
    w = TraceWriter(path)
    w.close()
    with pytest.raises(RuntimeError, match="closed"):
        w.write(_make_run_started())


def test_double_close_is_safe(tmp_path: Path) -> None:
    """Calling close twice does not raise."""
    path = tmp_path / "trace.jsonl"
    w = TraceWriter(path)
    w.close()
    w.close()  # should not raise


def test_context_manager_closes_on_exception(tmp_path: Path) -> None:
    """File is closed even when the with block exits with an exception."""
    path = tmp_path / "trace.jsonl"

    class _IntentionalError(Exception):
        pass

    with pytest.raises(_IntentionalError), TraceWriter(path) as w:
        w.write(_make_run_started())
        raise _IntentionalError("simulated runner crash")

    # File handle should be closed; verify by trying to write again
    with pytest.raises(RuntimeError, match="closed"):
        w.write(_make_run_started())
