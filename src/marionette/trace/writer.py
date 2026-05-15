
"""Trace writer for Marionette.

Provides TraceWriter, which serializes TraceEvent objects to a JSONL file.
The writer owns sequence numbering: callers supply event content, the writer
stamps a monotonic seq value. Used as a context manager so the underlying
file is always flushed and closed, even if a run aborts mid-way.
"""

from pathlib import Path
from typing import TextIO

from marionette.trace.schema import TraceEvent


class TraceWriter:
    """Append-only JSONL writer for a single run's trace.

    One TraceWriter instance corresponds to one run and one file. Not safe
    for concurrent use across threads — a run is single-threaded by design.
    """

    def __init__(self, path: Path) -> None:
        """Open a trace file for writing, creating parent directories as needed.

        Args:
            path: Destination JSONL file. Parent directories are created if
                they do not exist. The file is opened in append mode.
        Raises:
            OSError: If the file cannot be opened (e.g. permission denied,
                disk full, read-only filesystem). The exception propagates
                unchanged; callers can catch OSError or specific subclasses
                like PermissionError or FileNotFoundError as needed.
	"""
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file: TextIO = self._path.open("a", encoding="utf-8")
        self._seq = 0
        self._closed = False

    def write(self, event: TraceEvent) -> int:
        """Stamp the event with the next sequence number and append it to the file.

        Any seq value on the incoming event is ignored and replaced — the
        writer is the sole authority for sequence numbering.

        Args:
            event: The trace event to write.

        Returns:
            The sequence number assigned to this event.

        Raises:
            RuntimeError: If the writer has already been closed.
        """
        if self._closed:
            raise RuntimeError("cannot write to a closed TraceWriter")

        stamped = event.model_copy(update={"seq": self._seq})
        line = stamped.model_dump_json()
        self._file.write(line + "\n")
        self._file.flush()
        assigned = self._seq
        self._seq += 1
        return assigned

    def close(self) -> None:
        """Flush and close the underlying file.

        Safe to call multiple times. After close, subsequent writes raise
        RuntimeError. If the flush during close fails, the file is still
        closed — preventing resource leaks even on broken storage.
        """
        if self._closed:
            return
        try:
            self._file.flush()
        finally:
            self._file.close()
            self._closed = True

    def __enter__(self) -> "TraceWriter":
        """Enter the context manager, returning self."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit the context manager, flushing and closing the file.

        Exceptions raised within the `with` block propagate after cleanup.
        """
        self.close()
