"""The environment store: a shared record of what agents did.

Lives on the RunContext, created per run. Tools record actions into it; the
runner renders observations out of it and pushes them into agents' contexts.

This is what makes *tacit* coordination possible — agents adjusting to each
other with no communication channel at all, purely by observing consequences
across rounds. In the algorithmic-collusion literature that is the primary
result, and an explicit channel is a separate condition layered on top.

Unlike the message bus, records are not consumed by delivery. They persist,
because history is the thing agents coordinate on: a decision in round five
depends on rounds one through four.
"""

from dataclasses import dataclass, field
from typing import Any

from marionette.reveal import Reveal, is_visible


@dataclass(frozen=True)
class EnvironmentRecord:
    """One agent action, recorded for others to observe.

    Attributes:
        agent_id: Who acted.
        round_number: When.
        summary: How the action reads to another agent. Written by the tool
            that recorded it, in plain language, because it is rendered
            directly into a conversation.
        data: The same action as structured values, for analysis. Not shown
            to agents. Usually redundant with the tool_call event's args, and
            kept here so an analyser can read the environment alone.
    """

    agent_id: str
    round_number: int
    summary: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class EnvironmentStore:
    """Shared world state for one run.

    Mutable by design — it is the run's shared state. The RunContext holding
    it is frozen, so a tool cannot see position fields shift mid-execution,
    but this can and must change as agents act.
    """

    _records: list[EnvironmentRecord] = field(default_factory=list)

    def record(self, record: EnvironmentRecord) -> None:
        """Add an action to the shared record."""
        self._records.append(record)

    def visible_to(
        self,
        agent_id: str,
        current_round: int,
        reveal: Reveal,
    ) -> list[EnvironmentRecord]:
        """Records another agent made that this agent may now see.

        Excludes the agent's own actions: an agent already knows what it did,
        and echoing it back would pad the context and confound any measure of
        what the agent was responding to.

        Records are not removed. An agent observes the same history again in
        later rounds; the runner decides what is new.
        """
        return [
            r for r in self._records
            if r.agent_id != agent_id
            and is_visible(r.round_number, current_round, reveal)
        ]

    def latest_round_visible_to(
        self,
        agent_id: str,
        current_round: int,
        reveal: Reveal,
    ) -> list[EnvironmentRecord]:
        """Only the most recent round of visible records.

        What the runner pushes each round. Pushing the full history every
        round would grow the context quadratically and let recency effects
        masquerade as memory. Agents retain earlier rounds in their
        conversation, which is the honest way for history to persist.
        """
        visible = self.visible_to(agent_id, current_round, reveal)
        if not visible:
            return []
        latest = max(r.round_number for r in visible)
        return [r for r in visible if r.round_number == latest]

    def all_records(self) -> list[EnvironmentRecord]:
        """Every record, for analysis after the run."""
        return list(self._records)
