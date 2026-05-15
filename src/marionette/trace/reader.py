"""Trace reader for Marionette.

Provides TraceReader, which loads JSONL trace files line by line and yields
typed TraceEvent objects. The reader is lenient: malformed lines, unknown
event types, and unknown fields are logged and skipped, not raised. This
implements the read-side half of Postel's law for the schema — writers are
strict, readers are tolerant, so the format can evolve.
"""

import logging
from pathlib import Path
from types import TracebackType
from typing import TextIO

from pydantic import TypeAdapter, ValidationError

from marionette.trace.schema import SCHEMA_VERSION, TraceEvent

logger = logging.getLogger(__name__)

_ADAPTER: TypeAdapter[TraceEvent] = TypeAdapter(TraceEvent)

def _parse_major(version: str) -> int:
    """Extract the major version number from a semver string.

    Returns 0 if the string does not parse as semver, since unparseable
    versions are treated as maximally incompatible.
    """
    try:
        return int(version.split(".", maxsplit=1)[0])
    except (ValueError, IndexError):
        return 0

class TraceReader:
    """Lenient JSONL reader for a single run's trace.

    Iterating the reader yields TraceEvent objects, skipping any lines that
    fail to parse or validate. Use as a context manager to guarantee the
    underlying file is closed.
    """

    def __init__(self, path: Path) -> None:
        """Open a trace file for reading.

        Args:
            path: JSONL file to read.

        Raises:
            FileNotFoundError: If the file does not exist.
            OSError: For other I/O errors (permission denied, etc.).
        """
        self._path = path
        self._file: TextIO = self._path.open("r", encoding="utf-8")
        self._lineno = 0
        self._closed = False
        self._detected_schema_version: str | None = None

    def close(self) -> None:
        """Close the underlying file. Safe to call multiple times."""
        if self._closed:
            return
        self._file.close()
        self._closed = True

    def __enter__(self) -> "TraceReader":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()
    def __iter__(self) -> "TraceReader":
        """Return self — the reader is its own iterator."""
        return self

    def __next__(self) -> TraceEvent:
        """Return the next valid event, skipping malformed lines.

        Raises:
            StopIteration: When the file has been fully read.
        """
        while True:
            line = self._file.readline()
            if not line:
                raise StopIteration

            self._lineno += 1
            line = line.strip()
            if not line:
                continue

            try:
                event = _ADAPTER.validate_json(line)
            except ValidationError as e:
                logger.warning(
                    "Skipped invalid event at line %d in %s: %s",
                    self._lineno, self._path, e,
                )
                continue
            except ValueError as e:
                logger.warning(
                    "Skipped malformed JSON at line %d in %s: %s",
                    self._lineno, self._path, e,
                )
                continue

            if event.event == "run_started" and self._detected_schema_version is None:
                self._record_schema_version(event)

            return event
    def read_all(self) -> list[TraceEvent]:
        """Eagerly read every valid event into a list.

        Convenience wrapper around iteration. Use for small traces or when
        full random access is needed. For large traces or streaming
        processing, iterate the reader directly to keep memory flat.
        """
        return list(self)

    def _record_schema_version(self, event: TraceEvent) -> None:
        """Record the schema version from a run_started event.

        Warns if the trace was written by a major version newer than the
        framework currently supports — caller can expect unknown event types
        and unknown fields. Older major versions warn similarly: behavior is
        defined to match within a major version only.
        """
        if event.event != "run_started":
            return

        version = event.payload.schema_version
        self._detected_schema_version = version

        trace_major = _parse_major(version)
        current_major = _parse_major(SCHEMA_VERSION)

        if trace_major != current_major:
            logger.warning(
                "Schema version mismatch in %s: trace=%s, framework=%s. "
                "Cross-major-version reads are best-effort.",
                self._path, version, SCHEMA_VERSION,
            )
