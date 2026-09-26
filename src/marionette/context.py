"""Run-scoped state, passed to tools at call time.

Tools are stateless singletons. A Scenario is a frozen module-level constant,
so its tool instances are shared across every run in the process — a tool that
held state would leak it between runs.

Everything that varies per run lives here instead. The runner creates a
RunContext and hands it to the gateway on every call; the gateway passes it
to the tool.

Frozen, and rebuilt per turn with dataclasses.replace(). Position fields
(round, turn, acting agent) therefore cannot shift underneath a tool that is
mid-execution. Shared mutable state — the message bus and environment store,
arriving in 2.1.2 — will be objects this context *references*. Those are
mutable by design; the context itself is not.
"""

from dataclasses import dataclass, field

from marionette.bus import MessageBus
from marionette.environment import EnvironmentStore


@dataclass(frozen=True)
class RunContext:
    """Where a tool call is happening, within a run.

    Attributes:
        run_id: The run this call belongs to. Stable for the whole run.
        round_number: Zero-based round index. A round is one pass in which
            every agent acts once.
        turn_id: Correlation id for the model turn that produced this call.
            Matches the turn_id recorded on the turn's trace events.
        acting_agent_id: The agent making the call.
        bus: Messages sent but not yet delivered. Shared across the whole
            run — the same object is referenced by every turn's context, so
            a message queued in one turn is visible when the runner drains
            in another.
        env: Shared world state — what every agent has done, and when. Like
            bus, the same object is carried forward by replace(), so a
            record written in one turn is visible in another.
    """

    run_id: str
    round_number: int
    turn_id: str
    acting_agent_id: str
    bus: MessageBus = field(default_factory=MessageBus)
    env: EnvironmentStore = field(default_factory=EnvironmentStore)
