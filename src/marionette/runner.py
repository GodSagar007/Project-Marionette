"""The Marionette runner.

Orchestrates a single scenario run end-to-end: sets up the trace writer, drives
the agent loop (adapter → gateway → adapter), emits run lifecycle events, and
cleans up. The runner is the only component that wires the adapter and gateway
together — everything else stays decoupled.

For thread one this lives in a single module with a small Scenario dataclass.
When scenario tooling matures (SCENARIO.md parsing, asset loading), Scenario
gets promoted to its own module under scenarios/.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from marionette.gateway.tool import Tool


@dataclass(frozen=True)
class Scenario:
    """A scenario the runner can execute.

    Carries the minimum a run needs: an identifier (for trace organization),
    the system prompt that defines the agent's task, the initial user message
    that kicks off the conversation, and the tools the agent has access to.

    Frozen because a scenario is a specification — mutating it mid-run would
    invalidate the trace's claim about what the agent was given.
    """

    id: str
    system_prompt: str
    initial_user_message: str
    tools: list[Tool[Any, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class RunResult:
    """The outcome of a single run.

    Returned by run() so callers can inspect whether the run succeeded, how
    long it took, and where the trace landed. All the detail lives in the
    trace file at trace_path; this is the summary handle.
    """

    run_id: str
    status: Literal["ok", "aborted"]
    duration_ms: int
    event_count: int
    trace_path: Path
    abort_reason: str | None = None
